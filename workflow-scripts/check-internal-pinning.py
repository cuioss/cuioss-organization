#!/usr/bin/env python3
"""
Verify that reusable workflows execute only immutably-pinned actions.

A reusable workflow is consumed by pinning it at an immutable SHA. If that
commit's own ``uses:`` refs point at a mutable ref (a tag such as ``@v0.12.0``,
or ``@main``), moving that tag silently changes the code every consumer runs —
so the consumer's SHA pin buys nothing. OpenSSF Scorecard's Pinned-Dependencies
check flags exactly this.

Run before tagging a release, and in CI on every change.

Usage:
    ./check-internal-pinning.py [--path /path/to/repo]

Exit codes:
    0 - all executed internal references are SHA-pinned
    1 - at least one mutable reference found
"""

import argparse
import re
import sys
from pathlib import Path

# An executed reference to a cuioss-organization action or workflow.
# Template expressions (release.yml's @${{ steps.sha.outputs.sha }}) are
# resolved at runtime and are not statically checkable, so they are excluded.
#
# YAML permits the value to be quoted (uses: "owner/repo@ref"). Quotes are
# matched and excluded from the captured ref so a quoted mutable reference
# cannot slip past this check — a guard that silently ignores a form it does
# not recognise is worse than no guard.
EXECUTED_REF_PATTERN = re.compile(
    r"""uses:\s*['"]?(cuioss/cuioss-organization/[^@\s'"]+)@(?!\$\{\{)([^\s#'"]+)"""
)

SHA_PATTERN = re.compile(r'^[a-f0-9]{40}$')


def find_mutable_references(base_path: Path) -> list[tuple[Path, int, str, str]]:
    """Return (file, line number, target, ref) for each mutable executed ref."""
    violations: list[tuple[Path, int, str, str]] = []

    workflows_dir = base_path / '.github' / 'workflows'
    if not workflows_dir.exists():
        return violations

    for yml_file in sorted(workflows_dir.glob('*.yml')):
        for lineno, line in enumerate(yml_file.read_text().splitlines(), start=1):
            # Commented-out lines are usage examples for consumers, not
            # references this workflow executes.
            if line.lstrip().startswith('#'):
                continue

            match = EXECUTED_REF_PATTERN.search(line)
            if match and not SHA_PATTERN.match(match.group(2)):
                violations.append((yml_file, lineno, match.group(1), match.group(2)))

    return violations


def main():
    parser = argparse.ArgumentParser(
        description='Verify reusable workflows execute only SHA-pinned internal references'
    )
    parser.add_argument(
        '--path',
        default='.',
        help='Base path of the repository (default: current directory)'
    )
    args = parser.parse_args()

    base_path = Path(args.path).resolve()
    if not base_path.exists():
        print(f"Error: Path does not exist: {base_path}", file=sys.stderr)
        return 1

    violations = find_mutable_references(base_path)

    if not violations:
        print("OK: all executed cuioss-organization references are SHA-pinned")
        return 0

    print(
        f"Error: found {len(violations)} mutable cuioss-organization reference(s).",
        file=sys.stderr
    )
    print(
        "These must be pinned to a 40-character SHA — a consumer pinning this "
        "commit would otherwise execute code that a moved tag can change.\n",
        file=sys.stderr
    )
    for path, lineno, target, ref in violations:
        rel = path.relative_to(base_path)
        print(f"  {rel}:{lineno}: {target}@{ref}", file=sys.stderr)

    return 1


if __name__ == '__main__':
    sys.exit(main())
