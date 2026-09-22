"""Tests for covering-run-check.py - the #279 push-build rescue decision.

`gate` skips a push-triggered build when an open PR already covers the
commit, betting that a `pull_request` run will build it instead. This script
decides whether that bet paid off, and if not, whether the push run must
build the commit itself (`rescue=true`) rather than report an unverified
commit as green.

All GitHub access goes through `run_gh`, so tests patch the two lookup
functions directly (`covering_run_exists`, `open_pr_still_points_here`)
instead of shelling out to a real `gh` — matching the module-patching style
already used for `verify-consumer-prs.py`. The polling loop's own timing
functions (`time.monotonic`, `time.sleep`) are patched too, so a test that
needs several poll iterations does not actually wait.
"""

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT, run_script

SCRIPT_PATH = PROJECT_ROOT / "workflow-scripts/covering-run-check.py"


def _load_module():
    """Load covering-run-check.py as a module for unit testing."""
    spec = importlib.util.spec_from_file_location("covering_run_check", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeCompletedProcess:
    def __init__(self, returncode: int = 0, stdout: str = ""):
        self.returncode = returncode
        self.stdout = stdout


class TestArgumentValidation:
    def test_requires_repo(self):
        result = run_script(SCRIPT_PATH, "--sha", "abc123", "--ref", "main", "--workflow-name", "Maven Build")
        assert result.returncode != 0

    def test_requires_sha(self):
        result = run_script(SCRIPT_PATH, "--repo", "cuioss/x", "--ref", "main", "--workflow-name", "Maven Build")
        assert result.returncode != 0

    def test_requires_ref(self):
        result = run_script(SCRIPT_PATH, "--repo", "cuioss/x", "--sha", "abc123", "--workflow-name", "Maven Build")
        assert result.returncode != 0

    def test_requires_workflow_name(self):
        result = run_script(SCRIPT_PATH, "--repo", "cuioss/x", "--sha", "abc123", "--ref", "main")
        assert result.returncode != 0


class TestCoveringRunExists:
    """Unit tests for the raw `gh api` lookup, mocked at run_gh."""

    def test_true_when_matching_run_present(self):
        mod = _load_module()
        payload = json.dumps({"workflow_runs": [{"name": "Maven Build"}, {"name": "Other"}]})
        with patch.object(mod, "run_gh", return_value=FakeCompletedProcess(0, payload)):
            assert mod.covering_run_exists("cuioss/x", "abc123", "Maven Build") is True

    def test_false_when_no_matching_run(self):
        mod = _load_module()
        payload = json.dumps({"workflow_runs": [{"name": "Other"}]})
        with patch.object(mod, "run_gh", return_value=FakeCompletedProcess(0, payload)):
            assert mod.covering_run_exists("cuioss/x", "abc123", "Maven Build") is False

    def test_false_when_no_runs_at_all(self):
        mod = _load_module()
        payload = json.dumps({"workflow_runs": []})
        with patch.object(mod, "run_gh", return_value=FakeCompletedProcess(0, payload)):
            assert mod.covering_run_exists("cuioss/x", "abc123", "Maven Build") is False

    def test_none_when_gh_fails(self):
        mod = _load_module()
        with patch.object(mod, "run_gh", return_value=FakeCompletedProcess(1, "")):
            assert mod.covering_run_exists("cuioss/x", "abc123", "Maven Build") is None

    def test_none_when_response_is_not_json(self):
        mod = _load_module()
        with patch.object(mod, "run_gh", return_value=FakeCompletedProcess(0, "not json")):
            assert mod.covering_run_exists("cuioss/x", "abc123", "Maven Build") is None

    def test_none_when_workflow_runs_is_not_a_list(self):
        mod = _load_module()
        payload = json.dumps({"workflow_runs": "oops"})
        with patch.object(mod, "run_gh", return_value=FakeCompletedProcess(0, payload)):
            assert mod.covering_run_exists("cuioss/x", "abc123", "Maven Build") is None


class TestOpenPrStillPointsHere:
    def test_true_when_open_same_repo_pr_matches_sha(self):
        mod = _load_module()
        payload = json.dumps([{"headRefOid": "abc123", "isCrossRepository": False}])
        with patch.object(mod, "run_gh", return_value=FakeCompletedProcess(0, payload)):
            assert mod.open_pr_still_points_here("cuioss/x", "feature/y", "abc123") is True

    def test_false_when_pr_moved_to_a_different_sha(self):
        mod = _load_module()
        payload = json.dumps([{"headRefOid": "def456", "isCrossRepository": False}])
        with patch.object(mod, "run_gh", return_value=FakeCompletedProcess(0, payload)):
            assert mod.open_pr_still_points_here("cuioss/x", "feature/y", "abc123") is False

    def test_false_when_no_open_prs(self):
        mod = _load_module()
        with patch.object(mod, "run_gh", return_value=FakeCompletedProcess(0, "[]")):
            assert mod.open_pr_still_points_here("cuioss/x", "feature/y", "abc123") is False

    def test_cross_repository_pr_does_not_count(self):
        mod = _load_module()
        payload = json.dumps([{"headRefOid": "abc123", "isCrossRepository": True}])
        with patch.object(mod, "run_gh", return_value=FakeCompletedProcess(0, payload)):
            assert mod.open_pr_still_points_here("cuioss/x", "feature/y", "abc123") is False

    def test_none_when_gh_fails(self):
        mod = _load_module()
        with patch.object(mod, "run_gh", return_value=FakeCompletedProcess(1, "")):
            assert mod.open_pr_still_points_here("cuioss/x", "feature/y", "abc123") is None


class TestDecide:
    """Unit tests for the polling loop's decision, with time mocked out."""

    def test_covered_immediately_means_no_rescue(self):
        mod = _load_module()
        with (
            patch.object(mod, "covering_run_exists", return_value=True),
            patch.object(mod.time, "monotonic", return_value=0.0),
        ):
            rescue, reason = mod.decide("cuioss/x", "abc123", "feature/y", "Maven Build", timeout=300, poll_interval=20)
        assert rescue is False
        assert "abc123" in reason

    def test_covering_run_lookup_failure_rescues(self):
        mod = _load_module()
        with (
            patch.object(mod, "covering_run_exists", return_value=None),
            patch.object(mod.time, "monotonic", return_value=0.0),
        ):
            rescue, _ = mod.decide("cuioss/x", "abc123", "feature/y", "Maven Build", timeout=300, poll_interval=20)
        assert rescue is True

    def test_pr_lookup_failure_rescues(self):
        mod = _load_module()
        with (
            patch.object(mod, "covering_run_exists", return_value=False),
            patch.object(mod, "open_pr_still_points_here", return_value=None),
            patch.object(mod.time, "monotonic", return_value=0.0),
        ):
            rescue, _ = mod.decide("cuioss/x", "abc123", "feature/y", "Maven Build", timeout=300, poll_interval=20)
        assert rescue is True

    def test_pr_closed_or_moved_on_rescues_without_waiting_for_timeout(self):
        mod = _load_module()
        with (
            patch.object(mod, "covering_run_exists", return_value=False),
            patch.object(mod, "open_pr_still_points_here", return_value=False),
            patch.object(mod.time, "monotonic", return_value=0.0),
        ):
            rescue, reason = mod.decide("cuioss/x", "abc123", "feature/y", "Maven Build", timeout=300, poll_interval=20)
        assert rescue is True
        assert "no open same-repo PR" in reason

    def test_timeout_with_pr_still_open_rescues(self):
        mod = _load_module()
        # First monotonic() call sets the deadline; the second (inside the loop)
        # reads as already past it, so the timeout branch fires on the first pass.
        with (
            patch.object(mod, "covering_run_exists", return_value=False),
            patch.object(mod, "open_pr_still_points_here", return_value=True),
            patch.object(mod.time, "monotonic", side_effect=[0.0, 1000.0]),
        ):
            rescue, reason = mod.decide("cuioss/x", "abc123", "feature/y", "Maven Build", timeout=300, poll_interval=20)
        assert rescue is True
        assert "300s" in reason

    def test_covering_run_appears_after_polling(self):
        mod = _load_module()
        # Not covered on the first two polls, covered on the third - the deadline
        # is never reached, so this exercises the "keep waiting" path for real.
        with (
            patch.object(mod, "covering_run_exists", side_effect=[False, False, True]),
            patch.object(mod, "open_pr_still_points_here", return_value=True),
            patch.object(mod.time, "monotonic", return_value=0.0),
            patch.object(mod.time, "sleep") as sleep_mock,
        ):
            rescue, _ = mod.decide("cuioss/x", "abc123", "feature/y", "Maven Build", timeout=300, poll_interval=20)
        assert rescue is False
        assert sleep_mock.call_count == 2


class TestMainOutput:
    """End-to-end: the script's stdout is GITHUB_OUTPUT-formatted."""

    def test_prints_rescue_true_output_line(self):
        mod = _load_module()
        with (
            patch.object(mod, "decide", return_value=(True, "no covering run")),
            patch.object(
                sys,
                "argv",
                [
                    "covering-run-check.py",
                    "--repo",
                    "cuioss/x",
                    "--sha",
                    "abc123",
                    "--ref",
                    "y",
                    "--workflow-name",
                    "Maven Build",
                ],
            ),
            patch("builtins.print") as print_mock,
        ):
            exit_code = mod.main()
        assert exit_code == 0
        stdout_lines = [call.args[0] for call in print_mock.call_args_list if not call.kwargs.get("file")]
        assert "rescue=true" in stdout_lines

    def test_prints_rescue_false_output_line(self):
        mod = _load_module()
        with (
            patch.object(mod, "decide", return_value=(False, "covered")),
            patch.object(
                sys,
                "argv",
                [
                    "covering-run-check.py",
                    "--repo",
                    "cuioss/x",
                    "--sha",
                    "abc123",
                    "--ref",
                    "y",
                    "--workflow-name",
                    "Maven Build",
                ],
            ),
            patch("builtins.print") as print_mock,
        ):
            exit_code = mod.main()
        assert exit_code == 0
        stdout_lines = [call.args[0] for call in print_mock.call_args_list if not call.kwargs.get("file")]
        assert "rescue=false" in stdout_lines
