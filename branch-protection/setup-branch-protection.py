#!/usr/bin/env python3
"""Setup branch protection rulesets across cuioss repositories.

Requires: gh cli (https://cli.github.com/)

Usage:
    ./setup-branch-protection.py                              # Process all repos in config.json
    ./setup-branch-protection.py --repo cui-java-tools --diff # Show diff for single repo
    ./setup-branch-protection.py --repo cui-java-tools --apply # Apply ruleset to single repo
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
NC = "\033[0m"


def log_info(msg: str) -> None:
    print(f"{GREEN}[INFO]{NC} {msg}", file=sys.stderr)


def log_warn(msg: str) -> None:
    print(f"{YELLOW}[WARN]{NC} {msg}", file=sys.stderr)


def log_error(msg: str) -> None:
    print(f"{RED}[ERROR]{NC} {msg}", file=sys.stderr)


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


def build_ruleset_payload(
    config: dict,
    bypass_actor_id: str,
    required_checks_override: list[str] | None = None,
    required_reviews_override: int | None = None,
) -> dict:
    """Build ruleset JSON payload.

    Args:
        config: Configuration dictionary
        bypass_actor_id: GitHub App ID for bypass actor
        required_checks_override: Override for required status checks (None = use config)
        required_reviews_override: Override for required reviews count (None = use config)
    """
    ruleset = config["ruleset"]
    rules_config = ruleset["rules"]

    # Determine required checks
    if required_checks_override is not None:
        required_checks = required_checks_override
    else:
        required_checks = rules_config["require_status_checks"]["required_checks"]

    # Determine required reviews
    if required_reviews_override is not None:
        required_reviews = required_reviews_override
    else:
        required_reviews = rules_config["require_pull_request"]["required_approving_review_count"]

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
        ],
    }

    # Add pull_request rule only if reviews > 0
    if required_reviews > 0:
        payload["rules"].append({
            "type": "pull_request",
            "parameters": {
                "required_approving_review_count": required_reviews,
                "dismiss_stale_reviews_on_push": rules_config["require_pull_request"]["dismiss_stale_reviews_on_push"],
                "require_code_owner_review": rules_config["require_pull_request"].get("require_code_owner_review", False),
                "require_last_push_approval": rules_config["require_pull_request"]["require_last_push_approval"],
                "required_review_thread_resolution": rules_config["require_pull_request"].get("required_review_thread_resolution", False),
            },
        })

    # Add status checks rule only if there are required checks
    if required_checks:
        payload["rules"].append({
            "type": "required_status_checks",
            "parameters": {
                "strict_required_status_checks_policy": rules_config["require_status_checks"]["strict_required_status_checks_policy"],
                "required_status_checks": [
                    {"context": check}
                    for check in required_checks
                ],
            },
        })

    return payload


def get_existing_ruleset(org: str, repo: str, ruleset_name: str) -> dict | None:
    """Get existing ruleset by name."""
    result = run_gh(
        ["api", f"repos/{org}/{repo}/rulesets"],
        check=False,
    )
    if result.returncode != 0:
        return None

    rulesets = json.loads(result.stdout)
    for ruleset in rulesets:
        if ruleset.get("name") == ruleset_name:
            # Fetch full ruleset details
            ruleset_id = ruleset["id"]
            detail_result = run_gh(
                ["api", f"repos/{org}/{repo}/rulesets/{ruleset_id}"],
                check=False,
            )
            if detail_result.returncode == 0:
                return json.loads(detail_result.stdout)
    return None


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


def normalize_ruleset_for_comparison(ruleset: dict) -> dict:
    """Extract comparable fields from a ruleset."""
    return {
        "name": ruleset.get("name"),
        "enforcement": ruleset.get("enforcement"),
        "conditions": ruleset.get("conditions"),
        "bypass_actors": [
            {
                "actor_id": actor.get("actor_id"),
                "actor_type": actor.get("actor_type"),
                "bypass_mode": actor.get("bypass_mode"),
            }
            for actor in ruleset.get("bypass_actors", [])
        ],
        "rules": ruleset.get("rules", []),
    }


def compute_diff(
    org: str,
    repo: str,
    config: dict,
    bypass_actor_id: str,
    required_checks_override: list[str] | None = None,
    required_reviews_override: int | None = None,
) -> dict:
    """Compute diff between current and desired ruleset."""
    ruleset_name = config["ruleset"]["name"]
    existing = get_existing_ruleset(org, repo, ruleset_name)
    desired = build_ruleset_payload(config, bypass_actor_id, required_checks_override, required_reviews_override)

    diff = {
        "repository": f"{org}/{repo}",
        "ruleset_name": ruleset_name,
        "exists": existing is not None,
    }

    if existing is None:
        diff["action"] = "create"
        diff["desired"] = desired
    else:
        # Normalize both for comparison
        current_normalized = normalize_ruleset_for_comparison(existing)
        desired_normalized = normalize_ruleset_for_comparison(desired)

        if current_normalized == desired_normalized:
            diff["action"] = "none"
            diff["message"] = "Ruleset already matches desired configuration"
        else:
            diff["action"] = "update"
            diff["current"] = current_normalized
            diff["desired"] = desired_normalized
            diff["ruleset_id"] = existing.get("id")

    return diff


def apply_ruleset(
    org: str,
    repo: str,
    config: dict,
    bypass_actor_id: str,
    required_checks_override: list[str] | None = None,
    required_reviews_override: int | None = None,
) -> None:
    """Create or update ruleset for a repository."""
    ruleset_name = config["ruleset"]["name"]
    log_info(f"Processing {org}/{repo}...")

    payload = build_ruleset_payload(config, bypass_actor_id, required_checks_override, required_reviews_override)
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


def verify_ruleset(
    org: str,
    repo: str,
    config: dict,
    bypass_actor_id: str,
    required_checks_override: list[str] | None = None,
    required_reviews_override: int | None = None,
) -> bool:
    """Verify applied ruleset matches the desired configuration.

    Returns True if the ruleset matches, False otherwise.
    """
    log_info("Verifying ruleset...")

    ruleset_name = config["ruleset"]["name"]
    existing = get_existing_ruleset(org, repo, ruleset_name)

    if existing is None:
        log_error("  Could not fetch ruleset for verification")
        return False

    desired = build_ruleset_payload(config, bypass_actor_id, required_checks_override, required_reviews_override)

    # Normalize both for comparison
    current_normalized = normalize_ruleset_for_comparison(existing)
    desired_normalized = normalize_ruleset_for_comparison(desired)

    all_passed = True

    # Compare top-level fields
    for key in ["name", "enforcement"]:
        current_val = current_normalized.get(key)
        desired_val = desired_normalized.get(key)
        if current_val == desired_val:
            log_info(f"  ✓ {key}: {current_val}")
        else:
            log_error(f"  ✗ {key}: expected {desired_val}, got {current_val}")
            all_passed = False

    # Compare conditions
    if current_normalized.get("conditions") == desired_normalized.get("conditions"):
        log_info("  ✓ conditions: match")
    else:
        log_error("  ✗ conditions: mismatch")
        all_passed = False

    # Compare bypass actors
    if current_normalized.get("bypass_actors") == desired_normalized.get("bypass_actors"):
        log_info("  ✓ bypass_actors: match")
    else:
        log_error("  ✗ bypass_actors: mismatch")
        all_passed = False

    # Compare rules
    current_rules = sorted(current_normalized.get("rules", []), key=lambda r: r.get("type", ""))
    desired_rules = sorted(desired_normalized.get("rules", []), key=lambda r: r.get("type", ""))

    if current_rules == desired_rules:
        log_info("  ✓ rules: match")
    else:
        log_error("  ✗ rules: mismatch")
        log_error(f"    expected: {desired_rules}")
        log_error(f"    got: {current_rules}")
        all_passed = False

    return all_passed


def list_workflow_checks(org: str, repo: str) -> list[dict]:
    """List available workflow job names from recent runs."""
    # Get recent workflow runs
    result = run_gh(
        ["api", f"repos/{org}/{repo}/actions/runs", "--jq", ".workflow_runs[:10]"],
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []

    runs = json.loads(result.stdout)
    checks = {}

    for run in runs:
        run_id = run.get("id")
        workflow_name = run.get("name", "Unknown")

        # Get jobs for this run
        jobs_result = run_gh(
            ["api", f"repos/{org}/{repo}/actions/runs/{run_id}/jobs", "--jq", ".jobs"],
            check=False,
        )
        if jobs_result.returncode == 0 and jobs_result.stdout.strip():
            jobs = json.loads(jobs_result.stdout)
            for job in jobs:
                job_name = job.get("name")
                if job_name and job_name not in checks:
                    checks[job_name] = {
                        "name": job_name,
                        "workflow": workflow_name,
                        "conclusion": job.get("conclusion"),
                    }

    return list(checks.values())


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Setup branch protection rulesets across cuioss repositories.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                Process all repos in config.json
  %(prog)s --repo cui-java-tools --diff   Show diff for single repo
  %(prog)s --repo cui-java-tools --apply  Apply ruleset to single repo
  %(prog)s --repo my-repo --list-checks   List available workflow checks
  %(prog)s --repo my-repo --apply --required-checks verify --required-reviews 0
  %(prog)s custom-config.json             Use custom config file
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
        help="Output current vs desired ruleset as JSON (don't apply)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes (required when using --repo)",
    )
    parser.add_argument(
        "--list-checks",
        action="store_true",
        help="List available workflow checks for the repository (JSON output)",
    )
    parser.add_argument(
        "--required-checks",
        metavar="CHECKS",
        help="Comma-separated list of required status checks (empty string for none)",
    )
    parser.add_argument(
        "--required-reviews",
        type=int,
        choices=[0, 1, 2],
        metavar="N",
        help="Number of required approving reviews (0, 1, or 2)",
    )
    return parser.parse_args()


def get_bypass_actor_id(org: str, bypass_actor_name: str, config_app_id: str | None = None, interactive: bool = True) -> str:
    """Get bypass actor ID, optionally prompting user."""
    log_info(f"Looking up App ID for {bypass_actor_name}...")
    app_id = get_app_id(org, bypass_actor_name)

    if not app_id:
        # Try fallback from config
        if config_app_id:
            log_info(f"Using App ID from config: {config_app_id}")
            return config_app_id
        elif interactive:
            log_warn("Could not find app ID automatically.")
            app_id = input(f"Enter the App ID for {bypass_actor_name}: ").strip()
        else:
            log_error(f"Could not find app ID for {bypass_actor_name}")
            sys.exit(1)

    log_info(f"Using App ID: {app_id}")
    return app_id


def main() -> None:
    """Main entry point."""
    args = parse_args()

    # Validate argument combinations
    if args.repo and not (args.diff or args.apply or args.list_checks):
        log_error("When using --repo, you must specify --diff, --apply, or --list-checks")
        sys.exit(1)

    if sum([args.diff, args.apply, args.list_checks]) > 1:
        log_error("Cannot use --diff, --apply, and --list-checks together")
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
    bypass_actor_name = config["bypass_actor"]["name"]
    config_app_id = config["bypass_actor"].get("app_id")

    # Parse overrides
    required_checks_override = None
    if args.required_checks is not None:
        if args.required_checks == "":
            required_checks_override = []
        else:
            required_checks_override = [c.strip() for c in args.required_checks.split(",") if c.strip()]

    required_reviews_override = args.required_reviews

    # List checks mode
    if args.repo and args.list_checks:
        checks = list_workflow_checks(org, args.repo)
        print(json.dumps(checks, indent=2))
        return

    # Get bypass actor ID (non-interactive for diff mode)
    interactive = not args.diff
    bypass_actor_id = get_bypass_actor_id(org, bypass_actor_name, config_app_id=config_app_id, interactive=interactive)

    # Single repo diff mode
    if args.repo and args.diff:
        diff = compute_diff(org, args.repo, config, bypass_actor_id, required_checks_override, required_reviews_override)
        print(json.dumps(diff, indent=2))
        return

    # Single repo apply mode
    if args.repo and args.apply:
        apply_ruleset(org, args.repo, config, bypass_actor_id, required_checks_override, required_reviews_override)
        if not verify_ruleset(org, args.repo, config, bypass_actor_id, required_checks_override, required_reviews_override):
            log_error("Verification failed: ruleset was not applied correctly")
            sys.exit(1)
        return

    # Batch mode (original behavior)
    log_info("Branch Protection Setup Script")
    log_info(f"Config: {config_path}")
    print(file=sys.stderr)

    log_info(f"Organization: {org}")
    log_info(f"Bypass Actor: {bypass_actor_name} ({config['bypass_actor']['type']})")
    log_info(f"Ruleset: {config['ruleset']['name']} targeting '{config['ruleset']['branch_pattern']}'")
    print(file=sys.stderr)

    # Process each repository
    for repo in config["repositories"]:
        apply_ruleset(org, repo, config, bypass_actor_id)

    print(file=sys.stderr)
    log_info("All rulesets applied successfully!")


if __name__ == "__main__":
    main()
