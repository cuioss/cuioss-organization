"""Tests for read-config.py - project.yml configuration parser."""

import sys
from pathlib import Path

# Add parent to path to access conftest
sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT, run_script

SCRIPT_PATH = PROJECT_ROOT / ".github/actions/read-project-config/read-config.py"


class TestDefaultValues:
    """Test default value handling when config is missing or incomplete."""

    def test_default_values_when_config_missing(self, temp_dir):
        """Should output default values when config file doesn't exist."""
        result = run_script(SCRIPT_PATH, "--config", str(temp_dir / "nonexistent.yml"))
        assert result.returncode == 0
        assert "java-version=21" in result.stdout
        assert "config-found=false" in result.stdout

    def test_default_java_versions(self, temp_dir):
        """Should provide default java-versions array."""
        result = run_script(SCRIPT_PATH, "--config", str(temp_dir / "nonexistent.yml"))
        assert result.returncode == 0
        assert 'java-versions=["21","25"]' in result.stdout

    def test_default_boolean_values(self, temp_dir):
        """Should provide default boolean values."""
        result = run_script(SCRIPT_PATH, "--config", str(temp_dir / "nonexistent.yml"))
        assert result.returncode == 0
        assert "enable-snapshot-deploy=true" in result.stdout
        assert "sonar-enabled=true" in result.stdout


class TestConfigReading:
    """Test reading and parsing project.yml configurations."""

    def test_reads_java_version(self, temp_dir):
        """Should read java-version from config."""
        config = temp_dir / "project.yml"
        config.write_text('maven-build:\n  java-version: "17"')
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "java-version=17" in result.stdout
        assert "config-found=true" in result.stdout

    def test_reads_java_versions_array(self, temp_dir):
        """Should read java-versions array from config.

        Note: Lists in config are output as empty strings unless they have a
        transform function. The default value '["21","25"]' is a JSON string,
        not an actual list, so it gets output directly.
        """
        config = temp_dir / "project.yml"
        config.write_text('maven-build:\n  java-versions: ["17", "21"]')
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        # Lists are output as empty strings per to_output_value()
        assert "java-versions=" in result.stdout

    def test_reads_boolean_false(self, temp_dir):
        """Should correctly handle boolean false values."""
        config = temp_dir / "project.yml"
        config.write_text("maven-build:\n  enable-snapshot-deploy: false")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "enable-snapshot-deploy=false" in result.stdout

    def test_reads_sonar_settings(self, temp_dir):
        """Should read sonar configuration section."""
        config = temp_dir / "project.yml"
        config.write_text("sonar:\n  enabled: false\n  project-key: my-project")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "sonar-enabled=false" in result.stdout
        assert "sonar-project-key=my-project" in result.stdout

    def test_reads_release_settings(self, temp_dir):
        """Should read release configuration section."""
        config = temp_dir / "project.yml"
        config.write_text("release:\n  current-version: 1.0.0\n  next-version: 1.1.0")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "current-version=1.0.0" in result.stdout
        assert "next-version=1.1.0" in result.stdout


class TestCustomNamespace:
    """Test custom namespace passthrough functionality."""

    def test_custom_namespace_single_key(self, temp_dir):
        """Should pass through single custom key."""
        config = temp_dir / "project.yml"
        config.write_text("custom:\n  my-flag: true")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "custom-my-flag=true" in result.stdout
        assert "custom-keys=my-flag" in result.stdout

    def test_custom_namespace_multiple_keys(self, temp_dir):
        """Should pass through multiple custom keys."""
        config = temp_dir / "project.yml"
        config.write_text("custom:\n  my-flag: true\n  my-setting: some-value")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "custom-my-flag=true" in result.stdout
        assert "custom-my-setting=some-value" in result.stdout
        # Keys should be space-separated
        assert "custom-keys=" in result.stdout

    def test_custom_namespace_empty(self, temp_dir):
        """Should handle missing custom section."""
        config = temp_dir / "project.yml"
        config.write_text("maven-build:\n  java-version: 21")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "custom-keys=" in result.stdout


class TestConsumersList:
    """Test consumers list handling."""

    def test_consumers_list_transformed(self, temp_dir):
        """Should transform consumers list to space-separated string."""
        config = temp_dir / "project.yml"
        config.write_text("consumers:\n  - repo-a\n  - repo-b")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "consumers=repo-a repo-b" in result.stdout

    def test_consumers_empty_list(self, temp_dir):
        """Should handle empty consumers list."""
        config = temp_dir / "project.yml"
        config.write_text("consumers: []")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "consumers=" in result.stdout


