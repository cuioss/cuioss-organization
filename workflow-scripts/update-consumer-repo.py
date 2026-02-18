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
import subprocess
import sys
import tempfile
from pathlib import Path

from consumer_update_utils import (
    STATUS_ERROR,
    STATUS_NO_CHANGES,
    clone_consumer_repo,
    close_stale_prs,
    configure_git_author,
    create_pr_and_auto_merge,
    exit_with_result,
    make_result,
    read_auto_merge_config,
    run_git,
)

# Branch prefix for workflow update PRs
BRANCH_PREFIX = "chore/update-org-workflows-"


def update_consumer_repo(
    org: str, repo: str, version: str, sha: str, script_dir: Path
) -> dict:
    """Update a single consumer repository.

    Returns a result dict with status, pr_url, and error fields.
    """
    full_repo = f"{org}/{repo}"
    branch = f"{BRANCH_PREFIX}v{version}"

    print(f"::group::Processing {full_repo}")

    with tempfile.TemporaryDirectory() as tmp:
        repo_dir = Path(tmp) / repo

        # Clone repository
        print(f"Cloning {full_repo}...")
        result = clone_consumer_repo(full_repo, repo_dir)
        if result.returncode != 0:
            print(f"::warning::Failed to clone {full_repo}: {result.stderr}")
            print("::endgroup::")
            return make_result(STATUS_ERROR, error=f"Clone failed: {result.stderr.strip()}")

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
            # Close any stale PRs since the repo is already up to date
            close_stale_prs(
                full_repo,
                BRANCH_PREFIX,
                f"Closing: repository already uses workflow references v{version}.",
            )
            print("::endgroup::")
            return make_result(STATUS_NO_CHANGES)

        # Create branch
        run_git(["checkout", "-b", branch], cwd=repo_dir)

        # Configure git
        configure_git_author(repo_dir)

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

        # Create PR and enable auto-merge
        pr_body = (
            f"Updates workflow references to SHA `{sha}` (v{version})\n\n"
            "This PR was automatically created by the cuioss-organization release workflow."
        )
        pr_result = create_pr_and_auto_merge(
            full_repo,
            repo_dir,
            branch,
            f"chore: update cuioss-organization workflows to v{version}",
            pr_body,
            auto_merge_config,
        )

        # Close stale PRs from previous versions
        if pr_result["pr_url"]:
            close_stale_prs(
                full_repo,
                BRANCH_PREFIX,
                f"Superseded by new update to v{version}: {pr_result['pr_url']}",
                exclude_branch=branch,
            )

        print("::endgroup::")
        return pr_result


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

    exit_with_result(result)


if __name__ == "__main__":
    main()
