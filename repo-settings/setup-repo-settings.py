#!/usr/bin/env python3
"""Apply consistent repository settings across cuioss repositories.

Requires: gh cli (https://cli.github.com/)

Usage:
    ./setup-repo-settings.py                          # Process all repos in config.json
    ./setup-repo-settings.py --repo cui-java-tools --diff   # Show diff for single repo
    ./setup-repo-settings.py --repo cui-java-tools --apply  # Apply settings to single repo
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

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


def run_gh(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run gh command and return result."""
    return subprocess.run(
        ["gh"] + args,
        capture_output=True,
        text=True,
        check=check,
    )


def check_dependencies() -> None:
    """Check that required dependencies are available."""
    # Check gh cli
    try:
        subprocess.run(["gh", "--version"], capture_output=True, check=True)
    except FileNotFoundError:
        log_error("gh cli not found. Install: https://cli.github.com/")
        sys.exit(1)

    # Check gh auth
    result = subprocess.run(["gh", "auth", "status"], capture_output=True)
    if result.returncode != 0:
        log_error("Not authenticated with gh. Run: gh auth login")
        sys.exit(1)


def load_config(config_path: Path) -> dict:
    """Load configuration from JSON file."""
    with open(config_path) as f:
        return json.load(f)


def get_current_settings(org: str, repo: str) -> dict | None:
    """Fetch current repository settings from GitHub API."""
    result = run_gh(
        ["api", f"repos/{org}/{repo}"],
        check=False,
    )
    if result.returncode != 0:
        return None

    data = json.loads(result.stdout)
    return {
        "features": {
            "has_issues": data.get("has_issues"),
            "has_wiki": data.get("has_wiki"),
            "has_projects": data.get("has_projects"),
            "has_discussions": data.get("has_discussions"),
        },
        "merge": {
            "allow_squash_merge": data.get("allow_squash_merge"),
            "allow_merge_commit": data.get("allow_merge_commit"),
            "allow_rebase_merge": data.get("allow_rebase_merge"),
            "delete_branch_on_merge": data.get("delete_branch_on_merge"),
            "allow_auto_merge": data.get("allow_auto_merge"),
            "squash_merge_commit_title": data.get("squash_merge_commit_title"),
            "squash_merge_commit_message": data.get("squash_merge_commit_message"),
        },
    }


