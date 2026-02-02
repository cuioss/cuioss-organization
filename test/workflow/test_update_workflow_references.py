"""Tests for update-workflow-references.py - SHA reference updater."""

import sys
from pathlib import Path

# Add parent to path to access conftest
sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT, run_script

SCRIPT_PATH = PROJECT_ROOT / "workflow-scripts/update-workflow-references.py"

# Valid test SHA (40 hex characters)
VALID_SHA = "abcdef1234567890abcdef1234567890abcdef12"
VALID_VERSION = "1.0.0"


class TestArgumentValidation:
    """Test command line argument validation."""

    def test_requires_version_argument(self):
        """Should fail without --version argument."""
        result = run_script(SCRIPT_PATH, "--sha", VALID_SHA)
        assert result.returncode != 0
        assert "required" in result.stderr.lower() or "error" in result.stderr.lower()

    def test_requires_sha_argument_without_internal_only(self):
        """Should fail without --sha argument when not using --internal-only."""
        result = run_script(SCRIPT_PATH, "--version", VALID_VERSION)
        assert result.returncode != 0
        assert "required" in result.stderr.lower() or "error" in result.stderr.lower()

    def test_sha_not_required_with_internal_only(self, temp_dir):
        """Should not require --sha when --internal-only is specified."""
        result = run_script(
            SCRIPT_PATH,
            "--version", VALID_VERSION,
            "--internal-only",
            "--path", str(temp_dir)
        )
        # Returns 1 when no files modified (no error about missing SHA)
        assert "required" not in result.stderr.lower()
        assert "No files modified" in result.stdout or result.returncode == 1

    def test_validates_sha_length(self):
        """Should reject SHA that's not 40 characters."""
        result = run_script(SCRIPT_PATH, "--version", VALID_VERSION, "--sha", "abc123")
        assert result.returncode != 0
        assert "40-character" in result.stderr or "40" in result.stderr

    def test_validates_sha_hex(self):
        """Should reject non-hex SHA."""
        invalid_sha = "ghijkl1234567890ghijkl1234567890ghijkl12"
        result = run_script(SCRIPT_PATH, "--version", VALID_VERSION, "--sha", invalid_sha)
        assert result.returncode != 0

    def test_validates_path_exists(self, temp_dir):
        """Should reject non-existent path."""
        result = run_script(
            SCRIPT_PATH,
            "--version", VALID_VERSION,
            "--sha", VALID_SHA,
            "--path", str(temp_dir / "nonexistent")
        )
        assert result.returncode != 0
        assert "not exist" in result.stderr.lower() or "error" in result.stderr.lower()


