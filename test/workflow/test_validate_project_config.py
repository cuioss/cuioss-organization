"""Tests for validate-project-config.py - whole-file project.yml schema validator."""

from __future__ import annotations

import sys
from pathlib import Path

# Add parent to path to access conftest
sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT, run_script

SCRIPT_PATH = PROJECT_ROOT / ".github/actions/read-project-config/validate-project-config.py"
SCHEMA_PATH = PROJECT_ROOT / ".github/actions/read-project-config/schema.json"


class TestHelpAndCli:
    """Test CLI arguments and help output."""

    def test_help_option_exits_cleanly(self):
        """Should display help and exit 0."""
        result = run_script(SCRIPT_PATH, "--help")
        assert result.returncode == 0
        assert "Validate project.yml against the cuioss organization schema." in result.stdout
        assert "--config" in result.stdout
        assert "--schema" in result.stdout
        assert "--repo" in result.stdout

    def test_nonexistent_file_fails(self, temp_dir):
        """Should fail when specified file does not exist."""
        missing = temp_dir / "does_not_exist.yml"
        result = run_script(SCRIPT_PATH, str(missing))
        assert result.returncode == 1
        assert "File does not exist" in result.stderr

    def test_invalid_yaml_fails(self, temp_dir):
        """Should fail on invalid YAML syntax."""
        bad_yaml = temp_dir / "invalid.yml"
        bad_yaml.write_text("name: [unclosed list", encoding="utf-8")
        result = run_script(SCRIPT_PATH, str(bad_yaml))
        assert result.returncode == 1
        assert "YAML parsing error" in result.stdout


class TestValidConfiguration:
    """Test validation of valid project.yml files."""

    def test_cuioss_organization_own_project_yml(self):
        """cuioss-organization's own .github/project.yml must be valid."""
        own_config = PROJECT_ROOT / ".github/project.yml"
        assert own_config.exists()
        result = run_script(SCRIPT_PATH, str(own_config))
        assert result.returncode == 0
        assert "OK" in result.stdout

    def test_valid_minimal_config(self, temp_dir):
        """Minimal valid configuration should pass."""
        config = temp_dir / "project.yml"
        config.write_text("name: test-repo\n", encoding="utf-8")
        result = run_script(SCRIPT_PATH, str(config))
        assert result.returncode == 0
        assert "OK" in result.stdout

    def test_valid_full_config(self, temp_dir):
        """Comprehensive valid configuration should pass."""
        config = temp_dir / "project.yml"
        config.write_text(
            """name: sample-service
description: Sample service description
release:
  current-version: 1.0.0
  next-version: 1.1.0-SNAPSHOT
  create-github-release: true
sonar:
  project-key: cuioss_sample
  enabled: true
maven-build:
  java-version: "21"
  java-versions: '["21","25"]'
  enable-snapshot-deploy: true
github-automation:
  auto-merge-build-versions: true
  dependabot-automerge: true
""",
            encoding="utf-8",
        )
        result = run_script(SCRIPT_PATH, str(config))
        assert result.returncode == 0
        assert "OK" in result.stdout


class TestRejectionOfUnknownKeys:
    """Test that schema rejects unknown keys in strict sections while accepting declared keys."""

    def test_accepts_auto_merge_build_timeout(self, temp_dir):
        """github-automation section admits auto-merge-build-timeout as optional integer."""
        config = temp_dir / "project.yml"
        config.write_text(
            """name: test-repo
github-automation:
  auto-merge-build-versions: true
  auto-merge-build-timeout: 300
""",
            encoding="utf-8",
        )
        result = run_script(SCRIPT_PATH, str(config))
        assert result.returncode == 0
        assert "OK" in result.stdout

    def test_rejects_arbitrary_unknown_github_automation_key(self, temp_dir):
        """Any unexpected property in github-automation must name the key path."""
        config = temp_dir / "project.yml"
        config.write_text(
            """name: test-repo
github-automation:
  unexpected_automation_flag: true
""",
            encoding="utf-8",
        )
        result = run_script(SCRIPT_PATH, str(config))
        assert result.returncode == 1
        assert "github-automation.unexpected_automation_flag" in result.stdout

    def test_rejects_unknown_release_key(self, temp_dir):
        """release section has additionalProperties: false; unknown key must fail."""
        config = temp_dir / "project.yml"
        config.write_text(
            """name: test-repo
release:
  current-version: 1.0.0
  next-version: 1.1.0-SNAPSHOT
  unknown-release-key: invalid
""",
            encoding="utf-8",
        )
        result = run_script(SCRIPT_PATH, str(config))
        assert result.returncode == 1
        assert "release.unknown-release-key" in result.stdout


