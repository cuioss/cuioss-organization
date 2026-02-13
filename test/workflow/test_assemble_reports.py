"""Tests for assemble-reports.py - test report assembly script."""

import re
import sys
from pathlib import Path

# Add parent to path to access conftest
sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT, run_script

SCRIPT_PATH = PROJECT_ROOT / ".github/actions/assemble-test-reports/assemble-reports.py"


def _parse_output(stdout: str) -> dict[str, str]:
    """Parse GITHUB_OUTPUT-style key=value lines into a dict."""
    return {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in stdout.strip().split("\n")
        if "=" in line
    }


class TestArgumentValidation:
    """Test CLI argument validation."""

    def test_requires_report_name(self):
        """Should fail when --report-name is missing."""
        result = run_script(SCRIPT_PATH, "--reports-folder", "some/dir")
        assert result.returncode != 0

    def test_requires_reports_folder(self):
        """Should fail when --reports-folder is missing."""
        result = run_script(SCRIPT_PATH, "--report-name", "my-report")
        assert result.returncode != 0

    def test_empty_reports_folder_string_fails(self, temp_dir):
        """Should fail when --reports-folder is empty string."""
        result = run_script(
            SCRIPT_PATH,
            "--report-name", "my-report",
            "--reports-folder", "",
            "--output-dir", str(temp_dir / "out"),
        )
        assert result.returncode == 1
        assert "empty" in result.stderr.lower()

    def test_empty_report_logs_accepted(self, temp_dir):
        """Should accept empty --report-logs."""
        reports_dir = temp_dir / "reports"
        reports_dir.mkdir()
        (reports_dir / "index.html").write_text("test")

        result = run_script(
            SCRIPT_PATH,
            "--report-name", "my-report",
            "--reports-folder", str(reports_dir),
            "--report-logs", "",
            "--output-dir", str(temp_dir / "out"),
        )
        assert result.returncode == 0

    def test_output_dir_created_automatically(self, temp_dir):
        """Should create output directory if it doesn't exist."""
        reports_dir = temp_dir / "reports"
        reports_dir.mkdir()
        (reports_dir / "test.txt").write_text("test")
        output_dir = temp_dir / "nonexistent" / "output"

        result = run_script(
            SCRIPT_PATH,
            "--report-name", "my-report",
            "--reports-folder", str(reports_dir),
            "--output-dir", str(output_dir),
        )
        assert result.returncode == 0
        assert output_dir.exists()


