#!/usr/bin/env python3
"""Update a Maven dependency version in a consumer repository.

Supports two scopes:
- parent: Updates the <parent> POM version
- dependency: Updates <dependency> or <dependencyManagement> versions,
  including property references

Usage:
    ./update-consumer-dependency.py \
        --repo cui-java-tools \
        --group-id de.cuioss \
        --artifact-id cui-java-parent \
        --new-version 1.4.4 \
        --scope parent
"""

import argparse
import re
import tempfile
from pathlib import Path

from consumer_update_utils import (
    STATUS_ERROR,
    STATUS_NO_CHANGES,
    clone_consumer_repo,
    close_stale_prs,
    configure_git_author,
    create_pr_and_auto_merge,
    exit_with_result,
    make_result,
    read_auto_merge_config,
    run_git,
)

# Regex for matching parent POM block
# Matches <parent>...<groupId>G</groupId>...<artifactId>A</artifactId>...<version>V</version>...</parent>
PARENT_PATTERN = re.compile(
    r"(<parent>\s*"
    r"<groupId>{group_id}</groupId>\s*"
    r"<artifactId>{artifact_id}</artifactId>\s*"
    r"<version>)([^<]+)(</version>)",
    re.DOTALL,
)

# Regex for matching dependency blocks
# Matches <dependency>...<groupId>G</groupId>...<artifactId>A</artifactId>...<version>V</version>...</dependency>
DEPENDENCY_PATTERN = re.compile(
    r"(<dependency>\s*"
    r"<groupId>{group_id}</groupId>\s*"
    r"<artifactId>{artifact_id}</artifactId>\s*"
    r"(?:<[^v][^<]*</[^<]*>\s*)*"  # skip optional elements like <type>, <scope>
    r"<version>)([^<]+)(</version>)",
    re.DOTALL,
)

# Pattern for property reference: ${property.name}
PROPERTY_REF_PATTERN = re.compile(r"^\$\{(.+)\}$")

# Pattern for matching a property definition in <properties>
PROPERTY_DEF_PATTERN = re.compile(
    r"(<{prop_name}>)([^<]+)(</{prop_name}>)"
)


def _build_parent_pattern(group_id: str, artifact_id: str) -> re.Pattern:
    """Build a regex for matching the parent POM block."""
    return re.compile(
        r"(<parent>\s*"
        rf"<groupId>{re.escape(group_id)}</groupId>\s*"
        rf"<artifactId>{re.escape(artifact_id)}</artifactId>\s*"
        r"<version>)([^<]+)(</version>)",
        re.DOTALL,
    )


def _build_dependency_pattern(group_id: str, artifact_id: str) -> re.Pattern:
    """Build a regex for matching a dependency block."""
    return re.compile(
        r"(<dependency>\s*"
        rf"<groupId>{re.escape(group_id)}</groupId>\s*"
        rf"<artifactId>{re.escape(artifact_id)}</artifactId>\s*"
        r"(?:<[^v][^<]*</[^<]*>\s*)*"
        r"<version>)([^<]+)(</version>)",
        re.DOTALL,
    )


def _build_property_pattern(prop_name: str) -> re.Pattern:
    """Build a regex for matching a property definition."""
    return re.compile(
        rf"(<{re.escape(prop_name)}>)([^<]+)(</{re.escape(prop_name)}>)"
    )


def update_parent_version(
    pom_content: str, group_id: str, artifact_id: str, new_version: str
) -> tuple[str, str | None]:
    """Update the parent POM version.

    Returns:
        Tuple of (updated_content, old_version) or (original_content, None) if no match.
    """
    pattern = _build_parent_pattern(group_id, artifact_id)
    match = pattern.search(pom_content)
    if not match:
        return pom_content, None

    old_version = match.group(2).strip()
    if old_version == new_version:
        return pom_content, None

    # Skip SNAPSHOT versions
    if "SNAPSHOT" in old_version:
        print(f"Skipping SNAPSHOT version: {old_version}")
        return pom_content, None

    updated = pattern.sub(rf"\g<1>{new_version}\3", pom_content)
    return updated, old_version


