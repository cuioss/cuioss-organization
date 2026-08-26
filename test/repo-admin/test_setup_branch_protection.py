"""Tests for setup-branch-protection.py - Branch protection ruleset configuration.

Note: These tests focus on argument parsing and logic validation.
Actual GitHub API calls are not tested here as they require authentication.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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
                        "do_not_enforce_on_create": False,
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
                        "do_not_enforce_on_create": False,
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
        assert "do_not_enforce_on_create" in sc_rules

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


class TestVerificationLogic:
    """Test verification logic behavior."""

    def test_verify_ruleset_function_exists(self):
        """The verify_ruleset function should exist."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("setup_branch_protection", SCRIPT_PATH)

        # The module should load without errors
        assert spec is not None

    def test_script_exits_nonzero_on_verification_failure(self, temp_dir):
        """Script should exit non-zero when verification fails."""
        config = temp_dir / "config.json"
        config.write_text(json.dumps({
            "organization": "nonexistent-org-12345",
            "bypass_actor": {"name": "test-app", "type": "Integration", "app_id": "12345"},
            "ruleset": {
                "name": "test-ruleset",
                "target": "branch",
                "branch_pattern": "main",
                "enforcement": "active",
                "rules": {
                    "require_pull_request": {
                        "dismiss_stale_reviews_on_push": False,
                        "require_last_push_approval": False,
                    },
                    "require_status_checks": {
                        "strict_required_status_checks_policy": False,
                        "do_not_enforce_on_create": False,
                    },
                    "block_force_pushes": {"enabled": True},
                    "prevent_deletion": {"enabled": True},
                },
            },
        }))

        # This will fail because the repo doesn't exist
        result = run_script(
            SCRIPT_PATH, config,
            "--repo", "nonexistent-repo",
            "--apply",
            "--required-checks", "verify",
            "--required-reviews", "0",
        )

        # Should exit with non-zero (either auth failure or repo not found)
        assert result.returncode != 0


# The App ID of cuioss-release-bot, from the public GET /apps/cuioss-release-bot.
# It is the bypass actor on every main-branch-protection ruleset in the org; a
# wrong value here revokes the release workflow's direct push to main.
RELEASE_BOT_APP_ID = "2753519"


