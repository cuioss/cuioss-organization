#!/usr/bin/env python3
"""Verify and fix organization integration for cuioss repositories.

Identifies and removes:
- Repo-level secrets that should be org-level
- Duplicate community health files (inherited from cuioss/.github)

Requires: gh cli (https://cli.github.com/)

Usage:
    ./verify-org-integration.py --repo cui-java-tools --diff   # Show issues as JSON
    ./verify-org-integration.py --repo cui-java-tools --apply  # Apply fixes
    ./verify-org-integration.py --repo cui-java-tools --apply --local-path /path/to/repo
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Constants - secrets that should be at org level, not repo level
ORG_LEVEL_SECRETS = [
    "GPG_PRIVATE_KEY",
    "GPG_PASSPHRASE",
    "OSS_SONATYPE_USERNAME",
    "OSS_SONATYPE_PASSWORD",
    "PAGES_DEPLOY_TOKEN",
    "RELEASE_APP_ID",
    "RELEASE_APP_PRIVATE_KEY",
]

# Secrets that are expected at repo level
REPO_LEVEL_SECRETS = ["SONAR_TOKEN"]

# Community health files that are inherited from cuioss/.github
ORG_COMMUNITY_FILES = [
    "CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
]

ORG = "cuioss"

# ANSI colors
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
RED = "\033[0;31m"
BLUE = "\033[0;34m"
NC = "\033[0m"


def log_info(msg: str) -> None:
    print(f"{GREEN}[INFO]{NC} {msg}", file=sys.stderr)


def log_warn(msg: str) -> None:
    print(f"{YELLOW}[WARN]{NC} {msg}", file=sys.stderr)


def log_error(msg: str) -> None:
    print(f"{RED}[ERROR]{NC} {msg}", file=sys.stderr)


def log_section(msg: str) -> None:
    print(f"\n{BLUE}=== {msg} ==={NC}", file=sys.stderr)


def run_gh(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run gh command and return result."""
    return subprocess.run(
        ["gh"] + args,
        capture_output=True,
        text=True,
        check=check,
    )


def check_dependencies() -> None:
    """Check that required dependencies are available."""
    try:
        subprocess.run(["gh", "--version"], capture_output=True, check=True)
    except FileNotFoundError:
        log_error("gh cli not found. Install: https://cli.github.com/")
        sys.exit(1)

    result = subprocess.run(["gh", "auth", "status"], capture_output=True)
    if result.returncode != 0:
        log_error("Not authenticated with gh. Run: gh auth login")
        sys.exit(1)


def get_repo_secrets(org: str, repo: str) -> list[dict]:
    """Fetch repository-level secrets (names only, not values)."""
    result = run_gh(
        ["api", f"repos/{org}/{repo}/actions/secrets"],
        check=False,
    )
    if result.returncode != 0:
        return []

    data = json.loads(result.stdout)
    return data.get("secrets", [])


def delete_repo_secret(org: str, repo: str, name: str) -> bool:
    """Delete a repository-level secret."""
    result = run_gh(
        ["api", "--method", "DELETE", f"repos/{org}/{repo}/actions/secrets/{name}"],
        check=False,
    )
    return result.returncode == 0


def verify_secret_deleted(org: str, repo: str, name: str) -> bool:
    """Verify a secret has been deleted by re-checking the API."""
    secrets = get_repo_secrets(org, repo)
    secret_names = [s["name"] for s in secrets]
    return name not in secret_names


def check_duplicate_files(local_path: Path | None) -> list[str]:
    """Check for duplicate community health files in the local repo."""
    if local_path is None:
        return []

    duplicates = []
    for filename in ORG_COMMUNITY_FILES:
        file_path = local_path / filename
        if file_path.exists():
            duplicates.append(filename)

    return duplicates


def remove_duplicate_files(local_path: Path, files: list[str]) -> list[str]:
    """Remove duplicate community health files from local repo."""
    removed = []
    for filename in files:
        file_path = local_path / filename
        if file_path.exists():
            os.remove(file_path)
            removed.append(filename)
    return removed


def verify_file_removed(local_path: Path, name: str) -> bool:
    """Verify a file has been removed from the local path."""
    return not (local_path / name).exists()


def compute_diff(org: str, repo: str, local_path: Path | None) -> dict:
    """Compute the diff showing what needs to be fixed."""
    # Get current repo secrets
    secrets = get_repo_secrets(org, repo)
    secret_names = [s["name"] for s in secrets]

    # Identify secrets that should be org-level
    should_be_org_level = [name for name in secret_names if name in ORG_LEVEL_SECRETS]

    # Identify expected repo-level secrets
    expected_repo_level = [name for name in secret_names if name in REPO_LEVEL_SECRETS]

    # Check for duplicate community files
    duplicate_files = check_duplicate_files(local_path)

    result: dict = {
        "repository": f"{org}/{repo}",
        "secrets": {
            "repo_level": secret_names,
            "expected_repo_level": expected_repo_level,
            "should_be_org_level": should_be_org_level,
            "action_needed": len(should_be_org_level) > 0,
        },
        "community_files": {
            "duplicates": duplicate_files,
            "action_needed": len(duplicate_files) > 0,
        },
    }

    # Determine overall action
    if result["secrets"]["action_needed"] or result["community_files"]["action_needed"]:
        result["overall_action"] = "update"
    else:
        result["overall_action"] = "none"

    return result


