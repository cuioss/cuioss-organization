"""Tests for build_paths_filter_spec.py - shared docs-only paths-filter spec builder."""

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT, run_script

SCRIPT_PATH = PROJECT_ROOT / ".github/actions/build-paths-filter-spec/build_paths_filter_spec.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("build_paths_filter_spec", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestBuildSpec:
    def test_default_filter_name_is_code(self):
        mod = _load_module()
        spec = mod.build_spec("code", "")
        assert spec.startswith("code:\n")

    def test_custom_filter_name(self):
        mod = _load_module()
        spec = mod.build_spec("buildable", "")
        assert spec.startswith("buildable:\n")

    def test_includes_every_base_pattern(self):
        mod = _load_module()
        spec = mod.build_spec("code", "")
        for pattern in mod.BASE_IGNORED_PATTERNS:
            assert f"  - '!{pattern}'" in spec

    def test_gitignore_is_ignored(self):
        """Regression guard for the bug that motivated this script."""
        mod = _load_module()
        spec = mod.build_spec("code", "")
        assert "  - '!.gitignore'" in spec

    def test_dev_tooling_dirs_are_ignored(self):
        mod = _load_module()
        spec = mod.build_spec("code", "")
        for pattern in [".agents/**", ".opencode/**", "opencode.json", ".vscode/**"]:
            assert f"  - '!{pattern}'" in spec

    def test_appends_extra_patterns(self):
        mod = _load_module()
        spec = mod.build_spec("code", "e-2-e-playwright/docs/**")
        assert "  - '!e-2-e-playwright/docs/**'" in spec

    def test_extra_patterns_come_after_base_patterns(self):
        mod = _load_module()
        spec = mod.build_spec("code", "custom/path/**")
        assert spec.index("custom/path/**") > spec.index(".gitignore")

    def test_multiple_extra_patterns_are_split_on_whitespace(self):
        mod = _load_module()
        spec = mod.build_spec("code", "foo/** bar/**")
        assert "  - '!foo/**'" in spec
        assert "  - '!bar/**'" in spec

    def test_glob_characters_in_extra_are_not_shell_expanded(self):
        """The bug this script replaces: an unquoted bash `for pattern in $EXTRA`
        performs pathname expansion, turning a glob into whatever files happen to
        match in the current working directory. Pure Python string splitting has
        no such behavior - the glob string must survive verbatim regardless of
        what exists on disk at the location this runs.
        """
        mod = _load_module()
        spec = mod.build_spec("code", "**/*.txt")
        assert "  - '!**/*.txt'" in spec

    def test_empty_extra_adds_nothing_beyond_base_patterns(self):
        mod = _load_module()
        spec = mod.build_spec("code", "")
        assert spec.count("- '!") == len(mod.BASE_IGNORED_PATTERNS)


class TestMainOutput:
    def test_stdout_is_github_output_multiline_format(self):
        result = run_script(SCRIPT_PATH, "--filter-name", "code", "--extra", "")
        assert result.returncode == 0
        assert result.stdout.startswith("spec<<EOF\n")
        assert result.stdout.rstrip("\n").endswith("EOF")

    def test_defaults_to_filter_name_code(self):
        result = run_script(SCRIPT_PATH)
        assert result.returncode == 0
        assert "code:" in result.stdout

    def test_extra_reaches_stdout(self):
        result = run_script(SCRIPT_PATH, "--extra", "custom/**")
        assert result.returncode == 0
        assert "custom/**" in result.stdout