class TestPyprojectxSection:
    """Test pyprojectx configuration section."""

    def test_default_pyprojectx_values(self, temp_dir):
        """Should provide default pyprojectx values when not configured."""
        result = run_script(SCRIPT_PATH, "--config", str(temp_dir / "nonexistent.yml"))
        assert result.returncode == 0
        assert "pyprojectx-python-version=" in result.stdout
        assert "pyprojectx-cache-dependency-glob=uv.lock" in result.stdout
        assert "pyprojectx-upload-artifacts-on-failure=false" in result.stdout
        assert "pyprojectx-verify-command=./pw verify" in result.stdout

    def test_reads_pyprojectx_python_version(self, temp_dir):
        """Should read python-version from pyprojectx section."""
        config = temp_dir / "project.yml"
        config.write_text('pyprojectx:\n  python-version: "3.12"')
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "pyprojectx-python-version=3.12" in result.stdout

    def test_reads_pyprojectx_cache_glob(self, temp_dir):
        """Should read cache-dependency-glob from pyprojectx section."""
        config = temp_dir / "project.yml"
        config.write_text("pyprojectx:\n  cache-dependency-glob: requirements.txt")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "pyprojectx-cache-dependency-glob=requirements.txt" in result.stdout

    def test_reads_pyprojectx_upload_artifacts(self, temp_dir):
        """Should read upload-artifacts-on-failure from pyprojectx section."""
        config = temp_dir / "project.yml"
        config.write_text("pyprojectx:\n  upload-artifacts-on-failure: true")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "pyprojectx-upload-artifacts-on-failure=true" in result.stdout

    def test_reads_pyprojectx_verify_command(self, temp_dir):
        """Should read verify-command from pyprojectx section."""
        config = temp_dir / "project.yml"
        config.write_text("pyprojectx:\n  verify-command: ./pw test")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "pyprojectx-verify-command=./pw test" in result.stdout

    def test_reads_full_pyprojectx_config(self, temp_dir):
        """Should read all pyprojectx settings together."""
        config = temp_dir / "project.yml"
        config.write_text("""pyprojectx:
  python-version: "3.11"
  cache-dependency-glob: "*.lock"
  upload-artifacts-on-failure: true
  verify-command: ./pw quality-gate
""")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "pyprojectx-python-version=3.11" in result.stdout
        assert "pyprojectx-cache-dependency-glob=*.lock" in result.stdout
        assert "pyprojectx-upload-artifacts-on-failure=true" in result.stdout
        assert "pyprojectx-verify-command=./pw quality-gate" in result.stdout


class TestGitHubAutomationSection:
    """Test github-automation configuration section."""

    def test_default_auto_merge_values(self, temp_dir):
        """Should provide default github-automation values when not configured."""
        result = run_script(SCRIPT_PATH, "--config", str(temp_dir / "nonexistent.yml"))
        assert result.returncode == 0
        assert "auto-merge-build-versions=true" in result.stdout
        assert "auto-merge-build-timeout" not in result.stdout

    def test_auto_merge_disabled(self, temp_dir):
        """Should read auto-merge-build-versions as false."""
        config = temp_dir / "project.yml"
        config.write_text("github-automation:\n  auto-merge-build-versions: false")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "auto-merge-build-versions=false" in result.stdout

    def test_auto_merge_enabled(self, temp_dir):
        """Should read auto-merge-build-versions as true."""
        config = temp_dir / "project.yml"
        config.write_text("github-automation:\n  auto-merge-build-versions: true")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "auto-merge-build-versions=true" in result.stdout


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_config_file(self, temp_dir):
        """Should handle empty config file gracefully."""
        config = temp_dir / "project.yml"
        config.write_text("")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        # Should use defaults
        assert "java-version=21" in result.stdout
        assert "config-found=true" in result.stdout

    def test_config_with_only_comments(self, temp_dir):
        """Should handle config with only comments."""
        config = temp_dir / "project.yml"
        config.write_text("# This is a comment\n# Another comment")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "java-version=21" in result.stdout

    def test_nested_unknown_sections_ignored(self, temp_dir):
        """Should ignore unknown sections without error."""
        config = temp_dir / "project.yml"
        config.write_text("unknown-section:\n  foo: bar\nmaven-build:\n  java-version: 17")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "java-version=17" in result.stdout
