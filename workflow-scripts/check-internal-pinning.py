#!/usr/bin/env python3
"""
Verify that reusable workflows execute only immutably-pinned, in-sync
references to this repository.

A reusable workflow is consumed by pinning it at an immutable SHA. Two things
have to hold at the commit a release tags, or that pin buys the consumer
nothing:

1. **Immutability.** If the tagged commit's own refs point at a mutable ref (a
   tag such as ``@v0.12.0``, or ``@main``), moving that tag silently changes
   the code every consumer runs. OpenSSF Scorecard's Pinned-Dependencies check
   flags exactly this.

2. **Agreement.** Every reference a reusable workflow executes must select the
   *same* commit. Two forms select executed code — ``uses:`` for composite
   actions, and ``repository:``/``ref:`` for the checkout that fetches
   ``workflow-scripts/`` onto the runner — and only the first was ever
   checked. The second was therefore rewritten one pass too late in the release
   job, after the tag had already been created, so v0.22.0 through v0.25.0 each
   tagged a commit whose release job executed the *previous* release's
   ``workflow-scripts/``. Backward-compatible scripts hid it until v0.25.0
   added a flag the v0.24.0 script rejects, and consumer propagation failed
   while the job stayed green.

Run before tagging a release (with ``--expect-sha``, which additionally asserts
the pins name the commit being tagged), and in CI on every change.

Usage:
    ./check-internal-pinning.py [--path /path/to/repo] [--expect-sha <sha>]

Exit codes:
    0 - all executed internal references are SHA-pinned and agree
    1 - at least one mutable, disagreeing, or missing reference found
"""

import argparse
import re
import sys
from pathlib import Path

from internal_refs import (
    SHA_PATTERN,
    find_self_checkouts,
    iter_reusable_workflows,
)

# An executed reference to a cuioss-organization action or workflow.
# Template expressions (release.yml's @${{ steps.sha.outputs.sha }}) are
# resolved at runtime and are not statically checkable, so they are excluded.
#
# YAML permits the value to be quoted (uses: "owner/repo@ref"). Quotes are
# matched and excluded from the captured ref so a quoted mutable reference
# cannot slip past this check — a guard that silently ignores a form it does
# not recognise is worse than no guard.
EXECUTED_REF_PATTERN = re.compile(r"""uses:\s*['"]?(cuioss/cuioss-organization/[^@\s'"]+)@(?!\$\{\{)([^\s#'"]+)""")


class Violation:
    """One reference that would make a release tag unsafe to consume."""

    def __init__(self, path: Path, lineno: int, target: str, detail: str):
        self.path = path
        self.lineno = lineno
        self.target = target
        self.detail = detail

    def render(self, base_path: Path) -> str:
        rel = self.path.relative_to(base_path)
        return f"  {rel}:{self.lineno}: {self.target} — {self.detail}"


def _workflow_files(base_path: Path) -> list[Path]:
    workflows_dir = base_path / ".github" / "workflows"
    if not workflows_dir.exists():
        return []
    return sorted(workflows_dir.glob("*.yml"))


def find_mutable_references(base_path: Path) -> list[Violation]:
    """Return a violation for each executed reference that is not SHA-pinned."""
    violations: list[Violation] = []

    for yml_file in _workflow_files(base_path):
        lines = yml_file.read_text().splitlines()

        for lineno, line in enumerate(lines, start=1):
            # Commented-out lines are usage examples for consumers, not
            # references this workflow executes.
            if line.lstrip().startswith("#"):
                continue

            match = EXECUTED_REF_PATTERN.search(line)
            if match and not SHA_PATTERN.match(match.group(2)):
                violations.append(
                    Violation(
                        yml_file,
                        lineno,
                        f"{match.group(1)}@{match.group(2)}",
                        "mutable ref; a moved tag or branch changes executed code",
                    )
                )

        # The checkout that fetches this repository's workflow-scripts/ selects
        # executed code just as much as a `uses:` ref does, but is spelled
        # `repository:` + `ref:`. Omitting the ref is the worst case of all:
        # actions/checkout then resolves to the default branch.
        for checkout in find_self_checkouts(lines):
            if checkout.runtime_resolved:
                # Resolved at runtime, like release.yml's templated `uses:` ref.
                continue
            if checkout.ref is None:
                violations.append(
                    Violation(
                        yml_file,
                        (checkout.ref_index or checkout.repository_index) + 1,
                        "checkout of cuioss/cuioss-organization",
                        "no usable `ref:` — resolves to the default branch",
                    )
                )
            elif not SHA_PATTERN.match(checkout.ref):
                assert checkout.ref_index is not None
                violations.append(
                    Violation(
                        yml_file,
                        checkout.ref_index + 1,
                        f"checkout of cuioss/cuioss-organization@{checkout.ref}",
                        "mutable ref; a moved tag or branch changes executed code",
                    )
                )

    return violations


