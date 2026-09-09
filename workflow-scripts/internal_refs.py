"""Locate the cuioss-organization references a released commit executes.

Two syntactic forms select cuioss-organization code that consumers end up
running, and both must be pinned to the commit the release tags:

1. A composite-action reference::

       uses: cuioss/cuioss-organization/.github/actions/read-project-config@014db4eafdf4e9d32c74a1dd0a3f945c72437b00 # v0.25.1

2. A self-checkout that puts ``workflow-scripts/`` on the runner::

       - uses: actions/checkout@<sha>
         with:
           repository: cuioss/cuioss-organization
           ref: <sha>
           sparse-checkout: workflow-scripts

Form 2 is an executed reference in every sense that matters — its ``ref:``
decides which revision of the scripts runs — but it is not spelled ``uses:``.
Tooling that recognised only form 1 skipped it during the pre-tag pinning pass
and left it to the post-tag pass, so v0.22.0 through v0.25.0 each tagged a
commit whose release job ran the *previous* release's ``workflow-scripts/``.
It stayed invisible while those scripts were backward-compatible, and surfaced
when v0.25.0 added a flag the v0.24.0 script rejects.

This module is the single place that knows both forms, so the rewriter
(``update-workflow-references.py``) and the guard
(``check-internal-pinning.py``) cannot disagree about what counts as executed.
"""

import re
from pathlib import Path
from typing import NamedTuple

# A composite-action reference executed by a reusable workflow.
#
# The trailing comment is matched loosely rather than as `# vX.Y.Z`. Between
# releases these refs may sit on an unreleased main commit — a newly added
# action does not exist at the previous release commit, so it has to — and that
# carries an `# unreleased` marker instead of a version. Matching only the
# version shape would leave the old comment in place and produce
# `@sha # v0.18.0 # unreleased`.
INTERNAL_ACTION_REF_PATTERN = re.compile(
    r"(uses:\s*cuioss/cuioss-organization/\.github/actions/[^@]+)@[^\s#]+([ \t]*#[^\n]*)?"
)

# The `repository:` key naming this repository inside a checkout's `with:` block.
SELF_CHECKOUT_REPOSITORY_PATTERN = re.compile(
    r'^(?P<indent>[ \t]*)repository:\s*[\'"]?cuioss/cuioss-organization[\'"]?\s*(?:#.*)?$'
)

# A `ref:` mapping key holding a literal ref. The ref itself is captured without
# surrounding quotes so a quoted mutable ref cannot slip past the guard.
REF_KEY_PATTERN = re.compile(
    r"^(?P<indent>[ \t]*)(?P<key>ref:[ \t]*)"
    r'[\'"]?(?P<ref>[^\s\'"#]+)[\'"]?(?P<comment>[ \t]*#.*)?$'
)

# Any `ref:` mapping key, whatever its value. Used to tell "this block has a ref
# we could not read" from "this block has no ref at all" — the latter resolves
# to the default branch and must be reported, the former must not be silently
# treated as absent.
REF_ANY_PATTERN = re.compile(r"^[ \t]*ref:([ \t].*)?$")

# A ref supplied by a template expression is resolved at runtime, so it is
# neither statically checkable nor ours to rewrite — the same exclusion the
# `uses:` patterns make for release.yml's `@${{ steps.sha.outputs.sha }}`.
REF_TEMPLATE_PATTERN = re.compile(r'^[ \t]*ref:[ \t]*[\'"]?\$\{\{')

SHA_PATTERN = re.compile(r"^[a-f0-9]{40}$")


class SelfCheckout(NamedTuple):
    """A checkout of this repository found in a workflow file.

    ``repository_index`` and ``ref_index`` are 0-based line indices into the
    list the parser was given; report them as ``index + 1``.

    ``ref`` is ``None`` when the block carries no readable ``ref:``. That is not
    a harmless omission: ``actions/checkout`` then resolves to the default
    branch, which is the most mutable reference possible.

    ``runtime_resolved`` marks a ref given as a template expression. It is
    neither checkable nor rewritable here, so both callers pass over it.
    """

    repository_index: int
    ref_index: int | None
    ref: str | None
    runtime_resolved: bool = False


def is_internal_action_line(line: str) -> bool:
    """True if this line executes a cuioss-organization composite action.

    Commented-out lines are consumer-facing usage examples, not references this
    repository executes, so they are treated as external.
    """
    if line.lstrip().startswith("#"):
        return False
    return INTERNAL_ACTION_REF_PATTERN.search(line) is not None


def _mapping_sibling_indices(lines: list[str], anchor: int, indent: int) -> list[int]:
    """Indices of the keys sharing the mapping that ``anchor`` belongs to.

    Walks outward from the anchor in both directions and stops at the first
    line that dedents out of the mapping. Blank and comment lines do not end a
    YAML mapping, so they are stepped over rather than treated as a boundary —
    a `ref:` separated from its `repository:` by one of them must still be
    found, or the pin it holds would go unguarded.
    """
    siblings: list[int] = []

    for direction in (-1, 1):
        index = anchor + direction
        while 0 <= index < len(lines):
            stripped = lines[index].strip()
            if stripped and not stripped.startswith("#"):
                line_indent = len(lines[index]) - len(lines[index].lstrip())
                if line_indent < indent:
                    break
                if line_indent == indent:
                    siblings.append(index)
            index += direction

    return siblings


def find_self_checkouts(lines: list[str]) -> list[SelfCheckout]:
    """Find every checkout of cuioss-organization in the given lines.

    Args:
        lines: File lines, with or without their line endings.

    Returns:
        One entry per `repository: cuioss/cuioss-organization` key, in file
        order, each carrying the `ref:` from the same `with:` mapping.
    """
    plain = [line.rstrip("\n") for line in lines]
    checkouts: list[SelfCheckout] = []

    for index, line in enumerate(plain):
        if line.lstrip().startswith("#"):
            continue
        repo_match = SELF_CHECKOUT_REPOSITORY_PATTERN.match(line)
        if not repo_match:
            continue

        indent = len(repo_match.group("indent"))
        ref_index: int | None = None
        ref: str | None = None
        runtime_resolved = False
        for sibling in _mapping_sibling_indices(plain, index, indent):
            if not REF_ANY_PATTERN.match(plain[sibling]):
                continue
            ref_index = sibling
            runtime_resolved = REF_TEMPLATE_PATTERN.match(plain[sibling]) is not None
            ref_match = REF_KEY_PATTERN.match(plain[sibling])
            ref = ref_match.group("ref") if ref_match else None
            break

        checkouts.append(SelfCheckout(index, ref_index, ref, runtime_resolved))

    return checkouts


def replace_self_checkout_ref(line: str, sha: str, version: str) -> str:
    """Rewrite a `ref:` line to the given SHA, preserving indentation.

    Returns the line unchanged if it is not a `ref:` line.
    """
    ending = line[len(line.rstrip("\n")) :]
    match = REF_KEY_PATTERN.match(line.rstrip("\n"))
    if not match:
        return line
    return f"{match.group('indent')}{match.group('key')}{sha} # v{version}{ending}"


def iter_reusable_workflows(base_path: Path):
    """Yield the reusable workflow files whose executed refs must be SHA-pinned."""
    workflows_dir = base_path / ".github" / "workflows"
    if workflows_dir.exists():
        yield from sorted(workflows_dir.glob("reusable-*.yml"))