class TestWorkflowReferenceUpdate:
    """Test workflow reference updating functionality."""

    def test_updates_workflow_reference(self, temp_dir):
        """Should update cuioss-organization workflow references."""
        # Create workflow directory and file
        workflows_dir = temp_dir / ".github" / "workflows"
        workflows_dir.mkdir(parents=True)

        workflow_file = workflows_dir / "build.yml"
        workflow_file.write_text("""
name: Build
jobs:
  build:
    uses: cuioss/cuioss-organization/.github/workflows/reusable-maven-build.yml@main
""")

        result = run_script(
            SCRIPT_PATH,
            "--version", VALID_VERSION,
            "--sha", VALID_SHA,
            "--path", str(temp_dir)
        )

        assert result.returncode == 0
        updated_content = workflow_file.read_text()
        assert f"@{VALID_SHA}" in updated_content
        assert f"# v{VALID_VERSION}" in updated_content

    def test_updates_with_existing_version_comment(self, temp_dir):
        """Should replace existing version comment."""
        workflows_dir = temp_dir / ".github" / "workflows"
        workflows_dir.mkdir(parents=True)

        workflow_file = workflows_dir / "build.yml"
        workflow_file.write_text("""
name: Build
jobs:
  build:
    uses: cuioss/cuioss-organization/.github/workflows/reusable-maven-build.yml@oldsha123 # v0.0.1
""")

        result = run_script(
            SCRIPT_PATH,
            "--version", VALID_VERSION,
            "--sha", VALID_SHA,
            "--path", str(temp_dir)
        )

        assert result.returncode == 0
        updated_content = workflow_file.read_text()
        assert f"@{VALID_SHA}" in updated_content
        assert f"# v{VALID_VERSION}" in updated_content
        assert "v0.0.1" not in updated_content

    def test_updates_action_reference(self, temp_dir):
        """Should update cuioss-organization action references."""
        workflows_dir = temp_dir / ".github" / "workflows"
        workflows_dir.mkdir(parents=True)

        workflow_file = workflows_dir / "build.yml"
        workflow_file.write_text("""
name: Build
jobs:
  build:
    steps:
      - uses: cuioss/cuioss-organization/.github/actions/read-project-config@main
""")

        result = run_script(
            SCRIPT_PATH,
            "--version", VALID_VERSION,
            "--sha", VALID_SHA,
            "--path", str(temp_dir)
        )

        assert result.returncode == 0
        updated_content = workflow_file.read_text()
        assert f"@{VALID_SHA}" in updated_content

    def test_updates_multiple_references(self, temp_dir):
        """Should update multiple references in same file."""
        workflows_dir = temp_dir / ".github" / "workflows"
        workflows_dir.mkdir(parents=True)

        workflow_file = workflows_dir / "build.yml"
        workflow_file.write_text("""
name: Build
jobs:
  build:
    uses: cuioss/cuioss-organization/.github/workflows/reusable-maven-build.yml@main
  release:
    uses: cuioss/cuioss-organization/.github/workflows/reusable-maven-release.yml@main
""")

        result = run_script(
            SCRIPT_PATH,
            "--version", VALID_VERSION,
            "--sha", VALID_SHA,
            "--path", str(temp_dir)
        )

        assert result.returncode == 0
        updated_content = workflow_file.read_text()
        # Should have two SHA references
        assert updated_content.count(f"@{VALID_SHA}") == 2


class TestNoModificationCases:
    """Test cases where no modifications should occur."""

    def test_no_workflows_directory(self, temp_dir):
        """Should handle missing .github/workflows directory."""
        result = run_script(
            SCRIPT_PATH,
            "--version", VALID_VERSION,
            "--sha", VALID_SHA,
            "--path", str(temp_dir)
        )
        # Returns 1 when no files modified
        assert result.returncode == 1
        assert "No files modified" in result.stdout

    def test_no_cuioss_references(self, temp_dir):
        """Should not modify files without cuioss-organization references."""
        workflows_dir = temp_dir / ".github" / "workflows"
        workflows_dir.mkdir(parents=True)

        workflow_file = workflows_dir / "build.yml"
        original_content = """
name: Build
jobs:
  build:
    uses: actions/checkout@v4
"""
        workflow_file.write_text(original_content)

        run_script(
            SCRIPT_PATH,
            "--version", VALID_VERSION,
            "--sha", VALID_SHA,
            "--path", str(temp_dir)
        )

        assert workflow_file.read_text() == original_content


