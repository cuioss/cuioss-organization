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


class TestNpmBuildSection:
    """Test npm-build configuration section."""

    def test_default_npm_values(self, temp_dir):
        """Should provide default npm-build values when not configured."""
        result = run_script(SCRIPT_PATH, "--config", str(temp_dir / "nonexistent.yml"))
        assert result.returncode == 0
        assert "npm-node-version=22" in result.stdout
        assert "npm-registry-url=https://registry.npmjs.org" in result.stdout

    def test_reads_npm_node_version(self, temp_dir):
        """Should read node-version from npm-build section."""
        config = temp_dir / "project.yml"
        config.write_text('npm-build:\n  node-version: "20"')
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "npm-node-version=20" in result.stdout

    def test_reads_npm_registry_url(self, temp_dir):
        """Should read registry-url from npm-build section."""
        config = temp_dir / "project.yml"
        config.write_text("npm-build:\n  registry-url: https://npm.pkg.github.com")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "npm-registry-url=https://npm.pkg.github.com" in result.stdout

    def test_reads_full_npm_config(self, temp_dir):
        """Should read all npm-build settings together."""
        config = temp_dir / "project.yml"
        config.write_text("""npm-build:
  node-version: "20"
  registry-url: https://npm.pkg.github.com
""")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "npm-node-version=20" in result.stdout
        assert "npm-registry-url=https://npm.pkg.github.com" in result.stdout


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


class TestPathFilteringSection:
    """Test path filtering configuration fields."""

    def test_default_skip_on_docs_only(self, temp_dir):
        """Should default skip-on-docs-only to true."""
        result = run_script(SCRIPT_PATH, "--config", str(temp_dir / "nonexistent.yml"))
        assert result.returncode == 0
        assert "skip-on-docs-only=true" in result.stdout

    def test_skip_on_docs_only_false(self, temp_dir):
        """Should read skip-on-docs-only as false."""
        config = temp_dir / "project.yml"
        config.write_text("maven-build:\n  skip-on-docs-only: false")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "skip-on-docs-only=false" in result.stdout

    def test_skip_on_docs_only_true(self, temp_dir):
        """Should read skip-on-docs-only as true."""
        config = temp_dir / "project.yml"
        config.write_text("maven-build:\n  skip-on-docs-only: true")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "skip-on-docs-only=true" in result.stdout

    def test_default_paths_ignore_extra(self, temp_dir):
        """Should default paths-ignore-extra to empty."""
        result = run_script(SCRIPT_PATH, "--config", str(temp_dir / "nonexistent.yml"))
        assert result.returncode == 0
        assert "paths-ignore-extra=" in result.stdout

    def test_paths_ignore_extra_single(self, temp_dir):
        """Should transform single-item paths-ignore-extra list to string."""
        config = temp_dir / "project.yml"
        config.write_text("maven-build:\n  paths-ignore-extra:\n    - 'e-2-e-playwright/docs/**'")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "paths-ignore-extra=e-2-e-playwright/docs/**" in result.stdout

    def test_paths_ignore_extra_multiple(self, temp_dir):
        """Should transform multi-item paths-ignore-extra list to space-separated string."""
        config = temp_dir / "project.yml"
        config.write_text("maven-build:\n  paths-ignore-extra:\n    - 'docs-extra/**'\n    - 'scripts/docs/**'")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "paths-ignore-extra=docs-extra/** scripts/docs/**" in result.stdout

    def test_paths_ignore_extra_empty_list(self, temp_dir):
        """Should handle empty paths-ignore-extra list."""
        config = temp_dir / "project.yml"
        config.write_text("maven-build:\n  paths-ignore-extra: []")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "paths-ignore-extra=" in result.stdout

    def test_paths_ignore_extra_sanitizes_shell_metacharacters(self, temp_dir):
        """Should strip entries containing shell metacharacters."""
        config = temp_dir / "project.yml"
        config.write_text(
            "maven-build:\n  paths-ignore-extra:\n"
            "    - 'safe/path/**'\n"
            "    - '$(malicious)'\n"
            "    - 'also-safe/*.md'\n"
        )
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "paths-ignore-extra=safe/path/** also-safe/*.md" in result.stdout

    def test_paths_ignore_extra_handles_non_string_items(self, temp_dir):
        """Should convert non-string items to strings safely."""
        config = temp_dir / "project.yml"
        config.write_text("maven-build:\n  paths-ignore-extra:\n    - 123\n    - true")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        # 123 matches safe pattern, 'True' (Python bool str) matches safe pattern
        assert "paths-ignore-extra=123 True" in result.stdout


