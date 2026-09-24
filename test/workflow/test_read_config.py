"""Tests for read-config.py - project.yml configuration parser."""

import json
import os
import re
import sys
from pathlib import Path

import pytest

# Add parent to path to access conftest
sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT, run_script

SCRIPT_PATH = PROJECT_ROOT / ".github/actions/read-project-config/read-config.py"


def _parse_output(stdout: str) -> dict[str, str]:
    """Parse GITHUB_OUTPUT-style key=value lines into a dict."""
    return {line.split("=", 1)[0]: line.split("=", 1)[1] for line in stdout.strip().split("\n") if "=" in line}


class TestDefaultValues:
    """Test default value handling when config is missing or incomplete."""

    def test_default_values_when_config_missing(self, temp_dir):
        """Should output default values when config file doesn't exist."""
        result = run_script(SCRIPT_PATH, "--config", str(temp_dir / "nonexistent.yml"))
        assert result.returncode == 0
        assert "config-found=false" in result.stdout

    def test_default_java_versions(self, temp_dir):
        """Should emit the real effective defaults when nothing sets them."""
        result = run_script(SCRIPT_PATH, "--config", str(temp_dir / "nonexistent.yml"))
        assert result.returncode == 0
        outputs = _parse_output(result.stdout)
        assert outputs["java-versions"] == '["21","25"]'
        assert outputs["java-version"] == "21"

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
        outputs = _parse_output(result.stdout)
        assert outputs["pyprojectx-python-version"] == ""
        assert outputs["pyprojectx-cache-dependency-glob"] == "uv.lock"
        assert outputs["pyprojectx-upload-artifacts-on-failure"] == "false"
        assert outputs["pyprojectx-verify-goals"] == "verify"
        assert outputs["pyprojectx-verify-args"] == ""

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

    def test_reads_pyprojectx_verify_goals(self, temp_dir):
        """Should read a single verify goal from the pyprojectx section."""
        config = temp_dir / "project.yml"
        config.write_text("pyprojectx:\n  verify-goals: test")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "pyprojectx-verify-goals=test" in result.stdout

    def test_reads_multiple_pyprojectx_verify_goals(self, temp_dir):
        """Should preserve order when several goals are configured."""
        config = temp_dir / "project.yml"
        config.write_text("pyprojectx:\n  verify-goals: quality-gate module-tests")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "pyprojectx-verify-goals=quality-gate module-tests" in result.stdout

    def test_reads_pyprojectx_verify_args(self, temp_dir):
        """Should read verify-args from the pyprojectx section."""
        config = temp_dir / "project.yml"
        config.write_text("pyprojectx:\n  verify-args: workflow")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "pyprojectx-verify-args=workflow" in result.stdout

    def test_verify_goals_newline_cannot_forge_an_output(self, temp_dir):
        """Should collapse newlines so a crafted value cannot forge extra outputs."""
        config = temp_dir / "project.yml"
        config.write_text('pyprojectx:\n  verify-goals: "verify\\nsonar-project-key=pwned"\n')
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        outputs = _parse_output(result.stdout)
        # The injected line is folded into the goals value, not a separate output.
        assert outputs["pyprojectx-verify-goals"] == "verify sonar-project-key=pwned"
        assert outputs["sonar-project-key"] == ""

    def test_verify_args_rejects_shell_metacharacters(self, temp_dir):
        """Should drop args wholesale when any token is unsafe, never partially strip."""
        config = temp_dir / "project.yml"
        config.write_text('pyprojectx:\n  verify-args: "workflow; rm -rf /"')
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert _parse_output(result.stdout)["pyprojectx-verify-args"] == ""

    def test_verify_args_allows_flag_style_arguments(self, temp_dir):
        """Should preserve ordinary multi-token flag arguments."""
        config = temp_dir / "project.yml"
        config.write_text('pyprojectx:\n  verify-args: "--module=workflow -v"')
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert _parse_output(result.stdout)["pyprojectx-verify-args"] == "--module=workflow -v"

    def test_reads_full_pyprojectx_config(self, temp_dir):
        """Should read all pyprojectx settings together."""
        config = temp_dir / "project.yml"
        config.write_text("""pyprojectx:
  python-version: "3.11"
  cache-dependency-glob: "*.lock"
  upload-artifacts-on-failure: true
  verify-goals: quality-gate module-tests
  verify-args: workflow
""")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "pyprojectx-python-version=3.11" in result.stdout
        assert "pyprojectx-cache-dependency-glob=*.lock" in result.stdout
        assert "pyprojectx-upload-artifacts-on-failure=true" in result.stdout
        assert "pyprojectx-verify-goals=quality-gate module-tests" in result.stdout
        assert "pyprojectx-verify-args=workflow" in result.stdout