def get_current_security_settings(org: str, repo: str) -> dict:
    """Fetch current security settings from GitHub API."""
    security = {}

    # Private vulnerability reporting
    result = run_gh(
        ["api", f"repos/{org}/{repo}/private-vulnerability-reporting", "--jq", ".enabled"],
        check=False,
    )
    security["private_vulnerability_reporting"] = result.stdout.strip() == "true" if result.returncode == 0 else None

    # Dependabot alerts
    result = run_gh(
        ["api", f"repos/{org}/{repo}/vulnerability-alerts"],
        check=False,
    )
    security["dependabot_alerts"] = result.returncode == 204  # 204 means enabled

    # Dependabot security updates
    result = run_gh(
        ["api", f"repos/{org}/{repo}/automated-security-fixes"],
        check=False,
    )
    if result.returncode == 0:
        data = json.loads(result.stdout) if result.stdout else {}
        security["dependabot_security_updates"] = data.get("enabled", False)
    else:
        security["dependabot_security_updates"] = None

    # Secret scanning (from repo settings)
    result = run_gh(
        ["api", f"repos/{org}/{repo}", "--jq", ".security_and_analysis"],
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        try:
            sa_data = json.loads(result.stdout)
            security["secret_scanning"] = sa_data.get("secret_scanning", {}).get("status") == "enabled"
            security["secret_scanning_push_protection"] = sa_data.get("secret_scanning_push_protection", {}).get("status") == "enabled"
        except json.JSONDecodeError:
            security["secret_scanning"] = None
            security["secret_scanning_push_protection"] = None
    else:
        security["secret_scanning"] = None
        security["secret_scanning_push_protection"] = None

    return security


def compute_diff(org: str, repo: str, config: dict) -> dict:
    """Compute diff between current and desired settings."""
    current = get_current_settings(org, repo)
    current_security = get_current_security_settings(org, repo)

    if current is None:
        return {"error": f"Could not fetch settings for {org}/{repo}"}

    desired_features = config["features"]
    desired_merge = config["merge"]
    desired_security = config["security"]

    changes: list[dict] = []
    diff: dict = {
        "repository": f"{org}/{repo}",
        "changes": changes,
    }

    # Compare features
    for key, desired_value in desired_features.items():
        current_value = current["features"].get(key)
        if current_value != desired_value:
            changes.append({
                "category": "features",
                "setting": key,
                "current": current_value,
                "desired": desired_value,
            })

    # Compare merge settings
    for key, desired_value in desired_merge.items():
        current_value = current["merge"].get(key)
        if current_value != desired_value:
            changes.append({
                "category": "merge",
                "setting": key,
                "current": current_value,
                "desired": desired_value,
            })

    # Compare security settings
    for key, desired_value in desired_security.items():
        current_value = current_security.get(key)
        if current_value != desired_value:
            changes.append({
                "category": "security",
                "setting": key,
                "current": current_value,
                "desired": desired_value,
            })

    return diff


def apply_repo_settings(org: str, repo: str, config: dict) -> None:
    """Apply repository feature and merge settings."""
    log_section(f"Configuring {org}/{repo}")

    features = config["features"]
    merge = config["merge"]

    log_info("Applying repository settings...")

    args = [
        "api", "-X", "PATCH", f"repos/{org}/{repo}",
        "-F", f"has_issues={str(features['has_issues']).lower()}",
        "-F", f"has_wiki={str(features['has_wiki']).lower()}",
        "-F", f"has_projects={str(features['has_projects']).lower()}",
        "-F", f"has_discussions={str(features['has_discussions']).lower()}",
        "-F", f"allow_squash_merge={str(merge['allow_squash_merge']).lower()}",
        "-F", f"allow_merge_commit={str(merge['allow_merge_commit']).lower()}",
        "-F", f"allow_rebase_merge={str(merge['allow_rebase_merge']).lower()}",
        "-F", f"delete_branch_on_merge={str(merge['delete_branch_on_merge']).lower()}",
        "-F", f"allow_auto_merge={str(merge['allow_auto_merge']).lower()}",
        "-f", f"squash_merge_commit_title={merge['squash_merge_commit_title']}",
        "-f", f"squash_merge_commit_message={merge['squash_merge_commit_message']}",
    ]

    result = run_gh(args, check=False)
    if result.returncode == 0:
        log_info("  ✓ Repository settings applied")
    else:
        log_warn("  ⚠ Some settings may require admin access")


def apply_security_settings(org: str, repo: str, config: dict) -> None:
    """Apply security settings."""
    security = config["security"]

    log_info("Applying security settings...")

    # Private vulnerability reporting
    if security.get("private_vulnerability_reporting"):
        result = run_gh(
            ["api", "-X", "PUT", f"repos/{org}/{repo}/private-vulnerability-reporting"],
            check=False,
        )
        if result.returncode == 0:
            log_info("  ✓ Private vulnerability reporting enabled")
        else:
            log_warn("  ⚠ Could not enable vulnerability reporting")

    # Dependabot alerts
    if security.get("dependabot_alerts"):
        result = run_gh(
            ["api", "-X", "PUT", f"repos/{org}/{repo}/vulnerability-alerts"],
            check=False,
        )
        if result.returncode == 0:
            log_info("  ✓ Dependabot alerts enabled")
        else:
            log_warn("  ⚠ Could not enable Dependabot alerts")

    # Dependabot security updates
    if security.get("dependabot_security_updates"):
        result = run_gh(
            ["api", "-X", "PUT", f"repos/{org}/{repo}/automated-security-fixes"],
            check=False,
        )
        if result.returncode == 0:
            log_info("  ✓ Dependabot security updates enabled")
        else:
            log_warn("  ⚠ Could not enable Dependabot updates")

    # Secret scanning
    if security.get("secret_scanning"):
        result = run_gh(
            [
                "api", "-X", "PATCH", f"repos/{org}/{repo}",
                "--field", 'security_and_analysis={"secret_scanning":{"status":"enabled"}}',
            ],
            check=False,
        )
        if result.returncode == 0:
            log_info("  ✓ Secret scanning enabled")
        else:
            log_warn("  ⚠ Secret scanning may require GHAS")

    # Secret scanning push protection
    if security.get("secret_scanning_push_protection"):
        result = run_gh(
            [
                "api", "-X", "PATCH", f"repos/{org}/{repo}",
                "--field", 'security_and_analysis={"secret_scanning_push_protection":{"status":"enabled"}}',
            ],
            check=False,
        )
        if result.returncode == 0:
            log_info("  ✓ Push protection enabled")
        else:
            log_warn("  ⚠ Push protection may require GHAS")


def verify_settings(org: str, repo: str, config: dict) -> bool:
    """Verify applied settings match the desired configuration.

    Returns True if all settings match, False otherwise.
    """
    log_info("Verifying settings...")

    current = get_current_settings(org, repo)
    current_security = get_current_security_settings(org, repo)

    if current is None:
        log_error("  Could not fetch settings for verification")
        return False

    all_passed = True

    # Verify features
    for key, desired in config["features"].items():
        actual = current["features"].get(key)
        if actual == desired:
            log_info(f"  ✓ {key}: {actual}")
        else:
            log_error(f"  ✗ {key}: expected {desired}, got {actual}")
            all_passed = False

    # Verify merge settings
    for key, desired in config["merge"].items():
        actual = current["merge"].get(key)
        if actual == desired:
            log_info(f"  ✓ {key}: {actual}")
        else:
            log_error(f"  ✗ {key}: expected {desired}, got {actual}")
            all_passed = False

    # Verify security settings (some may not be verifiable due to permissions)
    for key, desired in config["security"].items():
        actual = current_security.get(key)
        if actual is None:
            log_warn(f"  ? {key}: could not verify (may require elevated permissions)")
        elif actual == desired:
            log_info(f"  ✓ {key}: {actual}")
        else:
            log_error(f"  ✗ {key}: expected {desired}, got {actual}")
            all_passed = False

    return all_passed


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Apply consistent repository settings across cuioss repositories.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                              Process all repos in config.json
  %(prog)s --repo cui-java-tools --diff Show diff for single repo
  %(prog)s --repo cui-java-tools --apply Apply settings to single repo
  %(prog)s custom-config.json           Use custom config file
        """,
    )
    parser.add_argument(
        "config",
        nargs="?",
        help="Path to config file (default: config.json in script directory)",
    )
    parser.add_argument(
        "--repo",
        metavar="NAME",
        help="Process a single repository instead of all in config",
    )
    parser.add_argument(
        "--diff",
        action="store_true",
        help="Output current vs desired settings as JSON (don't apply)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes (required when using --repo)",
    )
    return parser.parse_args()


def main() -> None:
    """Main entry point."""
    args = parse_args()

    # Validate argument combinations
    if args.repo and not (args.diff or args.apply):
        log_error("When using --repo, you must specify either --diff or --apply")
        sys.exit(1)

    if args.diff and args.apply:
        log_error("Cannot use --diff and --apply together")
        sys.exit(1)

    check_dependencies()

    # Determine config file path
    script_dir = Path(__file__).parent
    if args.config:
        config_path = Path(args.config)
    else:
        config_path = script_dir / "config.json"

    config = load_config(config_path)
    org = config["organization"]

    # Single repo diff mode
    if args.repo and args.diff:
        diff = compute_diff(org, args.repo, config)
        print(json.dumps(diff, indent=2))
        return

    # Single repo apply mode
    if args.repo and args.apply:
        apply_repo_settings(org, args.repo, config)
        apply_security_settings(org, args.repo, config)
        if not verify_settings(org, args.repo, config):
            log_error("Verification failed: some settings were not applied correctly")
            sys.exit(1)
        return

    # Batch mode (original behavior)
    log_info("Repository Settings Setup Script")
    print(file=sys.stderr)

    log_info(f"Organization: {org}")
    log_info(f"Config file: {config_path}")

    # Process each repository
    failed_repos: list[str] = []
    for repo in config["repositories"]:
        apply_repo_settings(org, repo, config)
        apply_security_settings(org, repo, config)
        if not verify_settings(org, repo, config):
            failed_repos.append(repo)
        print(file=sys.stderr)

    if failed_repos:
        log_error(f"Verification failed for {len(failed_repos)} repository(ies): {', '.join(failed_repos)}")
        sys.exit(1)

    log_info("All repository settings applied and verified!")


if __name__ == "__main__":
    main()