class TestDocumentationUpdate:
    """Test documentation file updating."""

    def test_updates_workflows_adoc(self, temp_dir):
        """Should update docs/Workflows.adoc if present."""
        docs_dir = temp_dir / "docs"
        docs_dir.mkdir()

        doc_file = docs_dir / "Workflows.adoc"
        doc_file.write_text("""
= Workflows

[source,yaml]
----
uses: cuioss/cuioss-organization/.github/workflows/reusable-maven-build.yml@main
----
""")

        result = run_script(
            SCRIPT_PATH,
            "--version", VALID_VERSION,
            "--sha", VALID_SHA,
            "--path", str(temp_dir)
        )

        assert result.returncode == 0
        updated_content = doc_file.read_text()
        assert f"@{VALID_SHA}" in updated_content

    def test_updates_readme_adoc(self, temp_dir):
        """Should update root README.adoc if present."""
        readme_file = temp_dir / "README.adoc"
        readme_file.write_text("""
= Project

[source,yaml]
----
uses: cuioss/cuioss-organization/.github/workflows/reusable-maven-build.yml@main
----
""")

        result = run_script(
            SCRIPT_PATH,
            "--version", VALID_VERSION,
            "--sha", VALID_SHA,
            "--path", str(temp_dir)
        )

        assert result.returncode == 0
        updated_content = readme_file.read_text()
        assert f"@{VALID_SHA}" in updated_content

    def test_updates_workflow_examples(self, temp_dir):
        """Should update files in docs/workflow-examples/."""
        examples_dir = temp_dir / "docs" / "workflow-examples"
        examples_dir.mkdir(parents=True)

        example_file = examples_dir / "maven-build.yml"
        example_file.write_text("""
name: Example
jobs:
  build:
    uses: cuioss/cuioss-organization/.github/workflows/reusable-maven-build.yml@main
""")

        result = run_script(
            SCRIPT_PATH,
            "--version", VALID_VERSION,
            "--sha", VALID_SHA,
            "--path", str(temp_dir)
        )

        assert result.returncode == 0
        updated_content = example_file.read_text()
        assert f"@{VALID_SHA}" in updated_content


class TestInternalOnlyMode:
    """Test --internal-only mode for reusable workflow updates."""

    def test_updates_only_reusable_workflows(self, temp_dir):
        """Should only update reusable-*.yml files in internal-only mode."""
        workflows_dir = temp_dir / ".github" / "workflows"
        workflows_dir.mkdir(parents=True)

        # Create a reusable workflow with internal reference
        reusable_file = workflows_dir / "reusable-build.yml"
        reusable_file.write_text("""
name: Reusable Build
on:
  workflow_call:
jobs:
  build:
    steps:
      - uses: cuioss/cuioss-organization/.github/actions/read-project-config@main
""")

        # Create a regular workflow that calls reusable workflows
        regular_file = workflows_dir / "build.yml"
        regular_file.write_text("""
name: Build
jobs:
  build:
    uses: cuioss/cuioss-organization/.github/workflows/reusable-maven-build.yml@main
""")

        result = run_script(
            SCRIPT_PATH,
            "--version", VALID_VERSION,
            "--internal-only",
            "--path", str(temp_dir)
        )

        assert result.returncode == 0

        # Reusable workflow should be updated with version tag (no SHA comment)
        reusable_content = reusable_file.read_text()
        assert f"@v{VALID_VERSION}" in reusable_content
        assert f"# v{VALID_VERSION}" not in reusable_content  # No SHA comment

        # Regular workflow should NOT be updated
        regular_content = regular_file.read_text()
        assert "@main" in regular_content
        assert f"@v{VALID_VERSION}" not in regular_content

    def test_does_not_update_docs_in_internal_only_mode(self, temp_dir):
        """Should not update docs/examples in internal-only mode."""
        workflows_dir = temp_dir / ".github" / "workflows"
        workflows_dir.mkdir(parents=True)
        docs_dir = temp_dir / "docs"
        docs_dir.mkdir()

        # Create a reusable workflow
        reusable_file = workflows_dir / "reusable-build.yml"
        reusable_file.write_text("""
name: Reusable
on:
  workflow_call:
jobs:
  build:
    steps:
      - uses: cuioss/cuioss-organization/.github/actions/read-project-config@main
""")

        # Create docs file
        doc_file = docs_dir / "Workflows.adoc"
        doc_file.write_text("""
= Workflows
uses: cuioss/cuioss-organization/.github/workflows/reusable-maven-build.yml@main
""")

        run_script(
            SCRIPT_PATH,
            "--version", VALID_VERSION,
            "--internal-only",
            "--path", str(temp_dir)
        )

        # Docs should NOT be updated
        doc_content = doc_file.read_text()
        assert "@main" in doc_content
        assert f"@v{VALID_VERSION}" not in doc_content

    def test_uses_version_tag_format(self, temp_dir):
        """Should use @v{version} format without SHA comment in internal-only mode."""
        workflows_dir = temp_dir / ".github" / "workflows"
        workflows_dir.mkdir(parents=True)

        reusable_file = workflows_dir / "reusable-build.yml"
        reusable_file.write_text("""
name: Reusable
on:
  workflow_call:
jobs:
  build:
    steps:
      - uses: cuioss/cuioss-organization/.github/actions/read-project-config@main
""")

        run_script(
            SCRIPT_PATH,
            "--version", VALID_VERSION,
            "--internal-only",
            "--path", str(temp_dir)
        )

        content = reusable_file.read_text()
        # Should have version tag without SHA
        assert f"@v{VALID_VERSION}" in content
        # Should not have a comment (no SHA comment)
        assert "# v" not in content