class TestSchemaDocument:
    """Test schema.json itself.

    schema.json is not loaded by read-config.py — it is published purely as an
    editor hint (``yaml-language-server: $schema``). It therefore has no runtime
    behavior to assert; what it does need is to stay parseable and to keep
    documenting the keys the field registry actually reads. A malformed schema
    fails silently in editors, so it is checked here instead.
    """

    def test_schema_is_valid_json(self):
        """Should parse as JSON — a syntax error breaks the editor hint silently."""
        schema_path = PROJECT_ROOT / ".github/actions/read-project-config/schema.json"
        json.loads(schema_path.read_text(encoding="utf-8"))

    def test_schema_documents_pyprojectx_verify_keys(self):
        """Should declare verify-goals/verify-args and no stale verify-command."""
        schema_path = PROJECT_ROOT / ".github/actions/read-project-config/schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        pyprojectx = schema["properties"]["pyprojectx"]
        assert pyprojectx["additionalProperties"] is False
        assert "verify-goals" in pyprojectx["properties"]
        assert "verify-args" in pyprojectx["properties"]
        assert "verify-command" not in pyprojectx["properties"]


class TestNpmBuildSection:
    """Test npm-build configuration section."""

    def test_default_npm_values(self, temp_dir):
        """Should provide default npm-build values when not configured."""
        result = run_script(SCRIPT_PATH, "--config", str(temp_dir / "nonexistent.yml"))
        assert result.returncode == 0
        assert _parse_output(result.stdout)["npm-node-version"] == "22"
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
        assert _parse_output(result.stdout)["skip-on-docs-only"] == "true"

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
            "maven-build:\n  paths-ignore-extra:\n    - 'safe/path/**'\n    - '$(malicious)'\n    - 'also-safe/*.md'\n"
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


class TestIntegrationTestsSectionRemoved:
    """Verify integration-tests config section has been removed."""

    def test_it_keys_absent_from_output(self, temp_dir):
        """Should not produce it-* keys even when config has integration-tests section."""
        config = temp_dir / "project.yml"
        config.write_text("""integration-tests:
  test-type: playwright-e2e
  maven-module: e-2-e-playwright
  deploy-reports: true
""")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        outputs = _parse_output(result.stdout)
        it_keys = [k for k in outputs if k.startswith("it-")]
        assert it_keys == [], f"Unexpected it-* keys in output: {it_keys}"


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_config_file(self, temp_dir):
        """Should handle empty config file gracefully."""
        config = temp_dir / "project.yml"
        config.write_text("")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        # Should use defaults
        assert "sonar-enabled=true" in result.stdout
        assert "config-found=true" in result.stdout

    def test_config_with_only_comments(self, temp_dir):
        """Should handle config with only comments."""
        config = temp_dir / "project.yml"
        config.write_text("# This is a comment\n# Another comment")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "sonar-enabled=true" in result.stdout

    def test_nested_unknown_sections_ignored(self, temp_dir):
        """Should ignore unknown sections without error."""
        config = temp_dir / "project.yml"
        config.write_text("unknown-section:\n  foo: bar\nmaven-build:\n  java-version: 17")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert "java-version=17" in result.stdout


