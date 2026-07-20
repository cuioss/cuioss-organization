#!/usr/bin/env python3
"""
Update cuioss-organization workflow references to SHA-pinned format.

Since all files share the same SHA after a release, this script discovers the
old SHA from existing files and does a simple global replacement — no need to
enumerate specific directories.

Usage:
    # Standard release update (discovers old SHA automatically)
    ./update-workflow-references.py --version 0.1.0 --sha abc123...

    # SHA-pin the composite actions the reusable workflows execute (before tagging)
    ./update-workflow-references.py --version 0.1.0 --sha <release-commit-sha> --internal-only

    # Full path specification
    ./update-workflow-references.py --version 0.1.0 --sha abc123... --path /path/to/repo
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

# Directories that should never be scanned
SKIP_DIRS = {'.git', '.pyprojectx', '__pycache__', 'node_modules', '.venv', 'venvs'}

# Pattern to find an existing cuioss-organization SHA reference
SHA_DISCOVERY_PATTERN = re.compile(
    r'cuioss/cuioss-organization/[^@]+@([a-f0-9]{40})'
)

# Pattern to match any cuioss-organization reference
CUIOSS_REF_PATTERN = re.compile(
    r'(uses:\s*cuioss/cuioss-organization/[^@]+)@[^\s#]+(\s*#\s*v[\d.]+)?'
)

# Pattern to match a composite-action reference (the refs a reusable workflow
# actually executes, as opposed to consumer-facing workflow references)
INTERNAL_ACTION_REF_PATTERN = re.compile(
    r'(uses:\s*cuioss/cuioss-organization/\.github/actions/[^@]+)@[^\s#]+(\s*#\s*v[\d.]+)?'
)


def is_internal_action_line(line: str) -> bool:
    """True if this line executes a cuioss-organization composite action.

    Commented-out lines are consumer-facing usage examples, not executed
    references, so they are treated as external.
    """
    if line.lstrip().startswith('#'):
        return False
    return INTERNAL_ACTION_REF_PATTERN.search(line) is not None


def iter_reusable_workflows(base_path: Path):
    """Yield the reusable workflow files whose executed refs must be SHA-pinned."""
    workflows_dir = base_path / '.github' / 'workflows'
    if workflows_dir.exists():
        yield from sorted(workflows_dir.glob('reusable-*.yml'))


def discover_old_sha(base_path: Path) -> str | None:
    """Find the current cuioss-organization SHA from existing files.

    Checks workflow examples first (most reliable), then falls back to
    any file in the repo.
    """
    # Try workflow examples first — these are always in sync after a release
    examples_dir = base_path / 'docs' / 'workflow-examples'
    if examples_dir.exists():
        for yml_file in examples_dir.glob('*.yml'):
            match = SHA_DISCOVERY_PATTERN.search(yml_file.read_text())
            if match:
                return match.group(1)

    # Fallback: search all text files
    for path in _iter_text_files(base_path):
        try:
            match = SHA_DISCOVERY_PATTERN.search(path.read_text())
            if match:
                return match.group(1)
        except (UnicodeDecodeError, PermissionError):
            continue

    return None


def _iter_text_files(base_path: Path):
    """Yield text files, skipping binary/vendored directories.

    Uses git ls-files if available, falls back to rglob.
    """
    try:
        result = subprocess.run(
            ['git', 'ls-files', '--cached', '--others', '--exclude-standard'],
            capture_output=True, text=True, cwd=base_path, check=True
        )
        for line in result.stdout.splitlines():
            path = base_path / line
            if path.is_file() and not any(d in path.parts for d in SKIP_DIRS):
                yield path
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fallback: walk the filesystem
        for path in base_path.rglob('*'):
            if path.is_file() and not any(d in path.parts for d in SKIP_DIRS):
                yield path


def update_workflow_references(
    version: str,
    base_path: Path,
    sha: str | None = None,
    internal_only: bool = False
) -> list[str]:
    """
    Update cuioss-organization references in workflow files.

    Normal mode: discovers old SHA, replaces with new SHA globally.
    Internal-only mode: updates reusable-*.yml with version tag format.

    Args:
        version: Version string (e.g., "0.1.0")
        base_path: Base path to search for workflows
        sha: Full 40-character SHA hash (required unless internal_only=True)
        internal_only: If True, only update internal references in reusable workflows

    Returns:
        List of modified file paths
    """
    assert sha is not None, "SHA is required in both modes"

    if internal_only:
        return _update_internal_only(version, sha, base_path)

    # Discover the old SHA from existing files
    old_sha = discover_old_sha(base_path)
    if old_sha is None:
        print("Warning: Could not discover old SHA from existing files")
        print("Using regex-based replacement only")
    elif old_sha == sha:
        print(f"Old SHA and new SHA are identical ({sha[:12]}...), nothing to do")
        return []
    else:
        print(f"Discovered old SHA: {old_sha[:12]}...")

    print(f"Updating references to SHA: {sha[:12]}...")

    new_ref = f'{sha} # v{version}'
    comment_suffix = f' # v{version}'
    modified_files = []
    reusable_workflows = set(iter_reusable_workflows(base_path))

    for path in _iter_text_files(base_path):
        try:
            content = path.read_text()
        except (UnicodeDecodeError, PermissionError):
            continue

        # Skip files where cuioss-organization refs use template expressions as the ref
        # (e.g. release.yml: uses: ...@${{ steps.sha.outputs.sha }})
        if re.search(r'cuioss/cuioss-organization/[^@]+@\$\{\{', content):
            continue

        # Internal action refs inside reusable workflows are owned by
        # internal-only mode and are pinned to a different (earlier) commit —
        # never rewrite them here.
        skip_internal = path in reusable_workflows

        updated_lines = []
        for line in content.splitlines(keepends=True):
            if skip_internal and is_internal_action_line(line):
                updated_lines.append(line)
                continue

            # Pass 1: SHA → SHA replacement (only when old SHA is known)
            if old_sha and old_sha in line:
                line = re.sub(
                    rf'{old_sha}(\s*#\s*v[\d.]+)?',
                    new_ref,
                    line
                )

            # Pass 2: catch remaining non-SHA refs (@v0.2.9, @main, etc.)
            line = CUIOSS_REF_PATTERN.sub(
                rf'\1@{sha}{comment_suffix}',
                line
            )
            updated_lines.append(line)

        new_content = ''.join(updated_lines)

        if new_content != content:
            path.write_text(new_content)
            modified_files.append(str(path))
            print(f"Updated: {path}")

    return modified_files


def _update_internal_only(version: str, sha: str, base_path: Path) -> list[str]:
    """SHA-pin the composite-action refs that reusable workflows execute.

    The SHA must be an already-existing commit (the release commit), not the
    commit this update produces — a commit cannot contain its own SHA. Pinning
    one commit back is safe because that commit holds the identical action
    source; only ``uses:`` lines change afterwards.

    Consumer-facing workflow references are left alone: they belong to the
    release tag and are updated by the external pass once the tag exists.
    """
    modified_files: list[str] = []
    new_ref = rf'\1@{sha} # v{version}'

    for yml_file in iter_reusable_workflows(base_path):
        content = yml_file.read_text()

        updated_lines = [
            INTERNAL_ACTION_REF_PATTERN.sub(new_ref, line)
            if is_internal_action_line(line) else line
            for line in content.splitlines(keepends=True)
        ]
        new_content = ''.join(updated_lines)

        if new_content != content:
            yml_file.write_text(new_content)
            modified_files.append(str(yml_file))
            print(f"Updated: {yml_file}")

    return modified_files



def main():
    parser = argparse.ArgumentParser(
        description='Update cuioss-organization workflow references to SHA-pinned format'
    )
    parser.add_argument(
        '--version',
        required=True,
        help='Version string (e.g., 0.1.0)'
    )
    parser.add_argument(
        '--sha',
        required=True,
        help='Full 40-character SHA hash to pin references to'
    )
    parser.add_argument(
        '--path',
        default='.',
        help='Base path to search for workflows (default: current directory)'
    )
    parser.add_argument(
        '--internal-only',
        action='store_true',
        help='Only SHA-pin the composite-action refs executed by reusable workflows'
    )

    args = parser.parse_args()

    if not re.match(r'^\d+\.\d+\.\d+$', args.version):
        print(f"Error: Version must be semver (e.g. 1.2.3), got: {args.version}", file=sys.stderr)
        sys.exit(1)

    if len(args.sha) != 40 or not re.match(r'^[a-f0-9]+$', args.sha):
        print(f"Error: SHA must be a 40-character hex string, got: {args.sha}", file=sys.stderr)
        sys.exit(1)

    base_path = Path(args.path).resolve()
    if not base_path.exists():
        print(f"Error: Path does not exist: {base_path}", file=sys.stderr)
        sys.exit(1)

    if args.internal_only:
        print(f"Pinning internal action references to v{args.version} ({args.sha})")
    else:
        print(f"Updating external workflow references to v{args.version} ({args.sha})")
    print(f"Searching in: {base_path}")

    modified = update_workflow_references(
        args.version,
        base_path,
        sha=args.sha,
        internal_only=args.internal_only
    )

    if modified:
        print(f"\nModified {len(modified)} file(s)")
    else:
        print("\nNo files modified")

    return 0 if modified else 1


if __name__ == '__main__':
    sys.exit(main())