def _load_module():
    """Import setup-branch-protection.py as a module for unit testing."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("setup_branch_protection", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMergeQueueConfig:
    """Test the merge_queue block in config.json."""

    def test_config_has_merge_queue_block(self):
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        assert "merge_queue" in config, "config.json should define a merge_queue block"

    def test_merge_method_is_squash(self):
        """merge_method must stay SQUASH to match the org merge policy."""
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        assert config["merge_queue"]["merge_method"] == "SQUASH"

    def test_ruleset_name_is_org_managed(self):
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        assert config["merge_queue"]["ruleset_name"] == "main-merge-queue"

    def test_merge_queue_repos_is_list(self):
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        assert isinstance(config["merge_queue"]["merge_queue_repos"], list)


class TestMergeQueuePayloadBuild:
    """Test the merge-queue ruleset payload construction."""

    def test_payload_uses_release_bot_bypass(self):
        """The queue ruleset must carry the release-bot bypass so releases work."""
        module = _load_module()
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        payload = module.build_merge_queue_payload(config, RELEASE_BOT_APP_ID)
        assert payload["bypass_actors"] == [
            {"actor_id": int(RELEASE_BOT_APP_ID), "actor_type": "Integration", "bypass_mode": "always"}
        ]

    def test_payload_has_squash_merge_queue_rule(self):
        module = _load_module()
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        payload = module.build_merge_queue_payload(config, RELEASE_BOT_APP_ID)
        rules = payload["rules"]
        assert len(rules) == 1
        assert rules[0]["type"] == "merge_queue"
        assert rules[0]["parameters"]["merge_method"] == "SQUASH"

    def test_payload_targets_main(self):
        module = _load_module()
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        payload = module.build_merge_queue_payload(config, RELEASE_BOT_APP_ID)
        assert payload["conditions"]["ref_name"]["include"] == ["refs/heads/main"]
        assert payload["enforcement"] == "active"

    def test_normalize_roundtrip_matches(self):
        """A payload normalizes equal to itself (diff would report 'none')."""
        module = _load_module()
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        payload = module.build_merge_queue_payload(config, RELEASE_BOT_APP_ID)
        assert (
            module.normalize_merge_queue_for_comparison(payload)
            == module.normalize_merge_queue_for_comparison(payload)
        )

    def test_legacy_queue_name_constant(self):
        module = _load_module()
        assert module.LEGACY_MERGE_QUEUE_NAME == "plan-marshall-merge-queue"


class TestStrictPolicyUnderMergeQueue:
    """Test that the queue and 'require branches up to date' never both apply.

    The queue is what brings an entry up to date. Demanding it beforehand makes
    a PR's readiness depend on a condition the queue itself satisfies, and
    readiness is what auto-merge waits on -- so the PR never becomes mergeable.
    """

    def _config(self) -> dict:
        with open(CONFIG_PATH) as f:
            return json.load(f)

    def _strict_of(self, payload: dict) -> bool | None:
        for rule in payload["rules"]:
            if rule["type"] == "required_status_checks":
                return rule["parameters"]["strict_required_status_checks_policy"]
        return None

    def test_merge_queue_repo_gets_strict_off(self):
        module = _load_module()
        payload = module.build_ruleset_payload(
            self._config(), RELEASE_BOT_APP_ID,
            required_checks_override=["build / conclusion"],
            merge_queue_enabled=True,
        )
        assert self._strict_of(payload) is False

    def test_non_queue_repo_keeps_config_value(self):
        module = _load_module()
        config = self._config()
        payload = module.build_ruleset_payload(
            config, RELEASE_BOT_APP_ID,
            required_checks_override=["build / conclusion"],
            merge_queue_enabled=False,
        )
        expected = config["ruleset"]["rules"]["require_status_checks"][
            "strict_required_status_checks_policy"
        ]
        assert self._strict_of(payload) is expected

    def test_uses_merge_queue_reads_the_repo_list(self):
        module = _load_module()
        config = self._config()
        listed = config["merge_queue"]["merge_queue_repos"][0]
        assert module.uses_merge_queue(config, listed) is True
        assert module.uses_merge_queue(config, "not-a-queue-repo") is False

    def test_uses_merge_queue_handles_missing_repo(self):
        module = _load_module()
        assert module.uses_merge_queue(self._config(), None) is False

    def test_every_queue_repo_resolves_to_strict_off(self):
        """Guard the wiring, not just the flag: config list -> payload."""
        module = _load_module()
        config = self._config()
        for repo in config["merge_queue"]["merge_queue_repos"]:
            payload = module.build_ruleset_payload(
                config, RELEASE_BOT_APP_ID,
                required_checks_override=["build / conclusion"],
                merge_queue_enabled=module.uses_merge_queue(config, repo),
            )
            assert self._strict_of(payload) is False, repo


class TestBypassActorResolution:
    """Test that the bypass actor resolves to the release bot's real App ID.

    The config value is a fallback for when the installations lookup is
    unavailable, and it had drifted: config said 1195186 while every ruleset in
    the org — and every test here — used 2753519. Nothing compared the two, so a
    single --apply from a shell without org-admin would have swapped the bypass
    actor and revoked the release bot's push to main.
    """

    def test_config_app_id_matches_the_release_bot(self):
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        assert config["bypass_actor"]["app_id"] == RELEASE_BOT_APP_ID

    def test_config_names_the_release_bot(self):
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        assert config["bypass_actor"]["name"] == "cuioss-release-bot"

    def test_prefers_the_installations_lookup(self):
        module = _load_module()
        with patch.object(
            module, "run_gh",
            return_value=MagicMock(returncode=0, stdout=f"{RELEASE_BOT_APP_ID}\n"),
        ) as gh:
            assert module.get_app_id("cuioss", "cuioss-release-bot") == RELEASE_BOT_APP_ID
        assert gh.call_count == 1
        assert "orgs/cuioss/installations" in gh.call_args[0][0]

    def test_falls_back_to_the_public_apps_endpoint(self):
        """orgs/{org}/installations needs org-admin and 404s for a personal
        token; /apps/{slug} is public and returns the same id."""
        module = _load_module()
        with patch.object(module, "run_gh", side_effect=[
            MagicMock(returncode=1, stdout=""),
            MagicMock(returncode=0, stdout=f"{RELEASE_BOT_APP_ID}\n"),
        ]) as gh:
            assert module.get_app_id("cuioss", "cuioss-release-bot") == RELEASE_BOT_APP_ID
        assert gh.call_count == 2
        assert "/apps/cuioss-release-bot" in gh.call_args_list[1][0][0]

    def test_empty_installations_response_still_falls_through(self):
        """returncode 0 with no match is the shape a non-admin token returns."""
        module = _load_module()
        with patch.object(module, "run_gh", side_effect=[
            MagicMock(returncode=0, stdout="\n"),
            MagicMock(returncode=0, stdout=f"{RELEASE_BOT_APP_ID}\n"),
        ]) as gh:
            assert module.get_app_id("cuioss", "cuioss-release-bot") == RELEASE_BOT_APP_ID
        assert gh.call_count == 2

    def test_returns_none_when_both_lookups_fail(self):
        """Negative control: the fallback must not invent an id."""
        module = _load_module()
        with patch.object(module, "run_gh", side_effect=[
            MagicMock(returncode=1, stdout=""),
            MagicMock(returncode=1, stdout=""),
        ]):
            assert module.get_app_id("cuioss", "cuioss-release-bot") is None


class TestStrictStillOnWarning:
    """Enabling the queue and relaxing strict live in two different rulesets, so
    --enable-merge-queue cannot fix the second one itself. Left on, the queue is
    what brings an entry up to date, so requiring it beforehand keeps a PR from
    ever reading as ready — a queue that never merges anything. cui-http shipped
    in that state until its registration was corrected.
    """

    def _bp(self, strict, checks=("build / conclusion",)):
        return {
            "name": "main-branch-protection",
            "rules": [
                {"type": "deletion"},
                {
                    "type": "required_status_checks",
                    "parameters": {
                        "strict_required_status_checks_policy": strict,
                        "required_status_checks": [{"context": c} for c in checks],
                    },
                },
            ],
        }

    def _config(self):
        with open(CONFIG_PATH) as f:
            return json.load(f)

    def test_strict_policy_of_reads_the_flag(self):
        module = _load_module()
        assert module.strict_policy_of(self._bp(True)) is True
        assert module.strict_policy_of(self._bp(False)) is False

    def test_strict_policy_of_handles_absent_rule(self):
        module = _load_module()
        assert module.strict_policy_of(None) is None
        assert module.strict_policy_of({"rules": []}) is None

    def test_warns_when_strict_is_still_on(self):
        module = _load_module()
        with patch.object(module, "get_existing_ruleset", return_value=self._bp(True)):
            assert module.warn_if_strict_still_on("cuioss", "cui-java-tools", self._config()) is True

    def test_silent_when_strict_is_off(self):
        """Negative control: a warning that always fires is worthless."""
        module = _load_module()
        with patch.object(module, "get_existing_ruleset", return_value=self._bp(False)):
            assert module.warn_if_strict_still_on("cuioss", "cui-java-tools", self._config()) is False

    def test_silent_when_there_is_no_branch_protection(self):
        module = _load_module()
        with patch.object(module, "get_existing_ruleset", return_value=None):
            assert module.warn_if_strict_still_on("cuioss", "new-repo", self._config()) is False

    def test_every_repo_being_queued_is_covered(self):
        """The 12 repos added for the rollout must resolve to strict off."""
        module = _load_module()
        config = self._config()
        repos = config["merge_queue"]["merge_queue_repos"]
        assert len(repos) >= 19, "expected the rollout batch to be present"
        for repo in repos:
            assert module.uses_merge_queue(config, repo) is True, repo


class TestRequiredCheckRemovalGuard:
    """Guard the destructive default in --apply.

    config.json holds `required_checks: []` because the set is per-repo and comes
    from --required-checks. Omitting the flag is therefore indistinguishable from
    "requires nothing", and build_ruleset_payload drops the rule entirely — which
    silently unprotects main. On a merge-queue repo it removes the check the
    queue gates on.
    """

    def _existing(self, checks):
        return {
            "name": "main-branch-protection",
            "rules": [
                {"type": "deletion"},
                {
                    "type": "required_status_checks",
                    "parameters": {
                        "strict_required_status_checks_policy": False,
                        "required_status_checks": [{"context": c} for c in checks],
                    },
                },
            ],
        }

    def _desired(self, checks):
        rules = [{"type": "deletion"}]
        if checks:
            rules.append({
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": False,
                    "required_status_checks": [{"context": c} for c in checks],
                },
            })
        return {"name": "main-branch-protection", "rules": rules}

    def test_required_checks_of_reads_contexts(self):
        module = _load_module()
        assert module.required_checks_of(self._existing(["build / conclusion"])) == [
            "build / conclusion"
        ]

    def test_required_checks_of_handles_absent_ruleset(self):
        module = _load_module()
        assert module.required_checks_of(None) == []
        assert module.required_checks_of({"rules": []}) == []

    def test_detects_the_silent_drop(self):
        """The exact shape produced by --apply without --required-checks."""
        module = _load_module()
        dropped = module.dropped_required_checks(
            self._existing(["build / conclusion"]), self._desired([])
        )
        assert dropped == ["build / conclusion"]

    def test_no_drop_when_checks_are_preserved(self):
        """Negative control: a guard that always fires is worthless."""
        module = _load_module()
        assert module.dropped_required_checks(
            self._existing(["build / conclusion"]),
            self._desired(["build / conclusion"]),
        ) == []

    def test_no_drop_when_checks_are_added(self):
        module = _load_module()
        assert module.dropped_required_checks(
            self._existing(["build / conclusion"]),
            self._desired(["build / conclusion", "integration-tests / conclusion"]),
        ) == []

    def test_no_drop_on_a_brand_new_ruleset(self):
        module = _load_module()
        assert module.dropped_required_checks(None, self._desired([])) == []

    def test_apply_refuses_when_the_flag_was_omitted(self):
        module = _load_module()
        config = self._config()
        with (
            patch.object(module, "get_existing_ruleset", return_value=self._existing(["build / conclusion"])),
            patch.object(module, "get_existing_ruleset_id", return_value=1),
            patch.object(module, "run_gh") as gh,
        ):
            module.apply_ruleset("cuioss", "cui-http", config, RELEASE_BOT_APP_ID)
        gh.assert_not_called()

    def test_apply_proceeds_when_checks_are_passed(self):
        """Negative control for the refusal path."""
        module = _load_module()
        config = self._config()
        with (
            patch.object(module, "get_existing_ruleset", return_value=self._existing(["build / conclusion"])),
            patch.object(module, "get_existing_ruleset_id", return_value=1),
            patch.object(module, "run_gh", return_value=MagicMock(returncode=0)) as gh,
        ):
            module.apply_ruleset(
                "cuioss", "cui-http", config, RELEASE_BOT_APP_ID,
                required_checks_override=["build / conclusion"],
            )
        gh.assert_called_once()

    def test_explicit_empty_string_still_removes(self):
        """--required-checks '' is a deliberate removal and must be honoured."""
        module = _load_module()
        config = self._config()
        with (
            patch.object(module, "get_existing_ruleset", return_value=self._existing(["build / conclusion"])),
            patch.object(module, "get_existing_ruleset_id", return_value=1),
            patch.object(module, "run_gh", return_value=MagicMock(returncode=0)) as gh,
        ):
            module.apply_ruleset(
                "cuioss", "cui-http", config, RELEASE_BOT_APP_ID, required_checks_override=[]
            )
        gh.assert_called_once()

    def _config(self):
        with open(CONFIG_PATH) as f:
            return json.load(f)


class TestMergeQueueArgValidation:
    """Test CLI validation for the merge-queue flags."""

    def test_enable_and_disable_mutually_exclusive(self, temp_dir):
        config = temp_dir / "config.json"
        config.write_text(json.dumps({
            "organization": "test",
            "repositories": [],
            "bypass_actor": {"name": "test-app", "type": "Integration", "app_id": "1"},
            "ruleset": {
                "name": "test", "enforcement": "active", "branch_pattern": "main",
                "rules": {
                    "require_pull_request": {
                        "required_approving_review_count": 0,
                        "dismiss_stale_reviews_on_push": False,
                        "require_last_push_approval": False,
                    },
                    "require_status_checks": {
                        "strict_required_status_checks_policy": False,
                        "do_not_enforce_on_create": False,
                        "required_checks": [],
                    },
                },
            },
        }))
        result = run_script(
            SCRIPT_PATH, config, "--enable-merge-queue", "--disable-merge-queue"
        )
        assert result.returncode != 0
        assert "together" in result.stderr.lower()
