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


class TestStuckPrDetection:
    """Test stuck PR detection (missing push event)."""

    def test_detects_stuck_pr_no_push_event(self, temp_dir):
        """Should classify PR as stuck when build is skipped and no push-event run exists."""
        mod = _load_module()
        results_file = temp_dir / "results.json"
        results_file.write_text(
            json.dumps(
                [
                    {
                        "repo": "stuck-repo",
                        "status": "pr_auto_merge_enabled",
                        "pr_url": "https://github.com/cuioss/stuck-repo/pull/1",
                    },
                ]
            )
        )

        # Mock check_pr_status to return OPEN with build skipped
        def mock_check_pr_status(pr_url):
            return {
                "state": "OPEN",
                "merged": False,
                "checks_passed": None,
                "head_branch": "chore/update-v1.0",
                "full_repo": "cuioss/stuck-repo",
                "build_skipped": True,
            }

        # Mock check_has_push_event_build to return False (no push event)
        with (
            patch.object(mod, "check_pr_status", side_effect=mock_check_pr_status),
            patch.object(mod, "check_has_push_event_build", return_value=False),
        ):
            final = mod.verify_prs(str(results_file), timeout=1, poll_interval=1)

        assert len(final) == 1
        assert final[0]["final_status"] == "stuck_no_push"
        assert final[0]["repo"] == "stuck-repo"

    def test_pending_when_push_event_exists(self, temp_dir):
        """Should classify PR as pending (not stuck) when push-event build exists."""
        mod = _load_module()
        results_file = temp_dir / "results.json"
        results_file.write_text(
            json.dumps(
                [
                    {
                        "repo": "pending-repo",
                        "status": "pr_auto_merge_enabled",
                        "pr_url": "https://github.com/cuioss/pending-repo/pull/1",
                    },
                ]
            )
        )

        def mock_check_pr_status(pr_url):
            return {
                "state": "OPEN",
                "merged": False,
                "checks_passed": None,
                "head_branch": "chore/update-v1.0",
                "full_repo": "cuioss/pending-repo",
                "build_skipped": True,
            }

        with (
            patch.object(mod, "check_pr_status", side_effect=mock_check_pr_status),
            patch.object(mod, "check_has_push_event_build", return_value=True),
        ):
            final = mod.verify_prs(str(results_file), timeout=1, poll_interval=1)

        assert len(final) == 1
        assert final[0]["final_status"] == "pending"

    def test_pending_when_build_not_skipped(self, temp_dir):
        """Should classify PR as pending when build check is not skipped."""
        mod = _load_module()
        results_file = temp_dir / "results.json"
        results_file.write_text(
            json.dumps(
                [
                    {
                        "repo": "normal-repo",
                        "status": "pr_auto_merge_enabled",
                        "pr_url": "https://github.com/cuioss/normal-repo/pull/1",
                    },
                ]
            )
        )

        def mock_check_pr_status(pr_url):
            return {
                "state": "OPEN",
                "merged": False,
                "checks_passed": None,
                "head_branch": "chore/update-v1.0",
                "full_repo": "cuioss/normal-repo",
                "build_skipped": False,
            }

        with patch.object(mod, "check_pr_status", side_effect=mock_check_pr_status):
            final = mod.verify_prs(str(results_file), timeout=1, poll_interval=1)

        assert len(final) == 1
        assert final[0]["final_status"] == "pending"


class TestPrintSummary:
    """Test print_summary output formatting."""

    def test_stuck_prs_show_instructions(self):
        """Should include manual intervention instructions for stuck PRs."""
        mod = _load_module()
        results = [
            {"repo": "stuck-repo", "pr_url": "https://github.com/cuioss/stuck-repo/pull/1", "final_status": "stuck_no_push"},
            {"repo": "merged-repo", "pr_url": "https://github.com/cuioss/merged-repo/pull/2", "final_status": "merged"},
        ]

        # Capture printed output
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            mod.print_summary(results)

        output = buf.getvalue()
        assert "Stuck" in output or "stuck" in output
        assert "manual intervention" in output.lower()
        assert "stuck-repo" in output
        assert "Maven Build" in output

    def test_no_stuck_section_when_all_merged(self):
        """Should not include stuck instructions when no PRs are stuck."""
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
