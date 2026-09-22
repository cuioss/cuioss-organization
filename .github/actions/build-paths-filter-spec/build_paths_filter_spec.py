#!/usr/bin/env python3
"""Build the dorny/paths-filter spec for a "docs-only" skip gate.

Three reusable workflows each independently skip their expensive jobs when a
diff touches only non-code paths: reusable-maven-build.yml's `check-changes`,
reusable-maven-integration-tests.yml's `check-changes`, and
reusable-pyprojectx-verify.yml's `buildable` filter. They used to each carry
their own copy of the same ignore-list `echo` lines — one drifted missing
`.gitignore` while the other two had it, and a later fix for one still left
an unquoted `for pattern in $EXTRA` bash loop performing pathname expansion
on a caller-supplied glob (see cuioss-organization#278's follow-ups). This
script is the single source of truth so that class of drift is no longer
possible, and a glob stays a literal string all the way to
`dorny/paths-filter` — argparse and Python's own string handling take care
of quoting/splitting correctly where the bash version could not.

Usage:
    ./build_paths_filter_spec.py --filter-name code --extra "$EXTRA" >> "$GITHUB_OUTPUT"
"""

import argparse
import sys

# Pure repo metadata / dev-tooling config: none of these affect what a build,
# test run, or Sonar analysis actually produces, so a diff touching only these
# is treated as non-code everywhere this ignore list is used.
BASE_IGNORED_PATTERNS = [
    "**/*.adoc",
    "**/*.md",
    "doc/**",
    ".plan/**",
    ".claude/**",
    ".agents/**",
    ".opencode/**",
    "opencode.json",
    ".vscode/**",
    ".gitignore",
    ".github/project.yml",
    ".github/dependabot.yml",
    "LICENSE",
    "NOTICE",
]


def build_spec(filter_name: str, extra: str) -> str:
    """Render the dorny/paths-filter spec YAML for one filter group.

    `extra` is whitespace-separated (never shell-globbed - Python's own
    `str.split()` treats it as plain text, unlike a bash `for` loop over an
    unquoted variable, which would also pathname-expand any glob that happens
    to match a file in the current working directory).
    """
    patterns = [*BASE_IGNORED_PATTERNS, *extra.split()]
    lines = [f"{filter_name}:"]
    lines.extend(f"  - '!{pattern}'" for pattern in patterns)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--filter-name", default="code", help="dorny/paths-filter group name (default: code)")
    parser.add_argument("--extra", default="", help="Space-separated extra glob patterns to also treat as non-code")
    args = parser.parse_args()

    print(f"spec<<EOF\n{build_spec(args.filter_name, args.extra)}\nEOF")
    return 0


if __name__ == "__main__":
    sys.exit(main())
