"""Tests for build_paths_filter_spec.py - shared docs-only paths-filter spec builder."""

import importlib.util
import re
import sys
from pathlib import Path

import pytest
import yaml

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


class TestBuildIncludeSpec:
    def test_empty_include_renders_no_spec(self):
        """An empty include is a no-op: the caller skips the second filter call."""
        mod = _load_module()
        assert mod.build_include_spec("code-include", "") == ""
        assert mod.build_include_spec("code-include", "   ") == ""

    def test_include_patterns_are_positive(self):
        mod = _load_module()
        spec = mod.build_include_spec("code-include", "doc/specification/**/*.adoc schema/*.md")
        assert spec == "code-include:\n  - 'doc/specification/**/*.adoc'\n  - 'schema/*.md'"

    def test_include_globs_never_enter_the_ignore_spec(self):
        """The include list is its own group: build_spec takes no include at all."""
        mod = _load_module()
        spec = mod.build_spec("code", "")
        assert "doc/specification" not in spec
        assert spec.count("- '!") == len(mod.BASE_IGNORED_PATTERNS)


class TestDecide:
    def test_include_match_builds_even_when_ignore_group_says_docs_only(self):
        mod = _load_module()
        assert mod.decide("false", "true") == "true"

    def test_no_include_match_keeps_the_ignore_group_result(self):
        mod = _load_module()
        assert mod.decide("false", "false") == "false"
        assert mod.decide("true", "false") == "true"

    def test_include_call_not_run_keeps_the_ignore_group_result(self):
        mod = _load_module()
        assert mod.decide("false", "") == "false"
        assert mod.decide("true", "") == "true"


def _glob_to_regex(pattern):
    """picomatch-style glob (dot: true, as dorny/paths-filter uses it) to a regex.

    Test-only model of how dorny matches a pattern, so the specs this script
    renders can be evaluated end to end against concrete changed-file lists.
    """
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(f"^{out}$")


def _patterns(spec):
    return [line.strip()[3:-1] for line in spec.splitlines()[1:]]


def _should_build(mod, changed, extra="", include=""):
    """Evaluate both rendered specs the way the workflows do, then decide."""
    ignores = [_glob_to_regex(p[1:]) for p in _patterns(mod.build_spec("code", extra))]
    # predicate-quantifier 'every': a file is code when it matches none of the ignore globs.
    code = any(not any(r.match(f) for r in ignores) for f in changed)
    include_spec = mod.build_include_spec("code-include", include)
    included = ""
    if include_spec:
        # default quantifier 'some': a file is included when it matches any include glob.
        includes = [_glob_to_regex(p) for p in _patterns(include_spec)]
        included = "true" if any(r.match(f) for r in includes for f in changed) else "false"
    return mod.decide("true" if code else "false", included)


class TestGateSemantics:
    INCLUDE = "doc/specification/**/*.adoc"

    def test_plan_only_change_still_skips_with_an_include_list(self):
        mod = _load_module()
        assert _should_build(mod, [".plan/orchestrator/ledger.json"], include=self.INCLUDE) == "false"

    def test_include_wins_over_the_base_ignore_list(self):
        mod = _load_module()
        assert _should_build(mod, ["doc/specification/api/schema.adoc"], include=self.INCLUDE) == "true"

    def test_file_matching_both_an_extra_ignore_and_an_include_builds(self):
        mod = _load_module()
        changed = ["doc/specification/api/schema.adoc"]
        assert _should_build(mod, changed, extra="doc/specification/**", include=self.INCLUDE) == "true"

    def test_empty_include_is_a_no_op(self):
        mod = _load_module()
        for changed in (
            ["doc/specification/api/schema.adoc"],
            [".plan/x"],
            ["src/Main.java"],
            ["README.md", "pom.xml"],
        ):
            assert _should_build(mod, changed, include="") == _should_build(mod, changed)
        assert _should_build(mod, ["doc/specification/api/schema.adoc"]) == "false"

    def test_other_docs_still_skip_with_an_include_list(self):
        mod = _load_module()
        assert _should_build(mod, ["README.md", "doc/guide/intro.adoc"], include=self.INCLUDE) == "false"

    def test_code_change_builds_regardless_of_include(self):
        mod = _load_module()
        assert _should_build(mod, ["src/main/java/A.java"], include=self.INCLUDE) == "true"


