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

It also renders the optional *include* spec (`--include`, project.yml
`maven-build.paths-code-extra`): globs that count as code even when they match
an ignore pattern. That cannot be a positive pattern inside the ignore group -
the ignore group is all-negation under `predicate-quantifier: every`, which ANDs
every pattern, so a positive pattern there would demand that a file match it
AND miss every ignore glob, i.e. the ignore list would still win. The include
globs are therefore a second group, evaluated by a second `dorny/paths-filter`
call under the default `some` quantifier, and the caller ORs the two results
(`decide`). An empty include renders an empty spec, the caller skips the second
call, and the gate is exactly what it was before the include list existed.

Usage:
    ./build_paths_filter_spec.py --filter-name code --extra "$EXTRA" --include "$INCLUDE" >> "$GITHUB_OUTPUT"
    ./build_paths_filter_spec.py --decide --code "$CODE" --included "$INCLUDED" >> "$GITHUB_OUTPUT"
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


def build_include_spec(filter_name: str, include: str) -> str:
    """Render the positive include spec, or '' when `include` names no glob.

    Same whitespace splitting as `build_spec`, so a glob stays literal. The
    patterns are positive and meant for the default `some` quantifier: a file
    matching ANY of them is code.
    """
    patterns = include.split()
    if not patterns:
        return ""
    lines = [f"{filter_name}:"]
    lines.extend(f"  - '{pattern}'" for pattern in patterns)
    return "\n".join(lines)


def decide(code: str, included: str) -> str:
    """Combine the two filter results into should-build ('true'/'false').

    `code` is the ignore group's result, `included` the include group's ('' when
    the include call did not run). The include group can only add a build, never
    remove one: with no include match the result is `code` unchanged.
    """
    return "true" if included == "true" else code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--filter-name", default="code", help="dorny/paths-filter group name (default: code)")
    parser.add_argument("--extra", default="", help="Space-separated extra glob patterns to also treat as non-code")
    parser.add_argument(
        "--include",
        default="",
        help="Space-separated glob patterns that count as code even when an ignore pattern matches them",
    )
    parser.add_argument(
        "--include-filter-name",
        default="code-include",
        help="dorny/paths-filter group name of the include spec (default: code-include)",
    )
    parser.add_argument(
        "--decide",
        action="store_true",
        help="Instead of rendering specs, combine --code and --included into should-build",
    )
    parser.add_argument("--code", default="", help="With --decide: the ignore group's result ('true'/'false')")
    parser.add_argument("--included", default="", help="With --decide: the include group's result ('' when not run)")
    args = parser.parse_args()

    if args.decide:
        if args.code not in ("true", "false"):
            # A missing ignore-group result must not read as "docs only": fail
            # the step, so should-build stays '' and the build runs (fail open).
            print(f"--code must be 'true' or 'false', got {args.code!r}", file=sys.stderr)
            return 2
        print(f"should-build={decide(args.code, args.included)}")
        return 0

    print(f"spec<<EOF\n{build_spec(args.filter_name, args.extra)}\nEOF")
    print(f"include-spec<<EOF\n{build_include_spec(args.include_filter_name, args.include)}\nEOF")
    return 0


if __name__ == "__main__":
    sys.exit(main())