def update_dependency_version(
    pom_content: str,
    group_id: str,
    artifact_id: str,
    new_version: str,
    all_pom_contents: dict[str, str] | None = None,
) -> tuple[str, str | None, dict[str, str]]:
    """Update a dependency version, handling property references.

    Args:
        pom_content: Content of the POM file being checked for the dependency declaration.
        group_id: Maven groupId to match.
        artifact_id: Maven artifactId to match.
        new_version: New version to set.
        all_pom_contents: Dict of path->content for all POMs (for property resolution).

    Returns:
        Tuple of (updated_content, old_version, updated_poms) where updated_poms
        maps file paths to their updated content (for property changes in other files).
    """
    updated_poms: dict[str, str] = {}
    pattern = _build_dependency_pattern(group_id, artifact_id)
    match = pattern.search(pom_content)
    if not match:
        return pom_content, None, updated_poms

    old_version_raw = match.group(2).strip()

    # Check for property reference
    prop_match = PROPERTY_REF_PATTERN.match(old_version_raw)
    if prop_match:
        prop_name = prop_match.group(1)
        return _update_property_version(
            pom_content, prop_name, new_version, all_pom_contents
        )

    # Direct version replacement
    if old_version_raw == new_version:
        return pom_content, None, updated_poms

    if "SNAPSHOT" in old_version_raw:
        print(f"Skipping SNAPSHOT version: {old_version_raw}")
        return pom_content, None, updated_poms

    updated = pattern.sub(rf"\g<1>{new_version}\3", pom_content)
    return updated, old_version_raw, updated_poms


def _update_property_version(
    pom_content: str,
    prop_name: str,
    new_version: str,
    all_pom_contents: dict[str, str] | None,
) -> tuple[str, str | None, dict[str, str]]:
    """Update a Maven property value across all POM files.

    Returns:
        Tuple of (updated_pom_content, old_version, updated_poms).
    """
    updated_poms: dict[str, str] = {}
    prop_pattern = _build_property_pattern(prop_name)

    # Search in the current POM first
    prop_match = prop_pattern.search(pom_content)
    if prop_match:
        old_version = prop_match.group(2).strip()
        if old_version == new_version:
            return pom_content, None, updated_poms
        if "SNAPSHOT" in old_version:
            print(f"Skipping SNAPSHOT property value: {old_version}")
            return pom_content, None, updated_poms
        updated = prop_pattern.sub(rf"\g<1>{new_version}\3", pom_content)
        return updated, old_version, updated_poms

    # Search in other POM files
    if all_pom_contents:
        for path, content in all_pom_contents.items():
            prop_match = prop_pattern.search(content)
            if prop_match:
                old_version = prop_match.group(2).strip()
                if old_version == new_version:
                    return pom_content, None, updated_poms
                if "SNAPSHOT" in old_version:
                    print(f"Skipping SNAPSHOT property value: {old_version}")
                    return pom_content, None, updated_poms
                updated_poms[path] = prop_pattern.sub(
                    rf"\g<1>{new_version}\3", content
                )
                return pom_content, old_version, updated_poms

    print(f"::warning::Property {prop_name} not found in any POM file")
    return pom_content, None, updated_poms


def find_pom_files(repo_dir: Path) -> list[Path]:
    """Find all pom.xml files in a repository."""
    return sorted(repo_dir.rglob("pom.xml"))


def _make_branch_name(artifact_id: str, new_version: str) -> str:
    """Create a branch name for the dependency update."""
    return f"chore/update-{artifact_id}-{new_version}"


def _make_branch_prefix(artifact_id: str) -> str:
    """Create a branch prefix for finding stale PRs."""
    return f"chore/update-{artifact_id}-"


