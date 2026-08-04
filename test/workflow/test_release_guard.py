"""Tests for release-guard.py - the version-changed release guard.

These build real git repositories rather than mocking git. The guard's whole
job is to read history correctly, and the failure mode it exists to prevent
(a clone too shallow to have a first parent) is invisible to a mock.
"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT, run_script

SCRIPT_PATH = PROJECT_ROOT / ".github/actions/release-guard/release-guard.py"

PROJECT_YML = """\
name: demo
release:
  current-version: {version}
  next-version: 9.9.9-SNAPSHOT
maven-build:
  java-versions: {java_versions}
sonar:
  enabled: true
"""


def _parse_output(stdout: str) -> dict[str, str]:
    """Parse GITHUB_OUTPUT-style key=value lines into a dict."""
    return {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in stdout.strip().split("\n")
        if "=" in line
    }


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


class Repo:
    """A throwaway git repository with a project.yml commit helper."""

    def __init__(self, path: Path):
        self.path = path
        path.mkdir(parents=True, exist_ok=True)
        _git(path, "init", "--quiet", "--initial-branch", "main")
        _git(path, "config", "user.email", "test@example.com")
        _git(path, "config", "user.name", "test")
        (path / ".github").mkdir()

    def commit(self, version: str, java_versions: str = '["21"]', message: str = "change") -> str:
        (self.path / ".github/project.yml").write_text(
            PROJECT_YML.format(version=version, java_versions=java_versions)
        )
        _git(self.path, "add", "-A")
        _git(self.path, "commit", "--quiet", "-m", message)
        return _git(self.path, "rev-parse", "HEAD")

    def commit_without_config(self, message: str = "no config") -> str:
        (self.path / "README.md").write_text(message)
        _git(self.path, "add", "-A")
        _git(self.path, "commit", "--quiet", "-m", message)
        return _git(self.path, "rev-parse", "HEAD")

    def tag(self, name: str) -> None:
        _git(self.path, "tag", name)


@pytest.fixture
def repo(tmp_path) -> Repo:
    return Repo(tmp_path / "repo")


def run_guard(repo: Repo, sha: str, event_name: str = "pull_request", merged: str = "true", **kwargs):
    args = [
        "--event-name",
        event_name,
        "--merge-sha",
        sha,
        "--pull-request-merged",
        merged,
        "--repo-dir",
        str(repo.path),
    ]
    for key, value in kwargs.items():
        args += [f"--{key.replace('_', '-')}", value]
    return run_script(SCRIPT_PATH, *args)


class TestWorkflowDispatch:
    """The deliberate path must never be blocked."""

    def test_dispatch_proceeds_on_unchanged_version(self, repo):
        repo.commit("1.0.0")
        sha = repo.commit("1.0.0", java_versions='["21","25"]')
        result = run_guard(repo, sha, event_name="workflow_dispatch")
        assert result.returncode == 0
        assert _parse_output(result.stdout)["proceed"] == "true"

    def test_dispatch_proceeds_on_already_tagged_version(self, repo):
        repo.commit("1.0.0")
        sha = repo.commit("2.0.0")
        repo.tag("2.0.0")
        result = run_guard(repo, sha, event_name="workflow_dispatch")
        assert result.returncode == 0
        assert _parse_output(result.stdout)["proceed"] == "true"

    def test_dispatch_needs_no_repository(self, tmp_path):
        """Dispatch short-circuits before touching git at all."""
        result = run_script(
            SCRIPT_PATH,
            "--event-name",
            "workflow_dispatch",
            "--repo-dir",
            str(tmp_path / "does-not-exist"),
        )
        assert result.returncode == 0
        assert _parse_output(result.stdout)["proceed"] == "true"


class TestNegativeControl:
    """A non-release project.yml edit must not release."""

    def test_unchanged_version_skips(self, repo):
        repo.commit("1.0.0")
        sha = repo.commit("1.0.0", java_versions='["21","25"]', message="bump java versions")
        result = run_guard(repo, sha)
        assert result.returncode == 0
        output = _parse_output(result.stdout)
        assert output["proceed"] == "false"
        assert "unchanged" in output["reason"]

    def test_unchanged_version_exits_success(self, repo):
        """A skip is a no-op, not a failure — the caller's run stays green."""
        repo.commit("1.0.0")
        sha = repo.commit("1.0.0", java_versions='["25"]')
        assert run_guard(repo, sha).returncode == 0


class TestPositiveControl:
    """The matched control: a version change must actually fire."""

    def test_changed_untagged_version_proceeds(self, repo):
        repo.commit("1.0.0")
        repo.tag("1.0.0")
        sha = repo.commit("1.1.0", message="release: prepare 1.1.0")
        result = run_guard(repo, sha)
        assert result.returncode == 0
        output = _parse_output(result.stdout)
        assert output["proceed"] == "true"
        assert output["current-version"] == "1.1.0"
        assert output["previous-version"] == "1.0.0"

    def test_config_absent_on_parent_counts_as_changed(self, repo):
        repo.commit_without_config()
        sha = repo.commit("0.1.0")
        result = run_guard(repo, sha)
        output = _parse_output(result.stdout)
        assert output["proceed"] == "true"
        assert output["previous-version"] == ""


