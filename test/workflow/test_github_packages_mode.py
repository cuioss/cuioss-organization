"""The GITHUB_TOKEN opt-in and the GitHub Packages mode of the Maven workflows.

Both are opt-in from project.yml, and the promise to every existing consumer is that
nothing changes for them. A unit test cannot run a workflow, but the properties that
promise rests on are all visible in the workflow files:

* no job that a Maven Central caller runs requests `packages: write` -- a called
  workflow cannot escalate its caller's token, so that request alone would be a
  startup failure for every caller that does not grant it;
* `GITHUB_TOKEN` is never set through an expression that can yield the empty string;
* every step that runs Maven carries the token hand-over, and the hand-over itself
  leaves the environment untouched when the carrier is empty;
* the Maven Central secrets appear only in steps a github-packages run skips.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT

WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"
EXAMPLES = PROJECT_ROOT / "docs" / "workflow-examples"

BUILD = "reusable-maven-build.yml"
RELEASE = "reusable-maven-release.yml"
INTEGRATION_TESTS = "reusable-maven-integration-tests.yml"
DEPLOY = "reusable-maven-github-packages-deploy.yml"
MAVEN_CENTRAL_WORKFLOWS = (BUILD, RELEASE, INTEGRATION_TESTS)

CARRIER = "MAVEN_GITHUB_TOKEN"
PREAMBLE = (
    f'if [ -n "${CARRIER}" ]; then export GITHUB_TOKEN="${CARRIER}"; fi',
    f"unset {CARRIER}",
)
CENTRAL_SECRETS = ("OSS_SONATYPE_USERNAME", "OSS_SONATYPE_PASSWORD", "GPG_PRIVATE_KEY", "GPG_PASSPHRASE")
NOT_GITHUB_PACKAGES = re.compile(r"deploy-target\s*!=\s*'github-packages'")
IS_GITHUB_PACKAGES = re.compile(r"deploy-target\s*==\s*'github-packages'")


def _load(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _steps(name):
    """Yield (job name, job, step) for every step of a workflow."""
    for job_name, job in (_load(name).get("jobs") or {}).items():
        for step in job.get("steps") or []:
            yield job_name, job, step


def _runs_maven(step):
    run = str(step.get("run", ""))
    return "./mvnw" in run or "check-quarkus-alignment.py" in run


def _label(job_name, step):
    return f"{job_name}: {step.get('name') or step.get('id') or step.get('uses')}"


class TestCallerContract:
    """`packages: write` is requested where only GitHub Packages consumers call."""

    @pytest.mark.parametrize("workflow", MAVEN_CENTRAL_WORKFLOWS)
    def test_no_maven_central_workflow_requests_a_packages_permission(self, workflow):
        """Should leave the token of every job a Maven Central caller runs as it was."""
        doc = _load(workflow)
        scopes = [doc.get("permissions") or {}] + [
            job.get("permissions") or {} for job in (doc.get("jobs") or {}).values()
        ]
        assert not [scope for scope in scopes if "packages" in scope], (
            f"{workflow} requests a `packages` permission. Its Maven Central callers do not grant "
            "one, and GitHub would reject their runs at startup; the request belongs in "
            f"{DEPLOY}."
        )

    def test_the_deploy_workflow_requests_packages_write_on_the_deploy_job_only(self):
        """Should scope the write permission to the one job that publishes."""
        doc = _load(DEPLOY)
        assert doc["permissions"] == {"contents": "read"}
        assert doc["jobs"]["deploy"]["permissions"] == {"contents": "read", "packages": "write"}
        assert doc["jobs"]["config"]["permissions"] == {"contents": "read"}

    @pytest.mark.parametrize("example", ["maven-build-caller.yml", "maven-build-caller-custom.yml"])
    def test_the_maven_central_build_examples_grant_what_they_always_granted(self, example):
        """Should not have widened the Maven Central caller contract."""
        doc = yaml.safe_load((EXAMPLES / example).read_text(encoding="utf-8"))
        assert doc["permissions"] == {"contents": "read", "pull-requests": "read", "actions": "read"}
        assert "permissions" not in doc["jobs"]["build"]

    def test_the_maven_central_release_example_grants_what_it_always_granted(self):
        """Should not have widened the Maven Central release caller contract."""
        doc = yaml.safe_load((EXAMPLES / "maven-release-caller.yml").read_text(encoding="utf-8"))
        assert doc["jobs"]["release"]["permissions"] == {"contents": "write"}

    @pytest.mark.parametrize(
        "example,job",
        [
            ("maven-github-packages-caller.yml", "deploy-snapshot"),
            ("maven-release-github-packages-caller.yml", "publish"),
        ],
    )
    def test_the_github_packages_examples_grant_packages_write_on_the_deploy_job_only(self, example, job):
        """Should grant the write permission on the calling job, and on no other."""
        doc = yaml.safe_load((EXAMPLES / example).read_text(encoding="utf-8"))
        assert "packages" not in (doc.get("permissions") or {})
        for name, spec in doc["jobs"].items():
            granted = spec.get("permissions") or {}
            if name == job:
                assert DEPLOY in spec["uses"]
                assert granted == {"contents": "read", "packages": "write"}
            else:
                assert "packages" not in granted, f"{example}:{name}"

    @pytest.mark.parametrize(
        "example", ["maven-github-packages-caller.yml", "maven-release-github-packages-caller.yml"]
    )
    def test_the_github_packages_examples_pass_no_maven_central_secret(self, example):
        """Should show a caller that never hands over a Sonatype or GPG credential."""
        doc = yaml.safe_load((EXAMPLES / example).read_text(encoding="utf-8"))
        for name, spec in doc["jobs"].items():
            passed = spec.get("secrets") or {}
            assert passed != "inherit", f"{example}:{name} inherits every secret"
            assert not set(passed) & set(CENTRAL_SECRETS), f"{example}:{name}"

    @pytest.mark.parametrize("workflow", [BUILD, RELEASE, DEPLOY])
    def test_no_maven_central_secret_is_required(self, workflow):
        """Should let a caller that passes none of them start the run."""
        doc = _load(workflow)
        declared = (doc.get("on", doc.get(True)) or {})["workflow_call"].get("secrets") or {}
        required = [name for name in CENTRAL_SECRETS if (declared.get(name) or {}).get("required")]
        assert not required, f"{workflow} still requires {required}"


class TestTokenHandOver:
    """GITHUB_TOKEN reaches Maven only on request, and is absent -- not empty -- otherwise."""

    @pytest.mark.parametrize("workflow", (*MAVEN_CENTRAL_WORKFLOWS, DEPLOY))
    def test_github_token_is_never_set_from_a_conditional_expression(self, workflow):
        """Should set GITHUB_TOKEN to the token or not at all.

        `GITHUB_TOKEN: ${{ cond && github.token || '' }}` defines an empty variable when
        the condition is false, which is not the environment the step had before.
        """
        offending = [
            _label(job_name, step)
            for job_name, _, step in _steps(workflow)
            if "GITHUB_TOKEN" in (step.get("env") or {})
            and str(step["env"]["GITHUB_TOKEN"]).strip() != "${{ github.token }}"
        ]
        assert not offending, f"{workflow}: GITHUB_TOKEN set conditionally in {offending}"

    def test_the_sonar_step_still_sets_github_token_unconditionally(self):
        """Should leave the one step that always had the token exactly as it was."""
        (step,) = [s for _, _, s in _steps(BUILD) if s.get("name") == "Build and analyze"]
        assert step["env"] == {"GITHUB_TOKEN": "${{ github.token }}", "SONAR_TOKEN": "${{ secrets.SONAR_TOKEN }}"}
        assert CARRIER not in step["run"]
        assert "if" not in step

    @pytest.mark.parametrize("workflow", MAVEN_CENTRAL_WORKFLOWS)
    def test_every_maven_step_hands_the_token_over_or_sets_it_outright(self, workflow):
        """Should cover every Maven invocation: the registry never answers anonymously."""
        maven_steps = [(job_name, step) for job_name, _, step in _steps(workflow) if _runs_maven(step)]
        assert maven_steps, f"non-vacuity: {workflow} runs Maven somewhere"
        missing = []
        for job_name, step in maven_steps:
            env = step.get("env") or {}
            if env.get("GITHUB_TOKEN") == "${{ github.token }}":
                continue
            lines = [line.strip() for line in step["run"].splitlines()]
            if CARRIER not in env or tuple(lines[:2]) != PREAMBLE:
                missing.append(_label(job_name, step))
        assert not missing, f"{workflow}: Maven steps without the GITHUB_TOKEN hand-over: {missing}"

    @pytest.mark.parametrize("workflow", MAVEN_CENTRAL_WORKFLOWS)
    def test_the_carrier_holds_the_token_only_when_the_key_is_on(self, workflow):
        """Should derive the carrier from github-token-env == 'true' and nothing else."""
        carriers = {str(step["env"][CARRIER]) for _, _, step in _steps(workflow) if CARRIER in (step.get("env") or {})}
        assert len(carriers) == 1, carriers
        assert re.fullmatch(
            r"\$\{\{ (needs|steps)\.config\.outputs\.github-token-env == 'true' && github\.token \|\| '' \}\}",
            carriers.pop(),
        )

    def test_every_maven_step_of_the_deploy_workflow_sets_the_token(self):
        """Should authenticate the version lookup as well as the deploy."""
        maven_steps = [step for _, _, step in _steps(DEPLOY) if _runs_maven(step)]
        assert len(maven_steps) == 2
        for step in maven_steps:
            assert step["env"]["GITHUB_TOKEN"] == "${{ github.token }}"

    @pytest.mark.parametrize(
        "carrier,preset,expected",
        [
            (None, None, "<unset>"),
            ("", None, "<unset>"),
            ("", "kept", "kept"),
            ("tok", None, "tok"),
            ("tok", "replaced", "tok"),
        ],
        ids=["carrier-absent", "off", "off-keeps-existing", "on", "on-overrides"],
    )
    def test_the_preamble_leaves_the_environment_alone_when_off(self, carrier, preset, expected):
        """Should export the token when the carrier holds one, and otherwise change nothing.

        Runs the two preamble lines under the shell GitHub uses for `run:` steps and reads
        back what a child process -- Maven -- would see.
        """
        env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", CARRIER)}
        if carrier is not None:
            env[CARRIER] = carrier
        if preset is not None:
            env["GITHUB_TOKEN"] = preset
        script = "\n".join(
            (*PREAMBLE, 'env | grep -c "^MAVEN_GITHUB_TOKEN=" || true', 'printenv GITHUB_TOKEN || echo "<unset>"')
        )
        result = subprocess.run(
            ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", script], capture_output=True, text=True, env=env
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.split() == ["0", expected]


class TestMavenCentralStepsAreSkipped:
    """In github-packages mode no step that touches a Maven Central secret runs."""

    def test_the_build_workflow_reads_them_in_the_deploy_snapshot_job_only(self):
        """Should confine the secrets to the job a github-packages run skips."""
        users = {job_name for job_name, _, step in _steps(BUILD) if any(name in str(step) for name in CENTRAL_SECRETS)}
        assert users == {"deploy-snapshot"}
        assert NOT_GITHUB_PACKAGES.search(_load(BUILD)["jobs"]["deploy-snapshot"]["if"])

    def test_the_build_workflow_offers_the_inverse_condition_as_an_output(self):
        """Should keep `github-packages-deploy` the deploy-snapshot condition, target inverted."""
        doc = _load(BUILD)
        central = doc["jobs"]["deploy-snapshot"]["if"]
        packages = doc["jobs"]["conclusion"]["outputs"]["github-packages-deploy"]

        def normalised(expression):
            expression = expression.replace("${{", "").replace("}}", "").replace("always() &&", "")
            expression = NOT_GITHUB_PACKAGES.sub("TARGET", IS_GITHUB_PACKAGES.sub("TARGET", expression))
            return " ".join(expression.split())

        assert NOT_GITHUB_PACKAGES.search(central) and IS_GITHUB_PACKAGES.search(packages)
        assert normalised(central) == normalised(packages)
        call = (doc.get("on", doc.get(True)) or {})["workflow_call"]
        assert call["outputs"]["github-packages-deploy"]["value"] == (
            "${{ jobs.conclusion.outputs.github-packages-deploy }}"
        )

    def test_every_release_step_reading_a_central_secret_is_skipped(self):
        """Should gate each such step on the deploy target, one by one."""
        users = [
            (job_name, step)
            for job_name, _, step in _steps(RELEASE)
            if any(f"secrets.{name}" in str(step) for name in CENTRAL_SECRETS)
        ]
        assert len(users) == 2, "non-vacuity: setup-java and the release step"
        for job_name, step in users:
            assert NOT_GITHUB_PACKAGES.search(str(step.get("if", ""))), _label(job_name, step)

    def test_the_release_job_has_one_maven_step_per_target(self):
        """Should run exactly one of the two release steps, and publish only for Maven Central."""
        steps = [step for job_name, _, step in _steps(RELEASE) if job_name == "release" and _runs_maven(step)]
        central, packages = steps
        assert NOT_GITHUB_PACKAGES.search(central["if"]) and IS_GITHUB_PACKAGES.search(packages["if"])
        assert "release:perform" in central["run"]
        assert "release:perform" not in packages["run"] and "deploy" not in packages["run"].replace("deploy-site", "")
        assert packages["env"] == {"GITHUB_TOKEN": "${{ github.token }}"}

    def test_the_release_job_sets_up_java_once_per_target(self):
        """Should write the `central` server and import the key only for Maven Central."""
        setups = [
            step
            for job_name, _, step in _steps(RELEASE)
            if job_name == "release" and "setup-java" in str(step.get("uses"))
        ]
        packages, central = setups
        assert IS_GITHUB_PACKAGES.search(packages["if"]) and NOT_GITHUB_PACKAGES.search(central["if"])
        assert central["with"]["server-id"] == "central"
        assert not {"server-id", "gpg-private-key", "gpg-passphrase"} & set(packages["with"])

    def test_wait_for_maven_central_is_skipped_and_propagation_survives_it(self):
        """Should skip the Central wait without taking propagation down with it."""
        jobs = _load(RELEASE)["jobs"]
        assert NOT_GITHUB_PACKAGES.search(jobs["wait-for-maven-central"]["if"])
        propagate = jobs["propagate-to-consumers"]
        assert "wait-for-maven-central" in propagate["needs"]
        assert "always()" in propagate["if"] and "needs.release.result == 'success'" in propagate["if"]
        assert "wait-for-maven-central.result" not in propagate["if"]
        assert jobs["release"]["outputs"]["deploy-target"] == "${{ steps.config.outputs.deploy-target }}"


class TestDeployWorkflow:
    """reusable-maven-github-packages-deploy.yml publishes with the workflow token alone."""

    def test_it_refuses_any_other_deploy_target(self):
        """Should fail closed when project.yml does not say github-packages."""
        (step,) = [s for _, _, s in _steps(DEPLOY) if s.get("name") == "Require deploy-target github-packages"]
        assert step["env"] == {"DEPLOY_TARGET": "${{ steps.config.outputs.deploy-target }}"}
        for target, code in (("github-packages", 0), ("maven-central", 1), ("", 1)):
            result = subprocess.run(
                ["bash", "-eo", "pipefail", "-c", step["run"]],
                capture_output=True,
                text=True,
                env={**os.environ, "DEPLOY_TARGET": target},
            )
            assert result.returncode == code, (target, result.stdout)

    def test_the_server_is_written_from_variable_names(self):
        """Should configure the server with GITHUB_ACTOR / GITHUB_TOKEN under the configured id."""
        setups = [step for _, _, step in _steps(DEPLOY) if "setup-java" in str(step.get("uses"))]
        assert len(setups) == 2
        for step in setups:
            assert step["with"]["server-id"] == "${{ needs.config.outputs.packages-server-id }}"
            assert step["with"]["server-username"] == "GITHUB_ACTOR"
            assert step["with"]["server-password"] == "GITHUB_TOKEN"

    def test_the_gpg_key_is_read_by_the_signing_variant_only(self):
        """Should import a key in exactly one step, guarded by sign-artifacts == 'true'."""
        readers = [step for _, _, step in _steps(DEPLOY) if "secrets.GPG_PRIVATE_KEY" in str(step)]
        (signing,) = readers
        assert signing["if"] == "${{ needs.config.outputs.sign-artifacts == 'true' }}"
        unsigned = [
            step for _, _, step in _steps(DEPLOY) if "setup-java" in str(step.get("uses")) and step is not signing
        ]
        assert unsigned[0]["if"] == "${{ needs.config.outputs.sign-artifacts != 'true' }}"
        assert "gpg-private-key" not in unsigned[0]["with"]

    def test_no_sonatype_secret_appears_anywhere(self):
        """Should not know the Sonatype credentials at all."""
        text = (WORKFLOWS / DEPLOY).read_text(encoding="utf-8")
        assert "OSS_SONATYPE" not in text and "MAVEN_USERNAME" not in text and "MAVEN_PASSWORD" not in text

    @pytest.mark.parametrize(
        "ref,snapshot_profiles,release_profiles,expected",
        [
            ("", "", "release", "-B -T1 --no-transfer-progress deploy -DskipTests"),
            ("", "snap,javadoc", "release", "-B -T1 --no-transfer-progress -Psnap,javadoc deploy -DskipTests"),
            ("1.0.0", "snap", "", "-B -T1 --no-transfer-progress deploy -DskipTests"),
            ("1.0.0", "snap", "rel", "-B -T1 --no-transfer-progress -Prel deploy -DskipTests"),
        ],
        ids=["snapshot-empty", "snapshot-profiles", "release-empty", "release-profiles"],
    )
    def test_an_empty_profile_list_yields_no_profile_argument(
        self, tmp_path, ref, snapshot_profiles, release_profiles, expected
    ):
        """Should pick the profile list by mode and never emit a bare -P.

        Runs the deploy step's script against a stand-in `mvnw` that records its arguments.
        """
        (step,) = [s for _, _, s in _steps(DEPLOY) if s.get("id") == "deploy"]
        mvnw = tmp_path / "mvnw"
        mvnw.write_text('#!/usr/bin/env bash\necho "$*" > args.txt\nprintenv MAVEN_GPG_PASSPHRASE > gpg.txt || true\n')
        mvnw.chmod(0o755)
        env = {
            **{k: v for k, v in os.environ.items() if k != "MAVEN_GPG_PASSPHRASE"},
            "RELEASE_REF": ref,
            "MAVEN_PROFILES_SNAPSHOT": snapshot_profiles,
            "MAVEN_PROFILES_RELEASE": release_profiles,
            "MAVEN_GPG_PASSPHRASE": "",
        }
        result = subprocess.run(
            ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env=env,
        )
        assert result.returncode == 0, result.stderr
        assert (tmp_path / "args.txt").read_text().strip() == expected
        assert (tmp_path / "gpg.txt").read_text() == "", "an empty passphrase must not reach Maven"

    @pytest.mark.parametrize(
        "ref,version,code",
        [
            ("", "1.0.0-SNAPSHOT", 0),
            ("", "1.0.0", 0),
            ("1.0.0", "1.0.0", 0),
            ("main", "1.1.0-SNAPSHOT", 1),
            ("", "", 1),
        ],
        ids=["snapshot", "snapshot-mode-release-version", "release", "release-mode-snapshot-version", "no-version"],
    )
    def test_the_version_check_rejects_a_snapshot_under_a_release_ref(self, ref, version, code):
        """Should refuse to publish a snapshot where a release was asked for."""
        (step,) = [s for _, _, s in _steps(DEPLOY) if s.get("name") == "Check the version against the requested mode"]
        result = subprocess.run(
            ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]],
            capture_output=True,
            text=True,
            env={**os.environ, "VERSION": version, "RELEASE_REF": ref},
        )
        assert result.returncode == code, result.stdout

    def test_snapshot_mode_keeps_the_gates_of_the_maven_central_deploy(self):
        """Should publish a snapshot only when enabled and on the default branch."""
        condition = _load(DEPLOY)["jobs"]["deploy"]["if"]
        assert "inputs.ref != ''" in condition
        assert "needs.config.outputs.enable-snapshot-deploy == 'true'" in condition
        assert "github.ref == format('refs/heads/{0}', github.event.repository.default_branch)" in condition
        (step,) = [s for _, _, s in _steps(DEPLOY) if s.get("id") == "deploy"]
        assert step["if"] == "${{ inputs.ref != '' || endsWith(steps.project.outputs.version, '-SNAPSHOT') }}"


def test_the_release_prepare_step_emits_no_bare_profile_flag():
    """Should build the -P argument of the github-packages release step from a non-empty list only."""
    steps = [step for job_name, _, step in _steps(RELEASE) if job_name == "release" and _runs_maven(step)]
    packages = steps[1]["run"]
    guarded = (
        "${{ steps.config.outputs.maven-profiles-release != '' && "
        "format('-P{0}', steps.config.outputs.maven-profiles-release) || '' }}"
    )
    assert packages.count(guarded) == 2
    assert "-P$" not in packages.replace(guarded, "")
