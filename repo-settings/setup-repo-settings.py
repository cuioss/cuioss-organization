#!/usr/bin/env python3
"""Apply consistent repository settings across cuioss repositories.

Requires: gh cli (https://cli.github.com/)
"""

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
    print(f"{GREEN}[INFO]{NC} {msg}")


def log_warn(msg: str) -> None:
    print(f"{YELLOW}[WARN]{NC} {msg}")


def log_error(msg: str) -> None:
    print(f"{RED}[ERROR]{NC} {msg}")


def log_section(msg: str) -> None:
    print(f"\n{BLUE}=== {msg} ==={NC}")


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


def apply_repo_settings(org: str, repo: str, config: dict) -> None:
    """Apply repository feature and merge settings."""
    log_section(f"Configuring {org}/{repo}")

    features = config["features"]
    merge = config["merge"]

    log_info("Applying repository settings...")

    args = [
        "api", "-X", "PATCH", f"repos/{org}/{repo}",
        "-f", f"has_issues={str(features['has_issues']).lower()}",
        "-f", f"has_wiki={str(features['has_wiki']).lower()}",
        "-f", f"has_projects={str(features['has_projects']).lower()}",
        "-f", f"has_discussions={str(features['has_discussions']).lower()}",
        "-f", f"allow_squash_merge={str(merge['allow_squash_merge']).lower()}",
        "-f", f"allow_merge_commit={str(merge['allow_merge_commit']).lower()}",
        "-f", f"allow_rebase_merge={str(merge['allow_rebase_merge']).lower()}",
        "-f", f"delete_branch_on_merge={str(merge['delete_branch_on_merge']).lower()}",
        "-f", f"allow_auto_merge={str(merge['allow_auto_merge']).lower()}",
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


def verify_settings(org: str, repo: str) -> None:
    """Verify applied settings."""
    log_info("Verifying settings...")

    # Check vulnerability reporting
    result = run_gh(
        ["api", f"repos/{org}/{repo}/private-vulnerability-reporting", "--jq", ".enabled"],
        check=False,
    )
    vuln_status = result.stdout.strip() if result.returncode == 0 else "unknown"
    if vuln_status == "true":
        log_info("  ✓ Private vulnerability reporting: enabled")
    else:
        log_warn(f"  ⚠ Private vulnerability reporting: {vuln_status}")

    # Check repo settings
    result = run_gh(
        ["api", f"repos/{org}/{repo}", "--jq", "{has_issues, has_wiki, delete_branch_on_merge}"],
        check=False,
    )
    if result.returncode == 0:
        log_info(f"  Current settings: {result.stdout.strip()}")


def main() -> None:
    """Main entry point."""
    log_info("Repository Settings Setup Script")
    print()

    check_dependencies()

    # Determine config file path
    script_dir = Path(__file__).parent
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else script_dir / "config.json"

    config = load_config(config_path)
    org = config["organization"]

    log_info(f"Organization: {org}")
    log_info(f"Config file: {config_path}")

    # Process each repository
    for repo in config["repositories"]:
        apply_repo_settings(org, repo, config)
        apply_security_settings(org, repo, config)
        verify_settings(org, repo)
        print()

    log_info("All repository settings applied!")


if __name__ == "__main__":
    main()
