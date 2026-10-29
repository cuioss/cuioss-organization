"""Tests for caller_triggers.py: the push-trigger normalization of the release fan-out.

A branch is built by its pull_request run, so a consumer's build caller must not list
feature, fix or chore branches in `on.push.branches`. The release fan-out removes
them in the same PR as the pin bump; these tests pin what is removed, what is kept
and what is left alone.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "workflow-scripts"))
import caller_triggers as ct

PIN = "711571432df351d3c5b08d5d50cb6c331f61abb1"


def _caller(push_block, workflow="reusable-maven-build.yml", extra_on=""):
    return (
        "name: Build\n"
        "\n"
        "on:\n"
        "  push:\n"
        f"{push_block}\n"
        "  pull_request:\n"
        "    branches: [main]\n"
        "  workflow_dispatch:\n"
        f"{extra_on}"
        "  merge_group:\n"
        "\n"
        "permissions:\n"
        "  contents: read\n"
        "\n"
        "jobs:\n"
        "  build:\n"
        f"    uses: cuioss/cuioss-organization/.github/workflows/{workflow}@{PIN} # v0.42.0\n"
    )


class TestFlowList:
    def test_removes_the_working_branch_patterns_and_the_ledger_negation(self):
        """Should keep main, release/* and dependabot/** and drop the rest."""
        text = _caller(
            '    branches: [main, "feature/*", "fix/*", "chore/*", "!chore/orchestrator-ledger", "release/*", "dependabot/**"]'
        )
        new, status, detail = ct.normalize_push_branches(text)
        assert (status, detail) == (ct.STATUS_CHANGED, "")
        assert '    branches: [main, "release/*", "dependabot/**"]\n' in new

    def test_only_the_push_list_changes(self):
        """Should leave pull_request, merge_group, permissions and the job untouched."""
        text = _caller('    branches: [main, "feature/*", "dependabot/**"]')
        new, _, _ = ct.normalize_push_branches(text)
        assert new.replace('"dependabot/**"]', "X").count("X") == 1
        removed = text.replace(
            '    branches: [main, "feature/*", "dependabot/**"]', '    branches: [main, "dependabot/**"]'
        )
        assert new == removed

    def test_keeps_the_trailing_comment_and_custom_entries(self):
        """Should keep a comment after the list and a branch pattern it knows nothing about."""
        text = _caller('    branches: [main, "feature/*", "staging", "release/*"]  # builds')
        new, status, _ = ct.normalize_push_branches(text)
        assert status == ct.STATUS_CHANGED
        assert '    branches: [main, "staging", "release/*"]  # builds\n' in new

    def test_accepts_single_quotes_and_plain_scalars(self):
        """Should read every scalar style a flow list can use."""
        text = _caller("    branches: [main, 'feature/*', fix/*, \"dependabot/**\"]")
        new, status, _ = ct.normalize_push_branches(text)
        assert status == ct.STATUS_CHANGED
        assert '    branches: [main, "dependabot/**"]\n' in new

    def test_a_list_without_working_branches_is_unchanged(self):
        text = _caller('    branches: [main, "release/*", "dependabot/**"]')
        assert ct.normalize_push_branches(text) == (text, ct.STATUS_UNCHANGED, "")

    def test_is_idempotent(self):
        text = _caller('    branches: [main, "feature/*", "fix/*", "chore/*", "release/*"]')
        once, _, _ = ct.normalize_push_branches(text)
        assert ct.normalize_push_branches(once) == (once, ct.STATUS_UNCHANGED, "")


class TestBlockList:
    def test_removes_items_and_keeps_comments_and_other_entries(self):
        """Should drop the pattern lines, and with them their own trailing comment only."""
        block = (
            "    branches:\n"
            "      - main\n"
            '      - "feature/*"  # early feedback\n'
            "      # release branches are built on push\n"
            '      - "release/*"\n'
            "      - fix/*"
        )
        new, status, _ = ct.normalize_push_branches(_caller(block))
        assert status == ct.STATUS_CHANGED
        assert new.split("  pull_request:")[0].endswith(
            '    branches:\n      - main\n      # release branches are built on push\n      - "release/*"\n'
        )

    def test_dashes_at_the_indent_of_their_key(self):
        """Should read a block sequence whose dashes are not indented under the key."""
        block = '    branches:\n    - main\n    - feature/*\n    - "dependabot/**"'
        new, status, _ = ct.normalize_push_branches(_caller(block))
        assert status == ct.STATUS_CHANGED
        assert '    branches:\n    - main\n    - "dependabot/**"\n  pull_request:' in new


class TestLeftAlone:
    def test_a_workflow_that_calls_no_build_workflow_is_not_a_caller(self):
        """Should never touch a workflow that does not call a reusable build workflow."""
        text = _caller('    branches: [main, "feature/*"]', workflow="reusable-scorecards.yml")
        assert ct.normalize_push_branches(text) == (text, ct.STATUS_NOT_A_CALLER, "")

    @pytest.mark.parametrize("workflow", ct.BUILD_WORKFLOWS)
    def test_each_build_workflow_is_normalized(self, workflow):
        text = _caller('    branches: [main, "feature/*"]', workflow=f"{workflow}.yml")
        assert ct.normalize_push_branches(text)[1] == ct.STATUS_CHANGED

    def test_a_push_trigger_without_branches_is_unchanged(self):
        text = _caller('    tags: ["v*"]')
        assert ct.normalize_push_branches(text) == (text, ct.STATUS_UNCHANGED, "")

    def test_pull_request_branches_are_not_the_push_list(self):
        """Should not read the pull_request list when push has none."""
        text = _caller('    tags: ["v*"]').replace("branches: [main]", 'branches: [main, "feature/*"]')
        assert ct.normalize_push_branches(text) == (text, ct.STATUS_UNCHANGED, "")

    def test_a_shorthand_on_is_unchanged(self):
        text = (
            "on: [push, pull_request]\n"
            "jobs:\n  build:\n"
            f"    uses: cuioss/cuioss-organization/.github/workflows/reusable-maven-build.yml@{PIN}\n"
        )
        assert ct.normalize_push_branches(text) == (text, ct.STATUS_UNCHANGED, "")


class TestUnparseable:
    @pytest.mark.parametrize(
        "block",
        [
            '    branches: [main,\n      "feature/*"]',
            "    branches: *shared",
            "    branches: [main, {a: b}]",
            "    branches:\n      - &anchor main\n      - feature/*",
            "    branches: [main, \"feature/*\", 'it''s']",
        ],
    )
    def test_reports_and_leaves_the_text_untouched(self, block):
        """Should never guess at a list it cannot read with certainty."""
        text = _caller(block)
        new, status, detail = ct.normalize_push_branches(text)
        assert new == text
        assert status == ct.STATUS_UNPARSEABLE
        assert detail

    def test_flow_mapping_for_push_is_unparseable(self):
        text = _caller("").replace("  push:\n\n", '  push: {branches: [main, "feature/*"]}\n')
        new, status, _ = ct.normalize_push_branches(text)
        assert (new, status) == (text, ct.STATUS_UNPARSEABLE)

    def test_does_not_leave_a_list_without_a_branch_to_build(self):
        """Should refuse a change that would leave only negations behind."""
        text = _caller('    branches: ["feature/*", "!feature/x"]')
        new, status, detail = ct.normalize_push_branches(text)
        assert (new, status) == (text, ct.STATUS_UNPARSEABLE)
        assert "no branch" in detail


class TestKeepsPushBuilds:
    @pytest.mark.parametrize(
        "yaml_text,expected",
        [
            ("ci:\n  push-builds: deduplicated\n", True),
            ("ci:\n  push-builds: 'deduplicated'  # early feedback\n", True),
            ("name: x\nci:\n  push-builds: deduplicated\nrelease:\n  current-version: 1\n", True),
            ("ci: {push-builds: deduplicated}\n", True),
            ("ci:\n  push-builds: default-branch-only\n", False),
            ("ci:\n  other: 1\nrelease:\n  push-builds: deduplicated\n", False),
            ("name: x\n", False),
        ],
    )
    def test_reads_the_opt_out_by_line(self, tmp_path, yaml_text, expected):
        project = tmp_path / "project.yml"
        project.write_text(yaml_text)
        assert ct.keeps_push_builds(project) is expected

    def test_no_project_yml_means_no_opt_out(self, tmp_path):
        assert ct.keeps_push_builds(tmp_path / "missing.yml") is False


class TestNormalizeRepo:
    def _repo(self, tmp_path, project_yml=None):
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "maven.yml").write_text(_caller('    branches: [main, "feature/*", "release/*"]'))
        (workflows / "odd.yaml").write_text(_caller('    branches: [main,\n      "feature/*"]'))
        (workflows / "scorecards.yml").write_text(
            _caller('    branches: [main, "feature/*"]', workflow="reusable-scorecards.yml")
        )
        if project_yml is not None:
            (tmp_path / ".github" / "project.yml").write_text(project_yml)
        return tmp_path

    def test_rewrites_callers_and_reports_what_it_could_not_read(self, tmp_path):
        repo = self._repo(tmp_path)
        changed, notes = ct.normalize_repo(repo)
        assert changed == [".github/workflows/maven.yml"]
        assert len(notes) == 1
        assert notes[0].startswith(".github/workflows/odd.yaml:")
        assert "by hand" in notes[0]
        assert '"feature/*"' in (repo / ".github/workflows/odd.yaml").read_text()
        assert '"feature/*"' in (repo / ".github/workflows/scorecards.yml").read_text()
        assert '"feature/*"' not in (repo / ".github/workflows/maven.yml").read_text()

    def test_a_repository_that_keeps_push_builds_is_not_touched(self, tmp_path):
        repo = self._repo(tmp_path, project_yml="ci:\n  push-builds: deduplicated\n")
        before = (repo / ".github/workflows/maven.yml").read_text()
        assert ct.normalize_repo(repo) == ([], [])
        assert (repo / ".github/workflows/maven.yml").read_text() == before
