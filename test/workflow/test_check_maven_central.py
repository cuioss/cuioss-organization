"""Tests for check-maven-central.py."""

import importlib.util
import json
import sys
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


class TestCheckArtifactIndexed:
    """Test check_artifact_indexed function."""

    @patch("urllib.request.urlopen")
    def test_returns_true_when_found(self, mock_urlopen):
        response_data = json.dumps({"response": {"numFound": 1}}).encode("utf-8")
        mock_response = MagicMock()
        mock_response.read.return_value = response_data
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        mod = _load_module()
        assert mod.check_artifact_indexed("de.cuioss", "cui-java-parent", "1.4.4") is True

    @patch("urllib.request.urlopen")
    def test_returns_false_when_not_found(self, mock_urlopen):
        response_data = json.dumps({"response": {"numFound": 0}}).encode("utf-8")
        mock_response = MagicMock()
        mock_response.read.return_value = response_data
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        mod = _load_module()
        assert mod.check_artifact_indexed("de.cuioss", "cui-java-parent", "1.4.4") is False

    @patch("urllib.request.urlopen")
    def test_returns_false_on_url_error(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        mod = _load_module()
        assert mod.check_artifact_indexed("de.cuioss", "cui-java-parent", "1.4.4") is False

    @patch("urllib.request.urlopen")
    def test_returns_false_on_invalid_json(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.read.return_value = b"not json"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        mod = _load_module()
        assert mod.check_artifact_indexed("de.cuioss", "cui-java-parent", "1.4.4") is False


class TestWaitForArtifact:
    """Test wait_for_artifact function."""

    @patch("time.sleep")
    def test_returns_immediately_when_found(self, mock_sleep):
        mod = _load_module()
        with patch.object(mod, "check_artifact_indexed", return_value=True):
            result = mod.wait_for_artifact("de.cuioss", "parent", "1.0", 60, 10)
        assert result is True
        mock_sleep.assert_not_called()

    @patch("time.sleep")
    def test_polls_until_found(self, mock_sleep):
        mod = _load_module()
        # Not found first two times, then found
        with patch.object(
            mod, "check_artifact_indexed", side_effect=[False, False, True]
        ):
            result = mod.wait_for_artifact("de.cuioss", "parent", "1.0", 120, 10)
        assert result is True
        assert mock_sleep.call_count == 2

    @patch("time.sleep")
    def test_returns_false_on_timeout(self, mock_sleep):
        mod = _load_module()
        with patch.object(mod, "check_artifact_indexed", return_value=False):
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
