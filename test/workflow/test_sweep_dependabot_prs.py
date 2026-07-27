"""Tests for sweep-dependabot-prs.py - the org-central Dependabot merge sweeper."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

# Add parent to path to access conftest
sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT, run_script

SCRIPT_PATH = PROJECT_ROOT / "workflow-scripts/sweep-dependabot-prs.py"


def _load_module():
    """Load sweep-dependabot-prs.py as a module for unit testing."""
    spec = importlib.util.spec_from_file_location("sweep_dependabot_prs", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _completed(returncode: int = 0, stdout: str = "", stderr: str = ""):
    """Build a CompletedProcess as run_gh returns it."""
    return subprocess.CompletedProcess(
        args=["gh"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _pr_state(**overrides) -> dict:
    """A ready-to-merge PR state, with overrides for the case under test."""
    state = {
        "state": "OPEN",
        "isDraft": False,
        "isInMergeQueue": False,
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
    }
    state.update(overrides)
    return state


class TestArgumentValidation:
    """Test command line argument handling."""

    def test_rejects_unknown_argument(self):
        """Should fail on an argument the script does not define."""
        result = run_script(SCRIPT_PATH, "--not-an-option")
        assert result.returncode != 0

    def test_help_lists_dry_run(self):
        """--help should advertise the dry-run mode."""
        result = run_script(SCRIPT_PATH, "--help")
        assert result.returncode == 0
        assert "--dry-run" in result.stdout


class TestClassify:
    """Test the merge-readiness decision."""

    def test_ready_pr_is_merged(self):
        mod = _load_module()
        assert mod.classify(_pr_state()) == "merge"

    def test_queued_pr_is_left_alone(self):
        """A PR already in the queue must not be re-enqueued."""
        mod = _load_module()
        assert mod.classify(_pr_state(isInMergeQueue=True)) == "queued"

    def test_draft_is_skipped(self):
        mod = _load_module()
        assert mod.classify(_pr_state(isDraft=True)) == "draft"

    def test_closed_pr_is_skipped(self):
        mod = _load_module()
        assert mod.classify(_pr_state(state="CLOSED")) == "not-open"

    def test_conflicting_pr_is_not_ready(self):
        mod = _load_module()
        assert mod.classify(_pr_state(mergeable="CONFLICTING")) == "not-ready"

    def test_blocked_pr_is_not_ready(self):
        """BLOCKED means a required check is missing or failing -- never force it."""
        mod = _load_module()
        assert mod.classify(_pr_state(mergeStateStatus="BLOCKED")) == "not-ready"

    def test_behind_pr_is_not_ready(self):
        mod = _load_module()
        assert mod.classify(_pr_state(mergeStateStatus="BEHIND")) == "not-ready"

    def test_unreadable_state_is_unknown(self):
        mod = _load_module()
        assert mod.classify(None) == "unknown"


class TestFindCandidates:
    """Test discovery of labelled Dependabot PRs."""

    def test_parses_search_results(self):
        mod = _load_module()
        payload = json.dumps(
            [
                {
                    "number": 12,
                    "repository": {"nameWithOwner": "cuioss/TokenSheriff"},
                    "url": "https://github.com/cuioss/TokenSheriff/pull/12",
                    "title": "bump x",
                }
            ]
        )
        with patch.object(mod, "run_gh", return_value=_completed(stdout=payload)):
            candidates = mod.find_candidates("cuioss", "automerge", "app/dependabot", 100)
        assert candidates == [
            {
                "repo": "cuioss/TokenSheriff",
                "number": 12,
                "url": "https://github.com/cuioss/TokenSheriff/pull/12",
                "title": "bump x",
            }
        ]

    def test_empty_output_yields_no_candidates(self):
        mod = _load_module()
        with patch.object(mod, "run_gh", return_value=_completed(stdout="")):
            assert mod.find_candidates("cuioss", "automerge", "app/dependabot", 100) == []

    def test_search_failure_raises(self):
        """A failed search must not be reported as 'nothing to merge'."""
        mod = _load_module()
        with patch.object(mod, "run_gh", return_value=_completed(1, stderr="boom")):
            try:
                mod.find_candidates("cuioss", "automerge", "app/dependabot", 100)
            except RuntimeError as exc:
                assert "boom" in str(exc)
            else:
                raise AssertionError("expected RuntimeError")

    def test_passes_label_and_author_filters(self):
        mod = _load_module()
        with patch.object(mod, "run_gh", return_value=_completed(stdout="[]")) as gh:
            mod.find_candidates("cuioss", "automerge", "app/dependabot", 50)
        args = gh.call_args[0][0]
        assert args[:3] == ["search", "prs", "--owner"]
        assert "--label" in args and args[args.index("--label") + 1] == "automerge"
        assert "--author" in args and args[args.index("--author") + 1] == "app/dependabot"
        assert "--limit" in args and args[args.index("--limit") + 1] == "50"


class TestSweep:
    """Test the end-to-end sweep over discovered PRs."""

    def _candidate(self):
        return [
            {
                "repo": "cuioss/TokenSheriff",
                "number": 7,
                "url": "u",
                "title": "bump x",
            }
        ]

    def test_merges_ready_pr(self):
        mod = _load_module()
        with (
            patch.object(mod, "find_candidates", return_value=self._candidate()),
            patch.object(mod, "read_pr_state", return_value=_pr_state()),
            patch.object(mod, "merge_pr", return_value=(True, "queued")) as merge,
        ):
            outcomes = mod.sweep("cuioss", "automerge", "app/dependabot", 100, False)
        merge.assert_called_once_with("cuioss/TokenSheriff", 7)
        assert outcomes[0]["action"] == "merged"

    def test_dry_run_does_not_merge(self):
        mod = _load_module()
        with (
            patch.object(mod, "find_candidates", return_value=self._candidate()),
            patch.object(mod, "read_pr_state", return_value=_pr_state()),
            patch.object(mod, "merge_pr") as merge,
        ):
            outcomes = mod.sweep("cuioss", "automerge", "app/dependabot", 100, True)
        merge.assert_not_called()
        assert outcomes[0]["action"] == "would-merge"

    def test_not_ready_pr_is_not_merged(self):
        mod = _load_module()
        with (
            patch.object(mod, "find_candidates", return_value=self._candidate()),
            patch.object(mod, "read_pr_state", return_value=_pr_state(mergeStateStatus="BLOCKED")),
            patch.object(mod, "merge_pr") as merge,
        ):
            outcomes = mod.sweep("cuioss", "automerge", "app/dependabot", 100, False)
        merge.assert_not_called()
        assert outcomes[0]["action"] == "not-ready"

    def test_merge_failure_is_reported(self):
        mod = _load_module()
        with (
            patch.object(mod, "find_candidates", return_value=self._candidate()),
            patch.object(mod, "read_pr_state", return_value=_pr_state()),
            patch.object(mod, "merge_pr", return_value=(False, "not mergeable")),
        ):
            outcomes = mod.sweep("cuioss", "automerge", "app/dependabot", 100, False)
        assert outcomes[0]["action"] == "merge-failed"
        assert outcomes[0]["detail"] == "not mergeable"


class TestMergePr:
    """Test the merge invocation itself."""

    def test_uses_squash_against_the_owning_repo(self):
        """The queue's merge_method is SQUASH; the direct-merge path must match."""
        mod = _load_module()
        with patch.object(mod, "run_gh", return_value=_completed(stdout="ok")) as gh:
            ok, detail = mod.merge_pr("cuioss/TokenSheriff", 7)
        assert ok
        assert gh.call_args[0][0] == [
            "pr", "merge", "7", "--repo", "cuioss/TokenSheriff", "--squash",
        ]

    def test_does_not_pass_auto(self):
        """--auto is what breaks under the queue; the sweeper merges outright."""
        mod = _load_module()
        with patch.object(mod, "run_gh", return_value=_completed(stdout="ok")) as gh:
            mod.merge_pr("cuioss/TokenSheriff", 7)
        assert "--auto" not in gh.call_args[0][0]


class TestSummary:
    """Test reporting."""

    def test_summary_written_to_step_summary(self, tmp_path, monkeypatch):
        mod = _load_module()
        summary_file = tmp_path / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
        mod.print_summary(
            [{"repo": "cuioss/x", "number": 1, "url": "u", "title": "t",
              "action": "merged", "detail": ""}]
        )
        assert "cuioss/x#1" in summary_file.read_text()

    def test_empty_sweep_reports_nothing_found(self, tmp_path, monkeypatch):
        mod = _load_module()
        summary_file = tmp_path / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
        mod.print_summary([])
        assert "No labelled Dependabot PRs" in summary_file.read_text()
