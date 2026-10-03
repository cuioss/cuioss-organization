"""The `central` server written by setup-java must declare central.sonatype.com.

Maven 3.10.0 sends a settings.xml server's credentials only to origins it can
associate with that server id, and the id `central` is associated with
https://repo.maven.apache.org alone. setup-java writes the server without
<repositoryOrigins> and has no input for it, so every workflow that publishes
with `server-id: central` patches the generated settings.xml in a step of its
own. Without it the Sonatype credentials are withheld and the deploy fails with
HTTP 401 -- which is how the Maven 3.10.0 wrapper bump broke the snapshot deploy
of every consumer at once.

Two things are checked here: that each publishing workflow carries the step,
directly after the setup-java step it patches and identical across workflows,
and that the step's script does what it claims against a settings.xml of the
shape setup-java generates.
"""

import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT

WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"
STEP_NAME = "Declare central.sonatype.com as an origin of the central server"
ORIGIN = "https://central.sonatype.com"
NAMESPACE = {"m": "http://maven.apache.org/SETTINGS/1.0.0"}

# The shape actions/setup-java generates (src/auth.ts, v6.0.1).
SETTINGS_HEADER = """<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xsi:schemaLocation="http://maven.apache.org/SETTINGS/1.0.0 https://maven.apache.org/xsd/settings-1.0.0.xsd">
  <interactiveMode>false</interactiveMode>
  <servers>
"""
SETTINGS_FOOTER = """  </servers>
</settings>
"""


def _server(server_id):
    return (
        "    <server>\n"
        f"      <id>{server_id}</id>\n"
        "      <username>${env.MAVEN_USERNAME}</username>\n"
        "      <password>${env.MAVEN_PASSWORD}</password>\n"
        "    </server>\n"
    )


def _settings(*server_ids):
    return SETTINGS_HEADER + "".join(_server(server_id) for server_id in server_ids) + SETTINGS_FOOTER


def _publishing_jobs():
    """Yield (workflow, job, steps) for every job with a `server-id: central` setup-java step."""
    for path in sorted(WORKFLOWS.glob("*.yml")):
        doc = yaml.safe_load(path.read_text())
        for job_name, job in (doc.get("jobs") or {}).items():
            steps = job.get("steps") or []
            if any((step.get("with") or {}).get("server-id") == "central" for step in steps):
                yield path.name, job_name, steps


PUBLISHING_JOBS = list(_publishing_jobs())
JOB_IDS = [f"{workflow}:{job}" for workflow, job, _ in PUBLISHING_JOBS]


def _script(steps):
    """Return the Python source of the patch step, without its heredoc wrapper."""
    run = next(step["run"] for step in steps if step.get("name") == STEP_NAME)
    lines = run.strip().splitlines()
    assert lines[0] == "python3 - <<'PY'" and lines[-1] == "PY", "unexpected heredoc wrapper"
    return "\n".join(lines[1:-1]) + "\n"


def _run(script, home):
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home)},
    )


@pytest.fixture
def script():
    return _script(PUBLISHING_JOBS[0][2])


@pytest.fixture
def settings_file(tmp_path):
    (tmp_path / ".m2").mkdir()
    return tmp_path / ".m2" / "settings.xml"


def test_publishing_workflows_are_found():
    assert {workflow for workflow, _, _ in PUBLISHING_JOBS} == {
        "reusable-maven-build.yml",
        "reusable-maven-release.yml",
    }


@pytest.mark.parametrize(("workflow", "job", "steps"), PUBLISHING_JOBS, ids=JOB_IDS)
def test_patch_step_directly_follows_setup_java(workflow, job, steps):
    index = next(i for i, step in enumerate(steps) if (step.get("with") or {}).get("server-id") == "central")
    assert steps[index + 1].get("name") == STEP_NAME, (
        f"{workflow}:{job} writes the 'central' server without declaring {ORIGIN} as its origin"
    )
    assert "if" not in steps[index + 1], "the patch step must not be conditional"


def test_patch_step_is_identical_across_workflows():
    assert len({_script(steps) for _, _, steps in PUBLISHING_JOBS}) == 1


def test_declares_origin_on_the_central_server(script, settings_file, tmp_path):
    settings_file.write_text(_settings("central"))

    result = _run(script, tmp_path)

    assert result.returncode == 0, result.stderr
    server = ET.fromstring(settings_file.read_text()).find("m:servers/m:server", NAMESPACE)
    assert [child.tag.split("}")[1] for child in server] == ["id", "username", "password", "repositoryOrigins"]
    assert [origin.text for origin in server.findall("m:repositoryOrigins/m:repositoryOrigin", NAMESPACE)] == [ORIGIN]
    assert server.find("m:password", NAMESPACE).text == "${env.MAVEN_PASSWORD}"


def test_leaves_other_servers_untouched(script, settings_file, tmp_path):
    settings_file.write_text(_settings("github", "central", "other"))

    result = _run(script, tmp_path)

    assert result.returncode == 0, result.stderr
    servers = ET.fromstring(settings_file.read_text()).findall("m:servers/m:server", NAMESPACE)
    declared = {
        server.find("m:id", NAMESPACE).text: server.find("m:repositoryOrigins", NAMESPACE) is not None
        for server in servers
    }
    assert declared == {"github": False, "central": True, "other": False}


def test_is_idempotent(script, settings_file, tmp_path):
    settings_file.write_text(_settings("central"))
    assert _run(script, tmp_path).returncode == 0
    patched = settings_file.read_text()

    result = _run(script, tmp_path)

    assert result.returncode == 0, result.stderr
    assert settings_file.read_text() == patched


@pytest.mark.parametrize("server_ids", [(), ("github",), ("central", "central")], ids=["none", "other", "duplicate"])
def test_fails_closed_without_exactly_one_central_server(script, settings_file, tmp_path, server_ids):
    original = _settings(*server_ids)
    settings_file.write_text(original)

    result = _run(script, tmp_path)

    assert result.returncode != 0
    assert "::error::" in result.stderr
    assert settings_file.read_text() == original


def test_fails_closed_without_settings_file(script, tmp_path):
    assert _run(script, tmp_path).returncode != 0
