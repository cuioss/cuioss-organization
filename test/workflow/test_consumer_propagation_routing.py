"""Consumer propagation across organisations: one token and one matrix leg per consumer owner.

An installation token of a GitHub App is valid for one account, so both release
workflows fan out over the owners named in the `consumers` list and mint a token per
owner. These tests pin the workflow shape that makes that true, and run the real
`Update consumer repos` step bodies under bash against a stub of the propagation
scripts, so a regression in the routing itself (not just in the YAML) fails here.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT

WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"
READ_CONFIG = PROJECT_ROOT / ".github" / "actions" / "read-project-config" / "read-config.py"
TOKEN_STEP_ID = "prop-token"
CREDENTIALS_STEP_ID = "app"
UPDATE_STEP_ID = "update-consumers"
VERIFY_STEP_NAME = "Verify consumer PR merges"

# (workflow file, propagation job, job that keeps the cuioss token, the script the loop calls)
PROPAGATIONS = [
    ("release.yml", "update-consumers", "release", "update-consumer-repo.py"),
    ("reusable-maven-release.yml", "propagate-to-consumers", "release", "update-consumer-dependency.py"),
]
IDS = [workflow for workflow, *_ in PROPAGATIONS]

STUB_RESULT = {"status": "pr_auto_merge_enabled", "pr_url": "https://example.invalid/pr/1", "error": None}


def _job(workflow, job):
    return yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))["jobs"][job]


def _step(job, step_id):
    return next(step for step in job["steps"] if step.get("id") == step_id)


@pytest.mark.parametrize(("workflow", "job_name", "release_job", "script"), PROPAGATIONS, ids=IDS)
class TestWorkflowShape:
    def test_the_job_fans_out_over_the_consumer_owners(self, workflow, job_name, release_job, script):
        strategy = _job(workflow, job_name)["strategy"]
        assert "needs.release.outputs.consumer-matrix" in strategy["matrix"]["group"]
        assert strategy["fail-fast"] is False

    def test_the_release_job_publishes_the_matrix(self, workflow, job_name, release_job, script):
        outputs = _job(workflow, release_job)["outputs"]
        assert "outputs.consumer-matrix" in outputs["consumer-matrix"]

    def test_the_token_is_minted_for_the_legs_owner_from_that_owners_app(self, workflow, job_name, release_job, script):
        token = _step(_job(workflow, job_name), TOKEN_STEP_ID)
        assert token["uses"].startswith("actions/create-github-app-token@")
        assert token["with"]["owner"] == "${{ matrix.group.owner }}"
        assert token["with"]["app-id"] == "${{ secrets[matrix.group.app-id-secret] }}"
        assert token["with"]["private-key"] == "${{ secrets[matrix.group.private-key-secret] }}"

    def test_the_propagation_job_names_no_release_app_secret_itself(self, workflow, job_name, release_job, script):
        """A literal `secrets.RELEASE_APP_*` here would be the cuioss App reaching a foreign owner."""
        job_text = yaml.safe_dump(_job(workflow, job_name))
        assert "secrets.RELEASE_APP" not in job_text

    def test_the_token_is_not_requested_without_credentials(self, workflow, job_name, release_job, script):
        job = _job(workflow, job_name)
        check = _step(job, CREDENTIALS_STEP_ID)
        assert check["env"]["APP_ID"] == "${{ secrets[matrix.group.app-id-secret] }}"
        assert check["env"]["PRIVATE_KEY"] == "${{ secrets[matrix.group.private-key-secret] }}"
        assert "continue-on-error" not in check
        steps = job["steps"]
        assert steps.index(check) < steps.index(_step(job, TOKEN_STEP_ID))
        assert _step(job, TOKEN_STEP_ID)["if"] == "steps.app.outputs.present == 'true'"
        assert _step(job, UPDATE_STEP_ID)["env"]["CREDENTIALS_MISSING"] == "${{ steps.app.outputs.missing }}"

    def test_a_failed_mint_reaches_the_step_that_reports_it(self, workflow, job_name, release_job, script):
        job = _job(workflow, job_name)
        assert _step(job, TOKEN_STEP_ID)["continue-on-error"] is True
        assert _step(job, UPDATE_STEP_ID)["env"]["TOKEN_OUTCOME"] == "${{ steps.prop-token.outcome }}"

    def test_every_consumer_step_uses_the_legs_token(self, workflow, job_name, release_job, script):
        job = _job(workflow, job_name)
        verify = next(step for step in job["steps"] if step.get("name") == VERIFY_STEP_NAME)
        for step in (_step(job, UPDATE_STEP_ID), verify):
            assert step["env"]["GH_TOKEN"] == "${{ steps.prop-token.outputs.token }}"

    def test_the_owner_is_handed_to_the_script_as_org(self, workflow, job_name, release_job, script):
        update = _step(_job(workflow, job_name), UPDATE_STEP_ID)
        assert update["env"]["OWNER"] == "${{ matrix.group.owner }}"
        assert script in update["run"]
        assert '--org "$OWNER"' in update["run"]

    def test_nothing_from_project_yml_is_interpolated_into_the_script(self, workflow, job_name, release_job, script):
        assert "${{" not in _step(_job(workflow, job_name), UPDATE_STEP_ID)["run"]

    def test_the_propagation_job_is_not_tolerated(self, workflow, job_name, release_job, script):
        job = _job(workflow, job_name)
        assert "continue-on-error" not in job
        assert "continue-on-error" not in _step(job, UPDATE_STEP_ID)

    def test_the_release_job_keeps_the_cuioss_token(self, workflow, job_name, release_job, script):
        token = _step(_job(workflow, release_job), "release-token")
        assert token["with"]["owner"] == "cuioss"
        assert token["with"]["app-id"] == "${{ secrets.RELEASE_APP_ID }}"
        assert token["with"]["private-key"] == "${{ secrets.RELEASE_APP_PRIVATE_KEY }}"


def _secret_names(owner):
    """The secret names read-project-config derives for an owner, taken from the script itself."""
    spec = importlib.util.spec_from_file_location("read_config", READ_CONFIG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.release_app_secret_names(owner)


def _consumer(repo, hint="", entry=None):
    return {"entry": entry or (f"{repo}:{hint}" if hint else repo), "repo": repo, "hint": hint}


def _run_update(
    tmp_path,
    workflow,
    job_name,
    owner,
    consumers,
    token="ghs_stub",
    outcome="success",
    stub_rc=0,
    scope="parent",
    missing="",
):
    """Run the workflow's real `Update consumer repos` body under `bash -e` (the Actions default).

    `python3` is replaced by a stub that records its arguments and the token it was given,
    then prints a RESULT line, so the loop's routing is observable without touching GitHub.

    Returns:
        (exit code, recorded script invocations, results-file rows, step summary, log).
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    calls = tmp_path / "calls.jsonl"
    calls.write_text("")
    stub = bin_dir / "python3"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        # Options reach jq on stdin: handed over as arguments, jq would parse `--org` itself.
        'printf "%s\\n" "$@" | jq -Rnc --arg token "$GH_TOKEN" \'{args: [inputs], token: $token}\' >> "$CALLS"\n'
        f"if [ {stub_rc} -ne 0 ]; then echo 'Traceback: boom' >&2; exit {stub_rc}; fi\n"
        f"echo 'RESULT:{json.dumps(STUB_RESULT)}'\n"
    )
    stub.chmod(0o755)
    output = tmp_path / "github_output"
    output.write_text("")
    summary = tmp_path / "summary.md"
    summary.write_text("")
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "TMPDIR": str(tmp_path),
        "CALLS": str(calls),
        "GITHUB_OUTPUT": str(output),
        "GITHUB_STEP_SUMMARY": str(summary),
        "GITHUB_WORKSPACE": str(PROJECT_ROOT),
        "GH_TOKEN": token,
        "TOKEN_OUTCOME": outcome,
        "CREDENTIALS_MISSING": missing,
        "APP_ID_SECRET": _secret_names(owner)[0],
        "PRIVATE_KEY_SECRET": _secret_names(owner)[1],
        "OWNER": owner,
        "CONSUMERS_JSON": json.dumps(consumers),
        "VERSION": "1.2.3",
        "SHA": "a" * 40,
        "GROUP_ID": "de.cuioss",
        "ARTIFACT_ID": "cui-java-parent",
        "SCOPE": scope,
        "MAVEN_CENTRAL_FOUND": "true",
    }
    script = _step(_job(workflow, job_name), UPDATE_STEP_ID)["run"]
    result = subprocess.run(["bash", "-e", "-c", script], capture_output=True, text=True, env=env, cwd=tmp_path)
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines() if "=" in line)
    rows = json.loads(Path(outputs["RESULTS_FILE"]).read_text())
    invocations = [json.loads(line) for line in calls.read_text().splitlines()]
    return result.returncode, invocations, rows, summary.read_text(), result.stdout + result.stderr


