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

    def test_requires_sha_argument(self):
        """Should fail without --sha argument."""
        result = run_script(SCRIPT_PATH, "--version", VALID_VERSION)
        assert result.returncode != 0
        assert "required" in result.stderr.lower() or "error" in result.stderr.lower()

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