class TestMainIncludeAndDecide:
    def test_include_spec_is_always_emitted(self):
        result = run_script(SCRIPT_PATH)
        assert result.returncode == 0
        assert "include-spec<<EOF\n\nEOF" in result.stdout

    def test_include_reaches_stdout(self):
        result = run_script(SCRIPT_PATH, "--include", "doc/specification/**/*.adoc")
        assert result.returncode == 0
        assert "include-spec<<EOF\ncode-include:\n  - 'doc/specification/**/*.adoc'\nEOF" in result.stdout

    def test_decide_mode_emits_should_build(self):
        result = run_script(SCRIPT_PATH, "--decide", "--code", "false", "--included", "true")
        assert result.returncode == 0
        assert result.stdout == "should-build=true\n"

    def test_decide_mode_without_include_result(self):
        result = run_script(SCRIPT_PATH, "--decide", "--code", "false", "--included", "")
        assert result.stdout == "should-build=false\n"

    def test_decide_mode_rejects_a_missing_code_result(self):
        """A missing ignore-group result must fail, never read as docs-only."""
        result = run_script(SCRIPT_PATH, "--decide", "--code", "", "--included", "")
        assert result.returncode != 0
        assert "should-build" not in result.stdout


@pytest.mark.parametrize(
    ("workflow", "output"),
    [("reusable-maven-build.yml", "should-build"), ("reusable-maven-integration-tests.yml", "should-test")],
)
class TestWorkflowWiring:
    """Both Maven gates OR the include group in the same way and still fail open."""

    def _job(self, workflow):
        doc = yaml.safe_load((PROJECT_ROOT / ".github/workflows" / workflow).read_text())
        return doc["jobs"]["check-changes"]

    def _step(self, job, step_id):
        return next(step for step in job["steps"] if step.get("id") == step_id)

    def test_gate_output_is_the_decided_result(self, workflow, output):
        assert self._job(workflow)["outputs"][output] == "${{ steps.decide.outputs.should-build }}"

    def test_include_spec_comes_from_paths_code_extra(self, workflow, output):
        build = self._step(self._job(workflow), "build-filter")
        assert build["with"]["include"] == "${{ needs.config.outputs.paths-code-extra }}"
        assert build["with"]["extra"] == "${{ needs.config.outputs.paths-ignore-extra }}"

    def test_include_filter_runs_only_with_an_include_spec_and_default_quantifier(self, workflow, output):
        include = self._step(self._job(workflow), "include")
        assert include["if"] == "steps.build-filter.outputs.include-spec != ''"
        assert "predicate-quantifier" not in include["with"]
        assert include["with"]["filters"] == "${{ steps.build-filter.outputs.include-spec }}"

    def test_ignore_filter_keeps_every_quantifier(self, workflow, output):
        assert self._step(self._job(workflow), "filter")["with"]["predicate-quantifier"] == "every"

    def test_decide_combines_both_results(self, workflow, output):
        decide = self._step(self._job(workflow), "decide")
        assert "build-paths-filter-spec@" in decide["uses"]
        assert decide["with"] == {
            "code-result": "${{ steps.filter.outputs.code }}",
            "include-result": "${{ steps.include.outputs.code-include }}",
        }

    def test_no_step_fails_closed(self, workflow, output):
        """A failing filter must fail the job (output '' -> builds), never be swallowed."""
        assert not any(step.get("continue-on-error") for step in self._job(workflow)["steps"])

    def test_config_job_passes_paths_code_extra_through(self, workflow, output):
        doc = yaml.safe_load((PROJECT_ROOT / ".github/workflows" / workflow).read_text())
        assert doc["jobs"]["config"]["outputs"]["paths-code-extra"] == "${{ steps.config.outputs.paths-code-extra }}"
        trigger = doc.get("on", doc.get(True))
        assert trigger["workflow_call"]["inputs"]["paths-code-extra"]["default"] == ""
