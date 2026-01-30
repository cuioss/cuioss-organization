#!/usr/bin/env python3
"""
Update cuioss-organization workflow references to SHA-pinned format.

This script scans workflow files and updates references to cuioss-organization
reusable workflows with SHA-pinned versions.

Usage:
    ./update-workflow-references.py --version 0.1.0 --sha abc123...
    ./update-workflow-references.py --version 0.1.0 --sha abc123... --path /path/to/repo
"""

import argparse
import re
import sys
from pathlib import Path


def update_workflow_references(version: str, sha: str, base_path: Path) -> list[str]:
    """
    Update cuioss-organization references in workflow files.

    Args:
        version: Version string (e.g., "0.1.0")
        sha: Full 40-character SHA hash
        base_path: Base path to search for workflows

    Returns:
        List of modified file paths
    """
    modified_files = []

    # Pattern to match cuioss-organization workflow references
    # Matches: cuioss/cuioss-organization/.github/workflows/<workflow>.yml@<ref>
    # With optional trailing comment
    pattern = re.compile(
        r'(uses:\s*cuioss/cuioss-organization/\.github/workflows/[^@]+\.yml)@[^\s#]+(\s*#\s*v[\d.]+)?'
    )

    # Search in .github/workflows/
    workflows_dir = base_path / '.github' / 'workflows'
    if workflows_dir.exists():
        for yml_file in workflows_dir.glob('**/*.yml'):
            content = yml_file.read_text()
            new_content = pattern.sub(rf'\1@{sha} # v{version}', content)
            if new_content != content:
                yml_file.write_text(new_content)
                modified_files.append(str(yml_file))
                print(f"Updated: {yml_file}")

    # Also update docs/Workflows.adoc if present
    workflows_doc = base_path / 'docs' / 'Workflows.adoc'
    if workflows_doc.exists():
        content = workflows_doc.read_text()
        # Pattern for AsciiDoc code blocks
        new_content = pattern.sub(rf'\1@{sha} # v{version}', content)
        if new_content != content:
            workflows_doc.write_text(new_content)
            modified_files.append(str(workflows_doc))
            print(f"Updated: {workflows_doc}")

    # Check root README.adoc as well
    root_readme = base_path / 'README.adoc'
    if root_readme.exists():
        content = root_readme.read_text()
        new_content = pattern.sub(rf'\1@{sha} # v{version}', content)
        if new_content != content:
            root_readme.write_text(new_content)
            modified_files.append(str(root_readme))
            print(f"Updated: {root_readme}")

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
        help='Full 40-character SHA hash'
    )
    parser.add_argument(
        '--path',
        default='.',
        help='Base path to search for workflows (default: current directory)'
    )

    args = parser.parse_args()

    # Validate SHA format
    if len(args.sha) != 40 or not re.match(r'^[a-f0-9]+$', args.sha):
        print(f"Error: SHA must be a 40-character hex string, got: {args.sha}", file=sys.stderr)
        sys.exit(1)

    base_path = Path(args.path).resolve()
    if not base_path.exists():
        print(f"Error: Path does not exist: {base_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Updating workflow references to v{args.version} ({args.sha})")
    print(f"Searching in: {base_path}")

    modified = update_workflow_references(args.version, args.sha, base_path)

    if modified:
        print(f"\nModified {len(modified)} file(s)")
    else:
        print("\nNo files modified")

    return 0 if modified else 1


if __name__ == '__main__':
    sys.exit(main())