def _option(invocation, name):
    args = invocation["args"]
    return args[args.index(name) + 1]


@pytest.mark.skipif(shutil.which("bash") is None or shutil.which("jq") is None, reason="needs bash and jq")
@pytest.mark.parametrize(("workflow", "job_name", "release_job", "script"), PROPAGATIONS, ids=IDS)
class TestOwnerRouting:
    def test_a_cuioss_leg_addresses_cuioss(self, tmp_path, workflow, job_name, release_job, script):
        rc, calls, rows, summary, log = _run_update(
            tmp_path, workflow, job_name, "cuioss", [_consumer("cui-http"), _consumer("cui-java-tools")]
        )
        assert rc == 0, log
        assert [(_option(call, "--org"), _option(call, "--repo")) for call in calls] == [
            ("cuioss", "cui-http"),
            ("cuioss", "cui-java-tools"),
        ]
        assert [row["repo"] for row in rows] == ["cuioss/cui-http", "cuioss/cui-java-tools"]

    def test_another_owners_leg_addresses_that_owner_with_its_token(
        self, tmp_path, workflow, job_name, release_job, script
    ):
        rc, calls, rows, summary, log = _run_update(
            tmp_path,
            workflow,
            job_name,
            "plan-marshall",
            [_consumer("plan-marshall-mcp", entry="plan-marshall/plan-marshall-mcp")],
            token="ghs_plan_marshall",
        )
        assert rc == 0, log
        assert len(calls) == 1
        assert calls[0]["args"][0].endswith(script)
        assert _option(calls[0], "--org") == "plan-marshall"
        assert _option(calls[0], "--repo") == "plan-marshall-mcp"
        assert calls[0]["token"] == "ghs_plan_marshall"
        assert rows == [{"repo": "plan-marshall/plan-marshall-mcp", **STUB_RESULT}]
        assert "| plan-marshall/plan-marshall-mcp | :hourglass: Auto-merge enabled |" in summary

    def test_missing_secrets_fail_every_consumer_of_that_owner_naming_both_secrets(
        self, tmp_path, workflow, job_name, release_job, script
    ):
        rc, calls, rows, summary, log = _run_update(
            tmp_path,
            workflow,
            job_name,
            "plan-marshall",
            [_consumer("plan-marshall-mcp"), _consumer("other")],
            token="",
            outcome="skipped",
            missing="RELEASE_APP_ID_PLAN_MARSHALL, RELEASE_APP_PRIVATE_KEY_PLAN_MARSHALL",
        )
        assert rc == 1
        assert calls == []
        assert [row["repo"] for row in rows] == ["plan-marshall/plan-marshall-mcp", "plan-marshall/other"]
        for row in rows:
            assert row["status"] == "error"
            assert "no release App credentials for 'plan-marshall'" in row["error"]
            assert "RELEASE_APP_ID_PLAN_MARSHALL and RELEASE_APP_PRIVATE_KEY_PLAN_MARSHALL" in row["error"]
        assert "| plan-marshall/plan-marshall-mcp | :x: Error | no release App credentials" in summary
        assert "::error::plan-marshall/plan-marshall-mcp: no release App credentials" in log

    def test_one_missing_secret_is_named_as_the_missing_one(self, tmp_path, workflow, job_name, release_job, script):
        rc, calls, rows, summary, log = _run_update(
            tmp_path,
            workflow,
            job_name,
            "plan-marshall",
            [_consumer("plan-marshall-mcp")],
            token="",
            outcome="skipped",
            missing="RELEASE_APP_PRIVATE_KEY_PLAN_MARSHALL",
        )
        assert rc == 1
        assert calls == []
        assert rows[0]["error"].endswith("missing or empty: RELEASE_APP_PRIVATE_KEY_PLAN_MARSHALL")

    def test_a_token_from_elsewhere_is_never_used_when_the_owners_secrets_are_missing(
        self, tmp_path, workflow, job_name, release_job, script
    ):
        """Even with a usable token in the environment, missing credentials propagate nothing."""
        rc, calls, rows, summary, log = _run_update(
            tmp_path,
            workflow,
            job_name,
            "plan-marshall",
            [_consumer("plan-marshall-mcp")],
            token="ghs_cuioss_token",
            outcome="success",
            missing="RELEASE_APP_ID_PLAN_MARSHALL, RELEASE_APP_PRIVATE_KEY_PLAN_MARSHALL",
        )
        assert rc == 1
        assert calls == []

    def test_a_failed_mint_fails_every_consumer_of_that_owner_naming_the_app_secrets(
        self, tmp_path, workflow, job_name, release_job, script
    ):
        rc, calls, rows, summary, log = _run_update(
            tmp_path,
            workflow,
            job_name,
            "plan-marshall",
            [_consumer("plan-marshall-mcp"), _consumer("other")],
            token="",
            outcome="failure",
        )
        assert rc == 1
        assert calls == []
        assert [row["repo"] for row in rows] == ["plan-marshall/plan-marshall-mcp", "plan-marshall/other"]
        for row in rows:
            assert row["status"] == "error"
            assert "no installation token for 'plan-marshall'" in row["error"]
            assert "RELEASE_APP_ID_PLAN_MARSHALL / RELEASE_APP_PRIVATE_KEY_PLAN_MARSHALL" in row["error"]
        assert "::error::plan-marshall/plan-marshall-mcp: no installation token" in log

    def test_a_malformed_entry_fails_the_leg_and_spares_its_siblings(
        self, tmp_path, workflow, job_name, release_job, script
    ):
        malformed = {"entry": "a/b/c", "repo": "", "hint": "", "error": "not a consumer entry"}
        rc, calls, rows, summary, log = _run_update(
            tmp_path, workflow, job_name, "cuioss", [malformed, _consumer("cui-http")]
        )
        assert rc == 1
        assert [_option(call, "--repo") for call in calls] == ["cui-http"]
        assert rows[0] == {"repo": "a/b/c", "status": "error", "error": "not a consumer entry"}
        assert rows[1]["repo"] == "cuioss/cui-http"

    def test_a_script_that_dies_without_a_result_fails_the_leg(self, tmp_path, workflow, job_name, release_job, script):
        rc, calls, rows, summary, log = _run_update(
            tmp_path, workflow, job_name, "plan-marshall", [_consumer("plan-marshall-mcp")], stub_rc=3
        )
        assert rc == 1
        assert rows[0]["repo"] == "plan-marshall/plan-marshall-mcp"
        assert rows[0]["status"] == "no_result"


