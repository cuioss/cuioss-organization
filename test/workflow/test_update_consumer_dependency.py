"""Tests for update-consumer-dependency.py."""

import importlib.util
import sys
from pathlib import Path

# Add parent to path to access conftest
sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT, run_script

# Add workflow-scripts to path
sys.path.insert(0, str(PROJECT_ROOT / "workflow-scripts"))

SCRIPT_PATH = PROJECT_ROOT / "workflow-scripts/update-consumer-dependency.py"


def _load_module():
    """Load update-consumer-dependency.py as a module for unit testing."""
    spec = importlib.util.spec_from_file_location(
        "update_consumer_dependency", SCRIPT_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- Sample POM content ---

PARENT_POM = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
    <modelVersion>4.0.0</modelVersion>
    <parent>
        <groupId>de.cuioss</groupId>
        <artifactId>cui-java-parent</artifactId>
        <version>1.4.2</version>
        <relativePath/>
    </parent>
    <artifactId>cui-java-tools</artifactId>
    <version>1.0.0-SNAPSHOT</version>
</project>
"""

PARENT_POM_SNAPSHOT = """\
<?xml version="1.0" encoding="UTF-8"?>
<project>
    <parent>
        <groupId>de.cuioss</groupId>
        <artifactId>cui-java-parent</artifactId>
        <version>1.5.0-SNAPSHOT</version>
    </parent>
</project>
"""

BOM_POM_WITH_PROPERTY = """\
<?xml version="1.0" encoding="UTF-8"?>
<project>
    <properties>
        <version.cui.test.juli.logger>2.1.2</version.cui.test.juli.logger>
        <version.cui.http>1.5.0</version.cui.http>
    </properties>
    <dependencyManagement>
        <dependencies>
            <dependency>
                <groupId>de.cuioss.test</groupId>
                <artifactId>cui-test-juli-logger</artifactId>
                <version>${version.cui.test.juli.logger}</version>
            </dependency>
        </dependencies>
    </dependencyManagement>
</project>
"""

BOM_POM_SNAPSHOT_PROPERTY = """\
<?xml version="1.0" encoding="UTF-8"?>
<project>
    <properties>
        <version.cui.http>1.6.0-SNAPSHOT</version.cui.http>
    </properties>
</project>
"""


class TestParentVersionUpdate:
    """Test update_parent_version function."""

    def test_updates_matching_parent(self):
        mod = _load_module()
        updated, old_ver = mod.update_parent_version(
            PARENT_POM, "de.cuioss", "cui-java-parent", "1.4.4"
        )
        assert old_ver == "1.4.2"
        assert "<version>1.4.4</version>" in updated
        assert "<version>1.4.2</version>" not in updated

    def test_already_current_version(self):
        mod = _load_module()
        updated, old_ver = mod.update_parent_version(
            PARENT_POM, "de.cuioss", "cui-java-parent", "1.4.2"
        )
        assert old_ver is None
        assert updated == PARENT_POM

    def test_different_artifact_no_match(self):
        mod = _load_module()
        updated, old_ver = mod.update_parent_version(
            PARENT_POM, "de.cuioss", "cui-other-parent", "1.4.4"
        )
        assert old_ver is None
        assert updated == PARENT_POM

    def test_different_group_no_match(self):
        mod = _load_module()
        updated, old_ver = mod.update_parent_version(
            PARENT_POM, "org.other", "cui-java-parent", "1.4.4"
        )
        assert old_ver is None
        assert updated == PARENT_POM

    def test_skips_snapshot_version(self):
        mod = _load_module()
        updated, old_ver = mod.update_parent_version(
            PARENT_POM_SNAPSHOT, "de.cuioss", "cui-java-parent", "1.5.0"
        )
        assert old_ver is None
        assert updated == PARENT_POM_SNAPSHOT

    def test_preserves_formatting(self):
        mod = _load_module()
        # Verify surrounding XML structure is preserved
        updated, old_ver = mod.update_parent_version(
            PARENT_POM, "de.cuioss", "cui-java-parent", "1.4.4"
        )
        assert "<relativePath/>" in updated
        assert "<artifactId>cui-java-tools</artifactId>" in updated
        assert "<version>1.0.0-SNAPSHOT</version>" in updated


class TestUpdatePropertyVersion:
    """Test update_property_version function (direct property update)."""

    def test_updates_named_property(self):
        mod = _load_module()
        all_poms = {"/repo/bom/pom.xml": BOM_POM_WITH_PROPERTY}
        old_ver, updated = mod.update_property_version(
            all_poms, "version.cui.test.juli.logger", "2.2.0"
        )
        assert old_ver == "2.1.2"
        assert "/repo/bom/pom.xml" in updated
        assert "<version.cui.test.juli.logger>2.2.0</version.cui.test.juli.logger>" in updated["/repo/bom/pom.xml"]
        # Other property should be unchanged
        assert "<version.cui.http>1.5.0</version.cui.http>" in updated["/repo/bom/pom.xml"]

    def test_already_current_version(self):
        mod = _load_module()
        all_poms = {"/repo/bom/pom.xml": BOM_POM_WITH_PROPERTY}
        old_ver, updated = mod.update_property_version(
            all_poms, "version.cui.test.juli.logger", "2.1.2"
        )
        assert old_ver is None
        assert updated == {}

    def test_property_not_found(self):
        mod = _load_module()
        all_poms = {"/repo/pom.xml": "<project><properties></properties></project>"}
        old_ver, updated = mod.update_property_version(
            all_poms, "version.nonexistent", "1.0.0"
        )
        assert old_ver is None
        assert updated == {}

    def test_skips_snapshot_property(self):
        mod = _load_module()
        all_poms = {"/repo/pom.xml": BOM_POM_SNAPSHOT_PROPERTY}
        old_ver, updated = mod.update_property_version(
            all_poms, "version.cui.http", "1.6.0"
        )
        assert old_ver is None
        assert updated == {}

    def test_searches_multiple_poms(self):
        """Property might be in a child module, not the root POM."""
        mod = _load_module()
        root_pom = "<project><properties></properties></project>"
        all_poms = {
            "/repo/pom.xml": root_pom,
            "/repo/bom/pom.xml": BOM_POM_WITH_PROPERTY,
        }
        old_ver, updated = mod.update_property_version(
            all_poms, "version.cui.test.juli.logger", "2.2.0"
        )
        assert old_ver == "2.1.2"
        assert "/repo/bom/pom.xml" in updated
        assert "/repo/pom.xml" not in updated

    def test_updates_different_property_in_same_pom(self):
        """Can target a different property in the same POM."""
        mod = _load_module()
        all_poms = {"/repo/bom/pom.xml": BOM_POM_WITH_PROPERTY}
        old_ver, updated = mod.update_property_version(
            all_poms, "version.cui.http", "1.6.0"
        )
        assert old_ver == "1.5.0"
        assert "<version.cui.http>1.6.0</version.cui.http>" in updated["/repo/bom/pom.xml"]
        # Other property should be unchanged
        assert "<version.cui.test.juli.logger>2.1.2</version.cui.test.juli.logger>" in updated["/repo/bom/pom.xml"]


class TestVersionValidation:
    """Test _validate_version function."""

    def test_accepts_simple_version(self):
        mod = _load_module()
        assert mod._validate_version("1.4.4") is True

    def test_accepts_snapshot(self):
        mod = _load_module()
        assert mod._validate_version("1.5.0-SNAPSHOT") is True

    def test_accepts_qualifier(self):
        mod = _load_module()
        assert mod._validate_version("2.0.0-beta.1") is True

    def test_rejects_xml_injection(self):
        mod = _load_module()
        assert mod._validate_version("1.0</version><evil>") is False

    def test_rejects_backreference(self):
        mod = _load_module()
        assert mod._validate_version(r"\g<0>") is False

    def test_rejects_empty(self):
        mod = _load_module()
        assert mod._validate_version("") is False

    def test_parent_update_rejects_bad_version(self):
        mod = _load_module()
        updated, old_ver = mod.update_parent_version(
            PARENT_POM, "de.cuioss", "cui-java-parent", "1.0</version><x>"
        )
        assert old_ver is None
        assert updated == PARENT_POM

    def test_property_update_rejects_bad_version(self):
        mod = _load_module()
        all_poms = {"/repo/bom/pom.xml": BOM_POM_WITH_PROPERTY}
        old_ver, updated = mod.update_property_version(
            all_poms, "version.cui.test.juli.logger", "2.0</bad>"
        )
        assert old_ver is None
        assert updated == {}


class TestBranchNaming:
    """Test branch name generation."""

    def test_branch_name(self):
        mod = _load_module()
        assert mod._make_branch_name("cui-java-parent", "1.4.4") == "chore/update-cui-java-parent-1.4.4"

    def test_branch_prefix(self):
        mod = _load_module()
        assert mod._make_branch_prefix("cui-java-parent") == "chore/update-cui-java-parent-"


class TestArgumentValidation:
    """Test command line argument validation."""

    def test_requires_repo(self):
        result = run_script(
            SCRIPT_PATH,
            "--group-id", "de.cuioss",
            "--artifact-id", "cui-java-parent",
            "--new-version", "1.4.4",
            "--scope", "parent",
        )
        assert result.returncode != 0
        assert "required" in result.stderr.lower() or "--repo" in result.stderr

    def test_requires_group_id(self):
        result = run_script(
            SCRIPT_PATH,
            "--repo", "test",
            "--artifact-id", "cui-java-parent",
            "--new-version", "1.4.4",
            "--scope", "parent",
        )
        assert result.returncode != 0

    def test_requires_artifact_id(self):
        result = run_script(
            SCRIPT_PATH,
            "--repo", "test",
            "--group-id", "de.cuioss",
            "--new-version", "1.4.4",
            "--scope", "parent",
        )
        assert result.returncode != 0

    def test_requires_new_version(self):
        result = run_script(
            SCRIPT_PATH,
            "--repo", "test",
            "--group-id", "de.cuioss",
            "--artifact-id", "cui-java-parent",
            "--scope", "parent",
        )
        assert result.returncode != 0

    def test_requires_scope(self):
        result = run_script(
            SCRIPT_PATH,
            "--repo", "test",
            "--group-id", "de.cuioss",
            "--artifact-id", "cui-java-parent",
            "--new-version", "1.4.4",
        )
        assert result.returncode != 0

    def test_rejects_invalid_scope(self):
        result = run_script(
            SCRIPT_PATH,
            "--repo", "test",
            "--group-id", "de.cuioss",
            "--artifact-id", "cui-java-parent",
            "--new-version", "1.4.4",
            "--scope", "invalid",
        )
        assert result.returncode != 0

    def test_accepts_valid_parent_scope(self):
        result = run_script(
            SCRIPT_PATH,
            "--repo", "nonexistent-repo-12345",
            "--group-id", "de.cuioss",
            "--artifact-id", "cui-java-parent",
            "--new-version", "1.4.4",
            "--scope", "parent",
        )
        # Will fail on clone, but should pass argument validation
        assert "required" not in result.stderr.lower()

    def test_accepts_valid_dependency_scope(self):
        result = run_script(
            SCRIPT_PATH,
            "--repo", "nonexistent-repo-12345",
            "--group-id", "de.cuioss",
            "--artifact-id", "cui-http",
            "--new-version", "1.3.0",
            "--scope", "dependency",
            "--version-property", "version.cui.http",
        )
        assert "required" not in result.stderr.lower()


class TestFindPomFiles:
    """Test find_pom_files function."""

    def test_finds_root_pom(self, temp_dir):
        mod = _load_module()
        (temp_dir / "pom.xml").write_text("<project/>")
        result = mod.find_pom_files(temp_dir)
        assert len(result) == 1

    def test_finds_multi_module_poms(self, temp_dir):
        mod = _load_module()
        (temp_dir / "pom.xml").write_text("<project/>")
        child = temp_dir / "child-module"
        child.mkdir()
        (child / "pom.xml").write_text("<project/>")
        result = mod.find_pom_files(temp_dir)
        assert len(result) == 2

    def test_empty_dir(self, temp_dir):
        mod = _load_module()
        result = mod.find_pom_files(temp_dir)
        assert result == []
