"""Tests for verify-consumer-prs.py argument validation."""

import importlib.util
import json
import sys
from pathlib import Path

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