class TestReusableWorkflowSkipping:
    """Test that reusable workflows are skipped in normal (SHA) mode."""

    def test_skips_reusable_workflows_in_normal_mode(self, temp_dir):
        """Should skip reusable-*.yml files in normal mode (they use version tags)."""
        workflows_dir = temp_dir / ".github" / "workflows"
        workflows_dir.mkdir(parents=True)

        # Create a reusable workflow with internal reference
        reusable_file = workflows_dir / "reusable-build.yml"
        reusable_file.write_text("""
name: Reusable Build
on:
  workflow_call:
jobs:
  build:
    steps:
      - uses: cuioss/cuioss-organization/.github/actions/read-project-config@v1.0.0
""")

        # Create a regular workflow
        regular_file = workflows_dir / "build.yml"
        regular_file.write_text("""
name: Build
jobs:
  build:
    uses: cuioss/cuioss-organization/.github/workflows/reusable-maven-build.yml@main
""")

        run_script(
            SCRIPT_PATH,
            "--version", VALID_VERSION,
            "--sha", VALID_SHA,
            "--path", str(temp_dir)
        )

        # Reusable workflow should NOT be updated in normal mode
        reusable_content = reusable_file.read_text()
        assert "@v1.0.0" in reusable_content  # Original reference preserved
        assert f"@{VALID_SHA}" not in reusable_content

        # Regular workflow SHOULD be updated
        regular_content = regular_file.read_text()
        assert f"@{VALID_SHA}" in regular_content
        assert f"# v{VALID_VERSION}" in regular_content


class TestReleaseWorkflowSkipping:
    """Test that release.yml is always skipped (contains template placeholders)."""

    def test_skips_release_yml_in_normal_mode(self, temp_dir):
        """Should skip release.yml in normal mode (contains template placeholders)."""
        workflows_dir = temp_dir / ".github" / "workflows"
        workflows_dir.mkdir(parents=True)

        # Create a release.yml with template placeholders
        release_file = workflows_dir / "release.yml"
        release_file.write_text("""
name: Release
jobs:
  release:
    steps:
      - name: Create Release
        body: |
          Example:
          uses: cuioss/cuioss-organization/.github/workflows/reusable-maven-build.yml@${{ steps.sha.outputs.sha }}
""")

        # Create a regular workflow that should be updated
        regular_file = workflows_dir / "build.yml"
        regular_file.write_text("""
name: Build
jobs:
  build:
    uses: cuioss/cuioss-organization/.github/workflows/reusable-maven-build.yml@main
""")

        run_script(
            SCRIPT_PATH,
            "--version", VALID_VERSION,
            "--sha", VALID_SHA,
            "--path", str(temp_dir)
        )

        # release.yml should NOT be updated (contains template placeholders)
        release_content = release_file.read_text()
        assert "${{ steps.sha.outputs.sha }}" in release_content
        assert f"@{VALID_SHA}" not in release_content

        # Regular workflow SHOULD be updated
        regular_content = regular_file.read_text()
        assert f"@{VALID_SHA}" in regular_content