@pytest.mark.skipif(shutil.which("bash") is None or shutil.which("jq") is None, reason="needs bash and jq")
class TestDependencyHints:
    """The `:hint` suffix survives the owner prefix and still means what the scope says."""

    WORKFLOW = ("reusable-maven-release.yml", "propagate-to-consumers")

    def test_a_qualified_parent_hint_selects_the_inherited_parent(self, tmp_path):
        rc, calls, rows, summary, log = _run_update(
            tmp_path,
            *self.WORKFLOW,
            "plan-marshall",
            [_consumer("plan-marshall-mcp", "cui-quarkus-parent")],
        )
        assert rc == 0, log
        assert _option(calls[0], "--org") == "plan-marshall"
        assert _option(calls[0], "--parent-artifact-id") == "cui-quarkus-parent"
        assert "--version-property" not in calls[0]["args"]

    def test_no_hint_passes_neither_option(self, tmp_path):
        rc, calls, rows, summary, log = _run_update(tmp_path, *self.WORKFLOW, "cuioss", [_consumer("cui-http")])
        assert rc == 0, log
        assert "--parent-artifact-id" not in calls[0]["args"]
        assert "--version-property" not in calls[0]["args"]

    def test_a_dependency_scope_hint_is_the_version_property(self, tmp_path):
        rc, calls, rows, summary, log = _run_update(
            tmp_path,
            *self.WORKFLOW,
            "plan-marshall",
            [_consumer("plan-marshall-mcp", "version.cui.http")],
            scope="dependency",
        )
        assert rc == 0, log
        assert _option(calls[0], "--version-property") == "version.cui.http"
        assert "--parent-artifact-id" not in calls[0]["args"]