class TestDirectoryAssembly:
    """Test report directory copying logic."""

    def test_single_folder_copied(self, temp_dir):
        """Should copy a single reports folder."""
        reports_dir = temp_dir / "target" / "results"
        reports_dir.mkdir(parents=True)
        (reports_dir / "report.html").write_text("<html>report</html>")
        output_dir = temp_dir / "out"

        result = run_script(
            SCRIPT_PATH,
            "--report-name", "my-report",
            "--reports-folder", str(reports_dir),
            "--output-dir", str(output_dir),
        )
        assert result.returncode == 0
        outputs = _parse_output(result.stdout)
        report_path = Path(outputs["report-dir"])
        assert (report_path / "results" / "report.html").exists()

    def test_multiple_folders_copied(self, temp_dir):
        """Should copy multiple reports folders."""
        dir1 = temp_dir / "target" / "results-selftests"
        dir1.mkdir(parents=True)
        (dir1 / "test1.html").write_text("test1")

        dir2 = temp_dir / "target" / "results-functional"
        dir2.mkdir(parents=True)
        (dir2 / "test2.html").write_text("test2")

        folder_arg = f"{dir1}\n{dir2}"
        output_dir = temp_dir / "out"

        result = run_script(
            SCRIPT_PATH,
            "--report-name", "my-report",
            "--reports-folder", folder_arg,
            "--output-dir", str(output_dir),
        )
        assert result.returncode == 0
        outputs = _parse_output(result.stdout)
        report_path = Path(outputs["report-dir"])
        assert (report_path / "results-selftests" / "test1.html").exists()
        assert (report_path / "results-functional" / "test2.html").exists()

    def test_leaf_name_extraction(self, temp_dir):
        """Should use leaf directory name as target."""
        deep_dir = temp_dir / "a" / "b" / "c" / "my-reports"
        deep_dir.mkdir(parents=True)
        (deep_dir / "data.json").write_text("{}")
        output_dir = temp_dir / "out"

        result = run_script(
            SCRIPT_PATH,
            "--report-name", "test",
            "--reports-folder", str(deep_dir),
            "--output-dir", str(output_dir),
        )
        assert result.returncode == 0
        outputs = _parse_output(result.stdout)
        report_path = Path(outputs["report-dir"])
        assert (report_path / "my-reports" / "data.json").exists()

    def test_missing_folder_warns_and_continues(self, temp_dir):
        """Should warn for missing folder but continue if others exist."""
        existing = temp_dir / "target" / "results"
        existing.mkdir(parents=True)
        (existing / "ok.txt").write_text("ok")

        folder_arg = f"/nonexistent/path\n{existing}"
        output_dir = temp_dir / "out"

        result = run_script(
            SCRIPT_PATH,
            "--report-name", "test",
            "--reports-folder", folder_arg,
            "--output-dir", str(output_dir),
        )
        assert result.returncode == 0
        assert "warning" in result.stderr.lower()
        outputs = _parse_output(result.stdout)
        report_path = Path(outputs["report-dir"])
        assert (report_path / "results" / "ok.txt").exists()

    def test_all_folders_missing_fails(self, temp_dir):
        """Should fail if no report directories exist at all."""
        folder_arg = "/nonexistent/a\n/nonexistent/b"
        output_dir = temp_dir / "out"

        result = run_script(
            SCRIPT_PATH,
            "--report-name", "test",
            "--reports-folder", folder_arg,
            "--output-dir", str(output_dir),
        )
        assert result.returncode == 1
        assert "error" in result.stderr.lower()

    def test_duplicate_leaf_names_handled(self, temp_dir):
        """Should handle duplicate leaf names with suffix."""
        dir1 = temp_dir / "module-a" / "target" / "reports"
        dir1.mkdir(parents=True)
        (dir1 / "a.txt").write_text("a")

        dir2 = temp_dir / "module-b" / "target" / "reports"
        dir2.mkdir(parents=True)
        (dir2 / "b.txt").write_text("b")

        folder_arg = f"{dir1}\n{dir2}"
        output_dir = temp_dir / "out"

        result = run_script(
            SCRIPT_PATH,
            "--report-name", "test",
            "--reports-folder", folder_arg,
            "--output-dir", str(output_dir),
        )
        assert result.returncode == 0
        outputs = _parse_output(result.stdout)
        report_path = Path(outputs["report-dir"])
        # First copy uses original name
        assert (report_path / "reports" / "a.txt").exists()
        # Second copy uses suffixed name
        assert (report_path / "reports-2" / "b.txt").exists()


class TestLogCollection:
    """Test log file collection logic."""

    def test_single_log_collected(self, temp_dir):
        """Should collect a single log file."""
        reports_dir = temp_dir / "reports"
        reports_dir.mkdir()
        (reports_dir / "test.html").write_text("test")

        log_file = temp_dir / "container.log"
        log_file.write_text("log content")

        output_dir = temp_dir / "out"

        result = run_script(
            SCRIPT_PATH,
            "--report-name", "test",
            "--reports-folder", str(reports_dir),
            "--report-logs", str(log_file),
            "--output-dir", str(output_dir),
        )
        assert result.returncode == 0
        outputs = _parse_output(result.stdout)
        report_path = Path(outputs["report-dir"])
        assert (report_path / "logs" / "container.log").exists()
        assert (report_path / "logs" / "container.log").read_text() == "log content"

    def test_multiple_logs_collected(self, temp_dir):
        """Should collect multiple log files."""
        reports_dir = temp_dir / "reports"
        reports_dir.mkdir()
        (reports_dir / "test.html").write_text("test")

        log1 = temp_dir / "keycloak.log"
        log1.write_text("keycloak")
        log2 = temp_dir / "nifi.log"
        log2.write_text("nifi")

        logs_arg = f"{log1}\n{log2}"
        output_dir = temp_dir / "out"

        result = run_script(
            SCRIPT_PATH,
            "--report-name", "test",
            "--reports-folder", str(reports_dir),
            "--report-logs", logs_arg,
            "--output-dir", str(output_dir),
        )
        assert result.returncode == 0
        outputs = _parse_output(result.stdout)
        report_path = Path(outputs["report-dir"])
        assert (report_path / "logs" / "keycloak.log").exists()
        assert (report_path / "logs" / "nifi.log").exists()

    def test_logs_subdir_created(self, temp_dir):
        """Should create logs/ subdirectory."""
        reports_dir = temp_dir / "reports"
        reports_dir.mkdir()
        (reports_dir / "test.html").write_text("test")

        log_file = temp_dir / "app.log"
        log_file.write_text("content")
        output_dir = temp_dir / "out"

        result = run_script(
            SCRIPT_PATH,
            "--report-name", "test",
            "--reports-folder", str(reports_dir),
            "--report-logs", str(log_file),
            "--output-dir", str(output_dir),
        )
        assert result.returncode == 0
        outputs = _parse_output(result.stdout)
        report_path = Path(outputs["report-dir"])
        assert (report_path / "logs").is_dir()

    def test_missing_log_warns_gracefully(self, temp_dir):
        """Should warn for missing log files but not fail."""
        reports_dir = temp_dir / "reports"
        reports_dir.mkdir()
        (reports_dir / "test.html").write_text("test")

        logs_arg = "/nonexistent/missing.log"
        output_dir = temp_dir / "out"

        result = run_script(
            SCRIPT_PATH,
            "--report-name", "test",
            "--reports-folder", str(reports_dir),
            "--report-logs", logs_arg,
            "--output-dir", str(output_dir),
        )
        assert result.returncode == 0
        assert "warning" in result.stderr.lower()