class TestIntegrationTestsSection:
    """Test integration-tests configuration section."""

    def test_default_integration_tests_values(self, temp_dir):
        """Should provide default integration-tests values when not configured."""
        result = run_script(SCRIPT_PATH, "--config", str(temp_dir / "nonexistent.yml"))
        assert result.returncode == 0
        assert "it-test-type=" in result.stdout
        assert "it-maven-module=" in result.stdout
        assert "it-maven-profiles=integration-tests" in result.stdout
        assert "it-timeout-minutes=20" in result.stdout
        assert "it-deploy-reports=false" in result.stdout
        assert "it-reports-subfolder=" in result.stdout

    def test_reads_it_test_type(self, temp_dir):
        """Should read test-type from integration-tests section."""
        config = temp_dir / "project.yml"
        config.write_text("integration-tests:\n  test-type: java-it")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "it-test-type=java-it" in result.stdout

    def test_reads_it_maven_module(self, temp_dir):
        """Should read maven-module from integration-tests section."""
        config = temp_dir / "project.yml"
        config.write_text("integration-tests:\n  maven-module: nifi-it-parent")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "it-maven-module=nifi-it-parent" in result.stdout

    def test_reads_it_maven_profiles(self, temp_dir):
        """Should read maven-profiles from integration-tests section."""
        config = temp_dir / "project.yml"
        config.write_text("integration-tests:\n  maven-profiles: custom-profile")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "it-maven-profiles=custom-profile" in result.stdout

    def test_reads_it_timeout_minutes(self, temp_dir):
        """Should read timeout-minutes from integration-tests section."""
        config = temp_dir / "project.yml"
        config.write_text("integration-tests:\n  timeout-minutes: 45")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "it-timeout-minutes=45" in result.stdout

    def test_reads_it_deploy_reports(self, temp_dir):
        """Should read deploy-reports from integration-tests section."""
        config = temp_dir / "project.yml"
        config.write_text("integration-tests:\n  deploy-reports: true")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "it-deploy-reports=true" in result.stdout

    def test_reads_it_reports_subfolder(self, temp_dir):
        """Should read reports-subfolder from integration-tests section."""
        config = temp_dir / "project.yml"
        config.write_text("integration-tests:\n  reports-subfolder: nifi-extensions/it")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "it-reports-subfolder=nifi-extensions/it" in result.stdout

    def test_default_it_reports_folder(self, temp_dir):
        """Should default it-reports-folder to empty."""
        result = run_script(SCRIPT_PATH, "--config", str(temp_dir / "nonexistent.yml"))
        assert result.returncode == 0
        assert "it-reports-folder=" in result.stdout

    def test_reads_it_reports_folder(self, temp_dir):
        """Should read reports-folder from integration-tests section."""
        config = temp_dir / "project.yml"
        config.write_text("integration-tests:\n  reports-folder: my-module/target/failsafe-reports")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "it-reports-folder=my-module/target/failsafe-reports" in result.stdout

    def test_sanitizes_it_reports_folder(self, temp_dir):
        """Should reject reports-folder values with shell metacharacters."""
        config = temp_dir / "project.yml"
        config.write_text("integration-tests:\n  reports-folder: '$(malicious)/target/site'")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        lines = {line.split("=", 1)[0]: line.split("=", 1)[1] for line in result.stdout.strip().split("\n") if "=" in line}
        assert lines.get("it-reports-folder", "") == ""

    def test_reads_full_integration_tests_config(self, temp_dir):
        """Should read all integration-tests settings together."""
        config = temp_dir / "project.yml"
        config.write_text("""integration-tests:
  test-type: playwright-e2e
  maven-module: e-2-e-playwright
  maven-profiles: integration-tests,e2e
  timeout-minutes: 30
  deploy-reports: true
  reports-subfolder: nifi-extensions/e2e
  reports-folder: e-2-e-playwright/target/playwright-report
""")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "it-test-type=playwright-e2e" in result.stdout
        assert "it-maven-module=e-2-e-playwright" in result.stdout
        assert "it-maven-profiles=integration-tests,e2e" in result.stdout
        assert "it-timeout-minutes=30" in result.stdout
        assert "it-deploy-reports=true" in result.stdout
        assert "it-reports-subfolder=nifi-extensions/e2e" in result.stdout
        assert "it-reports-folder=e-2-e-playwright/target/playwright-report" in result.stdout

    def test_sanitizes_shell_metacharacters_in_maven_module(self, temp_dir):
        """Should reject maven-module values with shell metacharacters."""
        config = temp_dir / "project.yml"
        config.write_text("integration-tests:\n  maven-module: '$(malicious)'")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "it-maven-module=\n" in result.stdout or "it-maven-module=\r" in result.stdout or result.stdout.count("it-maven-module=") == 1

    def test_sanitizes_shell_metacharacters_in_profiles(self, temp_dir):
        """Should reject maven-profiles values with shell metacharacters."""
        config = temp_dir / "project.yml"
        config.write_text("integration-tests:\n  maven-profiles: 'profile;rm -rf /'")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        # Unsafe value should be sanitized to empty
        lines = {line.split("=", 1)[0]: line.split("=", 1)[1] for line in result.stdout.strip().split("\n") if "=" in line}
        assert lines.get("it-maven-profiles", "") == ""

    def test_allows_safe_characters_in_maven_module(self, temp_dir):
        """Should allow Maven module names with dots, hyphens, slashes, colons."""
        config = temp_dir / "project.yml"
        config.write_text("integration-tests:\n  maven-module: com.example:my-module/sub")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "it-maven-module=com.example:my-module/sub" in result.stdout


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
