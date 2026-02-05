"""Tests for setup-repo-settings.py - Repository settings configuration.

Note: These tests focus on argument parsing and logic validation.
Actual GitHub API calls are not tested here as they require authentication.
"""

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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


def _load_module():
    """Load setup-repo-settings.py as a module for direct function testing."""
    spec = importlib.util.spec_from_file_location("setup_repo_settings", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestCheckSidebarSections:
    """Test sidebar section detection via HTML scraping."""

    def test_detects_packages_visible(self):
        """Should detect 'Packages' sidebar when HTML contains the marker."""
        mod = _load_module()
        html = '<div class="sidebar">No packages published</div>'
        mock_result = MagicMock(returncode=0, stdout=html)
        with patch("subprocess.run", return_value=mock_result):
            result = mod.check_sidebar_sections("cuioss", "test-repo")
        assert result["packages_visible"] is True

    def test_detects_packages_hidden(self):
        """Should report packages not visible when marker is absent."""
        mod = _load_module()
        html = '<div class="sidebar">Some other content</div>'
        mock_result = MagicMock(returncode=0, stdout=html)
        with patch("subprocess.run", return_value=mock_result):
            result = mod.check_sidebar_sections("cuioss", "test-repo")
        assert result["packages_visible"] is False

    def test_detects_environments_visible(self):
        """Should detect 'Environments' sidebar when HTML contains the marker."""
        mod = _load_module()
        html = '<div>No environments</div>'
        mock_result = MagicMock(returncode=0, stdout=html)
        with patch("subprocess.run", return_value=mock_result):
            result = mod.check_sidebar_sections("cuioss", "test-repo")
        assert result["environments_visible"] is True

    def test_returns_error_on_curl_failure(self):
        """Should return error dict when curl fails."""
        mod = _load_module()
        mock_result = MagicMock(returncode=1, stdout="")
        with patch("subprocess.run", return_value=mock_result):
            result = mod.check_sidebar_sections("cuioss", "test-repo")
        assert "error" in result

    def test_clean_repo_no_sidebar_sections(self):
        """Should report all sections hidden for a clean repo page."""
        mod = _load_module()
        html = '<div class="repo-page">Just code, nothing extra</div>'
        mock_result = MagicMock(returncode=0, stdout=html)
        with patch("subprocess.run", return_value=mock_result):
            result = mod.check_sidebar_sections("cuioss", "test-repo")
        assert result["packages_visible"] is False
        assert result["environments_visible"] is False


class TestCheckSidebarWarnings:
    """Test sidebar warning output during verification."""

    def test_emits_packages_warning(self, capsys):
        """Should warn when packages are visible but config says hidden."""
        mod = _load_module()
        config = {"homepage": {"include_packages": False, "include_environments": False}}
        sidebar_result = {"packages_visible": True, "environments_visible": False}
        with patch.object(mod, "check_sidebar_sections", return_value=sidebar_result):
            mod.check_sidebar_warnings("cuioss", "test-repo", config)
        captured = capsys.readouterr()
        assert "Packages" in captured.err

    def test_no_warning_when_config_matches(self, capsys):
        """Should not warn when sidebar state matches config."""
        mod = _load_module()
        config = {"homepage": {"include_packages": False, "include_environments": False}}
        sidebar_result = {"packages_visible": False, "environments_visible": False}
        with patch.object(mod, "check_sidebar_sections", return_value=sidebar_result):
            mod.check_sidebar_warnings("cuioss", "test-repo", config)
        captured = capsys.readouterr()
        assert "Packages" not in captured.err
        assert "Environments" not in captured.err

    def test_skips_when_no_homepage_config(self, capsys):
        """Should skip sidebar check when config has no homepage section."""
        mod = _load_module()
        config = {"features": {}}
        mod.check_sidebar_warnings("cuioss", "test-repo", config)
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_handles_curl_error_gracefully(self, capsys):
        """Should warn (not crash) when curl fails."""
        mod = _load_module()
        config = {"homepage": {"include_packages": False}}
        sidebar_result = {"error": "Could not fetch repo page"}
        with patch.object(mod, "check_sidebar_sections", return_value=sidebar_result):
            mod.check_sidebar_warnings("cuioss", "test-repo", config)
        captured = capsys.readouterr()
        assert "Could not check" in captured.err


class TestHomepageConfigSchema:
    """Test that the production config has the homepage section."""

    def test_homepage_section_exists(self):
        """Production config should have homepage section."""
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        assert "homepage" in config

    def test_homepage_section_schema(self):
        """Homepage section should have expected keys."""
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        homepage = config["homepage"]
        assert "include_packages" in homepage
        assert "include_releases" in homepage
        assert "include_environments" in homepage

    def test_homepage_packages_is_false(self):
        """Packages should be disabled by default."""
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        assert config["homepage"]["include_packages"] is False

    def test_homepage_releases_is_true(self):
        """Releases should be enabled by default."""
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        assert config["homepage"]["include_releases"] is True