class TestTimestampedNaming:
    """Test timestamped directory naming."""

    def test_name_format(self, temp_dir):
        """Should generate name matching expected pattern."""
        reports_dir = temp_dir / "reports"
        reports_dir.mkdir()
        (reports_dir / "test.html").write_text("test")
        output_dir = temp_dir / "out"

        result = run_script(
            SCRIPT_PATH,
            "--report-name", "e-2-e-playwright",
            "--reports-folder", str(reports_dir),
            "--output-dir", str(output_dir),
        )
        assert result.returncode == 0
        outputs = _parse_output(result.stdout)
        dirname = outputs["report-dirname"]
        # Pattern: <name>-YYYY-MM-DD-HHmm-SSSS
        assert re.match(r"e-2-e-playwright-\d{4}-\d{2}-\d{2}-\d{4}-\d{4}$", dirname)

    def test_report_name_prefix(self, temp_dir):
        """Should prefix with report-name."""
        reports_dir = temp_dir / "reports"
        reports_dir.mkdir()
        (reports_dir / "test.html").write_text("test")
        output_dir = temp_dir / "out"

        result = run_script(
            SCRIPT_PATH,
            "--report-name", "integration-testing",
            "--reports-folder", str(reports_dir),
            "--output-dir", str(output_dir),
        )
        assert result.returncode == 0
        outputs = _parse_output(result.stdout)
        assert outputs["report-dirname"].startswith("integration-testing-")


class TestGitHubOutput:
    """Test GITHUB_OUTPUT format."""

    def test_report_dir_output(self, temp_dir):
        """Should output report-dir with full path."""
        reports_dir = temp_dir / "reports"
        reports_dir.mkdir()
        (reports_dir / "test.html").write_text("test")
        output_dir = temp_dir / "out"

        result = run_script(
            SCRIPT_PATH,
            "--report-name", "test",
            "--reports-folder", str(reports_dir),
            "--output-dir", str(output_dir),
        )
        assert result.returncode == 0
        outputs = _parse_output(result.stdout)
        assert "report-dir" in outputs
        assert outputs["report-dir"].startswith(str(output_dir))

    def test_report_dirname_output(self, temp_dir):
        """Should output report-dirname without parent path."""
        reports_dir = temp_dir / "reports"
        reports_dir.mkdir()
        (reports_dir / "test.html").write_text("test")
        output_dir = temp_dir / "out"

        result = run_script(
            SCRIPT_PATH,
            "--report-name", "test",
            "--reports-folder", str(reports_dir),
            "--output-dir", str(output_dir),
        )
        assert result.returncode == 0
        outputs = _parse_output(result.stdout)
        assert "report-dirname" in outputs
        # dirname should not contain path separators
        assert "/" not in outputs["report-dirname"]

    def test_report_dir_contains_dirname(self, temp_dir):
        """Should have report-dir end with report-dirname."""
        reports_dir = temp_dir / "reports"
        reports_dir.mkdir()
        (reports_dir / "test.html").write_text("test")
        output_dir = temp_dir / "out"

        result = run_script(
            SCRIPT_PATH,
            "--report-name", "test",
            "--reports-folder", str(reports_dir),
            "--output-dir", str(output_dir),
        )
        assert result.returncode == 0
        outputs = _parse_output(result.stdout)
        assert outputs["report-dir"].endswith(outputs["report-dirname"])


