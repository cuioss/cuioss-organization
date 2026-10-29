"""Tests for verify-consumer-prs.py argument validation."""

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

# Add parent to path to access conftest
sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT, run_script

SCRIPT_PATH = PROJECT_ROOT / "workflow-scripts/verify-consumer-prs.py"


def _load_module():
    """Load verify-consumer-prs.py as a module for unit testing."""
    spec = importlib.util.spec_from_file_location("verify_consumer_prs", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestArgumentValidation:
    """Test command line argument validation."""

    def test_requires_results_file(self):
        """Should fail without --results-file argument."""
        result = run_script(SCRIPT_PATH)
        assert result.returncode != 0
        assert "required" in result.stderr.lower() or "--results-file" in result.stderr

    def test_rejects_missing_file(self):
        """Should fail when results file does not exist."""
        result = run_script(SCRIPT_PATH, "--results-file", "/nonexistent/file.json")
        assert result.returncode != 0
        assert "not found" in result.stderr.lower()


class TestVerifyPrs:
    """Test verify_prs logic with mock data."""

    def test_empty_results(self, temp_dir):
        """Should handle empty results gracefully."""
        mod = _load_module()
        results_file = temp_dir / "results.json"
        results_file.write_text("[]")
        final = mod.verify_prs(str(results_file), timeout=10)
        assert final == []

    def test_no_auto_merge_prs(self, temp_dir):
        """Should skip PRs that don't have auto-merge enabled."""
        mod = _load_module()
        results_file = temp_dir / "results.json"
        results_file.write_text(
            json.dumps(
                [
                    {"repo": "test-repo", "status": "pr_created", "pr_url": "https://example.com/pr/1"},
                    {"repo": "test-repo-2", "status": "no_changes", "pr_url": None},
                ]
            )
        )
        final = mod.verify_prs(str(results_file), timeout=10)
        assert final == []


class TestPendingClassification:
    """An open PR after the timeout is pending, whatever its build check says.

    A skipped `build` check used to be read as "GitHub dropped the push event" and
    triggered a lookup of push runs on the branch. That premise ended when the gate
    made the pull_request run always build; with `chore/*` gone from the consumers'
    push triggers no push run exists for these branches at all, so the lookup would
    have reported every skipped check as a stuck PR.
    """

    @staticmethod
    def _results(temp_dir):
        results_file = temp_dir / "results.json"
        results_file.write_text(
            json.dumps(
                [
                    {
                        "repo": "open-repo",
                        "status": "pr_auto_merge_enabled",
                        "pr_url": "https://github.com/cuioss/open-repo/pull/1",
                    },
                ]
            )
        )
        return results_file

    def test_open_pr_with_a_skipped_build_is_pending(self, temp_dir):
        """Should not look for push runs: a skipped build check no longer means a dropped event."""
        mod = _load_module()
        status = {
            "state": "OPEN",
            "merged": False,
            "checks_passed": None,
            "head_branch": "chore/update-org-workflows-v1.0",
            "full_repo": "cuioss/open-repo",
        }
        with (
            patch.object(mod, "check_pr_status", return_value=status),
            patch.object(mod, "run_gh") as run_gh,
        ):
            final = mod.verify_prs(str(self._results(temp_dir)), timeout=1, poll_interval=1)

        assert [r["final_status"] for r in final] == ["pending"]
        run_gh.assert_not_called()

    def test_the_push_run_lookup_is_gone(self):
        """Should not keep the helper whose premise ended: it would invite its own revival."""
        mod = _load_module()
        assert not hasattr(mod, "check_has_push_event_build")
        assert "build_skipped" not in mod.check_pr_status.__doc__


class TestPrintSummary:
    """Test print_summary output formatting."""

    def test_lists_each_repo_with_its_status(self):
        """Should render one row per result, with a link when there is a PR."""
        mod = _load_module()
        results = [
            {"repo": "open-repo", "pr_url": "https://github.com/cuioss/open-repo/pull/1", "final_status": "pending"},
            {"repo": "merged-repo", "pr_url": "https://github.com/cuioss/merged-repo/pull/2", "final_status": "merged"},
        ]

        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            mod.print_summary(results)

        output = buf.getvalue()
        assert (
            "| open-repo | :hourglass: Auto-merge pending | [PR](https://github.com/cuioss/open-repo/pull/1) |"
            in output
        )
        assert "| merged-repo | :white_check_mark: Merged |" in output
        assert "stuck" not in output.lower()

    def test_no_manual_intervention_section_when_all_merged(self):
        """Should not include manual-intervention instructions when everything merged."""
        mod = _load_module()
        results = [
            {"repo": "repo-a", "pr_url": "https://example.com/1", "final_status": "merged"},
        ]

        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            mod.print_summary(results)

        output = buf.getvalue()
        assert "manual intervention" not in output.lower()
        assert "stuck" not in output.lower()