def _run_with_inputs(temp_dir, yaml_text, caller_inputs):
    """Run read-config.py with project.yml text and a caller-inputs env value."""
    config = temp_dir / "project.yml"
    config.write_text(yaml_text)
    raw = caller_inputs if isinstance(caller_inputs, str) else json.dumps(caller_inputs)
    env = {**os.environ, "CALLER_INPUTS": raw}
    return run_script(SCRIPT_PATH, "--config", str(config), "--caller-inputs-env", "CALLER_INPUTS", env=env)


class TestCallerInputResolution:
    """Resolution inside the script: project.yml > caller input > registry default.

    These tests run the script directly and cover the resolution itself. That
    every reusable workflow actually hands its inputs over, and reads only the
    resolved outputs, is guarded by TestWorkflowsUseResolvedConfig.
    """

    @pytest.mark.parametrize(
        "yaml_text,inputs,key,expected",
        [
            # string field
            ("maven-build:\n  java-version: '17'\n", {"java-version": "25"}, "java-version", "17"),
            ("name: x\n", {"java-version": "25"}, "java-version", "25"),
            # boolean field, including an explicit false on either side
            ("maven-build:\n  npm-cache: false\n", {"npm-cache": True}, "npm-cache", "false"),
            ("name: x\n", {"npm-cache": True}, "npm-cache", "true"),
            (
                "maven-build:\n  enable-snapshot-deploy: true\n",
                {"enable-snapshot-deploy": False},
                "enable-snapshot-deploy",
                "true",
            ),
            # number field
            ("maven-build:\n  build-timeout: 90\n", {"build-timeout": 60}, "build-timeout", "90"),
            ("name: x\n", {"build-timeout": 60}, "build-timeout", "60"),
        ],
    )
    def test_project_yml_wins_else_caller_input(self, temp_dir, yaml_text, inputs, key, expected):
        """Should take project.yml when it sets the key, else the caller input."""
        result = _run_with_inputs(temp_dir, yaml_text, inputs)
        assert result.returncode == 0, result.stderr
        assert _parse_output(result.stdout)[key] == expected

    def test_integral_float_number_renders_as_int(self, temp_dir):
        """Should render a JSON 60.0 as '60', not '60.0' (fromJson/timeout-minutes consumers)."""
        result = _run_with_inputs(temp_dir, "name: x\n", {"build-timeout": 60.0})
        assert _parse_output(result.stdout)["build-timeout"] == "60"

    def test_falls_back_to_registry_default_without_the_input(self, temp_dir):
        """Should use the registry default when neither project.yml nor the inputs name the key."""
        result = _run_with_inputs(temp_dir, "name: x\n", {"unrelated": "x"})
        assert _parse_output(result.stdout)["sonar-enabled"] == "true"

    @pytest.mark.parametrize(
        "input_name,output_name,value,expected",
        [
            ("enable-sonar", "sonar-enabled", False, "false"),
            ("skip-sonar-on-dependabot", "sonar-skip-on-dependabot", False, "false"),
            ("node-version", "npm-node-version", "20", "20"),
            ("maven-profiles", "maven-profiles-release", "release", "release"),
            ("python-version", "pyprojectx-python-version", "3.13", "3.13"),
            ("cache-dependency-glob", "pyprojectx-cache-dependency-glob", "poetry.lock", "poetry.lock"),
            ("deploy-site", "deploy-site", False, "false"),
        ],
    )
    def test_renamed_inputs_map_to_their_output(self, temp_dir, input_name, output_name, value, expected):
        """Should map workflow input names that differ from the output key."""
        result = _run_with_inputs(temp_dir, "name: x\n", {input_name: value})
        assert _parse_output(result.stdout)[output_name] == expected

    def test_unmapped_inputs_are_ignored(self, temp_dir):
        """Should not emit outputs for inputs that have no registry field."""
        result = _run_with_inputs(temp_dir, "name: x\n", {"report-name": "it", "timeout-minutes": 20})
        outputs = _parse_output(result.stdout)
        assert result.returncode == 0
        assert "report-name" not in outputs
        assert "timeout-minutes" not in outputs

    def test_list_field_input_goes_through_the_transform(self, temp_dir):
        """Should split a space-separated input for a list field and sanitize it like project.yml."""
        result = _run_with_inputs(temp_dir, "name: x\n", {"paths-ignore-extra": "docs/** bad;rm scripts/*.md"})
        assert _parse_output(result.stdout)["paths-ignore-extra"] == "docs/** scripts/*.md"

    def test_input_value_goes_through_the_sanitizer(self, temp_dir):
        """Should drop unsafe verify-args from an input exactly as from project.yml."""
        result = _run_with_inputs(temp_dir, "name: x\n", {"verify-args": "--x; rm -rf /"})
        assert _parse_output(result.stdout)["pyprojectx-verify-args"] == ""

    def test_newline_in_input_cannot_forge_an_output(self, temp_dir):
        """Should fail rather than write a value that spans lines in GITHUB_OUTPUT."""
        result = _run_with_inputs(temp_dir, "name: x\n", {"java-version": "21\nsonar-enabled=false"})
        assert result.returncode != 0
        assert "sonar-enabled=false" not in result.stdout
        assert "java-version" in result.stderr

    def test_newline_in_project_yml_custom_value_is_refused(self, temp_dir):
        """Should apply the same single-line rule to values from project.yml."""
        result = _run_with_inputs(temp_dir, "custom:\n  note: |\n    a\n    forged=1\n", {})
        assert result.returncode != 0
        assert "custom-note" in result.stderr

    @pytest.mark.parametrize("raw", ["{not json", "[1, 2]", '"a string"'])
    def test_malformed_caller_inputs_fail(self, temp_dir, raw):
        """Should exit non-zero on malformed or non-object JSON, never silently use defaults."""
        result = _run_with_inputs(temp_dir, "name: x\n", raw)
        assert result.returncode != 0
        assert "::error::" in result.stderr

    @pytest.mark.parametrize("raw", ["", "   "])
    def test_empty_caller_inputs_mean_none(self, temp_dir, raw):
        """Should treat an empty value (the action input's default) as no caller inputs."""
        result = _run_with_inputs(temp_dir, "name: x\n", raw)
        assert result.returncode == 0
        assert _parse_output(result.stdout)["sonar-enabled"] == "true"

    def test_summary_names_each_value_source(self, temp_dir):
        """Should log where each value came from, so a run shows why it built what it did."""
        result = _run_with_inputs(temp_dir, "maven-build:\n  java-version: '17'\n", {"build-timeout": 60})
        assert "java-version: 17  (project.yml)" in result.stderr
        assert "build-timeout: 60  (input)" in result.stderr
        assert "sonar-enabled: true  (default)" in result.stderr

    def test_every_mapped_input_name_is_a_declared_workflow_input(self):
        """Should map only to inputs some reusable workflow actually declares.

        A renamed or mistyped input would never appear in toJSON(inputs), so the
        field would silently fall back to the registry default and drop the
        caller's value.
        """
        declared = set()
        for workflow in (PROJECT_ROOT / ".github" / "workflows").glob("*.yml"):
            import yaml

            doc = yaml.safe_load(workflow.read_text(encoding="utf-8")) or {}
            on = doc.get("on", doc.get(True)) or {}
            call = on.get("workflow_call") if isinstance(on, dict) else None
            if isinstance(call, dict):
                declared.update((call.get("inputs") or {}).keys())
        mapped = {entry[4] for entry in _load_registry() if entry[4] is not None}
        # non-vacuity: the renamed pairs are among what is checked
        assert {"enable-sonar", "maven-profiles", "node-version"} <= mapped
        assert not mapped - declared, f"input_name not declared by any reusable workflow: {sorted(mapped - declared)}"

    def test_every_mapped_input_name_is_unique(self):
        """Should keep the input->field mapping one-to-one, since it is global across workflows."""
        registry = _load_registry()
        names = [entry[4] for entry in registry if entry[4] is not None]
        assert len(names) == len(set(names))


