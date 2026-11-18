"""The Maven Central fallback repository and the cache that survives a failed build.

Maven Central throttles shared CI runner addresses (403/429). Every job that only RESOLVES
dependencies therefore adds the Google mirror of Maven Central as a second repository
behind `central`, in a step of its own; Maven takes an artifact from the first repository
that has it, so a refusal from Central falls through to the mirror.

What is checked here:

* the step is in every resolving job, directly after the ~/.m2 cache restore (the cache
  holds the settings.xml of whichever job saved it, so an earlier step would be undone),
  and identical across the jobs;
* it is in NO job that publishes: those hold the Sonatype or registry credentials and must
  not resolve through a third-party mirror;
* the script does what it claims against a settings.xml of the shape setup-java generates;
* a job that restores ~/.m2 also saves it when the build failed, after removing the
  resolver's record of failed lookups (which would turn one transient error into a cached
  failure for every later run).
"""

import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT

WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"
STEP_NAME = "Add the Maven Central fallback repository"
FALLBACK_ID = "central-fallback"
FALLBACK_URL = "https://maven-central.storage-download.googleapis.com/maven2"
NAMESPACE = {"m": "http://maven.apache.org/SETTINGS/1.0.0"}

SETTINGS_WITH_SERVER = """<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0">
  <interactiveMode>false</interactiveMode>
  <servers>
    <server>
      <id>github</id>
    </server>
  </servers>
</settings>
"""


def _jobs_with_step(name):
    """Yield (workflow, job, steps) for every job that carries a step of this name."""
    for path in sorted(WORKFLOWS.glob("*.yml")):
        doc = yaml.safe_load(path.read_text())
        for job_name, job in (doc.get("jobs") or {}).items():
            steps = job.get("steps") or []
            if any(step.get("name") == name for step in steps):
                yield path.name, job_name, steps


def _publishing_jobs():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        doc = yaml.safe_load(path.read_text())
        for job_name, job in (doc.get("jobs") or {}).items():
            steps = job.get("steps") or []
            if any((step.get("with") or {}).get("server-id") for step in steps):
                yield path.name, job_name


FALLBACK_JOBS = list(_jobs_with_step(STEP_NAME))
JOB_IDS = [f"{workflow}:{job}" for workflow, job, _ in FALLBACK_JOBS]


def _step(steps, name):
    return next(step for step in steps if step.get("name") == name)


def _script(steps):
    """Return the Python source of the fallback step, without its heredoc wrapper."""
    run = _step(steps, STEP_NAME)["run"]
    match = re.search(r"python3 - <<'PY'\n(.*?)\n\s*PY\n", run, re.DOTALL)
    assert match, "unexpected heredoc wrapper"
    return match.group(1) + "\n"


def _run(script, home):
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home)},
    )


@pytest.fixture
def script():
    return _script(FALLBACK_JOBS[0][2])


@pytest.fixture
def settings_file(tmp_path):
    (tmp_path / ".m2").mkdir()
    return tmp_path / ".m2" / "settings.xml"


def test_resolving_jobs_are_found():
    assert {(workflow, job) for workflow, job, _ in FALLBACK_JOBS} == {
        ("reusable-maven-build.yml", "build"),
        ("reusable-maven-build.yml", "quarkus-alignment"),
        ("reusable-maven-build.yml", "sonar-build"),
        ("reusable-maven-integration-tests.yml", "test"),
    }


@pytest.mark.parametrize(("workflow", "job", "steps"), FALLBACK_JOBS, ids=JOB_IDS)
def test_step_directly_follows_the_cache_restore(workflow, job, steps):
    names = [step.get("name") for step in steps]
    restore = steps[names.index("Cache Maven packages")]
    assert restore.get("id") == "m2-cache", f"{workflow}:{job} restore step must be addressable"
    assert str(restore["uses"]).startswith("actions/cache/restore@"), (
        f"{workflow}:{job} restores through the split action"
    )
    assert names[names.index("Cache Maven packages") + 1] == STEP_NAME, (
        f"{workflow}:{job}: the fallback must run after the restore, which brings back an older settings.xml"
    )


def test_step_is_identical_across_jobs():
    assert len({_step(steps, STEP_NAME)["run"] for _, _, steps in FALLBACK_JOBS}) == 1


def test_no_publishing_job_resolves_through_the_mirror():
    """The jobs that hold publishing credentials never get the third-party mirror."""
    publishing = set(_publishing_jobs())
    assert publishing, "non-vacuity: publishing jobs exist"
    resolving = {(workflow, job) for workflow, job, _ in FALLBACK_JOBS}
    assert not publishing & resolving, f"publishing jobs with the fallback: {sorted(publishing & resolving)}"


@pytest.mark.parametrize(("workflow", "job", "steps"), FALLBACK_JOBS, ids=JOB_IDS)
def test_cache_is_saved_when_the_build_failed(workflow, job, steps):
    if (workflow, job) == ("reusable-maven-build.yml", "quarkus-alignment"):
        pytest.skip("quarkus-alignment only restores; build and sonar-build save the same key")
    names = [step.get("name") for step in steps]
    clean, store = _step(steps, "Save Maven packages"), _step(steps, "Store Maven packages")
    assert names.index("Save Maven packages") < names.index("Store Maven packages"), "clean before saving"
    for step in (clean, store):
        assert step["if"] == "${{ !cancelled() && steps.m2-cache.outputs.cache-hit != 'true' }}"
    assert "*.lastUpdated" in clean["run"] and "resolver-status.properties" in clean["run"]
    assert str(store["uses"]).startswith("actions/cache/save@")
    # the key is the one the restore step looked up
    restore = _step(steps, "Cache Maven packages")
    assert store["with"]["key"] == restore["with"]["key"]
    assert store["with"]["path"] == restore["with"]["path"]


