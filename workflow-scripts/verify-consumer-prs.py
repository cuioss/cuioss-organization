#!/usr/bin/env python3
"""Verify auto-merge status of consumer repo PRs after batch creation.

After all consumer PRs are created with `gh pr merge --auto` enabled,
this script polls them in batch and reports final status.

Usage:
    ./verify-consumer-prs.py --results-file results.json --timeout 300
"""

import argparse
import json
import os
import subprocess
import sys
import time


def run_gh(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run gh CLI command."""
    return subprocess.run(
        ["gh"] + args, capture_output=True, text=True, check=check
    )


def write_summary(text: str) -> None:
    """Append markdown text to GitHub Actions step summary."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as f:
        f.write(text + "\n")


def check_pr_status(pr_url: str) -> dict:
    """Check current status of a PR.

    Returns dict with:
        state: str (MERGED, OPEN, CLOSED)
        merged: bool
        checks_passed: bool | None
        head_branch: str | None
        full_repo: str | None
        build_skipped: bool (True when build check exists but was skipped)
    """
    result = run_gh(
        [
            "pr",
            "view",
            pr_url,
            "--json",
            "state,mergedAt,statusCheckRollup,headRefName,headRepository",
        ],
        check=False,
    )

    if result.returncode != 0:
        return {
            "state": "UNKNOWN", "merged": False, "checks_passed": None,
            "head_branch": None, "full_repo": None, "build_skipped": False,
        }

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {
            "state": "UNKNOWN", "merged": False, "checks_passed": None,
            "head_branch": None, "full_repo": None, "build_skipped": False,
        }

    state = data.get("state", "UNKNOWN")
    merged = bool(data.get("mergedAt"))
    head_branch = data.get("headRefName")
    head_repo = data.get("headRepository", {}) or {}
    repo_owner = head_repo.get("owner", {}).get("login", "")
    repo_name = head_repo.get("name", "")
    full_repo = f"{repo_owner}/{repo_name}" if repo_owner and repo_name else None

    # Evaluate check status
    checks = data.get("statusCheckRollup", []) or []
    build_skipped = False
    if not checks:
        checks_passed = None
    else:
        failed = any(
            c.get("conclusion") in ("FAILURE", "CANCELLED", "TIMED_OUT")
            for c in checks
        )
        pending = any(c.get("status") in ("QUEUED", "IN_PROGRESS", "PENDING") for c in checks)
        # Detect if the build check was skipped (parent job reports SKIPPED
        # when the fork-detection `if:` condition prevents the build from running)
        build_skipped = any(
            c.get("name", "") == "build" and c.get("conclusion") == "SKIPPED"
            for c in checks
        )
        if failed:
            checks_passed = False
        elif pending:
            checks_passed = None
        else:
            checks_passed = True

    return {
        "state": state, "merged": merged, "checks_passed": checks_passed,
        "head_branch": head_branch, "full_repo": full_repo,
        "build_skipped": build_skipped,
    }


def check_has_push_event_build(full_repo: str, branch: str) -> bool:
    """Check if a push-event Maven Build run exists for the given branch.

    The caller maven.yml skips the build job on pull_request events for
    internal branches (fork-detection if-condition), relying on the push
    event to run the actual build.  When GitHub drops the push event, the
    required check runs are never created and the PR gets stuck.

    Returns True if at least one push-event Maven Build run exists.
    """
    result = run_gh(
        [
            "run", "list",
            "--repo", full_repo,
            "--branch", branch,
            "--json", "event,name",
            "-q", '.[] | select(.name == "Maven Build" and .event == "push")',
        ],
        check=False,
    )
    # If the jq filter matched anything, stdout is non-empty
    return bool(result.stdout.strip())


def verify_prs(results_file: str, timeout: int, poll_interval: int = 30) -> list[dict]:
    """Poll all PRs until resolved or timeout.

    Args:
        results_file: Path to JSON file with PR results from update-consumer-repo.
        timeout: Maximum seconds to wait.
        poll_interval: Seconds between poll rounds.

    Returns:
        List of dicts with repo, pr_url, and final_status.
    """
    with open(results_file, encoding="utf-8") as f:
        results = json.loads(f.read())

    # Filter to only PRs that have auto-merge enabled
    prs = [
        r
        for r in results
        if r.get("status") == "pr_auto_merge_enabled" and r.get("pr_url")
    ]

    if not prs:
        print("No PRs with auto-merge enabled to verify.")
        return []

    print(f"Verifying {len(prs)} PR(s) with timeout {timeout}s...")
    elapsed = 0
    final_results = []

    while elapsed < timeout and prs:
        remaining = []
        for pr in prs:
            status = check_pr_status(pr["pr_url"])

            if status["merged"]:
                final_results.append(
                    {"repo": pr["repo"], "pr_url": pr["pr_url"], "final_status": "merged"}
                )
                print(f"  {pr['repo']}: merged")
            elif status["checks_passed"] is False:
                final_results.append(
                    {"repo": pr["repo"], "pr_url": pr["pr_url"], "final_status": "failed"}
                )
                print(f"  {pr['repo']}: checks failed")
            elif status["state"] == "CLOSED":
                final_results.append(
                    {"repo": pr["repo"], "pr_url": pr["pr_url"], "final_status": "closed"}
                )
                print(f"  {pr['repo']}: closed")
            else:
                remaining.append(pr)
                print(f"  {pr['repo']}: pending ({elapsed}s/{timeout}s)")

        prs = remaining
        if prs and elapsed < timeout:
            time.sleep(poll_interval)
            elapsed += poll_interval

    # Classify remaining PRs: stuck (missing push event) vs genuinely pending
    for pr in prs:
        status = check_pr_status(pr["pr_url"])
        if (
            status["build_skipped"]
            and status["full_repo"]
            and status["head_branch"]
            and not check_has_push_event_build(status["full_repo"], status["head_branch"])
        ):
            final_results.append(
                {"repo": pr["repo"], "pr_url": pr["pr_url"], "final_status": "stuck_no_push"}
            )
            print(f"  {pr['repo']}: stuck — GitHub dropped the push event")
        else:
            final_results.append(
                {"repo": pr["repo"], "pr_url": pr["pr_url"], "final_status": "pending"}
            )

    return final_results


def print_summary(final_results: list[dict]) -> None:
    """Print summary table to GitHub Actions step summary."""
    if not final_results:
        return

    status_icons = {
        "merged": ":white_check_mark: Merged",
        "pending": ":hourglass: Auto-merge pending",
        "stuck_no_push": ":warning: Stuck — no push event",
        "failed": ":x: Failed",
        "closed": ":x: Closed",
    }

    lines = [
        "### Consumer PR Verification",
        "",
        "| Repository | Status | PR |",
        "|---|---|---|",
    ]

    stuck_prs = []
    for r in final_results:
        icon = status_icons.get(r["final_status"], r["final_status"])
        pr_link = f"[PR]({r['pr_url']})" if r.get("pr_url") else "-"
        lines.append(f"| {r['repo']} | {icon} | {pr_link} |")
        if r["final_status"] == "stuck_no_push":
            stuck_prs.append(r)

    if stuck_prs:
        lines.append("")
        lines.append(
            "> **Stuck PRs need manual intervention.** GitHub dropped the "
            "`push` event so the required build checks were never created. "
            "Open each link and trigger the build: "
            "**Actions → Maven Build → Run workflow** → select the PR branch."
        )
        for r in stuck_prs:
            lines.append(f"> - [{r['repo']}]({r['pr_url']})")

    summary = "\n".join(lines)
    print(summary)
    write_summary(summary)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify auto-merge status of consumer repo PRs"
    )
    parser.add_argument(
        "--results-file",
        required=True,
        help="Path to JSON results file from update-consumer-repo runs",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Maximum seconds to wait for PRs to merge (default: 300)",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=30,
        help="Seconds between poll rounds (default: 30)",
    )

    args = parser.parse_args()

    if not os.path.exists(args.results_file):
        print(f"Error: results file not found: {args.results_file}", file=sys.stderr)
        return 1

    final_results = verify_prs(args.results_file, args.timeout, args.poll_interval)
    print_summary(final_results)

    # Return non-zero if any PR failed
    failed = any(r["final_status"] == "failed" for r in final_results)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