def _load_module():
    """Import read-config.py from its hyphenated script path."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("read_config", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_registry():
    """Import FIELD_REGISTRY from the hyphenated script path."""
    return _load_module().FIELD_REGISTRY


@pytest.mark.parametrize(
    "action_yml", sorted((PROJECT_ROOT / ".github" / "actions").glob("*/action.yml")), ids=lambda p: p.parent.name
)
def test_action_descriptions_hold_no_expressions(action_yml):
    """Should keep `${{ }}` out of action descriptions.

    GitHub evaluates expressions even inside a description, where no `inputs`
    context exists, so a documented `${{ toJSON(inputs) }}` fails every step that
    uses the action with "Unrecognized named-value: 'inputs'". Unit tests run the
    script directly and cannot see it; only an Actions run does.
    """
    import yaml

    doc = yaml.safe_load(action_yml.read_text(encoding="utf-8"))
    entries = [("action", doc)] + [
        (f"{kind}.{name}", spec) for kind in ("inputs", "outputs") for name, spec in (doc.get(kind) or {}).items()
    ]
    offending = [where for where, spec in entries if "${{" in str((spec or {}).get("description", ""))]
    assert not offending, f"{action_yml}: expression in description of {offending}"


WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"

# (workflow, input) pairs deliberately read as `inputs.X` rather than through
# config. pyprojectx's skip-on-docs-only drives its own footprint filter in the
# `gate` job, which runs before config and has nothing to do with
# maven-build.skip-on-docs-only; its default (false) differs on purpose.
DIRECT_INPUT_EXEMPTIONS = {("reusable-pyprojectx-verify.yml", "skip-on-docs-only")}


def _reusable_workflows():
    """Yield (path, parsed doc, raw text, declared inputs) for every workflow_call workflow."""
    import yaml

    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        doc = yaml.safe_load(text) or {}
        on = doc.get("on", doc.get(True)) or {}
        call = on.get("workflow_call") if isinstance(on, dict) else None
        if isinstance(call, dict):
            yield path, doc, text, call.get("inputs") or {}


def _config_steps(doc):
    for job in (doc.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            if "read-project-config" in str(step.get("uses", "")):
                yield step


def _render(module, transform, value):
    """Render a raw value exactly as read-config.py would emit it."""
    return module.to_output_value(transform(value) if transform else value)


class TestWorkflowsUseResolvedConfig:
    """The workflows hand their inputs to read-project-config and use its outputs as-is.

    These replace the guards for the three inline resolution shapes
    (`X || inputs.Y`, `X != 'false' && inputs.Y`, `X == 'true' || (X == '' &&
    inputs.Y)`), which no longer exist. Each is derived from the workflow files,
    not from a hand-kept key list -- the hand-kept list is how seven keys went
    unguarded until #293.
    """

    def test_every_config_step_passes_caller_inputs(self):
        """Should pass toJSON(inputs) at every read-project-config step of a reusable workflow."""
        seen, missing = 0, []
        for path, doc, _, _ in _reusable_workflows():
            for step in _config_steps(doc):
                seen += 1
                if (step.get("with") or {}).get("caller-inputs") != "${{ toJSON(inputs) }}":
                    missing.append(f"{path.name}: {step.get('id') or step.get('name')}")
        assert seen >= 6, "found fewer config steps than the six reusable workflows that read project.yml"
        assert not missing, f"config steps without caller-inputs: ${{{{ toJSON(inputs) }}}}: {missing}"

    def test_mapped_inputs_are_not_read_directly(self):
        """Should read a mapped input only through config, where project.yml can win."""
        mapped = {entry[4] for entry in _load_registry() if entry[4] is not None}
        offending = []
        for path, _, text, _ in _reusable_workflows():
            for name in re.findall(r"\binputs\.([a-z0-9-]+)", text):
                if name in mapped and (path.name, name) not in DIRECT_INPUT_EXEMPTIONS:
                    offending.append(f"{path.name}: inputs.{name}")
        assert not offending, f"mapped inputs read directly, bypassing project.yml: {sorted(set(offending))}"

    def test_boolean_outputs_are_compared_explicitly(self):
        """Should compare every boolean output with 'true'/'false'.

        Outputs are strings, and the string 'false' is truthy in an `if:` -- a bare
        `needs.config.outputs.sonar-enabled` would silently always pass.
        """
        booleans = {entry[1] for entry in _load_registry() if isinstance(entry[2], bool)}
        pattern = re.compile(r"config\.outputs\.([a-z0-9-]+)\b(?!\s*[=!]=\s*'(?:true|false)')")
        passthrough = re.compile(r"^\s*([a-z0-9-]+):\s*\$\{\{\s*steps\.config\.outputs\.\1\s*\}\}\s*$")
        offending, checked = [], 0
        for path, _, text, _ in _reusable_workflows():
            for line in text.splitlines():
                if passthrough.match(line):
                    continue
                for m in re.finditer(r"config\.outputs\.([a-z0-9-]+)", line):
                    checked += m.group(1) in booleans
                for name in pattern.findall(line):
                    if name in booleans:
                        offending.append(f"{path.name}: {line.strip()[:120]}")
        assert checked >= 5, "non-vacuity: expected several boolean output comparisons"
        assert not offending, f"boolean outputs used without an explicit comparison: {offending}"

    def test_mapped_input_defaults_match_the_registry(self):
        """Should keep each workflow input default equal to the registry default.

        The input default is what a reusable workflow resolves to; the registry
        default is what direct users of the action get. Both are the same setting.
        """
        module = _load_module()
        registry = {entry[4]: entry for entry in module.FIELD_REGISTRY if entry[4] is not None}

        def render(entry, value):
            _, _, default, transform, _ = entry
            value = module._normalize_input(value, default)
            return module.to_output_value(transform(value) if transform else value)

        mismatches, compared = [], 0
        for path, _, _, inputs in _reusable_workflows():
            for name, spec in inputs.items():
                if name not in registry or (path.name, name) in DIRECT_INPUT_EXEMPTIONS or "default" not in spec:
                    continue
                entry = registry[name]
                compared += 1
                if render(entry, spec["default"]) != render(entry, entry[2]):
                    mismatches.append(f"{path.name}: {name}={spec['default']!r} vs registry {entry[2]!r}")
        assert compared >= 15, "non-vacuity: expected every mapped input across the workflows"
        assert not mismatches, f"workflow input default differs from the registry: {mismatches}"

    def test_schema_defaults_match_the_registry(self):
        """Should keep schema.json's documented defaults equal to the registry defaults."""
        module = _load_module()
        schema = json.loads((SCRIPT_PATH.parent / "schema.json").read_text(encoding="utf-8"))
        mismatches, compared = [], 0
        for yaml_path, output_name, default, transform, input_name in module.FIELD_REGISTRY:
            if input_name is None or len(yaml_path) != 2:
                continue
            node = schema["properties"].get(yaml_path[0], {}).get("properties", {}).get(yaml_path[1], {})
            if "default" not in node:
                continue
            compared += 1
            if _render(module, transform, node["default"]) != _render(module, transform, default):
                mismatches.append(f"{output_name}: schema {node['default']!r} vs registry {default!r}")
        assert compared >= 10, "non-vacuity: expected most mapped fields to document a schema default"
        assert not mismatches, f"schema.json default differs from the registry: {mismatches}"