def apply_fixes(
    org: str,
    repo: str,
    local_path: Path | None,
    secrets_to_delete: list[str] | None = None,
    files_to_remove: list[str] | None = None,
) -> dict:
    """Apply fixes: delete secrets and remove files."""
    log_section(f"Applying fixes to {org}/{repo}")

    result: dict = {
        "repository": f"{org}/{repo}",
        "secrets_deleted": [],
        "files_removed": [],
        "verification": {
            "secrets_verified": True,
            "files_verified": True,
            "all_passed": True,
        },
        "success": True,
    }

    # Delete secrets if specified
    if secrets_to_delete:
        log_info("Deleting repo-level secrets that should be org-level...")
        for name in secrets_to_delete:
            if delete_repo_secret(org, repo, name):
                log_info(f"  Deleted: {name}")
                result["secrets_deleted"].append(name)
            else:
                log_error(f"  Failed to delete: {name}")
                result["success"] = False

    # Remove files if specified and local_path provided
    if files_to_remove and local_path:
        log_info("Removing duplicate community health files...")
        removed = remove_duplicate_files(local_path, files_to_remove)
        result["files_removed"] = removed
        for name in removed:
            log_info(f"  Removed: {name}")

    # Verification
    log_info("Verifying changes...")

    # Verify secrets deleted
    for name in result["secrets_deleted"]:
        if verify_secret_deleted(org, repo, name):
            log_info(f"  ✓ {name} verified deleted")
        else:
            log_error(f"  ✗ {name} still exists")
            result["verification"]["secrets_verified"] = False
            result["verification"]["all_passed"] = False

    # Verify files removed
    if local_path:
        for name in result["files_removed"]:
            if verify_file_removed(local_path, name):
                log_info(f"  ✓ {name} verified removed")
            else:
                log_error(f"  ✗ {name} still exists")
                result["verification"]["files_verified"] = False
                result["verification"]["all_passed"] = False

    if not result["verification"]["all_passed"]:
        result["success"] = False

    return result


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Verify and fix organization integration for cuioss repositories.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --repo cui-java-tools --diff        Show issues as JSON (read-only)
  %(prog)s --repo cui-java-tools --apply       Apply fixes (delete secrets, remove files)
  %(prog)s --repo cui-java-tools --apply --local-path /path/to/repo
        """,
    )
    parser.add_argument(
        "--repo",
        metavar="NAME",
        required=True,
        help="Repository name (without org prefix)",
    )
    parser.add_argument(
        "--diff",
        action="store_true",
        help="Show issues as JSON (read-only)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply fixes",
    )
    parser.add_argument(
        "--local-path",
        metavar="PATH",
        help="Local repository path (required for file removal in apply mode)",
    )
    parser.add_argument(
        "--delete-secrets",
        metavar="SECRETS",
        help="Comma-separated list of secrets to delete (for apply mode)",
    )
    parser.add_argument(
        "--remove-files",
        metavar="FILES",
        help="Comma-separated list of files to remove (for apply mode)",
    )
    return parser.parse_args()


def main() -> None:
    """Main entry point."""
    args = parse_args()

    # Validate argument combinations
    if not (args.diff or args.apply):
        log_error("You must specify either --diff or --apply")
        sys.exit(1)

    if args.diff and args.apply:
        log_error("Cannot use --diff and --apply together")
        sys.exit(1)

    check_dependencies()

    local_path = Path(args.local_path) if args.local_path else None

    # Diff mode
    if args.diff:
        diff = compute_diff(ORG, args.repo, local_path)
        print(json.dumps(diff, indent=2))
        return

    # Apply mode
    if args.apply:
        # Parse secrets and files to process
        secrets_to_delete = None
        if args.delete_secrets:
            secrets_to_delete = [s.strip() for s in args.delete_secrets.split(",") if s.strip()]

        files_to_remove = None
        if args.remove_files:
            files_to_remove = [f.strip() for f in args.remove_files.split(",") if f.strip()]

        # If no specific items provided, compute what needs to be done
        if secrets_to_delete is None and files_to_remove is None:
            diff = compute_diff(ORG, args.repo, local_path)
            secrets_to_delete = diff["secrets"]["should_be_org_level"]
            files_to_remove = diff["community_files"]["duplicates"]

        result = apply_fixes(
            ORG,
            args.repo,
            local_path,
            secrets_to_delete,
            files_to_remove,
        )
        print(json.dumps(result, indent=2))

        if not result["verification"]["all_passed"]:
            sys.exit(1)


if __name__ == "__main__":
    main()
