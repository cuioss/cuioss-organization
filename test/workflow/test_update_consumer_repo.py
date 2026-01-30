"""Tests for update-consumer-repo.py argument validation."""

import sys
from pathlib import Path

# Add parent to path to access conftest
sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT, run_script

SCRIPT_PATH = PROJECT_ROOT / "workflow-scripts/update-consumer-repo.py"
VALID_SHA = "abcdef1234567890abcdef1234567890abcdef12"


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
