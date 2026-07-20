"""Tests for read-config.py - project.yml configuration parser."""

import json
import sys
from pathlib import Path

import pytest

# Add parent to path to access conftest
sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT, run_script

SCRIPT_PATH = PROJECT_ROOT / ".github/actions/read-project-config/read-config.py"


def _parse_output(stdout: str) -> dict[str, str]:
    """Parse GITHUB_OUTPUT-style key=value lines into a dict."""
    return {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in stdout.strip().split("\n")
        if "=" in line
    }


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
        assert "pyprojectx-cache-dependency-glob=\n" in result.stdout
        assert "pyprojectx-upload-artifacts-on-failure=false" in result.stdout
        # Empty, not 'verify': an absent key must fall through to the consuming
        # workflow's input default rather than always winning the `config || input`
        # resolution and shadowing what the caller passed.
        assert "pyprojectx-verify-goals=\n" in result.stdout
        assert "pyprojectx-verify-args=\n" in result.stdout

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
        config.write_text(
            'pyprojectx:\n  verify-goals: "verify\\nsonar-project-key=pwned"\n'
        )
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


class TestConfigOverInputPrecedence:
    """Guard the config-over-input resolution contract in the reusable workflows.

    The reusable workflows resolve most settings as
    ``steps.config.outputs.X || inputs.X``. GitHub Actions' ``||`` returns the
    left operand whenever it is truthy, so a NON-EMPTY registry default here makes
    the config side permanently truthy and silently renders the caller's input
    unreachable dead code — the build ignores what the caller asked for and no
    existing test noticed. That bug shipped for ``cache-dependency-glob`` and was
    reintroduced for ``verify-goals``; these tests are the standing guard.

    A key belongs in FALLTHROUGH_KEYS only if the workflow resolves it with a bare
    ``||``. Keys resolved by boolean OR (e.g. upload-artifacts-on-failure, via
    ``X == 'true' || inputs.X``) keep the input reachable and are excluded.
    """

    # (output name, the value the consuming workflow supplies as its input default)
    FALLTHROUGH_KEYS = [
        ("pyprojectx-python-version", "3.12"),
        ("pyprojectx-cache-dependency-glob", "uv.lock"),
        ("pyprojectx-verify-goals", "verify"),
        ("pyprojectx-verify-args", "--module=workflow"),
    ]

    @pytest.mark.parametrize("output_name,_caller_input", FALLTHROUGH_KEYS)
    def test_unset_key_emits_empty_so_caller_input_is_reachable(
        self, output_name, _caller_input, temp_dir
    ):
        """Should emit '' when project.yml omits the key, so `|| inputs.X` falls through."""
        config = temp_dir / "project.yml"
        config.write_text("name: some-repo\n")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        assert result.returncode == 0
        assert _parse_output(result.stdout)[output_name] == "", (
            f"{output_name} has a non-empty default, which makes the config side of "
            f"`config.outputs.{output_name} || inputs.*` permanently truthy and the "
            f"caller's input unreachable"
        )

    @pytest.mark.parametrize("output_name,caller_input", FALLTHROUGH_KEYS)
    def test_caller_input_wins_when_key_unset(self, output_name, caller_input, temp_dir):
        """Should let a caller-supplied input reach the command when project.yml is silent.

        Evaluates the workflow's actual `config || input` expression rather than
        only asserting the empty default, so the assertion is about the resolved
        value the build ultimately runs with.
        """
        config = temp_dir / "project.yml"
        config.write_text("name: some-repo\n")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        config_value = _parse_output(result.stdout)[output_name]

        resolved = config_value or caller_input  # mirrors `${{ config || inputs }}`
        assert resolved == caller_input

    def test_project_yml_still_overrides_the_caller_input(self, temp_dir):
        """Should keep project.yml winning when it DOES set the key.

        The counterpart to the tests above: the empty-default fix must not flip
        precedence, only restore reachability.
        """
        config = temp_dir / "project.yml"
        config.write_text("pyprojectx:\n  verify-goals: quality-gate\n")
        result = run_script(SCRIPT_PATH, "--config", str(config))
        config_value = _parse_output(result.stdout)["pyprojectx-verify-goals"]

        resolved = config_value or "verify"
        assert resolved == "quality-gate"


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