class TestNewlineParsing:
    """Test newline-separated input parsing."""

    def test_blank_lines_skipped(self, temp_dir):
        """Should skip blank lines in input."""
        reports_dir = temp_dir / "reports"
        reports_dir.mkdir()
        (reports_dir / "test.html").write_text("test")

        # Include blank lines and extra whitespace
        folder_arg = f"\n  \n{reports_dir}\n  \n"
        output_dir = temp_dir / "out"

        result = run_script(
            SCRIPT_PATH,
            "--report-name", "test",
            "--reports-folder", folder_arg,
            "--output-dir", str(output_dir),
        )
        assert result.returncode == 0

    def test_whitespace_trimmed(self, temp_dir):
        """Should trim whitespace from each line."""
        reports_dir = temp_dir / "reports"
        reports_dir.mkdir()
        (reports_dir / "test.html").write_text("test")

        folder_arg = f"  {reports_dir}  "
        output_dir = temp_dir / "out"

        result = run_script(
            SCRIPT_PATH,
            "--report-name", "test",
            "--reports-folder", folder_arg,
            "--output-dir", str(output_dir),
        )
        assert result.returncode == 0


class TestSecurity:
    """Test security hardening."""

    def test_report_name_sanitizes_newlines(self, temp_dir):
        """Should strip newlines from report-name (prevents GITHUB_OUTPUT injection)."""
        reports_dir = temp_dir / "reports"
        reports_dir.mkdir()
        (reports_dir / "test.html").write_text("test")
        output_dir = temp_dir / "out"

        result = run_script(
            SCRIPT_PATH,
            "--report-name", "test\ninjected=malicious",
            "--reports-folder", str(reports_dir),
            "--output-dir", str(output_dir),
        )
        assert result.returncode == 0
        outputs = _parse_output(result.stdout)
        # Should not contain the injected key
        assert "injected" not in outputs
        # dirname should start with sanitized name
        assert outputs["report-dirname"].startswith("testinjectedmalicious-")

    def test_report_name_sanitizes_special_chars(self, temp_dir):
        """Should strip shell metacharacters from report-name."""
        reports_dir = temp_dir / "reports"
        reports_dir.mkdir()
        (reports_dir / "test.html").write_text("test")
        output_dir = temp_dir / "out"

        result = run_script(
            SCRIPT_PATH,
            "--report-name", "test; rm -rf /",
            "--reports-folder", str(reports_dir),
            "--output-dir", str(output_dir),
        )
        assert result.returncode == 0
        outputs = _parse_output(result.stdout)
        # Special chars should be stripped
        assert ";" not in outputs["report-dirname"]

    def test_path_traversal_rejected_in_reports_folder(self, temp_dir):
        """Should reject reports-folder paths with .. components."""
        reports_dir = temp_dir / "reports"
        reports_dir.mkdir()
        (reports_dir / "test.html").write_text("test")

        # Try to traverse out via ..
        folder_arg = f"../../../etc\n{reports_dir}"
        output_dir = temp_dir / "out"

        result = run_script(
            SCRIPT_PATH,
            "--report-name", "test",
            "--reports-folder", folder_arg,
            "--output-dir", str(output_dir),
        )
        assert result.returncode == 0
        assert "warning" in result.stderr.lower()

    def test_path_traversal_rejected_in_report_logs(self, temp_dir):
        """Should reject report-logs paths with .. components."""
        reports_dir = temp_dir / "reports"
        reports_dir.mkdir()
        (reports_dir / "test.html").write_text("test")

        logs_arg = "../../../etc/passwd"
        output_dir = temp_dir / "out"

        result = run_script(
            SCRIPT_PATH,
            "--report-name", "test",
            "--reports-folder", str(reports_dir),
            "--report-logs", logs_arg,
            "--output-dir", str(output_dir),
        )
        assert result.returncode == 0
        assert "warning" in result.stderr.lower()
