#!/usr/bin/env python3
"""Update a Maven dependency version in a consumer repository.

Supports two scopes:
- parent: Updates the <parent> POM version directly
- dependency: Updates a named version property across all POM files
  (requires --version-property)

Usage:
    # Parent scope: updates <parent><version> in root pom.xml
    ./update-consumer-dependency.py \
        --repo cui-java-tools \
        --group-id de.cuioss \
        --artifact-id cui-java-parent \
        --new-version 1.4.4 \
        --scope parent

    # Dependency scope: updates a named property across all POM files
    ./update-consumer-dependency.py \
        --repo cuioss-parent-pom \
        --group-id de.cuioss.test \
        --artifact-id cui-test-juli-logger \
        --new-version 2.2.0 \
        --scope dependency \
        --version-property version.cui.test.juli.logger
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

# Safe characters for Maven version strings (semver + qualifiers)
_SAFE_VERSION_PATTERN = re.compile(r"^[a-zA-Z0-9._-]+$")


def _validate_version(version: str) -> bool:
    """Validate that a version string contains only safe characters.

    Prevents XML injection via regex replacement strings.
    """
    return bool(_SAFE_VERSION_PATTERN.match(version))


def _build_parent_pattern(group_id: str, artifact_id: str) -> re.Pattern:
    """Build a regex for matching the parent POM block."""
    return re.compile(
        r"(<parent>\s*"
        rf"<groupId>{re.escape(group_id)}</groupId>\s*"
        rf"<artifactId>{re.escape(artifact_id)}</artifactId>\s*"
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
    if not _validate_version(new_version):
        print(f"::error::Invalid version string: {new_version}")
        return pom_content, None
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


def update_property_version(
    all_pom_contents: dict[str, str],
    prop_name: str,
    new_version: str,
) -> tuple[str | None, dict[str, str]]:
    """Update a named version property across all POM files.

    Searches all POM files for a property definition matching the given name
    and updates its value to the new version.

    Returns:
        Tuple of (old_version, updated_poms) where updated_poms maps
        file paths to their updated content.
    """
    if not _validate_version(new_version):
        print(f"::error::Invalid version string: {new_version}")
        return None, {}
    prop_pattern = _build_property_pattern(prop_name)
    for path, content in all_pom_contents.items():
        prop_match = prop_pattern.search(content)
        if prop_match:
            old_version = prop_match.group(2).strip()
            if old_version == new_version:
                return None, {}
            if "SNAPSHOT" in old_version:
                print(f"Skipping SNAPSHOT property value: {old_version}")
                return None, {}
            updated = prop_pattern.sub(rf"\g<1>{new_version}\3", content)
            return old_version, {path: updated}

    print(f"::warning::Property {prop_name} not found in any POM file")
    return None, {}


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
    version_property: str | None = None,
) -> dict:
    """Update a Maven dependency in a consumer repository.

    Args:
        version_property: Property name for scope=dependency (required for
            that scope). The named property is updated directly across all
            POM files.

    Returns a result dict with status, pr_url, and error fields.
    """
    full_repo = f"{org}/{repo}"
    branch = _make_branch_name(artifact_id, new_version)
    branch_prefix = _make_branch_prefix(artifact_id)

    print(f"::group::Processing {full_repo} ({scope}: {group_id}:{artifact_id})")

    with tempfile.TemporaryDirectory() as tmp:
        repo_dir = Path(tmp) / Path(repo).name

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
            if not version_property:
                print("::error::--version-property is required for scope=dependency")
                print("::endgroup::")
                return make_result(
                    STATUS_ERROR,
                    error="--version-property is required for scope=dependency",
                )

            old_ver, extra_poms = update_property_version(
                all_pom_contents, version_property, new_version
            )
            if old_ver:
                old_version = old_ver
                for extra_path, extra_content in extra_poms.items():
                    extra_file = Path(extra_path)
                    extra_file.write_text(extra_content, encoding="utf-8")
                    if extra_file not in changed_files:
                        changed_files.append(extra_file)

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
    parser.add_argument(
        "--version-property",
        default=None,
        help="Version property name (required for --scope dependency). "
        "Example: version.cui.test.juli.logger",
    )

    args = parser.parse_args()

    result = update_consumer_dependency(
        args.org,
        args.repo,
        args.group_id,
        args.artifact_id,
        args.new_version,
        args.scope,
        version_property=args.version_property,
    )

    exit_with_result(result)


if __name__ == "__main__":
    main()
