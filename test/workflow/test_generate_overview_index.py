"""Tests for generate-overview-index.py - overview index generation script."""

import re
import sys
from pathlib import Path

# Add parent to path to access conftest
sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT, run_script

SCRIPT_PATH = PROJECT_ROOT / ".github/actions/assemble-test-reports/generate-overview-index.py"


class TestArgumentValidation:
    """Test CLI argument validation."""

    def test_requires_target_dir(self):
        """Should fail when --target-dir is missing."""
        result = run_script(SCRIPT_PATH, "--title", "my-project")
        assert result.returncode != 0

    def test_requires_title(self):
        """Should fail when --title is missing."""
        result = run_script(SCRIPT_PATH, "--target-dir", "/tmp/some-dir")
        assert result.returncode != 0


class TestNonexistentDir:
    """Test behavior with non-existent target directory."""

    def test_fails_on_missing_target_dir(self):
        """Should fail with non-zero exit on missing target-dir."""
        result = run_script(
            SCRIPT_PATH,
            "--target-dir", "/nonexistent/path",
            "--title", "test",
        )
        assert result.returncode != 0
        assert "error" in result.stderr.lower()


class TestOverviewIndex:
    """Test overview index generation."""

    def test_groups_by_report_name(self, temp_dir):
        """Should group directories by report name."""
        # Create directories for two different report names
        (temp_dir / "e-2-e-playwright-2025-01-15-1430-2300").mkdir()
        (temp_dir / "e-2-e-playwright-2025-01-16-1000-0000").mkdir()
        (temp_dir / "integration-tests-2025-01-15-0900-1000").mkdir()

        result = run_script(
            SCRIPT_PATH,
            "--target-dir", str(temp_dir),
            "--title", "my-project",
        )
        assert result.returncode == 0

        index_html = (temp_dir / "index.html").read_text()
        # Both report groups should appear
        assert "e-2-e-playwright" in index_html
        assert "integration-tests" in index_html

    def test_sorts_newest_first(self, temp_dir):
        """Should sort entries newest-first within each group."""
        (temp_dir / "report-2025-01-10-0900-0000").mkdir()
        (temp_dir / "report-2025-01-20-0900-0000").mkdir()
        (temp_dir / "report-2025-01-15-0900-0000").mkdir()

        result = run_script(
            SCRIPT_PATH,
            "--target-dir", str(temp_dir),
            "--title", "test",
        )
        assert result.returncode == 0

        index_html = (temp_dir / "index.html").read_text()
        # Newest should appear before oldest
        pos_20 = index_html.index("report-2025-01-20")
        pos_15 = index_html.index("report-2025-01-15")
        pos_10 = index_html.index("report-2025-01-10")
        assert pos_20 < pos_15 < pos_10

    def test_ignores_non_timestamped_dirs(self, temp_dir):
        """Should ignore directories that don't match the timestamp pattern."""
        (temp_dir / "report-2025-01-15-1430-2300").mkdir()
        (temp_dir / "legacy-reports").mkdir()
        (temp_dir / "some-random-dir").mkdir()

        result = run_script(
            SCRIPT_PATH,
            "--target-dir", str(temp_dir),
            "--title", "test",
        )
        assert result.returncode == 0

        index_html = (temp_dir / "index.html").read_text()
        assert "report-2025-01-15" in index_html
        assert "legacy-reports" not in index_html
        assert "some-random-dir" not in index_html

    def test_ignores_files(self, temp_dir):
        """Should ignore files (only process directories)."""
        (temp_dir / "report-2025-01-15-1430-2300").mkdir()
        (temp_dir / "some-file.txt").write_text("content")

        result = run_script(
            SCRIPT_PATH,
            "--target-dir", str(temp_dir),
            "--title", "test",
        )
        assert result.returncode == 0

        index_html = (temp_dir / "index.html").read_text()
        assert "some-file.txt" not in index_html

    def test_handles_empty_target_dir(self, temp_dir):
        """Should generate index even when no reports exist."""
        result = run_script(
            SCRIPT_PATH,
            "--target-dir", str(temp_dir),
            "--title", "test",
        )
        assert result.returncode == 0

        index_html = (temp_dir / "index.html").read_text()
        assert "No reports found" in index_html

    def test_html_escapes_title(self, temp_dir):
        """Should HTML-escape the title."""
        (temp_dir / "report-2025-01-15-1430-2300").mkdir()

        result = run_script(
            SCRIPT_PATH,
            "--target-dir", str(temp_dir),
            "--title", '<script>alert("xss")</script>',
        )
        assert result.returncode == 0

        index_html = (temp_dir / "index.html").read_text()
        assert "<script>" not in index_html
        assert "&lt;script&gt;" in index_html

    def test_idempotent_regeneration(self, temp_dir):
        """Should overwrite existing index.html on re-run."""
        (temp_dir / "report-2025-01-15-1430-2300").mkdir()

        # First run
        result1 = run_script(
            SCRIPT_PATH,
            "--target-dir", str(temp_dir),
            "--title", "test",
        )
        assert result1.returncode == 0
        first_content = (temp_dir / "index.html").read_text()

        # Add another report
        (temp_dir / "report-2025-01-16-1000-0000").mkdir()

        # Second run
        result2 = run_script(
            SCRIPT_PATH,
            "--target-dir", str(temp_dir),
            "--title", "test",
        )
        assert result2.returncode == 0
        second_content = (temp_dir / "index.html").read_text()

        # Second run should include the new report
        assert "report-2025-01-16" in second_content
        assert first_content != second_content

    def test_links_point_to_dirname_index(self, temp_dir):
        """Should link to <dirname>/index.html."""
        dirname = "e-2-e-playwright-2025-01-15-1430-2300"
        (temp_dir / dirname).mkdir()

        result = run_script(
            SCRIPT_PATH,
            "--target-dir", str(temp_dir),
            "--title", "test",
        )
        assert result.returncode == 0

        index_html = (temp_dir / "index.html").read_text()
        assert f'href="{dirname}/index.html"' in index_html


