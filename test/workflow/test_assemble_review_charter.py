"""Tests for assemble-review-charter.py."""

import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT, run_script

SCRIPT_PATH = PROJECT_ROOT / "workflow-scripts/assemble-review-charter.py"

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


class TestReadCommand:
    """The CLI emits one GITHUB_OUTPUT line and keeps diagnostics off stdout."""

    def test_block_present_output(self, temp_dir):
        body = temp_dir / "project.yml"
        body.write_text(DECLARING_PROJECT_YML, encoding="utf-8")
        result = run_script(SCRIPT_PATH, "read", "--http-status", "200", "--body-file", str(body))
        assert result.returncode == 0
        assert result.stdout == "declaration=block-present\n"

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
