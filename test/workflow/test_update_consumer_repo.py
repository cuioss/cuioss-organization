"""Tests for update-consumer-repo.py argument validation and auto-merge config."""

import importlib.util
import sys
from pathlib import Path

# Add parent to path to access conftest
sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT, run_script

SCRIPT_PATH = PROJECT_ROOT / "workflow-scripts/update-consumer-repo.py"
VALID_SHA = "abcdef1234567890abcdef1234567890abcdef12"


def _load_module():
    """Load update-consumer-repo.py as a module for unit testing."""
    spec = importlib.util.spec_from_file_location("update_consumer_repo", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestArgumentValidation:
    """Test command line argument validation."""

    def test_requires_repo_argument(self):
        """Should fail without --repo argument."""
        result = run_script(SCRIPT_PATH, "--version", "1.0.0", "--sha", VALID_SHA)
        assert result.returncode != 0
        assert "required" in result.stderr.lower() or "--repo" in result.stderr

    def test_requires_version_argument(self):
        """Should fail without --version argument."""
        result = run_script(SCRIPT_PATH, "--repo", "test", "--sha", VALID_SHA)
        assert result.returncode != 0
        assert "required" in result.stderr.lower() or "--version" in result.stderr

    def test_requires_sha_argument(self):
        """Should fail without --sha argument."""
        result = run_script(SCRIPT_PATH, "--repo", "test", "--version", "1.0.0")
        assert result.returncode != 0
        assert "required" in result.stderr.lower() or "--sha" in result.stderr

    def test_validates_sha_length(self):
        """Should reject SHA that's not 40 characters."""
        result = run_script(SCRIPT_PATH, "--repo", "test", "--version", "1.0.0", "--sha", "short")
        assert result.returncode != 0
        assert "40" in result.stderr

    def test_accepts_valid_arguments(self):
        """Should accept valid arguments (will fail on clone, but validates args)."""
        result = run_script(
            SCRIPT_PATH,
            "--repo",
            "nonexistent-repo-12345",
            "--version",
            "1.0.0",
            "--sha",
            VALID_SHA,
        )
        # Will fail because repo doesn't exist, but should get past argument validation
        # The error should be about cloning, not about arguments
        assert "40" not in result.stderr
        assert "required" not in result.stderr.lower()

    def test_accepts_custom_org(self):
        """Should accept --org argument."""
        result = run_script(
            SCRIPT_PATH,
            "--org",
            "custom-org",
            "--repo",
            "test",
            "--version",
            "1.0.0",
            "--sha",
            VALID_SHA,
        )
        # Will fail on clone but should accept the org argument
        assert "Processing custom-org/test" in result.stdout


class TestAutoMergeConfig:
    """Test read_auto_merge_config function."""

    def test_no_project_yml(self, temp_dir):
        """Should return defaults when project.yml doesn't exist."""
        mod = _load_module()
        config = mod.read_auto_merge_config(temp_dir)
        assert config["enabled"] is True
        assert "timeout" not in config

    def test_no_github_automation_section(self, temp_dir):
        """Should return defaults when github-automation section is missing."""
        mod = _load_module()
        github_dir = temp_dir / ".github"
        github_dir.mkdir()
        (github_dir / "project.yml").write_text("name: test-repo\n")
        config = mod.read_auto_merge_config(temp_dir)
        assert config["enabled"] is True
        assert "timeout" not in config

    def test_auto_merge_disabled(self, temp_dir):
        """Should read disabled auto-merge setting."""
        mod = _load_module()
        github_dir = temp_dir / ".github"
        github_dir.mkdir()
        (github_dir / "project.yml").write_text("github-automation:\n  auto-merge-build-versions: false\n")
        config = mod.read_auto_merge_config(temp_dir)
        assert config["enabled"] is False

    def test_auto_merge_enabled(self, temp_dir):
        """Should read enabled auto-merge setting."""
        mod = _load_module()
        github_dir = temp_dir / ".github"
        github_dir.mkdir()
        (github_dir / "project.yml").write_text("github-automation:\n  auto-merge-build-versions: true\n")
        config = mod.read_auto_merge_config(temp_dir)
        assert config["enabled"] is True

    def test_invalid_yaml(self, temp_dir):
        """Should return defaults on invalid YAML."""
        mod = _load_module()
        github_dir = temp_dir / ".github"
        github_dir.mkdir()
        (github_dir / "project.yml").write_text(": invalid: yaml: [broken")
        config = mod.read_auto_merge_config(temp_dir)
        # Should fall back to defaults on parse error
        assert config["enabled"] is True
        assert "timeout" not in config


class TestOwnerRouting:
    """`--org` decides which account the clone — and with it every later call — addresses."""

    def test_another_organisation_is_cloned_from_that_organisation(self):
        from subprocess import CompletedProcess
        from unittest.mock import patch

        mod = _load_module()
        cloned = []

        def clone(full_repo, target_dir):
            cloned.append(full_repo)
            return CompletedProcess([], 1, "", "not found")

        with patch.object(mod, "clone_consumer_repo", clone):
            result = mod.update_consumer_repo(
                "plan-marshall", "plan-marshall-mcp", "1.0.0", VALID_SHA, SCRIPT_PATH.parent
            )
        assert cloned == ["plan-marshall/plan-marshall-mcp"]
        assert result["status"] == "error"


class TestPushTriggerNormalization:
    """The fan-out rewrites the push trigger in the same PR as the pin bump.

    Runs the real `update_consumer_repo` against a local git repository standing in
    for the clone; only the clone itself and the GitHub calls (PR, stale PRs) are
    replaced.
    """

    OLD_SHA = "1" * 40
    CALLER = (
        "name: Maven Build\n"
        "on:\n"
        "  push:\n"
        '    branches: [main, "feature/*", "fix/*", "chore/*", "!chore/orchestrator-ledger", "release/*"]\n'
        "  pull_request:\n"
        "    branches: [main]\n"
        "jobs:\n"
        "  build:\n"
        "    uses: cuioss/cuioss-organization/.github/workflows/reusable-maven-build.yml@3e1ecafb6a194fe22fc6a9bfdc2a41c81584f989 # v0.43.0\n"
    )

    def _run(self, tmp_path, monkeypatch, caller, project_yml=None):
        import subprocess
        from unittest.mock import patch

        for name, value in (("NAME", "t"), ("EMAIL", "t@example.com")):
            monkeypatch.setenv(f"GIT_AUTHOR_{name}", value)
            monkeypatch.setenv(f"GIT_COMMITTER_{name}", value)
        mod = _load_module()
        seen = {}

        def clone(full_repo, target_dir):
            target_dir.mkdir(parents=True)
            workflows = target_dir / ".github" / "workflows"
            workflows.mkdir(parents=True)
            (workflows / "maven.yml").write_text(caller)
            if project_yml is not None:
                (target_dir / ".github" / "project.yml").write_text(project_yml)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=target_dir, check=True)
            subprocess.run(["git", "add", "-A"], cwd=target_dir, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=target_dir, check=True)
            return subprocess.CompletedProcess([], 0, "", "")

        def create_pr(full_repo, repo_dir, branch, title, body, auto_merge_config):
            seen["body"] = body
            seen["message"] = subprocess.run(
                ["git", "log", "-1", "--format=%B"], cwd=repo_dir, capture_output=True, text=True, check=True
            ).stdout
            seen["caller"] = (repo_dir / ".github" / "workflows" / "maven.yml").read_text()
            return mod.make_result("pr_created", pr_url="https://github.com/cuioss/x/pull/1")

        with (
            patch.object(mod, "clone_consumer_repo", clone),
            patch.object(mod, "create_pr_and_auto_merge", create_pr),
            patch.object(mod, "close_stale_prs"),
        ):
            result = mod.update_consumer_repo("cuioss", "x", "0.2.0", VALID_SHA, SCRIPT_PATH.parent)
        return result, seen

    def test_pin_bump_and_trigger_change_land_in_one_pr(self, tmp_path, monkeypatch):
        """Should bump the pin and strip the working-branch patterns together."""
        result, seen = self._run(tmp_path, monkeypatch, self.CALLER.format(sha=self.OLD_SHA))
        assert result["status"] == "pr_created"
        assert "notes" not in result
        assert f"@{VALID_SHA} # v0.2.0" in seen["caller"]
        assert '  push:\n    branches: [main, "release/*"]\n' in seen["caller"]
        assert '  pull_request:\n    branches: [main, "release/*"]\n' in seen["caller"]
        assert "no longer lists feature/fix/chore branches" in seen["message"]
        assert "ci.push-builds: deduplicated" in seen["body"]

    def test_a_trigger_only_change_still_opens_a_pr(self, tmp_path, monkeypatch):
        """Should not report 'no changes' for a consumer whose pins are current but whose trigger is old."""
        result, seen = self._run(tmp_path, monkeypatch, self.CALLER.format(sha=VALID_SHA).replace("v0.1.0", "v0.2.0"))
        assert result["status"] == "pr_created"
        assert 'branches: [main, "release/*"]' in seen["caller"]

    def test_a_repository_that_keeps_push_builds_gets_only_the_pin_bump(self, tmp_path, monkeypatch):
        """Should honour ci.push-builds: deduplicated in the consumer's project.yml."""
        result, seen = self._run(
            tmp_path,
            monkeypatch,
            self.CALLER.format(sha=self.OLD_SHA),
            project_yml="ci:\n  push-builds: deduplicated\n",
        )
        assert result["status"] == "pr_created"
        assert f"@{VALID_SHA} # v0.2.0" in seen["caller"]
        assert '"feature/*"' in seen["caller"]
        assert "Push trigger" not in seen["message"]

    def test_an_unreadable_trigger_is_reported_not_guessed(self, tmp_path, monkeypatch):
        """Should leave a trigger it cannot read alone and say so, in the PR and in the result."""
        caller = self.CALLER.format(sha=self.OLD_SHA).replace(
            'branches: [main, "feature/*", "fix/*", "chore/*", "!chore/orchestrator-ledger", "release/*"]',
            'branches: [main,\n      "feature/*"]',
        )
        result, seen = self._run(tmp_path, monkeypatch, caller)
        assert result["status"] == "pr_created"
        assert len(result["notes"]) == 1
        assert result["notes"][0].startswith(".github/workflows/maven.yml:")
        assert "Needs a manual edit" in seen["body"]
        assert '"feature/*"' in seen["caller"]

    def test_an_unreadable_trigger_with_current_pins_is_no_changes_with_a_note(self, tmp_path, monkeypatch):
        """Should surface the note even when there is nothing to commit."""
        caller = (
            self.CALLER.format(sha=VALID_SHA)
            .replace("v0.1.0", "v0.2.0")
            .replace(
                'branches: [main, "feature/*", "fix/*", "chore/*", "!chore/orchestrator-ledger", "release/*"]',
                'branches: [main,\n      "feature/*"]',
            )
        )
        result, _ = self._run(tmp_path, monkeypatch, caller)
        assert result["status"] == "no_changes"
        assert len(result["notes"]) == 1
