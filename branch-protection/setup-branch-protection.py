#!/usr/bin/env python3
"""Setup branch protection rulesets across cuioss repositories.

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
NC = "\033[0m"


def log_info(msg: str) -> None:
    print(f"{GREEN}[INFO]{NC} {msg}")


def log_warn(msg: str) -> None:
    print(f"{YELLOW}[WARN]{NC} {msg}")


def log_error(msg: str) -> None:
    print(f"{RED}[ERROR]{NC} {msg}")


def run_gh(args: list[str], check: bool = True, input_data: str | None = None) -> subprocess.CompletedProcess:
    """Run gh command and return result."""
    return subprocess.run(
        ["gh"] + args,
        capture_output=True,
        text=True,
        check=check,
        input=input_data,
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


def get_app_id(org: str, bypass_actor_name: str) -> str | None:
    """Get GitHub App ID by name."""
    result = run_gh(
        [
            "api", f"orgs/{org}/installations",
            "--jq", f'.installations[] | select(.app_slug == "{bypass_actor_name}") | .app_id',
        ],
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        # Return first matching app_id
        return result.stdout.strip().split("\n")[0]
    return None


def build_ruleset_payload(config: dict, bypass_actor_id: str) -> dict:
    """Build ruleset JSON payload."""
    ruleset = config["ruleset"]
    rules_config = ruleset["rules"]

    payload = {
        "name": ruleset["name"],
        "target": "branch",
        "enforcement": ruleset["enforcement"],
        "conditions": {
            "ref_name": {
                "include": [f"refs/heads/{ruleset['branch_pattern']}"],
                "exclude": [],
            }
        },
        "bypass_actors": [
            {
                "actor_id": int(bypass_actor_id),
                "actor_type": "Integration",
                "bypass_mode": "always",
            }
        ],
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": rules_config["require_pull_request"]["required_approving_review_count"],
                    "dismiss_stale_reviews_on_push": rules_config["require_pull_request"]["dismiss_stale_reviews_on_push"],
                    "require_last_push_approval": rules_config["require_pull_request"]["require_last_push_approval"],
                },
            },
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": rules_config["require_status_checks"]["strict_required_status_checks_policy"],
                    "required_status_checks": [
                        {"context": check}
                        for check in rules_config["require_status_checks"]["required_checks"]
                    ],
                },
            },
        ],
    }

    return payload


def get_existing_ruleset_id(org: str, repo: str, ruleset_name: str) -> str | None:
    """Check if ruleset exists and return its ID."""
    result = run_gh(
        [
            "api", f"repos/{org}/{repo}/rulesets",
            "--jq", f'.[] | select(.name == "{ruleset_name}") | .id',
        ],
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return None


def apply_ruleset(org: str, repo: str, config: dict, bypass_actor_id: str) -> None:
    """Create or update ruleset for a repository."""
    ruleset_name = config["ruleset"]["name"]
    log_info(f"Processing {org}/{repo}...")

    payload = build_ruleset_payload(config, bypass_actor_id)
    payload_json = json.dumps(payload)

    existing_id = get_existing_ruleset_id(org, repo, ruleset_name)

    if existing_id:
        log_info(f"  Updating existing ruleset (ID: {existing_id})")
        result = run_gh(
            ["api", "-X", "PUT", f"repos/{org}/{repo}/rulesets/{existing_id}", "--input", "-"],
            check=False,
            input_data=payload_json,
        )
    else:
        log_info("  Creating new ruleset")
        result = run_gh(
            ["api", "-X", "POST", f"repos/{org}/{repo}/rulesets", "--input", "-"],
            check=False,
            input_data=payload_json,
        )

    if result.returncode == 0:
        log_info("  ✓ Done")
    else:
        log_warn(f"  ⚠ Failed: {result.stderr}")


def main() -> None:
    """Main entry point."""
    log_info("Branch Protection Setup Script")

    check_dependencies()

    # Determine config file path
    script_dir = Path(__file__).parent
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else script_dir / "config.json"

    log_info(f"Config: {config_path}")
    print()

    config = load_config(config_path)
    org = config["organization"]
    bypass_actor_name = config["bypass_actor"]["name"]
    ruleset = config["ruleset"]

    log_info(f"Organization: {org}")
    log_info(f"Bypass Actor: {bypass_actor_name} ({config['bypass_actor']['type']})")
    log_info(f"Ruleset: {ruleset['name']} targeting '{ruleset['branch_pattern']}'")

    # Get bypass actor ID
    log_info(f"Looking up App ID for {bypass_actor_name}...")
    app_id = get_app_id(org, bypass_actor_name)

    if not app_id:
        log_warn("Could not find app ID automatically.")
        app_id = input(f"Enter the App ID for {bypass_actor_name}: ").strip()

    log_info(f"Using App ID: {app_id}")
    print()

    # Process each repository
    for repo in config["repositories"]:
        apply_ruleset(org, repo, config, app_id)

    print()
    log_info("All rulesets applied successfully!")


if __name__ == "__main__":
    main()