def update_consumer_dependency(
    org: str,
    repo: str,
    group_id: str,
    artifact_id: str,
    new_version: str,
    scope: str,
) -> dict:
    """Update a Maven dependency in a consumer repository.

    Returns a result dict with status, pr_url, and error fields.
    """
    full_repo = f"{org}/{repo}"
    branch = _make_branch_name(artifact_id, new_version)
    branch_prefix = _make_branch_prefix(artifact_id)

    print(f"::group::Processing {full_repo} ({scope}: {group_id}:{artifact_id})")

    with tempfile.TemporaryDirectory() as tmp:
        repo_dir = Path(tmp) / repo

        # Clone repository
        print(f"Cloning {full_repo}...")
        result = clone_consumer_repo(full_repo, repo_dir)
        if result.returncode != 0:
            print(f"::warning::Failed to clone {full_repo}: {result.stderr}")
            print("::endgroup::")
            return make_result(
                STATUS_ERROR, error=f"Clone failed: {result.stderr.strip()}"
            )

        # Read auto-merge config
        auto_merge_config = read_auto_merge_config(repo_dir)

        # Find POM files
        pom_files = find_pom_files(repo_dir)
        if not pom_files:
            print(f"::warning::No pom.xml found in {repo}")
            print("::endgroup::")
            return make_result(STATUS_ERROR, error="No pom.xml found")

        # Load all POM contents for property resolution
        all_pom_contents: dict[str, str] = {}
        for pom_file in pom_files:
            all_pom_contents[str(pom_file)] = pom_file.read_text(encoding="utf-8")

        old_version = None
        changed_files: list[Path] = []

        if scope == "parent":
            # Only check root pom.xml for parent
            root_pom = repo_dir / "pom.xml"
            if not root_pom.exists():
                print(f"::warning::No root pom.xml in {repo}")
                print("::endgroup::")
                return make_result(STATUS_ERROR, error="No root pom.xml")

            content = root_pom.read_text(encoding="utf-8")
            updated, old_ver = update_parent_version(
                content, group_id, artifact_id, new_version
            )
            if old_ver:
                old_version = old_ver
                root_pom.write_text(updated, encoding="utf-8")
                changed_files.append(root_pom)

        elif scope == "dependency":
            # Check all POM files for the dependency
            for pom_file in pom_files:
                content = all_pom_contents[str(pom_file)]
                updated, old_ver, extra_poms = update_dependency_version(
                    content, group_id, artifact_id, new_version, all_pom_contents
                )
                if old_ver:
                    old_version = old_ver
                    if updated != content:
                        pom_file.write_text(updated, encoding="utf-8")
                        changed_files.append(pom_file)
                    # Write any property updates in other POM files
                    for extra_path, extra_content in extra_poms.items():
                        extra_file = Path(extra_path)
                        extra_file.write_text(extra_content, encoding="utf-8")
                        if extra_file not in changed_files:
                            changed_files.append(extra_file)
                    break  # Found the dependency declaration

        # Check for actual changes
        diff_result = run_git(["diff", "--quiet"], cwd=repo_dir, check=False)
        if diff_result.returncode == 0:
            print(f"No changes needed for {group_id}:{artifact_id}")
            close_stale_prs(
                full_repo,
                branch_prefix,
                f"Closing: {repo} already uses {artifact_id} {new_version}.",
            )
            print("::endgroup::")
            return make_result(STATUS_NO_CHANGES)

        print(
            f"Updating {group_id}:{artifact_id} from {old_version} to {new_version}"
        )

        # Create branch and commit
        run_git(["checkout", "-b", branch], cwd=repo_dir)
        configure_git_author(repo_dir)

        for f in changed_files:
            run_git(["add", str(f)], cwd=repo_dir)
        # Also stage any unstaged changes (property updates)
        run_git(["add", "-u"], cwd=repo_dir, check=False)

        commit_msg = (
            f"chore: update {artifact_id} from {old_version} to {new_version}"
        )
        run_git(["commit", "-m", commit_msg], cwd=repo_dir)

        # Create PR
        pr_body = (
            f"Updates `{group_id}:{artifact_id}` from `{old_version}` to `{new_version}`\n\n"
            "This PR was automatically created by the cuioss-organization release workflow."
        )
        pr_result = create_pr_and_auto_merge(
            full_repo,
            repo_dir,
            branch,
            commit_msg,
            pr_body,
            auto_merge_config,
        )

        # Close stale PRs from previous versions
        if pr_result["pr_url"]:
            close_stale_prs(
                full_repo,
                branch_prefix,
                f"Superseded by update to {new_version}: {pr_result['pr_url']}",
                exclude_branch=branch,
            )

        print("::endgroup::")
        return pr_result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Update a Maven dependency version in a consumer repository"
    )
    parser.add_argument("--org", default="cuioss", help="GitHub organization")
    parser.add_argument("--repo", required=True, help="Repository name")
    parser.add_argument(
        "--group-id", required=True, help="Maven groupId (e.g., de.cuioss)"
    )
    parser.add_argument(
        "--artifact-id",
        required=True,
        help="Maven artifactId (e.g., cui-java-parent)",
    )
    parser.add_argument(
        "--new-version", required=True, help="New version (e.g., 1.4.4)"
    )
    parser.add_argument(
        "--scope",
        required=True,
        choices=["parent", "dependency"],
        help="Update scope: 'parent' for parent POM, 'dependency' for dependency/property",
    )

    args = parser.parse_args()

    result = update_consumer_dependency(
        args.org,
        args.repo,
        args.group_id,
        args.artifact_id,
        args.new_version,
        args.scope,
    )

    exit_with_result(result)


if __name__ == "__main__":
    main()
