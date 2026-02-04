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
        result = run_script(
            SCRIPT_PATH, "--repo", "test", "--version", "1.0.0", "--sha", "short"
        )
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
        assert config["timeout"] == 240

    def test_no_github_automation_section(self, temp_dir):
        """Should return defaults when github-automation section is missing."""
        mod = _load_module()
        github_dir = temp_dir / ".github"
        github_dir.mkdir()
        (github_dir / "project.yml").write_text("name: test-repo\n")
        config = mod.read_auto_merge_config(temp_dir)
        assert config["enabled"] is True
        assert config["timeout"] == 240

    def test_auto_merge_disabled(self, temp_dir):
        """Should read disabled auto-merge setting."""
        mod = _load_module()
        github_dir = temp_dir / ".github"
        github_dir.mkdir()
        (github_dir / "project.yml").write_text(
            "github-automation:\n  auto-merge-build-versions: false\n"
        )
        config = mod.read_auto_merge_config(temp_dir)
        assert config["enabled"] is False
        assert config["timeout"] == 240

    def test_custom_timeout(self, temp_dir):
        """Should read custom timeout value."""
        mod = _load_module()
        github_dir = temp_dir / ".github"
        github_dir.mkdir()
        (github_dir / "project.yml").write_text(
            "github-automation:\n  auto-merge-build-timeout: 120\n"
        )
        config = mod.read_auto_merge_config(temp_dir)
        assert config["enabled"] is True
        assert config["timeout"] == 120

    def test_both_settings(self, temp_dir):
        """Should read both settings correctly."""
        mod = _load_module()
        github_dir = temp_dir / ".github"
        github_dir.mkdir()
        (github_dir / "project.yml").write_text(
            "github-automation:\n"
            "  auto-merge-build-versions: true\n"
            "  auto-merge-build-timeout: 300\n"
        )
        config = mod.read_auto_merge_config(temp_dir)
        assert config["enabled"] is True
        assert config["timeout"] == 300

    def test_invalid_yaml(self, temp_dir):
        """Should return defaults on invalid YAML."""
        mod = _load_module()
        github_dir = temp_dir / ".github"
        github_dir.mkdir()
        (github_dir / "project.yml").write_text(": invalid: yaml: [broken")
        config = mod.read_auto_merge_config(temp_dir)
        # Should fall back to defaults on parse error
        assert config["enabled"] is True
        assert config["timeout"] == 240
