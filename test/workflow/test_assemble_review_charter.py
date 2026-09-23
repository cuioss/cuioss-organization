"""Tests for assemble-review-charter.py."""

import importlib.util
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT, run_script

SCRIPT_PATH = PROJECT_ROOT / "workflow-scripts/assemble-review-charter.py"

SPINE_BODY = "Report every issue you can substantiate, in these categories:\n- Injection.\n\nThere is no such bar."
PYTHON_BODY = "This pack is scoped to the python domain.\n\n- Defects specific to python."
PLUGIN_BODY = "This pack is scoped to the plugin domain.\n\n- Defects specific to plugin."


def _artifact(body: str) -> str:
    """A published artifact: the generated-header comment, a blank line, the body."""
    return (
        "<!-- GENERATED ARTIFACT — do not edit by hand.\n"
        "Derived from the cuioss/plan-marshall marketplace (marketplace/bundles/**).\n"
        "-->\n\n"
        f"{body}\n"
    )


SPINE_ARTIFACT = _artifact(SPINE_BODY)
PYTHON_ARTIFACT = _artifact(PYTHON_BODY)
PUBLISHED = {"spine": SPINE_ARTIFACT, "python": PYTHON_ARTIFACT, "plugin": _artifact(PLUGIN_BODY)}


def _fetcher():
    return PUBLISHED.__getitem__


def _mock_response(body: str):
    mock_response = MagicMock()
    mock_response.read.return_value = body.encode("utf-8")
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)
    return mock_response


def _http_error(code: int):
    return urllib.error.HTTPError(url="https://api.github.com", code=code, msg="error", hdrs={}, fp=None)


DECLARING_PROJECT_YML = """\
name: example
sonar:
  enabled: true
cuioss-review-bot:
  enabled: true
  packs: [python, plugin]
  additional_rules: []
"""

SILENT_PROJECT_YML = """\
name: example
sonar:
  enabled: true
"""