def _check_credentials(tmp_path, workflow, job_name, app_id, private_key, owner="plan-marshall"):
    """Run the workflow's real `Check release App credentials` body; return its outputs."""
    output = tmp_path / "github_output"
    output.write_text("")
    app_id_secret, private_key_secret = _secret_names(owner)
    env = {
        "PATH": os.environ["PATH"],
        "GITHUB_OUTPUT": str(output),
        "APP_ID": app_id,
        "PRIVATE_KEY": private_key,
        "APP_ID_SECRET": app_id_secret,
        "PRIVATE_KEY_SECRET": private_key_secret,
    }
    script = _step(_job(workflow, job_name), CREDENTIALS_STEP_ID)["run"]
    result = subprocess.run(["bash", "-e", "-c", script], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    return dict(line.split("=", 1) for line in output.read_text().splitlines() if "=" in line)


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
@pytest.mark.parametrize(("workflow", "job_name", "release_job", "script"), PROPAGATIONS, ids=IDS)
class TestCredentialCheck:
    """An absent secret reads as the empty string; the check turns that into a named list."""

    def test_both_present(self, tmp_path, workflow, job_name, release_job, script):
        assert _check_credentials(tmp_path, workflow, job_name, "12345", "pem") == {"missing": "", "present": "true"}

    def test_both_missing(self, tmp_path, workflow, job_name, release_job, script):
        assert _check_credentials(tmp_path, workflow, job_name, "", "") == {
            "missing": "RELEASE_APP_ID_PLAN_MARSHALL, RELEASE_APP_PRIVATE_KEY_PLAN_MARSHALL",
            "present": "false",
        }

    def test_only_the_app_id_missing(self, tmp_path, workflow, job_name, release_job, script):
        assert _check_credentials(tmp_path, workflow, job_name, "", "pem") == {
            "missing": "RELEASE_APP_ID_PLAN_MARSHALL",
            "present": "false",
        }

    def test_only_the_private_key_missing(self, tmp_path, workflow, job_name, release_job, script):
        assert _check_credentials(tmp_path, workflow, job_name, "12345", "") == {
            "missing": "RELEASE_APP_PRIVATE_KEY_PLAN_MARSHALL",
            "present": "false",
        }

    def test_the_cuioss_leg_checks_the_plain_secrets(self, tmp_path, workflow, job_name, release_job, script):
        outputs = _check_credentials(tmp_path, workflow, job_name, "", "", owner="cuioss")
        assert outputs["missing"] == "RELEASE_APP_ID, RELEASE_APP_PRIVATE_KEY"

    def test_the_value_of_a_secret_is_never_written_to_the_outputs(
        self, tmp_path, workflow, job_name, release_job, script
    ):
        outputs = _check_credentials(tmp_path, workflow, job_name, "12345", "-----BEGIN KEY-----")
        assert "12345" not in "".join(outputs.values())
        assert "BEGIN" not in "".join(outputs.values())


class TestForeignAppSecretsOfTheReusableWorkflow:
    """A caller can pass a secret explicitly only if the called workflow declares it."""

    @staticmethod
    def _declared():
        document = yaml.safe_load((WORKFLOWS / "reusable-maven-release.yml").read_text(encoding="utf-8"))
        # PyYAML reads the bare `on:` key as the boolean True.
        triggers = document.get("on") or document[True]
        return triggers["workflow_call"]["secrets"]

    def test_plan_marshalls_pair_is_declared_and_optional(self):
        declared = self._declared()
        for name in _secret_names("plan-marshall"):
            assert declared[name]["required"] is False

    def test_the_cuioss_pair_stays_required(self):
        declared = self._declared()
        for name in _secret_names("cuioss"):
            assert declared[name]["required"] is True

    def test_every_foreign_secret_is_one_half_of_a_complete_optional_pair(self):
        """A declared name that the convention cannot produce would never be read."""
        declared = self._declared()
        foreign_ids = [name for name in declared if name.startswith("RELEASE_APP_ID_")]
        foreign_keys = [name for name in declared if name.startswith("RELEASE_APP_PRIVATE_KEY_")]
        assert foreign_ids
        for name in foreign_ids:
            suffix = name.removeprefix("RELEASE_APP_ID_")
            assert suffix
            assert all(character.isupper() or character.isdigit() or character == "_" for character in suffix)
            assert f"RELEASE_APP_PRIVATE_KEY_{suffix}" in foreign_keys
            assert declared[name]["required"] is False
        assert len(foreign_ids) == len(foreign_keys)

    def test_the_caller_example_passes_only_declared_secrets(self):
        example = yaml.safe_load(
            (PROJECT_ROOT / "docs" / "workflow-examples" / "maven-release-caller.yml").read_text(encoding="utf-8")
        )
        passed = example["jobs"]["release"]["secrets"]
        assert set(passed) <= set(self._declared())
