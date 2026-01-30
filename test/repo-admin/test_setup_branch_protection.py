"""Tests for setup-branch-protection.py - Branch protection ruleset configuration.

Note: These tests focus on argument parsing and logic validation.
Actual GitHub API calls are not tested here as they require authentication.
"""

import json
import sys
from pathlib import Path

# Add parent to path to access conftest
sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT, run_script

SCRIPT_PATH = PROJECT_ROOT / "branch-protection/setup-branch-protection.py"
CONFIG_PATH = PROJECT_ROOT / "branch-protection/config.json"


class TestArgumentValidation:
    """Test command line argument validation."""

    def test_repo_requires_action(self, temp_dir):
        """Should fail when --repo is used without --diff or --apply."""
        config = temp_dir / "config.json"
        config.write_text(json.dumps({
            "organization": "test",
            "repositories": [],
            "bypass_actor": {"name": "test-app", "type": "Integration"},
            "ruleset": {
                "name": "test",
                "enforcement": "active",
                "branch_pattern": "main",
                "rules": {
                    "require_pull_request": {
                        "required_approving_review_count": 0,
                        "dismiss_stale_reviews_on_push": False,
                        "require_last_push_approval": False,
                    },
                    "require_status_checks": {
                        "strict_required_status_checks_policy": False,
                        "required_checks": [],
                    },
                },
            },
        }))

        result = run_script(SCRIPT_PATH, config, "--repo", "test-repo")
        assert result.returncode != 0
        assert "must specify" in result.stderr.lower() or "--diff" in result.stderr

    def test_diff_and_apply_mutually_exclusive(self, temp_dir):
        """Should fail when both --diff and --apply are specified."""
        config = temp_dir / "config.json"
        config.write_text(json.dumps({
            "organization": "test",
            "repositories": [],
            "bypass_actor": {"name": "test-app", "type": "Integration"},
            "ruleset": {
                "name": "test",
                "enforcement": "active",
                "branch_pattern": "main",
                "rules": {
                    "require_pull_request": {
                        "required_approving_review_count": 0,
                        "dismiss_stale_reviews_on_push": False,
                        "require_last_push_approval": False,
                    },
                    "require_status_checks": {
                        "strict_required_status_checks_policy": False,
                        "required_checks": [],
                    },
                },
            },
        }))

        result = run_script(SCRIPT_PATH, config, "--repo", "test-repo", "--diff", "--apply")
        assert result.returncode != 0
        assert "cannot" in result.stderr.lower() or "together" in result.stderr.lower()


class TestConfigLoading:
    """Test configuration file loading."""

    def test_loads_default_config(self):
        """Should load config.json from script directory by default."""
        assert CONFIG_PATH.exists(), "Default config.json should exist"

        with open(CONFIG_PATH) as f:
            config = json.load(f)

        assert "organization" in config
        assert "ruleset" in config

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
        assert "bypass_actor" in config
        assert "ruleset" in config

    def test_bypass_actor_schema(self):
        """Bypass actor should have required fields."""
        with open(CONFIG_PATH) as f:
            config = json.load(f)

        bypass_actor = config.get("bypass_actor", {})
        assert "name" in bypass_actor
        assert "type" in bypass_actor

    def test_ruleset_schema(self):
        """Ruleset should have required fields."""
        with open(CONFIG_PATH) as f:
            config = json.load(f)

        ruleset = config.get("ruleset", {})
        assert "name" in ruleset
        assert "enforcement" in ruleset
        assert "branch_pattern" in ruleset
        assert "rules" in ruleset

    def test_ruleset_rules_schema(self):
        """Ruleset rules should have expected structure."""
        with open(CONFIG_PATH) as f:
            config = json.load(f)

        rules = config.get("ruleset", {}).get("rules", {})
        assert "require_pull_request" in rules
        assert "require_status_checks" in rules

    def test_pull_request_rules_schema(self):
        """Pull request rules should have expected fields (defaults for non-CLI options)."""
        with open(CONFIG_PATH) as f:
            config = json.load(f)

        pr_rules = config.get("ruleset", {}).get("rules", {}).get("require_pull_request", {})
        # Only check fields that are defaults, not CLI-provided ones
        expected_keys = [
            "dismiss_stale_reviews_on_push",
            "require_last_push_approval",
        ]

        for key in expected_keys:
            assert key in pr_rules, f"require_pull_request.{key} should be present"

    def test_status_checks_rules_schema(self):
        """Status checks rules should have expected fields (defaults for non-CLI options)."""
        with open(CONFIG_PATH) as f:
            config = json.load(f)

        sc_rules = config.get("ruleset", {}).get("rules", {}).get("require_status_checks", {})
        # Only check fields that are defaults, required_checks is provided via CLI
        assert "strict_required_status_checks_policy" in sc_rules

    def test_organization_is_cuioss(self):
        """Organization should be 'cuioss'."""
        with open(CONFIG_PATH) as f:
            config = json.load(f)

        assert config["organization"] == "cuioss"

    def test_bypass_actor_is_release_bot(self):
        """Bypass actor should be the release bot."""
        with open(CONFIG_PATH) as f:
            config = json.load(f)

        assert config["bypass_actor"]["name"] == "cuioss-release-bot"
        assert config["bypass_actor"]["type"] == "app"


class TestRulesetPayloadBuild:
    """Test ruleset payload construction logic."""

    def test_enforcement_values(self):
        """Enforcement should be one of the valid values."""
        with open(CONFIG_PATH) as f:
            config = json.load(f)

        enforcement = config["ruleset"]["enforcement"]
        valid_values = ["active", "disabled", "evaluate"]
        assert enforcement in valid_values, f"enforcement should be one of {valid_values}"

    def test_branch_pattern_is_main(self):
        """Branch pattern should typically be 'main'."""
        with open(CONFIG_PATH) as f:
            config = json.load(f)

        assert config["ruleset"]["branch_pattern"] == "main"
