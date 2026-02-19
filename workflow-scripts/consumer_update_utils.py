"""Shared utilities for consumer repository update scripts.

Provides common helpers for:
- Running gh/git CLI commands
- GitHub Actions step summary
- Auto-merge configuration
- Stale PR management (close superseded PRs)
- Standardized result formatting
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# Result status constants
STATUS_PR_AUTO_MERGE_ENABLED = "pr_auto_merge_enabled"
STATUS_PR_CREATED = "pr_created"
STATUS_NO_CHANGES = "no_changes"
STATUS_ERROR = "error"


def run_gh(
    args: list[str], check: bool = True, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """Run gh CLI command."""
    return subprocess.run(
        ["gh"] + args, capture_output=True, text=True, check=check, cwd=cwd
    )


def run_git(
    args: list[str], cwd: Path, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run git command in specified directory."""
    return subprocess.run(
        ["git"] + args, capture_output=True, text=True, check=check, cwd=cwd
    )


def write_summary(text: str) -> None:
    """Append markdown text to GitHub Actions step summary.

    No-op when GITHUB_STEP_SUMMARY is not set (e.g. running locally).
    """
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as f:
        f.write(text + "\n")


def read_auto_merge_config(repo_dir: Path) -> dict:
    """Read auto-merge configuration from the consumer repo's project.yml.

    Returns a dict with:
        enabled: bool (default True)
    """
    config = {"enabled": True}
    project_yml = repo_dir / ".github" / "project.yml"

    if not project_yml.exists():
        return config

    try:
        import yaml
    except ImportError:
        print("::warning::PyYAML not available, using auto-merge defaults")
        return config

    try:
        with open(project_yml, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            return config

        automation = data.get("github-automation", {})
        if not isinstance(automation, dict):
            return config

        if "auto-merge-build-versions" in automation:
            config["enabled"] = bool(automation["auto-merge-build-versions"])

    except Exception as e:
        print(f"::warning::Failed to read auto-merge config: {e}")

    return config


def auto_merge_pr(full_repo: str, pr_url: str) -> bool:
    """Enable GitHub auto-merge on the PR (async, returns immediately).

    Args:
        full_repo: Full repo name (e.g. "cuioss/cui-java-tools")
        pr_url: URL of the PR to merge

    Returns:
        True if auto-merge was enabled, False otherwise.
    """
    print(f"Auto-merge: enabling for {pr_url}")
    result = run_gh(
        ["pr", "merge", "--auto", "--squash", "--delete-branch", pr_url],
        check=False,
    )
    if result.returncode == 0:
        print(f"Auto-merge enabled: {pr_url}")
        return True
    else:
        print(f"::warning::Failed to enable auto-merge: {result.stderr}")
        return False


def make_result(
    status: str, pr_url: str | None = None, error: str | None = None
) -> dict:
    """Create a standardized result dict."""
    return {"status": status, "pr_url": pr_url, "error": error}


def find_open_prs_by_branch_prefix(
    full_repo: str, branch_prefix: str
) -> list[dict]:
    """Find open PRs whose head branch starts with the given prefix.

    Args:
        full_repo: Full repo name (e.g. "cuioss/cui-java-tools")
        branch_prefix: Branch name prefix to match (e.g. "chore/update-org-workflows-")

    Returns:
        List of dicts with number, url, headRefName fields.
    """
    result = run_gh(
        [
            "pr",
            "list",
            "--repo",
            full_repo,
            "--state",
            "open",
            "--json",
            "number,url,headRefName",
            "--limit",
            "50",
        ],
        check=False,
    )
    if result.returncode != 0:
        print(f"::warning::Failed to list PRs for {full_repo}: {result.stderr}")
        return []

    try:
        prs = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    return [pr for pr in prs if pr.get("headRefName", "").startswith(branch_prefix)]


def close_stale_prs(
    full_repo: str,
    branch_prefix: str,
    reason: str,
    exclude_branch: str | None = None,
) -> list[str]:
    """Close open PRs matching a branch prefix with a comment.

    Args:
        full_repo: Full repo name (e.g. "cuioss/cui-java-tools")
        branch_prefix: Branch name prefix to match
        reason: Comment to add before closing (e.g. "Superseded by #42")
        exclude_branch: Branch name to exclude from closing (the new PR's branch)

    Returns:
        List of closed PR URLs.
    """
    stale_prs = find_open_prs_by_branch_prefix(full_repo, branch_prefix)
    closed = []

    for pr in stale_prs:
        if exclude_branch and pr.get("headRefName") == exclude_branch:
            continue

        pr_url = pr["url"]
        pr_num = pr["number"]
        print(f"Closing stale PR #{pr_num}: {pr_url}")

        # Add comment explaining why
        run_gh(
            [
                "pr",
                "comment",
                str(pr_num),
                "--repo",
                full_repo,
                "--body",
                reason,
            ],
            check=False,
        )

        # Close the PR
        result = run_gh(
            ["pr", "close", str(pr_num), "--repo", full_repo, "--delete-branch"],
            check=False,
        )
        if result.returncode == 0:
            closed.append(pr_url)
            print(f"Closed stale PR #{pr_num}")
        else:
            print(f"::warning::Failed to close PR #{pr_num}: {result.stderr}")

    return closed


def clone_consumer_repo(
    full_repo: str, target_dir: Path
) -> subprocess.CompletedProcess[str]:
    """Clone a consumer repo (shallow) and configure git credentials.

    Args:
        full_repo: Full repo name (e.g. "cuioss/cui-java-tools")
        target_dir: Directory to clone into

    Returns:
        The CompletedProcess from gh repo clone.
    """
    result = run_gh(
        ["repo", "clone", full_repo, str(target_dir), "--", "--depth", "1"],
        check=False,
    )
    if result.returncode == 0:
        # Configure git credential helper for push operations
        run_git(
            ["config", "credential.helper", "!gh auth git-credential"],
            cwd=target_dir,
            check=False,
        )
    return result


def configure_git_author(repo_dir: Path) -> None:
    """Configure git author for commits in the given repo directory."""
    run_git(["config", "user.email", "action@github.com"], cwd=repo_dir)
    run_git(["config", "user.name", "cuioss-release-bot"], cwd=repo_dir)


def create_pr_and_auto_merge(
    full_repo: str,
    repo_dir: Path,
    branch: str,
    title: str,
    body: str,
    auto_merge_config: dict,
) -> dict:
    """Push branch, create PR, and optionally enable auto-merge.

    Args:
        full_repo: Full repo name
        repo_dir: Local clone directory
        branch: Branch name to push
        title: PR title
        body: PR body
        auto_merge_config: Dict with 'enabled' key

    Returns:
        Result dict from make_result().
    """
    # Push branch
    print(f"Pushing branch {branch}...")
    result = run_git(["push", "-u", "origin", branch], cwd=repo_dir, check=False)
    if result.returncode != 0:
        print(f"::warning::Failed to push: {result.stderr}")
        return make_result(STATUS_ERROR, error=f"Push failed: {result.stderr.strip()}")
    print("Push successful")

    # Create PR
    print("Creating pull request...")
    result = run_gh(
        [
            "pr",
            "create",
            "--repo",
            full_repo,
            "--head",
            branch,
            "--title",
            title,
            "--body",
            body,
        ],
        check=False,
        cwd=repo_dir,
    )

    if result.returncode != 0:
        print(f"::warning::PR creation failed: {result.stderr}")
        return make_result(
            STATUS_ERROR, error=f"PR creation failed: {result.stderr.strip()}"
        )

    pr_url = result.stdout.strip()
    print(f"PR created: {pr_url}")

    # Attempt auto-merge if enabled
    if auto_merge_config["enabled"]:
        print(f"Auto-merge enabled for {full_repo}")
        enabled = auto_merge_pr(full_repo, pr_url)
        status = STATUS_PR_AUTO_MERGE_ENABLED if enabled else STATUS_PR_CREATED
    else:
        print(f"Auto-merge disabled for {full_repo}, leaving PR open")
        status = STATUS_PR_CREATED

    return make_result(status, pr_url=pr_url)


def output_result(result: dict) -> None:
    """Print result as parseable JSON line for workflow consumption."""
    print(f"RESULT:{json.dumps(result)}")


def exit_with_result(result: dict) -> None:
    """Print result and exit with appropriate code."""
    output_result(result)
    success = result["status"] in (
        STATUS_PR_CREATED,
        STATUS_PR_AUTO_MERGE_ENABLED,
        STATUS_NO_CHANGES,
    )
    sys.exit(0 if success else 1)
