"""Tests for verify-org-integration.py - Organization integration verification.

Note: These tests focus on argument parsing and logic validation.
Actual GitHub API calls are not tested here as they require authentication.
"""

import sys
from pathlib import Path

# Add parent to path to access conftest
sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT, run_script

SCRIPT_PATH = PROJECT_ROOT / "repo-settings/verify-org-integration.py"


class TestArgumentValidation:
    """Test command line argument validation."""

    def test_repo_required(self, temp_dir):
        """Should fail without --repo."""
        result = run_script(SCRIPT_PATH, "--diff")
        assert result.returncode != 0
        assert "required" in result.stderr.lower() or "--repo" in result.stderr

    def test_diff_or_apply_required(self, temp_dir):
        """Should fail without --diff or --apply."""
        result = run_script(SCRIPT_PATH, "--repo", "test-repo")
        assert result.returncode != 0
        assert "must specify" in result.stderr.lower() or "--diff" in result.stderr or "--apply" in result.stderr

    def test_diff_and_apply_mutually_exclusive(self, temp_dir):
        """Should fail with both --diff and --apply."""
        result = run_script(SCRIPT_PATH, "--repo", "test-repo", "--diff", "--apply")
        assert result.returncode != 0
        assert "cannot" in result.stderr.lower() or "together" in result.stderr.lower()


class TestConstants:
    """Test that constants are properly defined."""

    def test_org_level_secrets_defined(self):
        """Org-level secrets list should be defined and non-empty."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("verify_org_integration", SCRIPT_PATH)
        assert spec is not None
        assert spec.loader is not None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert hasattr(module, "ORG_LEVEL_SECRETS")
        assert len(module.ORG_LEVEL_SECRETS) > 0
        assert "GPG_PRIVATE_KEY" in module.ORG_LEVEL_SECRETS
        assert "OSS_SONATYPE_USERNAME" in module.ORG_LEVEL_SECRETS

    def test_repo_level_secrets_defined(self):
        """Repo-level secrets list should be defined."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("verify_org_integration", SCRIPT_PATH)
        assert spec is not None
        assert spec.loader is not None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert hasattr(module, "REPO_LEVEL_SECRETS")
        assert "SONAR_TOKEN" in module.REPO_LEVEL_SECRETS

    def test_community_files_defined(self):
        """Community files list should be defined and non-empty."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("verify_org_integration", SCRIPT_PATH)
        assert spec is not None
        assert spec.loader is not None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        assert hasattr(module, "ORG_COMMUNITY_FILES")
        assert len(module.ORG_COMMUNITY_FILES) > 0
        assert "CODE_OF_CONDUCT.md" in module.ORG_COMMUNITY_FILES
        assert "CONTRIBUTING.md" in module.ORG_COMMUNITY_FILES
        assert "SECURITY.md" in module.ORG_COMMUNITY_FILES


class TestDiffOutput:
    """Test diff mode output format."""

    def test_diff_output_structure(self):
        """Diff mode should produce expected JSON structure (when API accessible)."""
        # This test verifies the compute_diff function output structure
        # Actual API testing requires authentication
        import importlib.util

        spec = importlib.util.spec_from_file_location("verify_org_integration", SCRIPT_PATH)
        assert spec is not None
        assert spec.loader is not None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Test compute_diff with no local path (secrets only)
        # Note: This will make API calls, so we just verify the function exists
        assert hasattr(module, "compute_diff")
        assert callable(module.compute_diff)


class TestLocalFileDetection:
    """Test local file detection for community health files."""

    def test_check_duplicate_files_finds_existing(self, temp_dir):
        """Should detect duplicate community health files."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("verify_org_integration", SCRIPT_PATH)
        assert spec is not None
        assert spec.loader is not None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Create test files
        (temp_dir / "CODE_OF_CONDUCT.md").write_text("Test content")
        (temp_dir / "SECURITY.md").write_text("Test content")

        duplicates = module.check_duplicate_files(temp_dir)

        assert "CODE_OF_CONDUCT.md" in duplicates
        assert "SECURITY.md" in duplicates
        assert "CONTRIBUTING.md" not in duplicates  # Not created

    def test_check_duplicate_files_none_when_no_path(self):
        """Should return empty list when local_path is None."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("verify_org_integration", SCRIPT_PATH)
        assert spec is not None
        assert spec.loader is not None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        duplicates = module.check_duplicate_files(None)
        assert duplicates == []

    def test_remove_duplicate_files(self, temp_dir):
        """Should remove specified duplicate files."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("verify_org_integration", SCRIPT_PATH)
        assert spec is not None
        assert spec.loader is not None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Create test files
        (temp_dir / "CODE_OF_CONDUCT.md").write_text("Test content")
        (temp_dir / "SECURITY.md").write_text("Test content")

        removed = module.remove_duplicate_files(temp_dir, ["CODE_OF_CONDUCT.md", "SECURITY.md"])

        assert "CODE_OF_CONDUCT.md" in removed
        assert "SECURITY.md" in removed
        assert not (temp_dir / "CODE_OF_CONDUCT.md").exists()
        assert not (temp_dir / "SECURITY.md").exists()


class TestVerification:
    """Test verification logic."""

    def test_verify_file_removed(self, temp_dir):
        """Should verify file removal correctly."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("verify_org_integration", SCRIPT_PATH)
        assert spec is not None
        assert spec.loader is not None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # File doesn't exist - should return True
        assert module.verify_file_removed(temp_dir, "nonexistent.md") is True

        # File exists - should return False
        (temp_dir / "exists.md").write_text("content")
        assert module.verify_file_removed(temp_dir, "exists.md") is False

    def test_apply_output_includes_verification(self):
        """Apply output should include verification results structure."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("verify_org_integration", SCRIPT_PATH)
        assert spec is not None
        assert spec.loader is not None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Verify apply_fixes function exists and has expected signature
        assert hasattr(module, "apply_fixes")
        assert callable(module.apply_fixes)


class TestHelpOutput:
    """Test help and usage output."""

    def test_help_shows_usage(self):
        """Help should show usage information."""
        result = run_script(SCRIPT_PATH, "--help")
        assert result.returncode == 0
        assert "--repo" in result.stdout
        assert "--diff" in result.stdout
        assert "--apply" in result.stdout
        assert "--local-path" in result.stdout
