"""Tests for check-snapshot-published.py."""

import importlib.util
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT, run_script

SCRIPT_PATH = PROJECT_ROOT / "workflow-scripts/check-snapshot-published.py"

METADATA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<metadata modelVersion="1.1.0">
  <groupId>de.cuioss</groupId>
  <artifactId>my-parent</artifactId>
  <versioning>
    <lastUpdated>20260921132033</lastUpdated>
    <snapshot>
      <timestamp>{timestamp}</timestamp>
      <buildNumber>37</buildNumber>
    </snapshot>
  </versioning>
  <version>1.2-SNAPSHOT</version>
</metadata>
"""


def _load_module():
    spec = importlib.util.spec_from_file_location("check_snapshot_published", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mock_response(body: str):
    mock_response = MagicMock()
    mock_response.read.return_value = body.encode("utf-8")
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)
    return mock_response


class TestMetadataUrl:
    def test_group_id_path_conversion(self):
        mod = _load_module()
        url = mod._metadata_url("de.cuioss.test", "my-parent", "1.2-SNAPSHOT")
        assert url == (
            "https://central.sonatype.com/repository/maven-snapshots/"
            "de/cuioss/test/my-parent/1.2-SNAPSHOT/maven-metadata.xml"
        )


class TestFetchSnapshotTimestamp:
    @patch("urllib.request.urlopen")
    def test_returns_timestamp_when_present(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(METADATA_XML.format(timestamp="20260921.132033"))
        mod = _load_module()
        assert mod.fetch_snapshot_timestamp("de.cuioss", "my-parent", "1.2-SNAPSHOT") == "20260921.132033"

    @patch("urllib.request.urlopen")
    def test_returns_none_on_404(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://example.com", code=404, msg="Not Found", hdrs={}, fp=None
        )
        mod = _load_module()
        assert mod.fetch_snapshot_timestamp("de.cuioss", "my-parent", "1.2-SNAPSHOT") is None

    @patch("time.sleep", MagicMock())
    @patch("urllib.request.urlopen")
    def test_raises_after_retries_on_server_error(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://example.com", code=503, msg="Service Unavailable", hdrs={}, fp=None
        )
        mod = _load_module()
        try:
            mod.fetch_snapshot_timestamp("de.cuioss", "my-parent", "1.2-SNAPSHOT")
            assert False, "expected RuntimeError"
        except RuntimeError:
            pass
        assert mock_urlopen.call_count == mod.FETCH_ATTEMPTS

    @patch("urllib.request.urlopen")
    def test_returns_none_when_snapshot_element_absent(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(
            """<?xml version="1.0"?><metadata><groupId>de.cuioss</groupId></metadata>"""
        )
        mod = _load_module()
        assert mod.fetch_snapshot_timestamp("de.cuioss", "my-parent", "1.2-SNAPSHOT") is None


class TestAsComparable:
    def test_strips_dot(self):
        mod = _load_module()
        assert mod._as_comparable("20260921.132033") == "20260921132033"


class TestCmdRecord:
    """`record`'s stdout is captured straight into $GITHUB_OUTPUT by the caller
    (`>> "$GITHUB_OUTPUT"`), so only its two key=value lines may appear there —
    everything else must go to stderr, or the redirected file gets a line with no
    `=` and the next Actions step fails to parse it.
    """

    @patch("urllib.request.urlopen")
    def test_stdout_is_only_key_value_lines_when_metadata_exists(self, mock_urlopen, capsys):
        mock_urlopen.return_value = _mock_response(METADATA_XML.format(timestamp="20260921.132033"))
        mod = _load_module()
        args = argparse_namespace(group_id="de.cuioss", artifact_id="my-parent", version="1.2-SNAPSHOT")

        assert mod.cmd_record(args) == 0

        captured = capsys.readouterr()
        out_lines = [line for line in captured.out.splitlines() if line]
        assert out_lines[0] == "before-timestamp=20260921.132033"
        assert out_lines[1].startswith("deploy-start=")
        assert len(out_lines) == 2
        assert "Pre-deploy snapshot timestamp" in captured.err

    @patch("urllib.request.urlopen")
    def test_stdout_has_empty_before_timestamp_on_first_ever_publish(self, mock_urlopen, capsys):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://example.com", code=404, msg="Not Found", hdrs={}, fp=None
        )
        mod = _load_module()
        args = argparse_namespace(group_id="de.cuioss", artifact_id="my-parent", version="1.2-SNAPSHOT")

        assert mod.cmd_record(args) == 0

        out_lines = [line for line in capsys.readouterr().out.splitlines() if line]
        assert out_lines[0] == "before-timestamp="

    @patch("time.sleep", MagicMock())
    @patch("urllib.request.urlopen")
    def test_a_fetch_failure_prints_nothing_on_stdout(self, mock_urlopen, capsys):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://example.com", code=503, msg="Service Unavailable", hdrs={}, fp=None
        )
        mod = _load_module()
        args = argparse_namespace(group_id="de.cuioss", artifact_id="my-parent", version="1.2-SNAPSHOT")

        with pytest.raises(RuntimeError):
            mod.cmd_record(args)

        assert capsys.readouterr().out == ""


class TestCmdVerify:
    @patch("urllib.request.urlopen")
    def test_fails_when_nothing_published(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://example.com", code=404, msg="Not Found", hdrs={}, fp=None
        )
        mod = _load_module()
        args = argparse_namespace(
            group_id="de.cuioss",
            artifact_id="my-parent",
            version="1.2-SNAPSHOT",
            before_timestamp="",
            deploy_start="20260921120000",
        )
        assert mod.cmd_verify(args) == 1

    @patch("urllib.request.urlopen")
    def test_fails_when_timestamp_predates_deploy_start(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(METADATA_XML.format(timestamp="20260921.110000"))
        mod = _load_module()
        args = argparse_namespace(
            group_id="de.cuioss",
            artifact_id="my-parent",
            version="1.2-SNAPSHOT",
            before_timestamp="",
            deploy_start="20260921120000",
        )
        assert mod.cmd_verify(args) == 1

    @patch("urllib.request.urlopen")
    def test_fails_when_timestamp_did_not_advance_past_before(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(METADATA_XML.format(timestamp="20260921.130000"))
        mod = _load_module()
        args = argparse_namespace(
            group_id="de.cuioss",
            artifact_id="my-parent",
            version="1.2-SNAPSHOT",
            before_timestamp="20260921.130000",
            deploy_start="20260921120000",
        )
        assert mod.cmd_verify(args) == 1

    @patch("urllib.request.urlopen")
    def test_succeeds_when_timestamp_advanced(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(METADATA_XML.format(timestamp="20260921.140000"))
        mod = _load_module()
        args = argparse_namespace(
            group_id="de.cuioss",
            artifact_id="my-parent",
            version="1.2-SNAPSHOT",
            before_timestamp="20260921.130000",
            deploy_start="20260921120000",
        )
        assert mod.cmd_verify(args) == 0

    @patch("urllib.request.urlopen")
    def test_succeeds_on_first_ever_publish_with_empty_before(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(METADATA_XML.format(timestamp="20260921.140000"))
        mod = _load_module()
        args = argparse_namespace(
            group_id="de.cuioss",
            artifact_id="my-parent",
            version="1.2-SNAPSHOT",
            before_timestamp="",
            deploy_start="20260921120000",
        )
        assert mod.cmd_verify(args) == 0


def argparse_namespace(**kwargs):
    import argparse

    return argparse.Namespace(**kwargs)


class TestArgumentValidation:
    def test_requires_command(self):
        result = run_script(SCRIPT_PATH)
        assert result.returncode != 0

    def test_record_requires_group_id(self):
        result = run_script(SCRIPT_PATH, "record", "--artifact-id", "my-parent", "--version", "1.2-SNAPSHOT")
        assert result.returncode != 0

    def test_verify_requires_deploy_start(self):
        result = run_script(
            SCRIPT_PATH,
            "verify",
            "--group-id",
            "de.cuioss",
            "--artifact-id",
            "my-parent",
            "--version",
            "1.2-SNAPSHOT",
        )
        assert result.returncode != 0
