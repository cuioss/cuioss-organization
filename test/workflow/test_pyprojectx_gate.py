"""The pyprojectx verify gate: footprint skip on merge_group, fail-open, conclusion.

reusable-pyprojectx-verify.yml used to exclude merge_group from the
skip-on-docs-only footprint filter on the premise that a merge-queue run "has no
reliable diff base". It has one: merge_group.base_sha is the queue base and
merge_group.head_sha is that base plus the merge group, so their diff is
exactly what the group (possibly a batch of PRs) adds. Excluding it made every docs-only PR in a consumer skip
verify on pull_request and then spend a full verify in the queue.

These tests run the real `Decide whether to run` and `conclusion` shell bodies
lifted out of the workflow, under bash, so a regression in the logic (not just
in the YAML shape) fails here.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT

WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "reusable-pyprojectx-verify.yml"
BASE_SHA = "a" * 40
FOOTPRINT_STEPS = ("Checkout", "Build paths-filter spec", "Footprint filter")

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _doc():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _gate_step(name):
    steps = _doc()["jobs"]["gate"]["steps"]
    return next(s for s in steps if s.get("name") == name)


def _run_bash(script, env, tmp_path):
    """Run a step body under `bash -e` (the Actions default) and return (rc, outputs)."""
    output = tmp_path / "github_output"
    output.write_text("")
    # A `gh` that fails loudly: the merge_group / pull_request paths must never
    # reach the push-dedup PR lookup.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text("#!/usr/bin/env bash\necho 'gh must not be called' >&2\nexit 97\n")
    gh.chmod(0o755)
    full_env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_OUTPUT": str(output),
        **env,
    }
    result = subprocess.run(["bash", "-e", "-c", script], capture_output=True, text=True, env=full_env)
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines() if "=" in line)
    return result.returncode, outputs, result.stdout + result.stderr


def _decide(tmp_path, **env):
    defaults = {
        "EVENT_NAME": "merge_group",
        "REF_NAME": "gh-readonly-queue/main/pr-1-" + BASE_SHA,
        "DEFAULT_BRANCH": "main",
        "SKIP_ON_DOCS_ONLY": "true",
        "FOOTPRINT_OUTCOME": "success",
        "BUILDABLE": "false",
        "MERGE_GROUP_BASE_SHA": BASE_SHA,
        "GH_REPO": "cuioss/example",
    }
    script = _gate_step("Decide whether to run")["run"]
    rc, outputs, log = _run_bash(script, {**defaults, **env}, tmp_path)
    assert rc == 0, log
    return outputs.get("run"), log


class TestFootprintStepsRunOnMergeGroup:
    @pytest.mark.parametrize("name", FOOTPRINT_STEPS)
    def test_step_is_not_excluded_from_merge_group(self, name):
        """Should run the footprint steps on merge_group like any other event."""
        condition = str(_gate_step(name).get("if", ""))
        assert "merge_group" not in condition
        assert "inputs.skip-on-docs-only" in condition

    def test_filter_diffs_the_merge_group_range(self):
        """Should pass merge_group.base_sha/head_sha as the explicit diff range."""
        step = _gate_step("Footprint filter")
        assert step["uses"].startswith("dorny/paths-filter@")
        assert step.get("continue-on-error") is True
        with_ = step["with"]
        assert "github.event.merge_group.base_sha" in with_["base"]
        assert "github.event.merge_group.head_sha" in with_["ref"]
        # Outside merge_group both must resolve to '' (the paths-filter default).
        for key in ("base", "ref"):
            assert re.search(r"github\.event_name == 'merge_group' &&", with_[key])
            assert with_[key].rstrip("} ").endswith("|| ''")
        assert with_["predicate-quantifier"] == "every"

    def test_decide_receives_the_merge_group_base(self):
        """Should hand the queue base to the decide step for the fail-open check."""
        env = _gate_step("Decide whether to run")["env"]
        assert env["MERGE_GROUP_BASE_SHA"] == "${{ github.event.merge_group.base_sha }}"


class TestDecideOnMergeGroup:
    def test_docs_only_entry_skips(self, tmp_path):
        """Should skip verify for a docs-only merge_group entry."""
        run, _ = _decide(tmp_path)
        assert run == "false"

    def test_buildable_entry_runs(self, tmp_path):
        """Should run the full verify when the entry touches a building file."""
        run, _ = _decide(tmp_path, BUILDABLE="true")
        assert run == "true"

    @pytest.mark.parametrize("outcome", ["failure", "cancelled", "skipped", ""])
    def test_filter_error_fails_open(self, tmp_path, outcome):
        """Should run verify when the paths-filter did not finish cleanly."""
        run, _ = _decide(tmp_path, FOOTPRINT_OUTCOME=outcome, BUILDABLE="")
        assert run == "true"

    @pytest.mark.parametrize("base", ["", "main", "a" * 39, "A" * 40, "g" * 40])
    def test_missing_or_unresolvable_base_fails_open(self, tmp_path, base):
        """Should run verify when base_sha is missing or not a 40-hex commit."""
        run, log = _decide(tmp_path, MERGE_GROUP_BASE_SHA=base)
        assert run == "true"
        assert "base_sha" in log

    def test_toggle_off_runs(self, tmp_path):
        """Should never skip when skip-on-docs-only is off."""
        run, _ = _decide(tmp_path, SKIP_ON_DOCS_ONLY="false", FOOTPRINT_OUTCOME="skipped")
        assert run == "true"


class TestDecideOtherEvents:
    def test_pull_request_docs_only_skips(self, tmp_path):
        """Should keep the existing pull_request footprint skip."""
        run, _ = _decide(tmp_path, EVENT_NAME="pull_request", MERGE_GROUP_BASE_SHA="")
        assert run == "false"

    def test_pull_request_buildable_runs(self, tmp_path):
        """Should run pull_request verify when a building file changed."""
        run, _ = _decide(tmp_path, EVENT_NAME="pull_request", BUILDABLE="true", MERGE_GROUP_BASE_SHA="")
        assert run == "true"

    def test_default_branch_push_docs_only_skips(self, tmp_path):
        """Should keep the footprint skip on a default-branch push."""
        run, _ = _decide(tmp_path, EVENT_NAME="push", REF_NAME="main", MERGE_GROUP_BASE_SHA="")
        assert run == "false"

    def test_default_branch_push_buildable_runs(self, tmp_path):
        """Should always verify a default-branch push that builds."""
        run, _ = _decide(
            tmp_path,
            EVENT_NAME="push",
            REF_NAME="main",
            BUILDABLE="true",
            MERGE_GROUP_BASE_SHA="",
        )
        assert run == "true"


def _conclusion(tmp_path, gate_result, gate_run, verify_result):
    script = _doc()["jobs"]["conclusion"]["steps"][0]["run"]
    for expr, value in {
        "needs.gate.result": gate_result,
        "needs.gate.outputs.run": gate_run,
        "needs.verify.result": verify_result,
    }.items():
        script = re.sub(r"\$\{\{\s*" + re.escape(expr) + r"\s*\}\}", value, script)
    assert "${{" not in script
    rc, _, log = _run_bash(script, {}, tmp_path)
    return rc, log


class TestConclusionContract:
    def test_skipped_merge_group_entry_reports_success(self, tmp_path):
        """Should report SUCCESS for a deliberately gate-skipped run, so the queue merges."""
        rc, log = _conclusion(tmp_path, "success", "false", "skipped")
        assert rc == 0, log

    @pytest.mark.parametrize("gate_result", ["cancelled", "failure", "skipped"])
    def test_unsuccessful_gate_hard_fails(self, tmp_path, gate_result):
        """Should fail when the gate itself did not succeed, never mask it as a skip."""
        rc, _ = _conclusion(tmp_path, gate_result, "", "skipped")
        assert rc != 0

    @pytest.mark.parametrize("verify_result", ["failure", "cancelled"])
    def test_failed_verify_fails(self, tmp_path, verify_result):
        """Should fail when a verify that ran did not pass."""
        rc, _ = _conclusion(tmp_path, "success", "true", verify_result)
        assert rc != 0

    def test_passed_verify_succeeds(self, tmp_path):
        """Should succeed when verify ran and passed."""
        rc, log = _conclusion(tmp_path, "success", "true", "success")
        assert rc == 0, log