def _load_module():
    spec = importlib.util.spec_from_file_location("assemble_review_charter", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestReadDeclaration:
    """The three read outcomes, and the answers that are none of them."""

    def test_not_found_is_file_absent(self):
        mod = _load_module()
        declaration = mod.read_declaration(404, '{"message": "Not Found"}')
        assert declaration.outcome is mod.ReadOutcome.FILE_ABSENT
        assert declaration.block is None

    def test_file_without_the_block_is_block_absent(self):
        mod = _load_module()
        declaration = mod.read_declaration(200, SILENT_PROJECT_YML)
        assert declaration.outcome is mod.ReadOutcome.BLOCK_ABSENT
        assert declaration.block is None

    def test_empty_file_is_block_absent(self):
        mod = _load_module()
        assert mod.read_declaration(200, "").outcome is mod.ReadOutcome.BLOCK_ABSENT

    def test_declared_block_is_block_present_and_carried(self):
        mod = _load_module()
        declaration = mod.read_declaration(200, DECLARING_PROJECT_YML)
        assert declaration.outcome is mod.ReadOutcome.BLOCK_PRESENT
        assert declaration.block == {"enabled": True, "packs": ["python", "plugin"], "additional_rules": []}

    @pytest.mark.parametrize("status", [401, 403, 500, 502])
    def test_any_other_status_is_a_failure_not_absence(self, status):
        """An unreadable declaration must never read as "nothing declared"."""
        mod = _load_module()
        with pytest.raises(mod.DeclarationError, match=f"HTTP {status}"):
            mod.read_declaration(status, "")

    def test_non_mapping_document_is_a_failure(self):
        mod = _load_module()
        with pytest.raises(mod.DeclarationError, match="not a YAML mapping"):
            mod.read_declaration(200, "- just\n- a list\n")


class TestStripGeneratedHeader:
    def test_header_comment_is_dropped_and_body_kept(self):
        mod = _load_module()
        assert mod.strip_generated_header(SPINE_ARTIFACT) == SPINE_BODY

    def test_artifact_without_a_header_is_kept_whole(self):
        mod = _load_module()
        assert mod.strip_generated_header(f"\n{PYTHON_BODY}\n") == PYTHON_BODY

    def test_unclosed_header_is_a_failure(self):
        mod = _load_module()
        with pytest.raises(mod.DeclarationError, match="never closes"):
            mod.strip_generated_header("<!-- GENERATED ARTIFACT — do not edit by hand.\nno end")


class TestResolvePackKeys:
    def test_declared_order_is_kept(self):
        mod = _load_module()
        assert mod.resolve_pack_keys(["plugin", "python"]) == ["plugin", "python"]

    def test_the_spine_is_not_selectable(self):
        mod = _load_module()
        with pytest.raises(mod.DeclarationError, match="not selectable"):
            mod.resolve_pack_keys(["python", "spine"])

    @pytest.mark.parametrize("key", ["../secrets", "python.md", "Python", "py/thon", "", "python?ref=x", "python\n", 7])
    def test_a_key_that_is_not_an_artifact_stem_is_rejected(self, key):
        mod = _load_module()
        with pytest.raises(mod.DeclarationError, match="unknown pack key"):
            mod.resolve_pack_keys([key])


class TestComposition:
    """Spine first byte-identical, packs in declared order, additional rules last."""

    def test_packs_python_plugin_compose_to_spine_python_plugin(self):
        mod = _load_module()
        charter = mod.assemble_charter(
            {"enabled": True, "packs": ["python", "plugin"], "additional_rules": []}, _fetcher()
        )
        assert charter == f"{SPINE_BODY}\n\n{PYTHON_BODY}\n\n{PLUGIN_BODY}"

    def test_declared_order_governs_pack_order(self):
        mod = _load_module()
        charter = mod.assemble_charter({"packs": ["plugin", "python"]}, _fetcher())
        assert charter.index(PLUGIN_BODY) < charter.index(PYTHON_BODY)

    def test_additional_rules_are_appended_after_every_pack(self):
        mod = _load_module()
        charter = mod.assemble_charter(
            {"packs": ["python"], "additional_rules": ["Flag every new TODO.", "Prefer pathlib."]}, _fetcher()
        )
        assert charter == (
            f"{SPINE_BODY}\n\n{PYTHON_BODY}\n\n"
            "Additional rules for this repository:\n- Flag every new TODO.\n- Prefer pathlib."
        )

    def test_the_spine_is_applied_even_when_no_pack_is_selected(self):
        mod = _load_module()
        assert mod.assemble_charter({"packs": []}, _fetcher()) == SPINE_BODY

    def test_no_generated_header_reaches_the_charter(self):
        mod = _load_module()
        charter = mod.assemble_charter({"packs": ["python", "plugin"]}, _fetcher())
        assert "GENERATED ARTIFACT" not in charter
        assert "-->" not in charter


class TestFetchPack:
    @patch("urllib.request.urlopen")
    def test_reads_the_settings_repository_default_branch(self, mock_urlopen):
        mock_urlopen.return_value = _mock_response(PYTHON_ARTIFACT)
        mod = _load_module()
        assert mod.fetch_pack("python", "token") == PYTHON_ARTIFACT
        request = mock_urlopen.call_args.args[0]
        assert request.full_url == "https://api.github.com/repos/cuioss/cuioss-review-bot/contents/packs/python.md"
        assert request.get_header("Authorization") == "Bearer token"

    @patch("urllib.request.urlopen")
    def test_not_found_names_the_unknown_key(self, mock_urlopen):
        mock_urlopen.side_effect = _http_error(404)
        mod = _load_module()
        with pytest.raises(mod.DeclarationError, match="unknown pack key 'rust'"):
            mod.fetch_pack("rust", "token")

    @patch("urllib.request.urlopen")
    def test_any_other_error_is_an_unfetchable_pack(self, mock_urlopen):
        mock_urlopen.side_effect = _http_error(500)
        mod = _load_module()
        with pytest.raises(mod.DeclarationError, match="could not be fetched.*HTTP 500"):
            mod.fetch_pack("python", "token")


class TestReadCommand:
    """The CLI writes GITHUB_OUTPUT entries to stdout and keeps diagnostics on stderr."""

    @patch("urllib.request.urlopen")
    def test_block_present_output_carries_the_charter(self, mock_urlopen, temp_dir, monkeypatch, capsys):
        mock_urlopen.side_effect = lambda request, timeout: _mock_response(
            PUBLISHED[request.full_url.rsplit("/", 1)[1].removesuffix(".md")]
        )
        body = temp_dir / "project.yml"
        body.write_text(DECLARING_PROJECT_YML, encoding="utf-8")
        monkeypatch.setattr(
            sys, "argv", ["assemble-review-charter.py", "read", "--http-status", "200", "--body-file", str(body)]
        )
        mod = _load_module()

        assert mod.main() == 0

        lines = capsys.readouterr().out.splitlines()
        assert lines[0] == "declaration=block-present"
        name, delimiter = lines[1].split("<<")
        assert name == "charter"
        assert lines[-1] == delimiter
        assert "\n".join(lines[2:-1]) == f"{SPINE_BODY}\n\n{PYTHON_BODY}\n\n{PLUGIN_BODY}"

    def test_block_absent_output(self, temp_dir):
        body = temp_dir / "project.yml"
        body.write_text(SILENT_PROJECT_YML, encoding="utf-8")
        result = run_script(SCRIPT_PATH, "read", "--http-status", "200", "--body-file", str(body))
        assert result.returncode == 0
        assert result.stdout == "declaration=block-absent\n"

    def test_file_absent_output_ignores_the_error_body(self, temp_dir):
        body = temp_dir / "project.yml"
        body.write_text('{"message": "Not Found"}', encoding="utf-8")
        result = run_script(SCRIPT_PATH, "read", "--http-status", "404", "--body-file", str(body))
        assert result.returncode == 0
        assert result.stdout == "declaration=file-absent\n"

    def test_failed_read_exits_non_zero_with_an_error_annotation(self, temp_dir):
        body = temp_dir / "project.yml"
        body.write_text('{"message": "Bad credentials"}', encoding="utf-8")
        result = run_script(SCRIPT_PATH, "read", "--http-status", "401", "--body-file", str(body))
        assert result.returncode == 1
        assert result.stdout == ""
        assert "::error::" in result.stderr
        assert "HTTP 401" in result.stderr