class TestTimestampDetection:
    """Test timestamp pattern matching."""

    def test_valid_pattern(self, temp_dir):
        """Should match standard timestamped names."""
        (temp_dir / "report-2025-01-15-1430-2300").mkdir()
        result = run_script(
            SCRIPT_PATH,
            "--target-dir", str(temp_dir),
            "--title", "test",
        )
        assert result.returncode == 0
        assert "1 report" in result.stderr

    def test_invalid_pattern_short_year(self, temp_dir):
        """Should not match names with short year."""
        (temp_dir / "report-25-01-15-1430-2300").mkdir()
        result = run_script(
            SCRIPT_PATH,
            "--target-dir", str(temp_dir),
            "--title", "test",
        )
        assert result.returncode == 0
        assert "0 report" in result.stderr

    def test_invalid_pattern_missing_parts(self, temp_dir):
        """Should not match names with missing timestamp parts."""
        (temp_dir / "report-2025-01-15-1430").mkdir()
        result = run_script(
            SCRIPT_PATH,
            "--target-dir", str(temp_dir),
            "--title", "test",
        )
        assert result.returncode == 0
        assert "0 report" in result.stderr

    def test_hyphenated_report_names(self, temp_dir):
        """Should handle hyphenated report names like e-2-e-playwright."""
        (temp_dir / "e-2-e-playwright-2025-01-15-1430-2300").mkdir()
        result = run_script(
            SCRIPT_PATH,
            "--target-dir", str(temp_dir),
            "--title", "test",
        )
        assert result.returncode == 0

        index_html = (temp_dir / "index.html").read_text()
        # The greedy prefix should capture the full report name
        assert "e-2-e-playwright" in index_html


class TestHtmlOutput:
    """Test HTML output quality."""

    def test_valid_html5_doctype(self, temp_dir):
        """Should output valid HTML5 doctype."""
        (temp_dir / "report-2025-01-15-1430-2300").mkdir()
        result = run_script(
            SCRIPT_PATH,
            "--target-dir", str(temp_dir),
            "--title", "test",
        )
        assert result.returncode == 0

        index_html = (temp_dir / "index.html").read_text()
        assert index_html.startswith("<!DOCTYPE html>")

    def test_viewport_meta(self, temp_dir):
        """Should include viewport meta tag for mobile."""
        (temp_dir / "report-2025-01-15-1430-2300").mkdir()
        result = run_script(
            SCRIPT_PATH,
            "--target-dir", str(temp_dir),
            "--title", "test",
        )
        assert result.returncode == 0

        index_html = (temp_dir / "index.html").read_text()
        assert 'name="viewport"' in index_html

    def test_relative_links(self, temp_dir):
        """Should use relative links (no leading /)."""
        dirname = "report-2025-01-15-1430-2300"
        (temp_dir / dirname).mkdir()
        result = run_script(
            SCRIPT_PATH,
            "--target-dir", str(temp_dir),
            "--title", "test",
        )
        assert result.returncode == 0

        index_html = (temp_dir / "index.html").read_text()
        # Links should be relative, not absolute
        assert f'href="{dirname}/index.html"' in index_html
        assert 'href="/' not in index_html

    def test_dark_mode_css(self, temp_dir):
        """Should include dark mode CSS (prefers-color-scheme)."""
        (temp_dir / "report-2025-01-15-1430-2300").mkdir()
        result = run_script(
            SCRIPT_PATH,
            "--target-dir", str(temp_dir),
            "--title", "test",
        )
        assert result.returncode == 0

        index_html = (temp_dir / "index.html").read_text()
        assert "prefers-color-scheme" in index_html

    def test_generation_timestamp_in_footer(self, temp_dir):
        """Should include generation timestamp in footer."""
        (temp_dir / "report-2025-01-15-1430-2300").mkdir()
        result = run_script(
            SCRIPT_PATH,
            "--target-dir", str(temp_dir),
            "--title", "test",
        )
        assert result.returncode == 0

        index_html = (temp_dir / "index.html").read_text()
        assert "<footer>" in index_html
        assert "Generated" in index_html
        # Should contain a date-like pattern in the footer
        assert re.search(r"Generated \d{4}-\d{2}-\d{2}", index_html)
