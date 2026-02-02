#!/usr/bin/env python3
"""
Update cuioss-organization workflow references to SHA-pinned format.

This script scans workflow files and updates references to cuioss-organization
reusable workflows with SHA-pinned versions.

Usage:
    # Update external docs/examples with SHA (default behavior)
    ./update-workflow-references.py --version 0.1.0 --sha abc123...

    # Update internal references in reusable workflows with version tag (before tagging)
    ./update-workflow-references.py --version 0.1.0 --internal-only

    # Full path specification
    ./update-workflow-references.py --version 0.1.0 --sha abc123... --path /path/to/repo
"""

import argparse
import re
import sys
from pathlib import Path


def update_workflow_references(
    version: str,
    base_path: Path,
    sha: str | None = None,
    internal_only: bool = False
) -> list[str]:
    """
    Update cuioss-organization references in workflow files.

    Args:
        version: Version string (e.g., "0.1.0")
        base_path: Base path to search for workflows
        sha: Full 40-character SHA hash (required unless internal_only=True)
        internal_only: If True, only update internal references in reusable workflows
                      using version tag format (@v{version}) instead of SHA

    Returns:
        List of modified file paths
    """
    modified_files = []

    # Determine the reference format based on mode
    if internal_only:
        ref_format = f'v{version}'
        comment_suffix = ''
    else:
        assert sha is not None, "SHA required when not in internal-only mode"
        ref_format = sha
        comment_suffix = f' # v{version}'

    # Pattern to match cuioss-organization workflow references
    # Matches: cuioss/cuioss-organization/.github/workflows/reusable-<workflow>.yml@<ref>
    # With optional trailing comment
    workflow_pattern = re.compile(
        r'(uses:\s*cuioss/cuioss-organization/\.github/workflows/reusable-[^@]+\.yml)@[^\s#]+(\s*#\s*v[\d.]+)?'
    )

    # Pattern to match cuioss-organization action references
    # Matches: cuioss/cuioss-organization/.github/actions/<action-name>@<ref>
    # With optional trailing comment
    action_pattern = re.compile(
        r'(uses:\s*cuioss/cuioss-organization/\.github/actions/[^@]+)@[^\s#]+(\s*#\s*v[\d.]+)?'
    )

    def apply_patterns(content: str) -> str:
        """Apply both workflow and action patterns to content."""
        result = workflow_pattern.sub(rf'\1@{ref_format}{comment_suffix}', content)
        result = action_pattern.sub(rf'\1@{ref_format}{comment_suffix}', result)
        return result

    # Search in .github/workflows/
    workflows_dir = base_path / '.github' / 'workflows'
    if workflows_dir.exists():
        for yml_file in workflows_dir.glob('**/*.yml'):
            # In internal_only mode, only process reusable workflows
            if internal_only and not yml_file.name.startswith('reusable-'):
                continue
            # In normal mode, skip reusable workflows (they use version tags)
            if not internal_only and yml_file.name.startswith('reusable-'):
                continue
            # Always skip release.yml - it contains template placeholders like ${{ steps.sha.outputs.sha }}
            if yml_file.name == 'release.yml':
                continue

            content = yml_file.read_text()
            new_content = apply_patterns(content)
            if new_content != content:
                yml_file.write_text(new_content)
                modified_files.append(str(yml_file))
                print(f"Updated: {yml_file}")

    # In internal-only mode, we're done after processing reusable workflows
    if internal_only:
        return modified_files

    # Also update docs/Workflows.adoc if present
    workflows_doc = base_path / 'docs' / 'Workflows.adoc'
    if workflows_doc.exists():
        content = workflows_doc.read_text()
        new_content = apply_patterns(content)
        if new_content != content:
            workflows_doc.write_text(new_content)
            modified_files.append(str(workflows_doc))
            print(f"Updated: {workflows_doc}")

    # Also update docs/workflow-examples/ if present
    examples_dir = base_path / 'docs' / 'workflow-examples'
    if examples_dir.exists():
        for yml_file in examples_dir.glob('*.yml'):
            content = yml_file.read_text()
            new_content = apply_patterns(content)
            if new_content != content:
                yml_file.write_text(new_content)
                modified_files.append(str(yml_file))
                print(f"Updated: {yml_file}")

    # Check root README.adoc as well
    root_readme = base_path / 'README.adoc'
    if root_readme.exists():
        content = root_readme.read_text()
        new_content = apply_patterns(content)
        if new_content != content:
            root_readme.write_text(new_content)
            modified_files.append(str(root_readme))
            print(f"Updated: {root_readme}")

    # Update action README files (both .md and .adoc)
    actions_dir = base_path / '.github' / 'actions'
    if actions_dir.exists():
        for pattern in ['**/README.md', '**/README.adoc']:
            for readme_file in actions_dir.glob(pattern):
                content = readme_file.read_text()
                new_content = apply_patterns(content)
                if new_content != content:
                    readme_file.write_text(new_content)
                    modified_files.append(str(readme_file))
                    print(f"Updated: {readme_file}")

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
        required=False,
        help='Full 40-character SHA hash (required unless --internal-only is used)'
    )
    parser.add_argument(
        '--path',
        default='.',
        help='Base path to search for workflows (default: current directory)'
    )
    parser.add_argument(
        '--internal-only',
        action='store_true',
        help='Only update internal references in reusable workflows using version tag format'
    )

    args = parser.parse_args()

    # Validate arguments
    if not args.internal_only and not args.sha:
        print("Error: --sha is required unless --internal-only is specified", file=sys.stderr)
        sys.exit(1)

    if args.sha and (len(args.sha) != 40 or not re.match(r'^[a-f0-9]+$', args.sha)):
        print(f"Error: SHA must be a 40-character hex string, got: {args.sha}", file=sys.stderr)
        sys.exit(1)

    base_path = Path(args.path).resolve()
    if not base_path.exists():
        print(f"Error: Path does not exist: {base_path}", file=sys.stderr)
        sys.exit(1)

    if args.internal_only:
        print(f"Updating internal workflow references to v{args.version}")
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
