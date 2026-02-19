"""Tests for check-maven-central.py."""

import importlib.util
import os
import sys
import tempfile
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add parent to path to access conftest
sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT, run_script

SCRIPT_PATH = PROJECT_ROOT / "workflow-scripts/check-maven-central.py"


def _load_module():
    """Load check-maven-central.py as a module for unit testing."""
    spec = importlib.util.spec_from_file_location("check_maven_central", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestCheckArtifactAvailable:
    """Test check_artifact_available function."""

    @patch("urllib.request.urlopen")
    def test_returns_true_when_found(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        mod = _load_module()
        assert mod.check_artifact_available("de.cuioss", "cui-java-parent", "1.4.4") is True

        # Verify the URL uses repo1 with correct group path
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert "repo1.maven.org/maven2/de/cuioss/cui-java-parent/1.4.4/" in req.full_url
        assert req.method == "HEAD"

    @patch("urllib.request.urlopen")
    def test_returns_false_on_404(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://example.com", code=404, msg="Not Found", hdrs={}, fp=None
        )

        mod = _load_module()
        assert mod.check_artifact_available("de.cuioss", "cui-java-parent", "1.4.4") is False

    @patch("urllib.request.urlopen")
    def test_returns_false_on_server_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://example.com", code=503, msg="Service Unavailable", hdrs={}, fp=None
        )

        mod = _load_module()
        assert mod.check_artifact_available("de.cuioss", "cui-java-parent", "1.4.4") is False

    @patch("urllib.request.urlopen")
    def test_returns_false_on_url_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        mod = _load_module()
        assert mod.check_artifact_available("de.cuioss", "cui-java-parent", "1.4.4") is False

    def test_group_id_path_conversion(self):
        """Verify that group ID dots are converted to path separators in the URL."""
        mod = _load_module()
        url = mod.MAVEN_CENTRAL_REPO_URL.format(
            group_path="de.cuioss.test".replace(".", "/"),
            artifact_id="cui-test-value-objects",
            version="2.1.3",
        )
        assert "/de/cuioss/test/cui-test-value-objects/2.1.3/" in url


class TestGitHubOutputWriting:
    """Test _write_github_output function."""

    def test_writes_found_true(self):
        mod = _load_module()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            output_file = f.name
        try:
            with patch.dict(os.environ, {"GITHUB_OUTPUT": output_file}):
                mod._write_github_output(True)
            content = Path(output_file).read_text()
            assert "found=true" in content
        finally:
            os.unlink(output_file)

    def test_writes_found_false(self):
        mod = _load_module()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            output_file = f.name
        try:
            with patch.dict(os.environ, {"GITHUB_OUTPUT": output_file}):
                mod._write_github_output(False)
            content = Path(output_file).read_text()
            assert "found=false" in content
        finally:
            os.unlink(output_file)

    def test_noop_without_github_output(self):
        mod = _load_module()
        with patch.dict(os.environ, {}, clear=True):
            # Ensure GITHUB_OUTPUT is not set
            os.environ.pop("GITHUB_OUTPUT", None)
            # Should not raise
            mod._write_github_output(True)


class TestWaitForArtifact:
    """Test wait_for_artifact function."""

    @patch("time.sleep")
    def test_returns_immediately_when_found(self, mock_sleep):
        mod = _load_module()
        with patch.object(mod, "check_artifact_available", return_value=True):
            result = mod.wait_for_artifact("de.cuioss", "parent", "1.0", 60, 10)
        assert result is True
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    def test_polls_until_found(self, mock_sleep):
        mod = _load_module()
        # Not found first two times, then found
        with patch.object(
            mod, "check_artifact_available", side_effect=[False, False, True]
        ):
            result = mod.wait_for_artifact("de.cuioss", "parent", "1.0", 120, 10)
        assert result is True
        assert mock_sleep.call_count == 2

    @patch("time.sleep")
    def test_returns_false_on_timeout(self, mock_sleep):
        mod = _load_module()
        with patch.object(mod, "check_artifact_available", return_value=False):
            result = mod.wait_for_artifact("de.cuioss", "parent", "1.0", 20, 10)
        assert result is False


class TestArgumentValidation:
    """Test command line argument validation."""

    def test_requires_group_id(self):
        result = run_script(
            SCRIPT_PATH,
            "--artifact-id", "cui-java-parent",
            "--version", "1.4.4",
        )
        assert result.returncode != 0

    def test_requires_artifact_id(self):
        result = run_script(
            SCRIPT_PATH,
            "--group-id", "de.cuioss",
            "--version", "1.4.4",
        )
        assert result.returncode != 0

    def test_requires_version(self):
        result = run_script(
            SCRIPT_PATH,
            "--group-id", "de.cuioss",
            "--artifact-id", "cui-java-parent",
        )
        assert result.returncode != 0
