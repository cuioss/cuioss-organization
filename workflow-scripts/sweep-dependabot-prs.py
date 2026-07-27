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

try:
    import yaml
except ImportError:  # pragma: no cover - pre-installed on GitHub runners
    print("Error: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

DEFAULT_LABEL = "automerge"
DEFAULT_OWNER = "cuioss"
DEFAULT_AUTHOR = "app/dependabot"

# Dependabot always opens from a branch under this prefix. Checked as defence in
# depth: a label survives a force-push, so a collaborator could otherwise reuse
# an already-labelled Dependabot branch for unrelated content. The PR author
# cannot be forged -- dependabot[bot] is an App-derived login and GitHub
# usernames admit no brackets -- but the branch it points at can be rewritten.
DEPENDABOT_BRANCH_PREFIX = "dependabot/"

# Per-repo switch in .github/project.yml:
#   github-automation:
#     dependabot-automerge: false
PROJECT_CONFIG_PATH = ".github/project.yml"
AUTOMATION_KEY = "github-automation"
OPT_IN_KEY = "dependabot-automerge"

# GitHub's own readiness verdict. Anything else means a required check is
# missing, failing, or the PR is blocked -- never force it.
READY_MERGE_STATE = "CLEAN"

# Upper bound on any single gh call. Well under the job's timeout-minutes so a
# stalled call surfaces as a reported failure rather than a killed job.
GH_CALL_TIMEOUT_SECONDS = 120


def run_gh(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a gh CLI command without raising on failure.

    Bounded by GH_CALL_TIMEOUT_SECONDS: the sweeper runs on a 15-minute cron
    with cancel-in-progress: false, so one hung call (network stall, rate-limit
    backoff) would otherwise hold the job until the runner default and stack the
    following scheduled runs behind it. A timeout is reported as a failed call,
    which every caller already handles.
    """
    try:
        return subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=GH_CALL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            args=["gh", *args],
            returncode=124,
            stdout="",
            stderr=f"gh call timed out after {GH_CALL_TIMEOUT_SECONDS}s",
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


PR_STATE_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      state
      isDraft
      mergeable
      mergeStateStatus
      isInMergeQueue
      headRefName
    }
  }
}
"""


def read_pr_state(repo: str, number: int) -> dict | None:
    """Read the merge-readiness fields GitHub computes for a PR.

    Queried over GraphQL rather than `gh pr view --json`: isInMergeQueue is not
    among the fields that command exposes (checked on gh 2.95.0), and without it
    the sweeper would re-enqueue a PR the queue is already building.
    """
    owner, _, name = repo.partition("/")
    result = run_gh(
        [
            "api", "graphql",
            "-f", f"query={PR_STATE_QUERY}",
            "-F", f"owner={owner}",
            "-F", f"name={name}",
            "-F", f"number={number}",
        ]
    )
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    pr = ((payload.get("data") or {}).get("repository") or {}).get("pullRequest")
    return pr or None


def repo_participates(repo: str, cache: dict[str, str]) -> str:
    """Report whether a repo takes part in automated Dependabot merging.

    Returns "yes", "no" (opted out), or "indeterminate".

    Reads github-automation.dependabot-automerge from the repo's project.yml.
    Absent file or absent key means yes: participation is already gated by the
    label, which only the caller workflow applies, so a repo without the caller
    never produces candidates in the first place.

    A file that exists but cannot be parsed is "indeterminate", not yes. A
    definite absence is an answer; an unreadable config is not, and guessing
    "participate" there would merge on a repo whose intent is unknown.
    """
    if repo in cache:
        return cache[repo]

    result = run_gh(["api", f"repos/{repo}/contents/{PROJECT_CONFIG_PATH}", "--jq", ".content"])
    if result.returncode != 0:
        # Distinguish "no such file" (a definite no-config answer) from any
        # other API failure (indeterminate).
        verdict = "yes" if "404" in result.stderr or "Not Found" in result.stderr else "indeterminate"
        cache[repo] = verdict
        return verdict

    import base64

    try:
        raw = base64.b64decode(result.stdout.strip()).decode("utf-8")
        config = yaml.safe_load(raw) or {}
    except (ValueError, UnicodeDecodeError, yaml.YAMLError):
        cache[repo] = "indeterminate"
        return "indeterminate"

    automation = config.get(AUTOMATION_KEY) or {}
    if not isinstance(automation, dict):
        cache[repo] = "indeterminate"
        return "indeterminate"

    value = automation.get(OPT_IN_KEY, True)
    cache[repo] = "yes" if value is True else "no"
    return cache[repo]


def classify(state: dict | None) -> str:
    """Decide what to do with a PR from its merge-readiness fields.

    Returns one of: merge, queued, draft, not-open, not-ready, foreign-branch,
    unknown.
    """
    if state is None:
        return "unknown"
    if state.get("state") != "OPEN":
        return "not-open"
    head = state.get("headRefName") or ""
    if not head.startswith(DEPENDABOT_BRANCH_PREFIX):
        return "foreign-branch"
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
    """Merge (or enqueue) a single PR. Returns (ok, detail).

    Two behaviours of `gh pr merge` force the shape of this function:

    - On a PR that already has an auto-merge request, it is a silent no-op that
      still exits 0. Observed on nifi-extensions#466: the command reported
      success and the PR was never queued. So any pre-existing auto-merge
      request is cleared first.
    - Exit 0 does not mean the PR moved. The outcome is therefore read back from
      GitHub -- merged, or sitting in the queue -- and only that counts as
      success. An exit code is necessary but never sufficient.
    """
    run_gh(["pr", "merge", str(number), "--repo", repo, "--disable-auto"])

    result = run_gh(["pr", "merge", str(number), "--repo", repo, "--squash"])
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()

    state = read_pr_state(repo, number)
    if state is None:
        return False, "merge reported success but the PR state could not be read"
    if state.get("state") == "MERGED":
        return True, "merged"
    if state.get("isInMergeQueue"):
        return True, "enqueued"
    return False, (
        f"gh exited 0 but the PR did not move "
        f"(state={state.get('state')} merge={state.get('mergeStateStatus')})"
    )


def sweep(owner: str, label: str, author: str, limit: int, dry_run: bool) -> list[dict]:
    """Process every labelled Dependabot PR and report per-PR outcomes."""
    outcomes = []
    participation: dict[str, str] = {}
    for pr in find_candidates(owner, label, author, limit):
        verdict = repo_participates(pr["repo"], participation)
        if verdict != "yes":
            outcomes.append({
                **pr,
                "action": "opted-out" if verdict == "no" else "config-unreadable",
                "detail": "",
            })
            continue

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
        "opted-out": ":no_entry_sign: repo opted out (github-automation.dependabot-automerge)",
        "config-unreadable": ":question: project.yml unreadable - not merging",
        "foreign-branch": ":warning: labelled PR is not on a dependabot/ branch",
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