class TestAlreadyTagged:
    """A revert or re-merge changes the value at a version already released."""

    def test_changed_but_tagged_skips(self, repo):
        repo.commit("1.0.0")
        repo.tag("1.0.0")
        repo.commit("1.1.0")
        repo.tag("1.1.0")
        # A revert of the 1.1.0 bump: the value genuinely changes 1.1.0 -> 1.0.0.
        sha = repo.commit("1.0.0", message="revert version bump")
        result = run_guard(repo, sha)
        output = _parse_output(result.stdout)
        assert output["proceed"] == "false"
        assert "already exists" in output["reason"]

    def test_v_prefixed_tag_counts(self, repo):
        repo.commit("1.0.0")
        sha = repo.commit("2.0.0")
        repo.tag("v2.0.0")
        assert _parse_output(run_guard(repo, sha).stdout)["proceed"] == "false"

    def test_maven_default_tag_name_format_counts(self, repo):
        """Maven's default tagNameFormat is ${artifactId}-${version}."""
        repo.commit("1.0.0")
        sha = repo.commit("2.0.0")
        repo.tag("demo-artifact-2.0.0")
        assert _parse_output(run_guard(repo, sha).stdout)["proceed"] == "false"

    def test_unrelated_tag_does_not_block(self, repo):
        repo.commit("1.0.0")
        sha = repo.commit("2.0.0")
        repo.tag("1.9.0")
        repo.tag("v1.0.0")
        assert _parse_output(run_guard(repo, sha).stdout)["proceed"] == "true"

    def test_tag_prefix_alone_does_not_block(self, repo):
        """'2.0.0' must not be considered tagged by the existence of '2.0.0-rc1'."""
        repo.commit("1.0.0")
        sha = repo.commit("2.0.0")
        repo.tag("2.0.0-rc1")
        assert _parse_output(run_guard(repo, sha).stdout)["proceed"] == "true"


class TestUnmergedPullRequest:
    """A closed-but-unmerged PR must never release, even if it bumps the version."""

    def test_unmerged_pull_request_skips(self, repo):
        repo.commit("1.0.0")
        sha = repo.commit("2.0.0")
        result = run_guard(repo, sha, merged="false")
        output = _parse_output(result.stdout)
        assert output["proceed"] == "false"
        assert "without being merged" in output["reason"]

    def test_non_pull_request_event_is_unaffected_by_merged_flag(self, repo):
        repo.commit("1.0.0")
        sha = repo.commit("2.0.0")
        result = run_guard(repo, sha, event_name="push", merged="")
        assert _parse_output(result.stdout)["proceed"] == "true"


class TestFailsClosed:
    """Every undecidable case must refuse loudly rather than release quietly."""

    def test_shallow_clone_is_an_error_not_a_skip(self, repo, tmp_path):
        """The fetch-depth: 1 trap: a stuck guard must be loud, not green."""
        repo.commit("1.0.0")
        repo.commit("2.0.0")
        shallow = tmp_path / "shallow"
        subprocess.run(
            ["git", "clone", "--quiet", "--depth", "1", f"file://{repo.path}", str(shallow)],
            check=True,
            capture_output=True,
        )
        sha = _git(shallow, "rev-parse", "HEAD")
        result = run_script(
            SCRIPT_PATH,
            "--event-name",
            "pull_request",
            "--merge-sha",
            sha,
            "--pull-request-merged",
            "true",
            "--repo-dir",
            str(shallow),
        )
        assert result.returncode == 1
        assert "fetch-depth: 0" in result.stderr

    def test_missing_config_at_merge_commit_is_an_error(self, repo):
        repo.commit("1.0.0")
        _git(repo.path, "rm", "--quiet", ".github/project.yml")
        _git(repo.path, "commit", "--quiet", "-m", "remove config")
        sha = _git(repo.path, "rev-parse", "HEAD")
        result = run_guard(repo, sha)
        assert result.returncode == 1
        assert "current-version" in result.stderr

    def test_unknown_commit_is_an_error(self, repo):
        repo.commit("1.0.0")
        result = run_guard(repo, "0" * 40)
        assert result.returncode == 1

    def test_non_sha_merge_sha_is_an_error(self, repo):
        repo.commit("1.0.0")
        result = run_guard(repo, "refs/heads/main")
        assert result.returncode == 1

    def test_initial_commit_has_no_parent_and_errors(self, repo):
        sha = repo.commit("1.0.0")
        result = run_guard(repo, sha)
        assert result.returncode == 1
        assert "first parent" in result.stderr

    def test_hostile_version_value_is_rejected(self, repo):
        repo.commit("1.0.0")
        sha = repo.commit('"1.0.0; rm -rf /"')
        result = run_guard(repo, sha)
        assert result.returncode == 1
        assert "not a usable version" in result.stderr


class TestVersionExtraction:
    """Parsing details that decide whether the comparison means anything."""

    def test_unquoted_version_is_read_as_written(self, repo, tmp_path):
        """YAML would read an unquoted 1.10 as a float; 1.10 must not become 1.1."""
        repo.commit("1.0.0")
        (repo.path / ".github/project.yml").write_text("release:\n  current-version: 1.10\n")
        _git(repo.path, "add", "-A")
        _git(repo.path, "commit", "--quiet", "-m", "unquoted")
        sha = _git(repo.path, "rev-parse", "HEAD")
        result = run_guard(repo, sha)
        assert result.returncode == 0
        assert _parse_output(result.stdout)["current-version"] == "1.10"

    def test_reason_is_a_single_line(self, repo):
        """A multi-line reason would corrupt GITHUB_OUTPUT."""
        repo.commit("1.0.0")
        sha = repo.commit("1.0.0", java_versions='["25"]')
        assert len(run_guard(repo, sha).stdout.strip().split("\n")) == 4
