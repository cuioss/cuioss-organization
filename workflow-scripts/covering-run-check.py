#!/usr/bin/env python3
"""Decide whether a gate-skipped push run must build its own commit.

``gate`` (in ``reusable-maven-build.yml``) skips a push-triggered build when
an open PR already covers the same commit, on the assumption that the PR's
own ``pull_request`` run will build it. That run can be delayed several
minutes - GitHub has been observed to create it well after the push run
starts - or never appear at all: the triggering event can be silently
dropped, and the PR can also close before its run starts. Either way,
nothing then builds the commit.

A bare poll-then-fail guard (the original #243 design) turned that into a
*permanently* red required check: re-running the same push re-evaluates
``gate``, which reaches the same "skip" verdict and never builds the commit
either, so only a brand-new commit could clear it (#279).

This script waits for the covering run, exactly as that guard did, but
never just gives up. Whenever it cannot positively confirm a covering run
exists - the wait times out, the PR closed and moved on, or a lookup itself
fails - it says the push run should build the commit itself (``rescue``)
rather than leave it unverified forever. The rare cost is a duplicate build
if the covering run turns up moments later; the alternative was an
unrecoverable red check.

Usage:
    covering-run-check.py --repo owner/repo --sha <sha> --ref <branch-name> \\
        --workflow-name "Maven Build" [--timeout 300] [--poll-interval 20]

Output:
    key=value lines in GITHUB_OUTPUT format on stdout (``rescue=true|false``);
    diagnostics on stderr.

Exit codes:
    Always 0 - every branch reaches a decision; an unresolvable lookup
    resolves to ``rescue=true``, never to a failure that blocks the run.
"""

import argparse
import json
import subprocess
import sys
import time


def run_gh(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run the gh CLI, never raising - callers read returncode instead."""
    return subprocess.run(["gh"] + args, capture_output=True, text=True, check=False)


def covering_run_exists(repo: str, sha: str, workflow_name: str) -> bool | None:
    """True/False, or None if the lookup itself could not be completed."""
    result = run_gh(["api", f"repos/{repo}/actions/runs?head_sha={sha}&event=pull_request"])
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    runs = payload.get("workflow_runs") if isinstance(payload, dict) else None
    if not isinstance(runs, list):
        return None
    return any(isinstance(run, dict) and run.get("name") == workflow_name for run in runs)


def open_pr_still_points_here(repo: str, ref: str, sha: str) -> bool | None:
    """True if an open, same-repo PR for ``ref`` still has ``sha`` as its head.

    Only internal PRs count: a fork PR that happens to reuse this branch name
    builds a different repository's commit (gh's --head matches a bare branch
    name across forks), so cross-repository PRs are excluded - matching the
    same rule `gate` uses to decide whether to skip in the first place.
    """
    result = run_gh(
        ["pr", "list", "--repo", repo, "--head", ref, "--state", "open", "--json", "headRefOid,isCrossRepository"]
    )
    if result.returncode != 0:
        return None
    try:
        prs = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(prs, list):
        return None
    return any(
        isinstance(pr, dict) and pr.get("isCrossRepository") is False and pr.get("headRefOid") == sha for pr in prs
    )


def decide(repo: str, sha: str, ref: str, workflow_name: str, timeout: int, poll_interval: int) -> tuple[bool, str]:
    """Return (rescue, reason). ``rescue=True`` means: build this commit now."""
    deadline = time.monotonic() + timeout
    while True:
        covered = covering_run_exists(repo, sha, workflow_name)
        if covered is None:
            return True, "the covering pull_request run could not be looked up"
        if covered:
            return False, f"a covering pull_request run was found for {sha}"

        # No covering run yet. Only keep waiting while one is still expected -
        # an open same-repo PR still pointing at THIS sha is proof one is
        # still coming; anything else means it never will.
        pending = open_pr_still_points_here(repo, ref, sha)
        if pending is None:
            return True, "the open PR could not be looked up"
        if not pending:
            return True, (
                f"no open same-repo PR points at {sha} any more and no {workflow_name} pull_request run exists for it"
            )
        if time.monotonic() >= deadline:
            return True, f"no {workflow_name} pull_request run appeared for {sha} within {timeout}s"

        print(
            f"No covering run for {sha} yet; an open PR still points at it - waiting {poll_interval}s",
            file=sys.stderr,
        )
        time.sleep(poll_interval)


def main() -> int:
    parser = argparse.ArgumentParser(description="Decide whether a gate-skipped push run must build its own commit")
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--sha", required=True, help="Commit SHA this push run is building")
    parser.add_argument("--ref", required=True, help="Branch name that was pushed")
    parser.add_argument("--workflow-name", required=True, help="Workflow name a covering run must match")
    parser.add_argument("--timeout", type=int, default=300, help="Seconds to wait for a covering run (default: 300)")
    parser.add_argument("--poll-interval", type=int, default=20, help="Seconds between polls (default: 20)")
    args = parser.parse_args()

    rescue, reason = decide(args.repo, args.sha, args.ref, args.workflow_name, args.timeout, args.poll_interval)

    verdict = "RESCUE" if rescue else "COVERED"
    print(f"Covering-run check: {verdict} - {reason}", file=sys.stderr)
    print(f"rescue={'true' if rescue else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
