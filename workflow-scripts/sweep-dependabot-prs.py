#!/usr/bin/env python3
"""Merge Dependabot PRs that the auto-merge workflow marked eligible.

reusable-dependabot-auto-merge.yml runs under GITHUB_TOKEN and can only label.
GitHub does not start workflow runs for events created by GITHUB_TOKEN, so under
a required merge queue that token cannot land a PR: either its queue entry never
receives merge_group check runs and is dropped at check_response_timeout_minutes,
or the auto-merge request never converts into a queue entry at all.

This sweeper runs on a schedule under the cuioss-release-bot App identity, whose
events do start workflow runs, and performs the merge for every labelled PR that
GitHub reports as ready. On a merge-queue repo `gh pr merge` enqueues; elsewhere
it merges directly.

Usage:
    ./sweep-dependabot-prs.py --dry-run
    ./sweep-dependabot-prs.py
"""

import argparse
import json
import os
import subprocess
import sys

DEFAULT_LABEL = "automerge"
DEFAULT_OWNER = "cuioss"
DEFAULT_AUTHOR = "app/dependabot"

# GitHub's own readiness verdict. Anything else means a required check is
# missing, failing, or the PR is blocked -- never force it.
READY_MERGE_STATE = "CLEAN"


def run_gh(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a gh CLI command without raising on failure."""
    return subprocess.run(
        ["gh"] + args, capture_output=True, text=True, check=False
    )


def write_summary(text: str) -> None:
    """Append markdown text to the GitHub Actions step summary."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as f:
        f.write(text + "\n")


def find_candidates(owner: str, label: str, author: str, limit: int) -> list[dict]:
    """Find open, labelled Dependabot PRs across the organization.

    The label is applied only by reusable-dependabot-auto-merge.yml, so its
    presence is the opt-in signal -- no repository list to keep in sync.
    """
    result = run_gh(
        [
            "search", "prs",
            "--owner", owner,
            "--label", label,
            "--author", author,
            "--state", "open",
            "--limit", str(limit),
            "--json", "number,repository,url,title",
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh search prs failed: {result.stderr.strip()}")
    if not result.stdout.strip():
        return []
    candidates = []
    for item in json.loads(result.stdout):
        repo = (item.get("repository") or {}).get("nameWithOwner")
        if not repo or not item.get("number"):
            continue
        candidates.append(
            {
                "repo": repo,
                "number": item["number"],
                "url": item.get("url", ""),
                "title": item.get("title", ""),
            }
        )
    return candidates


def read_pr_state(repo: str, number: int) -> dict | None:
    """Read the merge-readiness fields GitHub computes for a PR."""
    result = run_gh(
        [
            "pr", "view", str(number),
            "--repo", repo,
            "--json", "isDraft,mergeable,mergeStateStatus,isInMergeQueue,state",
        ]
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def classify(state: dict | None) -> str:
    """Decide what to do with a PR from its merge-readiness fields.

    Returns one of: merge, queued, draft, not-open, not-ready, unknown.
    """
    if state is None:
        return "unknown"
    if state.get("state") != "OPEN":
        return "not-open"
    if state.get("isInMergeQueue"):
        return "queued"
    if state.get("isDraft"):
        return "draft"
    if state.get("mergeable") != "MERGEABLE":
        return "not-ready"
    if state.get("mergeStateStatus") != READY_MERGE_STATE:
        return "not-ready"
    return "merge"


def merge_pr(repo: str, number: int) -> tuple[bool, str]:
    """Merge (or enqueue) a single PR. Returns (ok, detail)."""
    result = run_gh(["pr", "merge", str(number), "--repo", repo, "--squash"])
    if result.returncode == 0:
        return True, (result.stdout or result.stderr).strip()
    return False, (result.stderr or result.stdout).strip()


def sweep(owner: str, label: str, author: str, limit: int, dry_run: bool) -> list[dict]:
    """Process every labelled Dependabot PR and report per-PR outcomes."""
    outcomes = []
    for pr in find_candidates(owner, label, author, limit):
        action = classify(read_pr_state(pr["repo"], pr["number"]))
        outcome = {**pr, "action": action, "detail": ""}
        if action == "merge":
            if dry_run:
                outcome["action"] = "would-merge"
            else:
                ok, detail = merge_pr(pr["repo"], pr["number"])
                outcome["action"] = "merged" if ok else "merge-failed"
                outcome["detail"] = detail
        outcomes.append(outcome)
    return outcomes


def print_summary(outcomes: list[dict]) -> None:
    """Print a per-PR table to stdout and the Actions step summary."""
    if not outcomes:
        message = "### Dependabot sweep\n\nNo labelled Dependabot PRs found."
        print(message)
        write_summary(message)
        return

    icons = {
        "merged": ":white_check_mark: merged/enqueued",
        "would-merge": ":mag: would merge (dry run)",
        "merge-failed": ":x: merge failed",
        "queued": ":hourglass: already in merge queue",
        "not-ready": ":hourglass: checks not green yet",
        "draft": ":pencil: draft",
        "not-open": ":heavy_minus_sign: no longer open",
        "unknown": ":question: could not read PR state",
    }
    lines = [
        "### Dependabot sweep",
        "",
        "| PR | Outcome | Detail |",
        "|---|---|---|",
    ]
    for o in outcomes:
        pr_link = f"[{o['repo']}#{o['number']}]({o['url']})" if o["url"] else f"{o['repo']}#{o['number']}"
        lines.append(f"| {pr_link} | {icons.get(o['action'], o['action'])} | {o['detail']} |")
    summary = "\n".join(lines)
    print(summary)
    write_summary(summary)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge Dependabot PRs marked eligible for auto-merge"
    )
    parser.add_argument("--owner", default=DEFAULT_OWNER, help="GitHub organization")
    parser.add_argument("--label", default=DEFAULT_LABEL, help="Eligibility label")
    parser.add_argument("--author", default=DEFAULT_AUTHOR, help="PR author to sweep")
    parser.add_argument("--limit", type=int, default=100, help="Maximum PRs to inspect")
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would be merged"
    )
    args = parser.parse_args()

    try:
        outcomes = sweep(args.owner, args.label, args.author, args.limit, args.dry_run)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print_summary(outcomes)
    return 1 if any(o["action"] == "merge-failed" for o in outcomes) else 0


if __name__ == "__main__":
    sys.exit(main())