def collect_released_pins(base_path: Path) -> list[tuple[Path, int, str, str]]:
    """Return (file, line, description, sha) for every pin the tag ships.

    Scoped to ``reusable-*.yml``: those are the files a consumer executes, and
    the ones the pre-tag pinning pass owns. Caller workflows in this repo
    (dependabot-auto-merge.yml) consume the released *tag* and are updated
    after it exists, so they legitimately carry a different SHA.
    """
    pins: list[tuple[Path, int, str, str]] = []

    for yml_file in iter_reusable_workflows(base_path):
        lines = yml_file.read_text().splitlines()

        for lineno, line in enumerate(lines, start=1):
            if line.lstrip().startswith("#"):
                continue
            match = EXECUTED_REF_PATTERN.search(line)
            if match and SHA_PATTERN.match(match.group(2)):
                pins.append((yml_file, lineno, match.group(1), match.group(2)))

        for checkout in find_self_checkouts(lines):
            if checkout.runtime_resolved:
                continue
            if checkout.ref_index is not None and checkout.ref is not None and SHA_PATTERN.match(checkout.ref):
                pins.append((yml_file, checkout.ref_index + 1, "checkout of cuioss/cuioss-organization", checkout.ref))

    return pins


def find_disagreeing_pins(base_path: Path, expected_sha: str | None) -> list[Violation]:
    """Return a violation for each executed pin that names the wrong commit.

    Without ``expected_sha`` the pins only have to agree with each other; the
    majority SHA is taken as the intended one. With it — the release job, which
    knows the commit about to be tagged — every pin must name that commit.
    """
    pins = collect_released_pins(base_path)
    if not pins:
        return []

    target = expected_sha
    if target is None:
        shas = [sha for _, _, _, sha in pins]
        if len(set(shas)) == 1:
            return []
        target = max(set(shas), key=shas.count)

    reason = (
        "does not match the commit being tagged"
        if expected_sha
        else f"disagrees with the {sum(1 for p in pins if p[3] == target)} other "
        "executed ref(s) in the released workflows"
    )

    return [
        Violation(path, lineno, f"{descr}@{sha}", f"{reason} ({target})")
        for path, lineno, descr, sha in pins
        if sha != target
    ]


def main():
    parser = argparse.ArgumentParser(
        description="Verify reusable workflows execute only SHA-pinned internal references"
    )
    parser.add_argument("--path", default=".", help="Base path of the repository (default: current directory)")
    parser.add_argument(
        "--expect-sha",
        help="Commit the released workflows must pin (the commit about to be "
        "tagged). Without it, the pins only have to agree with each other.",
    )
    args = parser.parse_args()

    base_path = Path(args.path).resolve()
    if not base_path.exists():
        print(f"Error: Path does not exist: {base_path}", file=sys.stderr)
        return 1

    if args.expect_sha and not SHA_PATTERN.match(args.expect_sha):
        print(f"Error: --expect-sha must be a 40-character lowercase hex SHA, got: {args.expect_sha}", file=sys.stderr)
        return 1

    violations = find_mutable_references(base_path)
    violations += find_disagreeing_pins(base_path, args.expect_sha)

    if not violations:
        print("OK: all executed cuioss-organization references are SHA-pinned and name the same commit")
        return 0

    print(f"Error: found {len(violations)} unsafe cuioss-organization reference(s).", file=sys.stderr)
    print(
        "Every reference a released workflow executes — `uses:` refs and the "
        "`ref:` of the checkout that fetches workflow-scripts/ — must be a "
        "40-character SHA naming the commit being tagged. Otherwise the tag "
        "runs code its consumers did not pin.\n",
        file=sys.stderr,
    )
    for violation in violations:
        print(violation.render(base_path), file=sys.stderr)

    return 1


if __name__ == "__main__":
    sys.exit(main())
