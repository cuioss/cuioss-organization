#!/usr/bin/env python3
"""Update a single consumer repository with new workflow references.

This script encapsulates the per-repository update logic from the release
workflow. It clones a repository, runs the update-workflow-references.py
script, and creates a PR if changes were made.

When the consumer repo has auto-merge enabled in its project.yml, the script
will poll PR checks and auto-merge when CI passes.

Usage:
    ./update-consumer-repo.py --repo cui-java-tools --version 0.1.0 --sha abc123...
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
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


def make_result(status: str, pr_url: str | None = None, error: str | None = None) -> dict:
    """Create a standardized result dict."""
    return {"status": status, "pr_url": pr_url, "error": error}


def update_consumer_repo(
    org: str, repo: str, version: str, sha: str, script_dir: Path
) -> dict:
    """Update a single consumer repository.

    Returns a result dict with status, pr_url, and error fields.
    """
    full_repo = f"{org}/{repo}"
    branch = f"chore/update-org-workflows-v{version}"

    print(f"::group::Processing {full_repo}")

    with tempfile.TemporaryDirectory() as tmp:
        repo_dir = Path(tmp) / repo

        # Clone repository
        print(f"Cloning {full_repo}...")
        result = run_gh(
            ["repo", "clone", full_repo, str(repo_dir), "--", "--depth", "1"],
            check=False,
        )
        if result.returncode != 0:
            print(f"::warning::Failed to clone {full_repo}: {result.stderr}")
            print("::endgroup::")
            return make_result(STATUS_ERROR, error=f"Clone failed: {result.stderr.strip()}")

        # Configure git credential helper to use GH_TOKEN for push operations
        # gh repo clone sets up HTTPS remote but git push needs explicit auth
        run_git(
            ["config", "credential.helper", "!gh auth git-credential"],
            cwd=repo_dir,
            check=False,
        )

        # Check for workflows directory
        if not (repo_dir / ".github" / "workflows").exists():
            print(f"::warning::No .github/workflows directory in {repo}, skipping")
            print("::endgroup::")
            return make_result(STATUS_ERROR, error="No .github/workflows directory")

        # Read auto-merge config before running update (uses cloned repo's project.yml)
        auto_merge_config = read_auto_merge_config(repo_dir)

        # Run update script
        print("Updating workflow references...")
        update_script = script_dir / "update-workflow-references.py"
        result = subprocess.run(
            [
                sys.executable,
                str(update_script),
                "--version",
                version,
                "--sha",
                sha,
                "--path",
                str(repo_dir),
            ],
            capture_output=True,
            text=True,
        )
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)

        # Check for changes
        diff_result = run_git(["diff", "--quiet"], cwd=repo_dir, check=False)
        if diff_result.returncode == 0:
            print("No changes needed")
            print("::endgroup::")
            return make_result(STATUS_NO_CHANGES)

        # Create branch
        run_git(["checkout", "-b", branch], cwd=repo_dir)

        # Configure git
        run_git(["config", "user.email", "action@github.com"], cwd=repo_dir)
        run_git(["config", "user.name", "cuioss-release-bot"], cwd=repo_dir)

        # Stage and commit
        run_git(["add", ".github/workflows/"], cwd=repo_dir)
        # Also add docs if they exist and were modified
        run_git(["add", "docs/", "README.adoc"], cwd=repo_dir, check=False)
        run_git(
            [
                "commit",
                "-m",
                f"chore: update cuioss-organization workflows to v{version}",
            ],
            cwd=repo_dir,
        )

        # Push branch
        print(f"Pushing branch {branch}...")
        result = run_git(["push", "-u", "origin", branch], cwd=repo_dir, check=False)
        if result.returncode != 0:
            print(f"::warning::Failed to push: {result.stderr}")
            print("::endgroup::")
            return make_result(STATUS_ERROR, error=f"Push failed: {result.stderr.strip()}")
        print("Push successful")

        # Create PR (--head is required for shallow clones in temp directories)
        print("Creating pull request...")
        pr_body = (
            f"Updates workflow references to SHA `{sha}` (v{version})\n\n"
            "This PR was automatically created by the cuioss-organization release workflow."
        )
        result = run_gh(
            [
                "pr",
                "create",
                "--repo",
                full_repo,
                "--head",
                branch,
                "--title",
                f"chore: update cuioss-organization workflows to v{version}",
                "--body",
                pr_body,
            ],
            check=False,
            cwd=repo_dir,
        )

        if result.returncode != 0:
            print(f"::warning::PR creation failed: {result.stderr}")
            print("::endgroup::")
            return make_result(STATUS_ERROR, error=f"PR creation failed: {result.stderr.strip()}")

        pr_url = result.stdout.strip()
        print(f"✓ PR created: {pr_url}")

        # Attempt auto-merge if enabled
        if auto_merge_config["enabled"]:
            print(f"Auto-merge enabled for {full_repo}")
            enabled = auto_merge_pr(full_repo, pr_url)
            status = STATUS_PR_AUTO_MERGE_ENABLED if enabled else STATUS_PR_CREATED
        else:
            print(f"Auto-merge disabled for {full_repo}, leaving PR open")
            status = STATUS_PR_CREATED

        print("::endgroup::")
        return make_result(status, pr_url=pr_url)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Update consumer repo with new workflow references"
    )
    parser.add_argument("--org", default="cuioss", help="GitHub organization")
    parser.add_argument("--repo", required=True, help="Repository name")
    parser.add_argument(
        "--version", required=True, help="Version string (e.g., 0.1.0)"
    )
    parser.add_argument("--sha", required=True, help="40-character commit SHA")

    args = parser.parse_args()

    # Validate SHA
    if len(args.sha) != 40:
        print(
            f"Error: SHA must be 40 characters, got {len(args.sha)}", file=sys.stderr
        )
        sys.exit(1)

    script_dir = Path(__file__).parent
    result = update_consumer_repo(
        args.org, args.repo, args.version, args.sha, script_dir
    )

    # Output result as parseable JSON line for the release workflow
    print(f"RESULT:{json.dumps(result)}")

    # Exit with appropriate code
    success = result["status"] in (STATUS_PR_CREATED, STATUS_PR_AUTO_MERGE_ENABLED, STATUS_NO_CHANGES)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
