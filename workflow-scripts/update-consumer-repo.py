#!/usr/bin/env python3
"""Update a single consumer repository with new workflow references.

This script encapsulates the per-repository update logic from the release
workflow. It clones a repository, runs the update-workflow-references.py
script, and creates a PR if changes were made.

Usage:
    ./update-consumer-repo.py --repo cui-java-tools --version 0.1.0 --sha abc123...
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


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


def update_consumer_repo(
    org: str, repo: str, version: str, sha: str, script_dir: Path
) -> bool:
    """Update a single consumer repository.

    Returns True if PR was created, False if no changes needed or on error.
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
            return False

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
            return False

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
            return False

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
            return False
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

        if result.returncode == 0:
            print(f"✓ PR created: {result.stdout.strip()}")
        else:
            print(f"::warning::PR creation failed: {result.stderr}")

        print("::endgroup::")
        return result.returncode == 0


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
    success = update_consumer_repo(
        args.org, args.repo, args.version, args.sha, script_dir
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
