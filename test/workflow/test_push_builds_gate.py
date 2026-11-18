"""`ci.push-builds` in the gate of the three reusable build workflows.

A first push to a branch cannot have a PR yet, so the PR-dedup in `gate` only helps
once the PR exists. With `ci.push-builds: default-branch-only` (the default) the
gate skips a push to a non-default branch outright and leaves the build to the
`pull_request` run. `release/*` and `dependabot/**` keep the PR-dedup because the
`pull_request` trigger covers only the default branch. `deduplicated` and an
unreadable key (empty value) keep the earlier behaviour.

These tests run the real `Decide whether to run` and `conclusion` shell bodies
lifted out of each workflow, under bash, so a regression in the logic fails here.
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

WORKFLOWS_DIR = PROJECT_ROOT / ".github" / "workflows"
WORKFLOWS = {
    "maven": "reusable-maven-build.yml",
    "npm": "reusable-npm-build.yml",
    "pyprojectx": "reusable-pyprojectx-verify.yml",
}

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _doc(key):
    return yaml.safe_load((WORKFLOWS_DIR / WORKFLOWS[key]).read_text(encoding="utf-8"))


def _gate_step(key, name):
    return next(s for s in _doc(key)["jobs"]["gate"]["steps"] if s.get("name") == name)


def _run_bash(script, env, tmp_path, pr_count="0"):
    """Run a step body under `bash -e` with a `gh` that answers the open-PR lookup."""
    output = tmp_path / "github_output"
    output.write_text("")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(f"#!/usr/bin/env bash\necho {pr_count}\n")
    gh.chmod(0o755)
    full_env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_OUTPUT": str(output),
        **env,
    }
    result = subprocess.run(["bash", "-e", "-c", script], capture_output=True, text=True, env=full_env)
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines() if "=" in line)
    return result.returncode, outputs, result.stdout + result.stderr


def _decide(key, tmp_path, pr_count="0", **env):
    defaults = {
        "EVENT_NAME": "push",
        "REF_NAME": "feature/x",
        "DEFAULT_BRANCH": "main",
        "PUSH_BUILDS": "default-branch-only",
        "GH_REPO": "cuioss/example",
        "SKIP_ON_DOCS_ONLY": "false",
    }
    script = _gate_step(key, "Decide whether to run")["run"]
    rc, outputs, log = _run_bash(script, {**defaults, **env}, tmp_path, pr_count)
    assert rc == 0, log
    return outputs, log


@pytest.mark.parametrize("key", WORKFLOWS)
class TestDecideOnPush:
    def test_default_branch_only_skips_a_feature_branch_push(self, key, tmp_path):
        """Should skip a push to a non-default branch without waiting for a PR."""
        outputs, log = _decide(key, tmp_path)
        assert outputs["run"] == "false"
        assert outputs["reason"] == "disabled"
        assert "default-branch-only" in log

    def test_skips_even_when_no_pr_exists_yet(self, key, tmp_path):
        """Should not depend on the PR lookup: the first push has no PR."""
        outputs, _ = _decide(key, tmp_path, pr_count="0", REF_NAME="chore/orchestrator-ledger")
        assert (outputs["run"], outputs["reason"]) == ("false", "disabled")

    @pytest.mark.parametrize(
        "ref", ["release/1.x", "release/1.x/hotfix", "dependabot/maven/foo-1.2", "dependabot/npm_and_yarn/a/b"]
    )
    def test_release_and_dependabot_keep_the_pr_dedup(self, key, tmp_path, ref):
        """Should fall through to the PR-dedup: pull_request covers only the default branch."""
        outputs, _ = _decide(key, tmp_path, pr_count="0", REF_NAME=ref)
        assert outputs["run"] == "true"
        assert "reason" not in outputs
        outputs, _ = _decide(key, tmp_path, pr_count="1", REF_NAME=ref)
        assert outputs["run"] == "false"
        assert "reason" not in outputs

    def test_deduplicated_keeps_the_earlier_behaviour(self, key, tmp_path):
        """Should build a PR-less push and skip one an open PR already covers."""
        outputs, _ = _decide(key, tmp_path, pr_count="0", PUSH_BUILDS="deduplicated")
        assert outputs["run"] == "true"
        outputs, _ = _decide(key, tmp_path, pr_count="2", PUSH_BUILDS="deduplicated")
        assert outputs["run"] == "false"
        assert "reason" not in outputs

    @pytest.mark.parametrize("value", ["", "garbage"])
    def test_an_unreadable_value_fails_open(self, key, tmp_path, value):
        """Should build the push when the key could not be read, never skip it silently."""
        outputs, _ = _decide(key, tmp_path, pr_count="0", PUSH_BUILDS=value)
        assert outputs["run"] == "true"

    def test_the_default_branch_always_runs(self, key, tmp_path):
        """Should never skip a push to the default branch."""
        outputs, _ = _decide(key, tmp_path, REF_NAME="main")
        assert outputs["run"] == "true"

    @pytest.mark.parametrize("event", ["pull_request", "workflow_dispatch"])
    def test_other_events_always_run(self, key, tmp_path, event):
        """Should leave pull_request and workflow_dispatch untouched."""
        outputs, _ = _decide(key, tmp_path, EVENT_NAME=event)
        assert outputs["run"] == "true"
        assert "reason" not in outputs


def _conclusion(key, tmp_path, **values):
    """Run the real `conclusion` body; unlisted `needs.*` results read as skipped."""
    steps = _doc(key)["jobs"]["conclusion"]["steps"]
    script = next(s["run"] for s in steps if "run" in s)

    def resolve(match):
        expr = match.group(1).strip()
        if expr in values:
            return values[expr]
        if expr.startswith("github.ref =="):
            # "is this the default branch?": a gate-skipped push run never is
            return "false"
        return "skipped" if expr.endswith(".result") else ""

    # `.+?` and not `[^}]+?`: format('refs/heads/{0}', ...) carries a `}` of its own
    script = re.sub(r"\$\{\{\s*(.+?)\s*\}\}", resolve, script)
    assert "${{" not in script
    rc, _, log = _run_bash(script, {}, tmp_path)
    return rc, log


@pytest.mark.parametrize("key", WORKFLOWS)
class TestConclusion:
    def test_a_disabled_skip_reports_success_with_an_accurate_message(self, key, tmp_path):
        """Should be green, and say the push build is off rather than 'covered'."""
        rc, log = _conclusion(
            key,
            tmp_path,
            **{
                "needs.gate.result": "success",
                "needs.gate.outputs.run": "false",
                "needs.gate.outputs.reason": "disabled",
            },
        )
        assert rc == 0, log
        assert "default-branch-only" in log
        assert "covering pull_request run was confirmed" not in log
        assert "rescued" not in log

    def test_a_failed_gate_still_hard_fails(self, key, tmp_path):
        """Should not let the disabled branch mask a gate that did not succeed."""
        rc, _ = _conclusion(
            key,
            tmp_path,
            **{"needs.gate.result": "failure", "needs.gate.outputs.reason": "disabled"},
        )
        assert rc != 0


class TestMavenCoveringRunCheck:
    def test_a_disabled_skip_never_starts_the_covering_run_check(self):
        """Should not wait for (and then rescue on) a covering run nobody expects."""
        condition = _doc("maven")["jobs"]["covering-run-check"]["if"]
        assert "needs.gate.outputs.reason != 'disabled'" in condition
        assert "needs.gate.outputs.run == 'false'" in condition

    def test_the_maven_conclusion_keeps_the_covered_message_for_a_confirmed_run(self, tmp_path):
        """Should still report a confirmed covering run as covered, not as disabled."""
        rc, log = _conclusion(
            "maven",
            tmp_path,
            **{
                "needs.gate.result": "success",
                "needs.gate.outputs.run": "false",
                "needs.covering-run-check.result": "success",
                "needs.covering-run-check.outputs.rescue": "false",
            },
        )
        assert rc == 0, log
        assert "covering pull_request run was confirmed" in log


@pytest.mark.parametrize("key", WORKFLOWS)
class TestGateWiring:
    def test_the_gate_exposes_the_reason(self, key):
        """Should output `reason` next to `run`."""
        assert "steps.decide.outputs.reason" in _doc(key)["jobs"]["gate"]["outputs"]["reason"]

    def test_the_key_is_read_only_for_a_push_to_a_non_default_branch(self, key):
        """Should leave pull_request, merge_group and default-branch runs without the extra steps."""
        step = _gate_step(key, "Read ci.push-builds")
        for condition in (step["if"], _gate_checkout(key)["if"]):
            assert "github.event_name == 'push'" in str(condition)
            assert "github.event.repository.default_branch" in str(condition)

    def test_a_failed_read_does_not_fail_the_gate(self, key):
        """Should fail open: the read is continue-on-error and feeds `decide` by output."""
        step = _gate_step(key, "Read ci.push-builds")
        assert step["continue-on-error"] is True
        env = _gate_step(key, "Decide whether to run")["env"]
        assert env["PUSH_BUILDS"] == "${{ steps.push-builds.outputs.ci-push-builds }}"
        assert step["id"] == "push-builds"


def _gate_checkout(key):
    steps = _doc(key)["jobs"]["gate"]["steps"]
    return next(s for s in steps if str(s.get("uses", "")).startswith("actions/checkout@"))


class TestPyprojectxValidatesProjectYmlOnPullRequests:
    """The footprint skip can skip `verify`, the only other read of project.yml on a PR.

    A pull request that changes only project.yml is a non-building change, so with
    skip-on-docs-only `verify` never runs and never rejects an invalid
    `ci.push-builds`. The gate therefore validates the file itself on pull_request.
    """

    def test_the_gate_reads_project_yml_on_a_pull_request_without_failing_open(self):
        step = _gate_step("pyprojectx", "Validate project.yml configuration")
        assert step["if"] == "github.event_name == 'pull_request'"
        assert "continue-on-error" not in step
        assert step["uses"].startswith("cuioss/cuioss-organization/.github/actions/read-project-config@")
        assert step["with"]["caller-inputs"] == "${{ toJSON(inputs) }}"

    def test_the_checkout_runs_for_it(self):
        assert "github.event_name == 'pull_request'" in str(_gate_checkout("pyprojectx")["if"])