def test_declares_the_fallback_as_repository_and_plugin_repository(script, settings_file, tmp_path):
    settings_file.write_text(SETTINGS_WITH_SERVER)

    result = _run(script, tmp_path)

    assert result.returncode == 0, result.stderr
    root = ET.fromstring(settings_file.read_text())
    profile = root.find("m:profiles/m:profile", NAMESPACE)
    assert profile.find("m:id", NAMESPACE).text == FALLBACK_ID
    for container, tag in (("m:repositories", "m:repository"), ("m:pluginRepositories", "m:pluginRepository")):
        repository = profile.find(f"{container}/{tag}", NAMESPACE)
        assert repository.find("m:id", NAMESPACE).text == FALLBACK_ID
        assert repository.find("m:url", NAMESPACE).text == FALLBACK_URL
        assert repository.find("m:snapshots/m:enabled", NAMESPACE).text == "false"
    assert [a.text for a in root.findall("m:activeProfiles/m:activeProfile", NAMESPACE)] == [FALLBACK_ID]
    assert root.find("m:servers/m:server/m:id", NAMESPACE).text == "github"


def test_keeps_existing_profiles_and_active_profiles(script, settings_file, tmp_path):
    settings_file.write_text(
        SETTINGS_WITH_SERVER.replace(
            "</settings>",
            "  <profiles>\n    <profile>\n      <id>mine</id>\n    </profile>\n  </profiles>\n"
            "  <activeProfiles>\n    <activeProfile>mine</activeProfile>\n  </activeProfiles>\n</settings>",
        )
    )

    result = _run(script, tmp_path)

    assert result.returncode == 0, result.stderr
    root = ET.fromstring(settings_file.read_text())
    assert [p.find("m:id", NAMESPACE).text for p in root.findall("m:profiles/m:profile", NAMESPACE)] == [
        "mine",
        FALLBACK_ID,
    ]
    assert [a.text for a in root.findall("m:activeProfiles/m:activeProfile", NAMESPACE)] == ["mine", FALLBACK_ID]


def test_is_idempotent(script, settings_file, tmp_path):
    settings_file.write_text(SETTINGS_WITH_SERVER)
    assert _run(script, tmp_path).returncode == 0
    patched = settings_file.read_text()

    result = _run(script, tmp_path)

    assert result.returncode == 0, result.stderr
    assert settings_file.read_text() == patched


def test_fails_closed_without_settings_file(script, tmp_path):
    result = _run(script, tmp_path)

    assert result.returncode != 0
    assert "::error::" in result.stderr


def test_resolver_retry_options_are_exported():
    run = _step(FALLBACK_JOBS[0][2], STEP_NAME)["run"]
    assert "MAVEN_OPTS=${MAVEN_OPTS:+$MAVEN_OPTS }" in run, "existing MAVEN_OPTS must be kept"
    assert "-Daether.connector.http.retryHandler.count=5" in run
    assert "-Daether.connector.http.retryHandler.serviceUnavailable=429,503" in run
    assert run.rstrip().endswith('>> "$GITHUB_ENV"')


# ---- Sonar in the build leg (project.yml sonar.run-in-build) --------------------------------


def _build_workflow():
    return yaml.safe_load((WORKFLOWS / "reusable-maven-build.yml").read_text())


def test_run_in_build_is_exposed_by_the_config_job():
    outputs = _build_workflow()["jobs"]["config"]["outputs"]
    assert outputs["sonar-run-in-build"] == "${{ steps.config.outputs.sonar-run-in-build }}"


def test_sonar_build_stands_down_only_when_the_build_leg_analyses():
    condition = _build_workflow()["jobs"]["sonar-build"]["if"]
    # off by default: the job still runs when the key is not 'true'
    assert "needs.config.outputs.sonar-run-in-build != 'true'" in condition
    # and when the primary Java version is not in the matrix, no leg would analyse: the job must still run
    assert "contains(fromJson(needs.config.outputs.java-versions), needs.config.outputs.java-version)" in condition


def test_build_leg_analyses_exactly_when_it_is_the_primary_leg():
    steps = _build_workflow()["jobs"]["build"]["steps"]
    analyse = _step(steps, "Build and analyze, Java ${{ matrix.version }}")
    plain = _step(steps, "Build with Maven, Java ${{ matrix.version }}")
    condition = analyse["if"].removeprefix("${{ ").removesuffix(" }}")
    assert plain["if"] == "${{ !(" + condition + ") }}", "the two build steps must be complementary"
    for required in (
        "needs.config.outputs.sonar-run-in-build == 'true'",
        "matrix.version == needs.config.outputs.java-version",
        "needs.config.outputs.sonar-enabled == 'true'",
        "github.event_name != 'merge_group'",
        "github.actor == 'dependabot[bot]'",
    ):
        assert required in condition, f"analysis condition lacks: {required}"
    command = analyse["run"]
    assert "-Psonar" in command and "sonar:sonar" in command and "-Dsonar.qualitygate.wait=true" in command
    assert analyse["env"]["SONAR_TOKEN"] == "${{ secrets.SONAR_TOKEN }}"
    # full history only for the analysing leg
    checkout = next(step for step in steps if str(step.get("uses", "")).startswith("actions/checkout@"))
    assert checkout["with"]["fetch-depth"] == "${{ (" + condition + ") && '0' || '1' }}"
