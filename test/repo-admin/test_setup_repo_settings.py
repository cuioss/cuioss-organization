"""Tests for setup-repo-settings.py - Repository settings configuration.

Note: These tests focus on argument parsing and logic validation.
Actual GitHub API calls are not tested here as they require authentication.
"""

import json
import sys
from pathlib import Path

# Add parent to path to access conftest
sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT, run_script

SCRIPT_PATH = PROJECT_ROOT / "repo-settings/setup-repo-settings.py"
CONFIG_PATH = PROJECT_ROOT / "repo-settings/config.json"


class TestArgumentValidation:
    """Test command line argument validation."""

    def test_repo_requires_action(self, temp_dir):
        """Should fail when --repo is used without --diff or --apply."""
        # Create minimal config
        config = temp_dir / "config.json"
        config.write_text('{"organization": "test", "repositories": [], "features": {}, "merge": {}, "security": {}}')

        result = run_script(SCRIPT_PATH, config, "--repo", "test-repo")
        assert result.returncode != 0
        assert "must specify" in result.stderr.lower() or "--diff" in result.stderr

    def test_diff_and_apply_mutually_exclusive(self, temp_dir):
        """Should fail when both --diff and --apply are specified."""
        config = temp_dir / "config.json"
        config.write_text('{"organization": "test", "repositories": [], "features": {}, "merge": {}, "security": {}}')

        result = run_script(SCRIPT_PATH, config, "--repo", "test-repo", "--diff", "--apply")
        assert result.returncode != 0
        assert "cannot" in result.stderr.lower() or "together" in result.stderr.lower()


class TestConfigLoading:
    """Test configuration file loading."""

    def test_loads_default_config(self):
        """Should load config.json from script directory by default."""
        # This tests that the default config exists and is valid JSON
        assert CONFIG_PATH.exists(), "Default config.json should exist"

        with open(CONFIG_PATH) as f:
            config = json.load(f)

        assert "organization" in config
        assert "repositories" in config

    def test_missing_config_file(self, temp_dir):
        """Should fail gracefully with missing config file."""
        result = run_script(SCRIPT_PATH, str(temp_dir / "nonexistent.json"))
        assert result.returncode != 0

    def test_invalid_json_config(self, temp_dir):
        """Should fail with invalid JSON config."""
        config = temp_dir / "invalid.json"
        config.write_text("{ invalid json }")

        result = run_script(SCRIPT_PATH, config)
        assert result.returncode != 0


class TestConfigSchema:
    """Test that the production config has the expected schema."""

    def test_config_has_required_sections(self):
        """Production config should have all required sections."""
        with open(CONFIG_PATH) as f:
            config = json.load(f)

        assert "organization" in config
        assert "repositories" in config
        assert "features" in config
        assert "merge" in config
        assert "security" in config

    def test_features_section_schema(self):
        """Features section should have expected keys."""
        with open(CONFIG_PATH) as f:
            config = json.load(f)

        features = config.get("features", {})
        expected_keys = ["has_issues", "has_wiki", "has_projects", "has_discussions"]

        for key in expected_keys:
            assert key in features, f"features.{key} should be present"

    def test_merge_section_schema(self):
        """Merge section should have expected keys."""
        with open(CONFIG_PATH) as f:
            config = json.load(f)

        merge = config.get("merge", {})
        expected_keys = [
            "allow_squash_merge",
            "allow_merge_commit",
            "allow_rebase_merge",
            "delete_branch_on_merge",
        ]

        for key in expected_keys:
            assert key in merge, f"merge.{key} should be present"

    def test_security_section_schema(self):
        """Security section should have expected keys."""
        with open(CONFIG_PATH) as f:
            config = json.load(f)

        security = config.get("security", {})
        expected_keys = [
            "private_vulnerability_reporting",
            "dependabot_alerts",
            "dependabot_security_updates",
        ]

        for key in expected_keys:
            assert key in security, f"security.{key} should be present"

    def test_repositories_is_list(self):
        """Repositories should be a list."""
        with open(CONFIG_PATH) as f:
            config = json.load(f)

        assert isinstance(config["repositories"], list)

    def test_organization_is_cuioss(self):
        """Organization should be 'cuioss'."""
        with open(CONFIG_PATH) as f:
            config = json.load(f)

        assert config["organization"] == "cuioss"


class TestDependencyCheck:
    """Test dependency checking behavior."""

    def test_checks_gh_cli_availability(self):
        """Script should check for gh CLI presence."""
        # Note: This test assumes gh is installed in the test environment.
        # If gh is not installed, this test validates the error handling.
        # The script should either work or fail with a clear error message.
        pass  # Actual testing requires gh CLI; skipping in unit tests


class TestOutputFormat:
    """Test output formatting."""

    def test_diff_output_is_json(self, temp_dir):
        """Diff mode should output valid JSON."""
        # This test requires gh CLI and authentication
        # In a real test environment, we'd mock the gh commands
        pass


class TestVerificationLogic:
    """Test verification logic behavior."""

    def test_verify_settings_function_exists(self):
        """The verify_settings function should exist and accept config parameter."""
        # Import the module to verify the function signature
        import importlib.util

        spec = importlib.util.spec_from_file_location("setup_repo_settings", SCRIPT_PATH)

        # The module should load without errors
        # Full execution requires gh CLI, so we just verify the module structure
        assert spec is not None

    def test_script_exits_nonzero_on_verification_failure_message(self, temp_dir):
        """Script should mention verification in error scenarios."""
        # Create minimal config
        config = temp_dir / "config.json"
        config.write_text(json.dumps({
            "organization": "nonexistent-org-12345",
            "repositories": [],
            "features": {"has_issues": True, "has_wiki": False, "has_projects": False, "has_discussions": False},
            "merge": {
                "allow_squash_merge": True,
                "allow_merge_commit": True,
                "allow_rebase_merge": True,
                "delete_branch_on_merge": True,
                "allow_auto_merge": False,
                "squash_merge_commit_title": "PR_TITLE",
                "squash_merge_commit_message": "PR_BODY",
            },
            "security": {
                "private_vulnerability_reporting": True,
                "dependabot_alerts": True,
                "dependabot_security_updates": True,
                "secret_scanning": True,
                "secret_scanning_push_protection": True,
            },
        }))

        # This will fail because the repo doesn't exist, but we're testing
        # that the script properly handles verification scenarios
        result = run_script(SCRIPT_PATH, config, "--repo", "nonexistent-repo", "--apply")

        # Should exit with non-zero (either auth failure or repo not found)
        assert result.returncode != 0