class TestVersionPatternValidation:
    """Test validation of version patterns under the settled schema."""

    def test_accepts_two_part_current_version_string(self, temp_dir):
        """Settled schema accepts two-part current-version strings like '3.2'."""
        config = temp_dir / "project.yml"
        config.write_text(
            """name: test-repo
release:
  current-version: "3.2"
  next-version: 3.3.0-SNAPSHOT
""",
            encoding="utf-8",
        )
        result = run_script(SCRIPT_PATH, str(config))
        assert result.returncode == 0
        assert "OK" in result.stdout

    def test_accepts_two_part_current_version_number(self, temp_dir):
        """Settled schema accepts unquoted float versions like 3.2."""
        config = temp_dir / "project.yml"
        config.write_text(
            """name: test-repo
release:
  current-version: 3.2
  next-version: 3.3.0-SNAPSHOT
""",
            encoding="utf-8",
        )
        result = run_script(SCRIPT_PATH, str(config))
        assert result.returncode == 0
        assert "OK" in result.stdout

    def test_accepts_two_part_next_version(self, temp_dir):
        """Settled schema accepts two-part next-version like '2.7-SNAPSHOT'."""
        config = temp_dir / "project.yml"
        config.write_text(
            """name: test-repo
release:
  current-version: 2.6.0
  next-version: "2.7-SNAPSHOT"
""",
            encoding="utf-8",
        )
        result = run_script(SCRIPT_PATH, str(config))
        assert result.returncode == 0
        assert "OK" in result.stdout

    def test_accepts_valid_three_part_versions(self, temp_dir):
        """Three-part version formats should pass."""
        config = temp_dir / "project.yml"
        config.write_text(
            """name: test-repo
release:
  current-version: 2.7.0
  next-version: 2.8.0-SNAPSHOT
""",
            encoding="utf-8",
        )
        result = run_script(SCRIPT_PATH, str(config))
        assert result.returncode == 0
        assert "OK" in result.stdout

    def test_rejects_malformed_current_version(self, temp_dir):
        """Invalid non-semver versions must fail."""
        config = temp_dir / "project.yml"
        config.write_text(
            """name: test-repo
release:
  current-version: "not-a-version"
  next-version: 1.1.0-SNAPSHOT
""",
            encoding="utf-8",
        )
        result = run_script(SCRIPT_PATH, str(config))
        assert result.returncode == 1
        assert "release.current-version" in result.stdout

    def test_rejects_malformed_next_version(self, temp_dir):
        """Malformed next-version must fail."""
        config = temp_dir / "project.yml"
        config.write_text(
            """name: test-repo
release:
  current-version: 1.0.0
  next-version: "bad-snapshot-format"
""",
            encoding="utf-8",
        )
        result = run_script(SCRIPT_PATH, str(config))
        assert result.returncode == 1
        assert "release.next-version" in result.stdout


class TestDecisionsConsistencyAcrossFiles:
    """Assert all four authoritative files agree on settled decisions."""

    def test_auto_merge_build_timeout_agrees_across_files(self):
        """schema.json, README.adoc, docs/project-yml-schema.adoc, and update-github-actions.md agree."""
        schema_text = (PROJECT_ROOT / ".github/actions/read-project-config/schema.json").read_text(encoding="utf-8")
        readme_text = (PROJECT_ROOT / ".github/actions/read-project-config/README.adoc").read_text(encoding="utf-8")
        docs_text = (PROJECT_ROOT / "docs/project-yml-schema.adoc").read_text(encoding="utf-8")
        template_text = (PROJECT_ROOT / ".claude/commands/update-github-actions.md").read_text(encoding="utf-8")

        for text, name in [
            (schema_text, "schema.json"),
            (readme_text, "README.adoc"),
            (docs_text, "docs/project-yml-schema.adoc"),
            (template_text, "update-github-actions.md"),
        ]:
            assert "auto-merge-build-timeout" in text, f"Missing auto-merge-build-timeout in {name}"
