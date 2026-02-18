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

DEPENDENCY_POM_DIRECT = """\
<?xml version="1.0" encoding="UTF-8"?>
<project>
    <dependencies>
        <dependency>
            <groupId>de.cuioss</groupId>
            <artifactId>cui-http</artifactId>
            <version>1.2.3</version>
        </dependency>
    </dependencies>
</project>
"""

DEPENDENCY_POM_PROPERTY = """\
<?xml version="1.0" encoding="UTF-8"?>
<project>
    <properties>
        <cui-http.version>1.2.3</cui-http.version>
    </properties>
    <dependencies>
        <dependency>
            <groupId>de.cuioss</groupId>
            <artifactId>cui-http</artifactId>
            <version>${cui-http.version}</version>
        </dependency>
    </dependencies>
</project>
"""

DEPENDENCY_POM_MGMT = """\
<?xml version="1.0" encoding="UTF-8"?>
<project>
    <dependencyManagement>
        <dependencies>
            <dependency>
                <groupId>de.cuioss</groupId>
                <artifactId>cui-test-value-objects</artifactId>
                <version>2.0.0</version>
                <scope>test</scope>
            </dependency>
        </dependencies>
    </dependencyManagement>
</project>
"""

NO_MATCH_POM = """\
<?xml version="1.0" encoding="UTF-8"?>
<project>
    <dependencies>
        <dependency>
            <groupId>org.other</groupId>
            <artifactId>other-lib</artifactId>
            <version>3.0.0</version>
        </dependency>
    </dependencies>
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


class TestDependencyVersionUpdate:
    """Test update_dependency_version function."""

    def test_direct_version_update(self):
        mod = _load_module()
        updated, old_ver, extra = mod.update_dependency_version(
            DEPENDENCY_POM_DIRECT, "de.cuioss", "cui-http", "1.3.0"
        )
        assert old_ver == "1.2.3"
        assert "<version>1.3.0</version>" in updated
        assert extra == {}

    def test_direct_version_already_current(self):
        mod = _load_module()
        updated, old_ver, extra = mod.update_dependency_version(
            DEPENDENCY_POM_DIRECT, "de.cuioss", "cui-http", "1.2.3"
        )
        assert old_ver is None
        assert updated == DEPENDENCY_POM_DIRECT

    def test_property_reference_update(self):
        mod = _load_module()
        updated, old_ver, extra = mod.update_dependency_version(
            DEPENDENCY_POM_PROPERTY, "de.cuioss", "cui-http", "1.3.0"
        )
        assert old_ver == "1.2.3"
        assert "<cui-http.version>1.3.0</cui-http.version>" in updated
        # The dependency version should still be the property reference
        assert "${cui-http.version}" in updated

    def test_property_reference_already_current(self):
        mod = _load_module()
        updated, old_ver, extra = mod.update_dependency_version(
            DEPENDENCY_POM_PROPERTY, "de.cuioss", "cui-http", "1.2.3"
        )
        assert old_ver is None

    def test_dependency_management_with_scope(self):
        mod = _load_module()
        updated, old_ver, extra = mod.update_dependency_version(
            DEPENDENCY_POM_MGMT, "de.cuioss", "cui-test-value-objects", "2.1.0"
        )
        assert old_ver == "2.0.0"
        assert "<version>2.1.0</version>" in updated
        # Scope should be preserved
        assert "<scope>test</scope>" in updated

    def test_no_matching_dependency(self):
        mod = _load_module()
        updated, old_ver, extra = mod.update_dependency_version(
            NO_MATCH_POM, "de.cuioss", "cui-http", "1.3.0"
        )
        assert old_ver is None
        assert updated == NO_MATCH_POM

    def test_skips_snapshot_direct_version(self):
        snapshot_pom = DEPENDENCY_POM_DIRECT.replace("1.2.3", "1.3.0-SNAPSHOT")
        mod = _load_module()
        updated, old_ver, extra = mod.update_dependency_version(
            snapshot_pom, "de.cuioss", "cui-http", "1.3.0"
        )
        assert old_ver is None

    def test_skips_snapshot_property_value(self):
        snapshot_pom = DEPENDENCY_POM_PROPERTY.replace("1.2.3", "1.3.0-SNAPSHOT")
        mod = _load_module()
        updated, old_ver, extra = mod.update_dependency_version(
            snapshot_pom, "de.cuioss", "cui-http", "1.3.0"
        )
        assert old_ver is None

    def test_property_in_different_pom(self):
        """Property defined in parent POM, dependency in child POM."""
        mod = _load_module()
        child_pom = """\
<project>
    <dependencies>
        <dependency>
            <groupId>de.cuioss</groupId>
            <artifactId>cui-http</artifactId>
            <version>${cui-http.version}</version>
        </dependency>
    </dependencies>
</project>
"""
        parent_pom = """\
<project>
    <properties>
        <cui-http.version>1.2.3</cui-http.version>
    </properties>
</project>
"""
        all_poms = {"/repo/pom.xml": parent_pom}
        updated, old_ver, extra = mod.update_dependency_version(
            child_pom, "de.cuioss", "cui-http", "1.3.0", all_pom_contents=all_poms
        )
        assert old_ver == "1.2.3"
        # The child POM should not be changed (property is in parent)
        assert updated == child_pom
        # The parent POM should be updated
        assert "/repo/pom.xml" in extra
        assert "<cui-http.version>1.3.0</cui-http.version>" in extra["/repo/pom.xml"]


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
