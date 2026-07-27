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


class TestRunGh:
    """Test that no single gh call can hang the scheduled sweep."""

    def test_passes_a_timeout(self):
        mod = _load_module()
        with patch("subprocess.run", return_value=_completed()) as run:
            mod.run_gh(["pr", "list"])
        assert run.call_args.kwargs["timeout"] == mod.GH_CALL_TIMEOUT_SECONDS

    def test_timeout_becomes_a_failed_call(self):
        """A stalled call must be reported, not raised -- callers handle rc != 0."""
        mod = _load_module()
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="gh", timeout=120),
        ):
            result = mod.run_gh(["pr", "list"])
        assert result.returncode != 0
        assert "timed out" in result.stderr

    def test_timeout_is_below_the_job_budget(self):
        """The job is capped at 10 minutes; a single call must not consume it."""
        mod = _load_module()
        assert 0 < mod.GH_CALL_TIMEOUT_SECONDS <= 300


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


class TestReadPrState:
    """Test how the merge-readiness fields are read.

    isInMergeQueue is not exposed by `gh pr view --json` (gh 2.95.0), so the
    state has to come from GraphQL -- without that field the sweeper would
    re-enqueue a PR the queue is already building.
    """

    def test_reads_state_over_graphql(self):
        mod = _load_module()
        payload = json.dumps(
            {"data": {"repository": {"pullRequest": _pr_state()}}}
        )
        with patch.object(mod, "run_gh", return_value=_completed(stdout=payload)) as gh:
            state = mod.read_pr_state("cuioss/TokenSheriff", 591)
        assert state == _pr_state()
        args = gh.call_args[0][0]
        assert args[:2] == ["api", "graphql"]

    def test_splits_owner_and_repo(self):
        mod = _load_module()
        payload = json.dumps({"data": {"repository": {"pullRequest": _pr_state()}}})
        with patch.object(mod, "run_gh", return_value=_completed(stdout=payload)) as gh:
            mod.read_pr_state("cuioss/TokenSheriff", 591)
        args = gh.call_args[0][0]
        assert "owner=cuioss" in args
        assert "name=TokenSheriff" in args

    def test_queries_is_in_merge_queue(self):
        mod = _load_module()
        assert "isInMergeQueue" in mod.PR_STATE_QUERY

    def test_api_failure_yields_none(self):
        mod = _load_module()
        with patch.object(mod, "run_gh", return_value=_completed(1, stderr="boom")):
            assert mod.read_pr_state("cuioss/TokenSheriff", 591) is None

    def test_missing_pull_request_yields_none(self):
        mod = _load_module()
        payload = json.dumps({"data": {"repository": {"pullRequest": None}}})
        with patch.object(mod, "run_gh", return_value=_completed(stdout=payload)):
            assert mod.read_pr_state("cuioss/TokenSheriff", 591) is None

    def test_malformed_output_yields_none(self):
        mod = _load_module()
        with patch.object(mod, "run_gh", return_value=_completed(stdout="not json")):
            assert mod.read_pr_state("cuioss/TokenSheriff", 591) is None


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
    """Test the merge invocation and its outcome check.

    `gh pr merge` exits 0 without doing anything when the PR already carries an
    auto-merge request (observed on nifi-extensions#466), so neither the call
    nor its exit code can be trusted on its own.
    """

    def test_uses_squash_against_the_owning_repo(self):
        """The queue's merge_method is SQUASH; the direct-merge path must match."""
        mod = _load_module()
        with (
            patch.object(mod, "run_gh", return_value=_completed(stdout="ok")) as gh,
            patch.object(mod, "read_pr_state", return_value=_pr_state(state="MERGED")),
        ):
            ok, detail = mod.merge_pr("cuioss/TokenSheriff", 7)
        assert ok
        assert detail == "merged"
        assert gh.call_args_list[-1][0][0] == [
            "pr", "merge", "7", "--repo", "cuioss/TokenSheriff", "--squash",
        ]

    def test_clears_auto_merge_before_merging(self):
        """A pre-existing auto-merge request makes the merge a silent no-op."""
        mod = _load_module()
        with (
            patch.object(mod, "run_gh", return_value=_completed(stdout="ok")) as gh,
            patch.object(mod, "read_pr_state", return_value=_pr_state(state="MERGED")),
        ):
            mod.merge_pr("cuioss/TokenSheriff", 7)
        first_call = gh.call_args_list[0][0][0]
        assert "--disable-auto" in first_call
        assert "--squash" not in first_call

    def test_does_not_pass_auto(self):
        """--auto is what breaks under the queue; the sweeper merges outright."""
        mod = _load_module()
        with (
            patch.object(mod, "run_gh", return_value=_completed(stdout="ok")) as gh,
            patch.object(mod, "read_pr_state", return_value=_pr_state(state="MERGED")),
        ):
            mod.merge_pr("cuioss/TokenSheriff", 7)
        assert "--auto" not in gh.call_args_list[-1][0][0]

    def test_enqueued_counts_as_success(self):
        mod = _load_module()
        with (
            patch.object(mod, "run_gh", return_value=_completed(stdout="ok")),
            patch.object(mod, "read_pr_state", return_value=_pr_state(isInMergeQueue=True)),
        ):
            ok, detail = mod.merge_pr("cuioss/TokenSheriff", 7)
        assert ok
        assert detail == "enqueued"

    def test_exit_zero_without_movement_is_a_failure(self):
        """The nifi-extensions#466 case: success reported, nothing happened."""
        mod = _load_module()
        with (
            patch.object(mod, "run_gh", return_value=_completed(stdout="ok")),
            patch.object(mod, "read_pr_state", return_value=_pr_state()),
        ):
            ok, detail = mod.merge_pr("cuioss/TokenSheriff", 7)
        assert ok is False
        assert "did not move" in detail

    def test_unreadable_state_after_merge_is_a_failure(self):
        mod = _load_module()
        with (
            patch.object(mod, "run_gh", return_value=_completed(stdout="ok")),
            patch.object(mod, "read_pr_state", return_value=None),
        ):
            ok, detail = mod.merge_pr("cuioss/TokenSheriff", 7)
        assert ok is False
        assert "could not be read" in detail

    def test_nonzero_exit_is_a_failure_without_state_read(self):
        mod = _load_module()
        with (
            patch.object(mod, "run_gh", return_value=_completed(1, stderr="nope")),
            patch.object(mod, "read_pr_state") as read,
        ):
            ok, detail = mod.merge_pr("cuioss/TokenSheriff", 7)
        assert ok is False
        assert detail == "nope"
        read.assert_not_called()


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
