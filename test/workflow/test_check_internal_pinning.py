"""Tests for check-internal-pinning.py - release-time mutable reference guard."""

import sys
from pathlib import Path

# Add parent to path to access conftest
sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT, run_script

SCRIPT_PATH = PROJECT_ROOT / "workflow-scripts/check-internal-pinning.py"

VALID_SHA = "abcdef1234567890abcdef1234567890abcdef12"


def write_workflow(temp_dir, name, body):
    workflows_dir = temp_dir / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    path = workflows_dir / name
    path.write_text(body)
    return path


class TestDetectsMutableReferences:
    """The defect this guard exists for: a released commit referencing a tag."""

    def test_rejects_version_tag_reference(self, temp_dir):
        """A @v{version} ref is mutable — moving the tag changes executed code."""
        write_workflow(temp_dir, "reusable-build.yml", """
jobs:
  build:
    steps:
      - uses: cuioss/cuioss-organization/.github/actions/read-project-config@v0.12.0
""")

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 1
        assert "read-project-config@v0.12.0" in result.stderr

    def test_rejects_branch_reference(self, temp_dir):
        write_workflow(temp_dir, "reusable-build.yml", """
jobs:
  build:
    steps:
      - uses: cuioss/cuioss-organization/.github/actions/read-project-config@main
""")

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 1
        assert "@main" in result.stderr

    def test_reports_every_violation(self, temp_dir):
        """Must not stop at the first file — the defect spanned six workflows."""
        for name in ("reusable-maven-build.yml", "reusable-npm-build.yml"):
            write_workflow(temp_dir, name, """
jobs:
  build:
    steps:
      - uses: cuioss/cuioss-organization/.github/actions/read-project-config@v0.12.0
""")

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 1
        assert "reusable-maven-build.yml" in result.stderr
        assert "reusable-npm-build.yml" in result.stderr
        assert "found 2 mutable" in result.stderr

    def test_reports_line_numbers(self, temp_dir):
        write_workflow(temp_dir, "reusable-build.yml", """jobs:
  build:
    steps:
      - uses: cuioss/cuioss-organization/.github/actions/read-project-config@v0.12.0
""")

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 1
        assert "reusable-build.yml:4" in result.stderr


class TestAcceptsPinnedReferences:
    """Legitimate content must not fail the release."""

    def test_accepts_sha_pinned_reference(self, temp_dir):
        write_workflow(temp_dir, "reusable-build.yml", f"""
jobs:
  build:
    steps:
      - uses: cuioss/cuioss-organization/.github/actions/read-project-config@{VALID_SHA} # v1.0.0
""")

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 0

    def test_ignores_commented_usage_example(self, temp_dir):
        """Commented examples are documentation, not executed references.

        reusable-dependabot-auto-merge.yml carries exactly such a comment.
        """
        write_workflow(temp_dir, "reusable-build.yml", f"""
# Usage:
#   jobs:
#     build:
#       uses: cuioss/cuioss-organization/.github/workflows/reusable-build.yml@v0.12.0
jobs:
  build:
    steps:
      - uses: cuioss/cuioss-organization/.github/actions/read-project-config@{VALID_SHA} # v1.0.0
""")

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 0

    def test_ignores_template_expression_reference(self, temp_dir):
        """release.yml resolves its ref at runtime — not statically checkable."""
        write_workflow(temp_dir, "release.yml", """
jobs:
  build:
    uses: cuioss/cuioss-organization/.github/workflows/reusable-maven-build.yml@${{ steps.sha.outputs.sha }}
""")

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 0

    def test_ignores_third_party_actions(self, temp_dir):
        """Only cuioss-organization self-references are in scope here."""
        write_workflow(temp_dir, "reusable-build.yml", """
jobs:
  build:
    steps:
      - uses: actions/checkout@v4
""")

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 0

    def test_accepts_missing_workflows_directory(self, temp_dir):
        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 0


class TestRepositoryInvariant:
    """Run the guard against the real repository.

    This is what makes the sequencing fix self-enforcing: every PR re-checks
    that no mutable internal reference has crept back in.
    """

    def test_repository_has_no_mutable_internal_references(self):
        result = run_script(SCRIPT_PATH, "--path", str(PROJECT_ROOT))

        assert result.returncode == 0, (
            f"Repository contains mutable internal references:\n{result.stderr}"
        )
