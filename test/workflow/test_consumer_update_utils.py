"""Tests for consumer_update_utils.py shared utilities."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add parent to path to access conftest
sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT

# Add workflow-scripts to path so we can import the module directly
sys.path.insert(0, str(PROJECT_ROOT / "workflow-scripts"))

import consumer_update_utils as utils


class TestStatusConstants:
    """Test that status constants are defined."""

    def test_status_constants_exist(self):
        assert utils.STATUS_PR_AUTO_MERGE_ENABLED == "pr_auto_merge_enabled"
        assert utils.STATUS_PR_AUTO_MERGE_FAILED == "pr_auto_merge_failed"
        assert utils.STATUS_PR_CREATED == "pr_created"
        assert utils.STATUS_NO_CHANGES == "no_changes"
        assert utils.STATUS_ERROR == "error"


class TestMakeResult:
    """Test make_result helper."""

    def test_basic_result(self):
        result = utils.make_result("no_changes")
        assert result == {"status": "no_changes", "pr_url": None, "error": None}

    def test_result_with_pr_url(self):
        result = utils.make_result("pr_created", pr_url="https://github.com/org/repo/pull/1")
        assert result["status"] == "pr_created"
        assert result["pr_url"] == "https://github.com/org/repo/pull/1"
        assert result["error"] is None

    def test_result_with_error(self):
        result = utils.make_result("error", error="Clone failed")
        assert result["status"] == "error"
        assert result["pr_url"] is None
        assert result["error"] == "Clone failed"


class TestReadAutoMergeConfig:
    """Test read_auto_merge_config function."""

    def test_no_project_yml(self, temp_dir):
        config = utils.read_auto_merge_config(temp_dir)
        assert config["enabled"] is True

    def test_no_github_automation_section(self, temp_dir):
        github_dir = temp_dir / ".github"
        github_dir.mkdir()
        (github_dir / "project.yml").write_text("name: test-repo\n")
        config = utils.read_auto_merge_config(temp_dir)
        assert config["enabled"] is True

    def test_auto_merge_disabled(self, temp_dir):
        github_dir = temp_dir / ".github"
        github_dir.mkdir()
        (github_dir / "project.yml").write_text(
            "github-automation:\n  auto-merge-build-versions: false\n"
        )
        config = utils.read_auto_merge_config(temp_dir)
        assert config["enabled"] is False

    def test_auto_merge_enabled(self, temp_dir):
        github_dir = temp_dir / ".github"
        github_dir.mkdir()
        (github_dir / "project.yml").write_text(
            "github-automation:\n  auto-merge-build-versions: true\n"
        )
        config = utils.read_auto_merge_config(temp_dir)
        assert config["enabled"] is True

    def test_invalid_yaml(self, temp_dir):
        github_dir = temp_dir / ".github"
        github_dir.mkdir()
        (github_dir / "project.yml").write_text(": invalid: yaml: [broken")
        config = utils.read_auto_merge_config(temp_dir)
        assert config["enabled"] is True


class TestWriteSummary:
    """Test write_summary function."""

    def test_no_op_without_env(self):
        """Should not fail when GITHUB_STEP_SUMMARY is not set."""
        with patch.dict("os.environ", {}, clear=True):
            # Should not raise
            utils.write_summary("test text")

    def test_writes_to_summary_file(self, temp_dir):
        summary_file = temp_dir / "summary.md"
        with patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": str(summary_file)}):
            utils.write_summary("## Hello")
            utils.write_summary("World")
        content = summary_file.read_text()
        assert "## Hello" in content
        assert "World" in content


class TestFindOpenPrsByBranchPrefix:
    """Test find_open_prs_by_branch_prefix function."""

    @patch("consumer_update_utils.run_gh")
    def test_finds_matching_prs(self, mock_gh):
        prs = [
            {"number": 1, "url": "https://github.com/org/repo/pull/1", "headRefName": "chore/update-org-workflows-v0.3.10"},
            {"number": 2, "url": "https://github.com/org/repo/pull/2", "headRefName": "chore/update-org-workflows-v0.3.11"},
            {"number": 3, "url": "https://github.com/org/repo/pull/3", "headRefName": "feature/something-else"},
        ]
        mock_gh.return_value = MagicMock(returncode=0, stdout=json.dumps(prs))

        result = utils.find_open_prs_by_branch_prefix(
            "cuioss/test-repo", "chore/update-org-workflows-"
        )
        assert len(result) == 2
        assert result[0]["number"] == 1
        assert result[1]["number"] == 2

    @patch("consumer_update_utils.run_gh")
    def test_returns_empty_on_error(self, mock_gh):
        mock_gh.return_value = MagicMock(returncode=1, stderr="API error")
        result = utils.find_open_prs_by_branch_prefix("cuioss/test-repo", "chore/")
        assert result == []

    @patch("consumer_update_utils.run_gh")
    def test_returns_empty_on_invalid_json(self, mock_gh):
        mock_gh.return_value = MagicMock(returncode=0, stdout="not json")
        result = utils.find_open_prs_by_branch_prefix("cuioss/test-repo", "chore/")
        assert result == []

    @patch("consumer_update_utils.run_gh")
    def test_no_matching_prs(self, mock_gh):
        prs = [
            {"number": 3, "url": "https://github.com/org/repo/pull/3", "headRefName": "feature/something"},
        ]
        mock_gh.return_value = MagicMock(returncode=0, stdout=json.dumps(prs))
        result = utils.find_open_prs_by_branch_prefix("cuioss/test-repo", "chore/update-")
        assert result == []


class TestCloseStalePrs:
    """Test close_stale_prs function."""

    @patch("consumer_update_utils.find_open_prs_by_branch_prefix")
    @patch("consumer_update_utils.run_gh")
    def test_closes_stale_prs(self, mock_gh, mock_find):
        mock_find.return_value = [
            {"number": 1, "url": "https://github.com/org/repo/pull/1", "headRefName": "chore/update-v0.3.10"},
            {"number": 2, "url": "https://github.com/org/repo/pull/2", "headRefName": "chore/update-v0.3.11"},
        ]
        mock_gh.return_value = MagicMock(returncode=0)

        closed = utils.close_stale_prs(
            "cuioss/test-repo", "chore/update-", "Superseded by v0.3.12"
        )
        assert len(closed) == 2
        # Should have called comment + close for each PR (4 calls total)
        assert mock_gh.call_count == 4

    @patch("consumer_update_utils.find_open_prs_by_branch_prefix")
    @patch("consumer_update_utils.run_gh")
    def test_excludes_current_branch(self, mock_gh, mock_find):
        mock_find.return_value = [
            {"number": 1, "url": "https://github.com/org/repo/pull/1", "headRefName": "chore/update-v0.3.10"},
            {"number": 2, "url": "https://github.com/org/repo/pull/2", "headRefName": "chore/update-v0.3.11"},
        ]
        mock_gh.return_value = MagicMock(returncode=0)

        closed = utils.close_stale_prs(
            "cuioss/test-repo",
            "chore/update-",
            "Superseded",
            exclude_branch="chore/update-v0.3.11",
        )
        assert len(closed) == 1
        assert closed[0] == "https://github.com/org/repo/pull/1"

    @patch("consumer_update_utils.find_open_prs_by_branch_prefix")
    def test_no_stale_prs(self, mock_find):
        mock_find.return_value = []
        closed = utils.close_stale_prs("cuioss/test-repo", "chore/update-", "Superseded")
        assert closed == []

    @patch("consumer_update_utils.find_open_prs_by_branch_prefix")
    @patch("consumer_update_utils.run_gh")
    def test_handles_close_failure(self, mock_gh, mock_find):
        mock_find.return_value = [
            {"number": 1, "url": "https://github.com/org/repo/pull/1", "headRefName": "chore/update-v0.3.10"},
        ]
        # Comment succeeds, close fails
        mock_gh.side_effect = [
            MagicMock(returncode=0),  # comment
            MagicMock(returncode=1, stderr="Permission denied"),  # close
        ]

        closed = utils.close_stale_prs("cuioss/test-repo", "chore/update-", "Superseded")
        assert closed == []


# Probe result helpers: base_branch_has_merge_queue runs `gh api ...` first and
# reads returncode + stdout ('true'/'false'/other).
def _probe(has_queue):
    """A mock gh-api result for base_branch_has_merge_queue: True/False/None."""
    if has_queue is None:
        return MagicMock(returncode=1, stdout="", stderr="api error")
    return MagicMock(returncode=0, stdout="true\n" if has_queue else "false\n")


class TestBaseBranchHasMergeQueue:
    """Test the deterministic merge-queue probe."""

    @patch("consumer_update_utils.run_gh")
    def test_true(self, mock_gh):
        mock_gh.return_value = MagicMock(returncode=0, stdout="true\n")
        assert utils.base_branch_has_merge_queue("cuioss/repo") is True

    @patch("consumer_update_utils.run_gh")
    def test_false(self, mock_gh):
        mock_gh.return_value = MagicMock(returncode=0, stdout="false\n")
        assert utils.base_branch_has_merge_queue("cuioss/repo") is False

    @patch("consumer_update_utils.run_gh")
    def test_none_on_api_error(self, mock_gh):
        mock_gh.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
        assert utils.base_branch_has_merge_queue("cuioss/repo") is None

    @patch("consumer_update_utils.run_gh")
    def test_none_on_unparseable(self, mock_gh):
        mock_gh.return_value = MagicMock(returncode=0, stdout="not-a-bool")
        assert utils.base_branch_has_merge_queue("cuioss/repo") is None


class TestAutoMergePr:
    """Test auto_merge_pr function (probe-first)."""

    @patch("consumer_update_utils.run_gh")
    def test_no_queue_enables_auto_merge_with_squash(self, mock_gh):
        mock_gh.side_effect = [
            _probe(False),           # probe: no queue
            MagicMock(returncode=0),  # pr merge --auto --squash
        ]
        result = utils.auto_merge_pr("cuioss/repo", "https://github.com/cuioss/repo/pull/1")
        assert result is True
        assert mock_gh.call_count == 2
        merge_args = mock_gh.call_args_list[1][0][0]
        assert "--auto" in merge_args and "--squash" in merge_args

    @patch("consumer_update_utils.run_gh")
    def test_merge_queue_enqueues_without_method(self, mock_gh):
        mock_gh.side_effect = [
            _probe(True),            # probe: queue present
            MagicMock(returncode=0),  # pr merge --auto (no method)
        ]
        result = utils.auto_merge_pr("cuioss/repo", "https://github.com/cuioss/repo/pull/1")
        assert result is True
        assert mock_gh.call_count == 2
        merge_args = mock_gh.call_args_list[1][0][0]
        assert "--auto" in merge_args and "--squash" not in merge_args

    @patch("consumer_update_utils.run_gh")
    def test_merge_queue_enqueue_failure_returns_false(self, mock_gh):
        mock_gh.side_effect = [
            _probe(True),
            MagicMock(returncode=1, stderr="not mergeable"),
        ]
        result = utils.auto_merge_pr("cuioss/repo", "https://github.com/cuioss/repo/pull/1")
        assert result is False
        assert mock_gh.call_count == 2

    @patch("consumer_update_utils.run_gh")
    def test_returns_false_on_generic_failure(self, mock_gh):
        mock_gh.side_effect = [
            _probe(False),
            MagicMock(returncode=1, stderr="Permission denied"),
        ]
        result = utils.auto_merge_pr("cuioss/repo", "https://github.com/cuioss/repo/pull/1")
        assert result is False

    @patch("consumer_update_utils.run_gh")
    def test_falls_back_to_direct_merge_on_clean_status(self, mock_gh):
        """No queue + already-clean status: fall back to a direct squash merge."""
        mock_gh.side_effect = [
            _probe(False),
            MagicMock(returncode=1, stderr="GraphQL: Pull request Pull request is in clean status (enablePullRequestAutoMerge)"),
            MagicMock(returncode=0),  # direct merge succeeds
        ]
        result = utils.auto_merge_pr("cuioss/repo", "https://github.com/cuioss/repo/pull/1")
        assert result is True
        assert mock_gh.call_count == 3
        third_call_args = mock_gh.call_args_list[2][0][0]
        assert "--auto" not in third_call_args

    @patch("consumer_update_utils.run_gh")
    def test_probe_undeterminable_retries_on_merge_queue_error(self, mock_gh):
        """Probe fails (None); the no-queue attempt hits a queue error → retry --auto."""
        mock_gh.side_effect = [
            _probe(None),  # probe undeterminable
            MagicMock(returncode=1, stderr="X Cannot use `--delete-branch` when merge queue enabled"),
            MagicMock(returncode=0),  # retry --auto (no method) enqueues
        ]
        result = utils.auto_merge_pr("cuioss/repo", "https://github.com/cuioss/repo/pull/1")
        assert result is True
        assert mock_gh.call_count == 3
        retry_args = mock_gh.call_args_list[2][0][0]
        assert "--auto" in retry_args and "--squash" not in retry_args


class TestOutputResult:
    """Test output_result function."""

    def test_outputs_json(self, capsys):
        utils.output_result({"status": "no_changes", "pr_url": None, "error": None})
        captured = capsys.readouterr()
        assert captured.out.startswith("RESULT:")
        data = json.loads(captured.out.strip().replace("RESULT:", ""))
        assert data["status"] == "no_changes"


class TestExitWithResult:
    """Test exit_with_result function."""

    def test_exits_zero_on_success(self):
        with pytest.raises(SystemExit) as exc_info:
            utils.exit_with_result(utils.make_result("no_changes"))
        assert exc_info.value.code == 0

    def test_exits_zero_on_pr_created(self):
        with pytest.raises(SystemExit) as exc_info:
            utils.exit_with_result(utils.make_result("pr_created", pr_url="url"))
        assert exc_info.value.code == 0

    def test_exits_nonzero_on_error(self):
        with pytest.raises(SystemExit) as exc_info:
            utils.exit_with_result(utils.make_result("error", error="fail"))
        assert exc_info.value.code == 1
