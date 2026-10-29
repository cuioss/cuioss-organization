"""Normalize the push trigger of a consumer's build caller workflows.

A branch is built by its ``pull_request`` run. A caller that lists feature, fix or
chore branches in ``on.push.branches`` starts a run on the first push, before any PR
exists, and that run builds the commit a second time once the PR run starts (see
"Push builds on branches" in docs/Workflows.adoc). The release fan-out therefore
removes those patterns from every caller of a reusable build workflow, in the same PR
that bumps the pins.

Edits are line based so comments and formatting survive (the rest of the reference
tooling does the same). A list that cannot be read with certainty is reported and
left untouched; nothing here guesses.

A repository that set ``ci.push-builds: deduplicated`` in ``.github/project.yml``
chose to build every push and keeps its triggers.
"""

import re
from pathlib import Path

# Callers of these reusable workflows are normalized; every other workflow is not.
BUILD_WORKFLOWS = ("reusable-maven-build", "reusable-npm-build", "reusable-pyprojectx-verify")

# Patterns that start a push run before the PR exists. The negation is the
# chore/orchestrator-ledger exclusion this normalization supersedes.
REMOVED_PATTERNS = frozenset(
    {
        "feature/*",
        "feature/**",
        "fix/*",
        "fix/**",
        "chore/*",
        "chore/**",
        "!chore/orchestrator-ledger",
    }
)

STATUS_NOT_A_CALLER = "not_a_caller"
STATUS_UNCHANGED = "unchanged"
STATUS_CHANGED = "changed"
STATUS_UNPARSEABLE = "unparseable"

_CALLER_RE = re.compile(
    r"^\s*uses:\s*cuioss/cuioss-organization/\.github/workflows/(?:" + "|".join(BUILD_WORKFLOWS) + r")\.yml@",
    re.MULTILINE,
)
_ON_RE = re.compile(r"""^(["']?)on\1\s*:\s*(?:#.*)?$""")
_KEY_RE = re.compile(r"^(\s*)([A-Za-z_\"'][^:#]*?)\s*:(.*)$")
_FLOW_RE = re.compile(r"^(?P<head>\s*branches:\s*)\[(?P<body>.*)\](?P<tail>\s*(?:#.*)?)$")
_BLOCK_ITEM_RE = re.compile(r"^(\s*)-\s+(?P<value>.*?)\s*(?:#.*)?$")


def is_build_caller(text: str) -> bool:
    """True if a job of this workflow calls one of the reusable build workflows."""
    return _CALLER_RE.search(text) is not None


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_blank_or_comment(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _unquote(token: str) -> str | None:
    """The plain value of a flow or block scalar, or None if it is not a simple one."""
    token = token.strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        inner = token[1:-1]
        return None if token[0] in inner else inner
    # A plain scalar: `feature/*` is one (`*` only means an alias at the start), but a
    # structural character, a comment, or a YAML indicator up front is not ours to read.
    if not token or token[0] in "&*!|>%@`" or " #" in token or any(c in token for c in "[]{},\"'"):
        return None
    return token


def _split_flow(body: str) -> list[str] | None:
    """Split the inside of a one-line flow sequence on top-level commas, respecting quotes."""
    items: list[str] = []
    current: list[str] = []
    quote = ""
    for char in body:
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
            current.append(char)
        elif char == ",":
            items.append("".join(current))
            current = []
        elif char in "[]{}":
            return None
        else:
            current.append(char)
    if quote:
        return None
    items.append("".join(current))
    if items and not items[-1].strip():
        items.pop()  # a trailing comma is legal
    return items


def _find_push_branches(lines: list[str]) -> tuple[int, int] | str | None:
    """Locate the ``branches:`` line under ``on: push:``.

    Returns (index of the branches line, index of the end of its block), None if the
    workflow has no ``on.push.branches`` to normalize, or an explanation if the
    structure is present but not readable.
    """
    on_index = next((i for i, line in enumerate(lines) if _ON_RE.match(line)), None)
    if on_index is None:
        return None
    push_index = None
    on_end = len(lines)
    child_indent = None
    for i in range(on_index + 1, len(lines)):
        line = lines[i]
        if _is_blank_or_comment(line):
            continue
        if _indent(line) == 0:
            on_end = i
            break
        if child_indent is None:
            child_indent = _indent(line)
        match = _KEY_RE.match(line)
        if match and _indent(line) == child_indent and match.group(2).strip("\"'") == "push":
            push_index = i
    if push_index is None:
        return None
    push_indent = _indent(lines[push_index])
    rest = lines[push_index].split(":", 1)[1].strip()
    if rest and not rest.startswith("#"):
        return "on.push is not a block mapping"
    push_end = on_end
    for i in range(push_index + 1, on_end):
        if not _is_blank_or_comment(lines[i]) and _indent(lines[i]) <= push_indent:
            push_end = i
            break
    branches_index = None
    for i in range(push_index + 1, push_end):
        match = _KEY_RE.match(lines[i])
        if match and match.group(2).strip("\"'") == "branches":
            if branches_index is not None:
                return "on.push.branches appears twice"
            branches_index = i
    if branches_index is None:
        return None
    branches_indent = _indent(lines[branches_index])
    end = branches_index + 1
    while end < push_end and (
        _is_blank_or_comment(lines[end])
        or _indent(lines[end]) > branches_indent
        # YAML lets the dashes of a block sequence sit at the indent of their key
        or (_indent(lines[end]) == branches_indent and lines[end].lstrip().startswith("- "))
    ):
        end += 1
    # A trailing blank or comment line belongs to whatever follows, not to the block.
    while end > branches_index + 1 and _is_blank_or_comment(lines[end - 1]):
        end -= 1
    return branches_index, end


def normalize_push_branches(text: str) -> tuple[str, str, str]:
    """Remove the working-branch patterns from ``on.push.branches``.

    Returns ``(new_text, status, detail)``. ``status`` is one of the STATUS_*
    constants; ``detail`` explains an ``unparseable`` result and is empty otherwise.
    """
    if not is_build_caller(text):
        return text, STATUS_NOT_A_CALLER, ""
    lines = text.split("\n")
    found = _find_push_branches(lines)
    if found is None:
        return text, STATUS_UNCHANGED, ""
    if isinstance(found, str):
        return text, STATUS_UNPARSEABLE, found
    start, end = found

    flow = _FLOW_RE.match(lines[start])
    if flow:
        tokens = _split_flow(flow.group("body"))
        if tokens is None:
            return text, STATUS_UNPARSEABLE, "on.push.branches is a flow list this tool cannot read"
        values = [_unquote(t) for t in tokens]
        if any(v is None for v in values):
            return text, STATUS_UNPARSEABLE, "on.push.branches has an entry this tool cannot read"
        kept = [t.strip() for t, v in zip(tokens, values, strict=True) if v not in REMOVED_PATTERNS]
        if len(kept) == len(tokens):
            return text, STATUS_UNCHANGED, ""
        if not any(not (_unquote(t) or "").startswith("!") for t in kept):
            return text, STATUS_UNPARSEABLE, "removing the patterns would leave no branch to build"
        lines[start] = f"{flow.group('head')}[{', '.join(kept)}]{flow.group('tail')}"
        return "\n".join(lines), STATUS_CHANGED, ""

    rest = lines[start].split(":", 1)[1].strip()
    if rest and not rest.startswith("#"):
        return text, STATUS_UNPARSEABLE, "on.push.branches is not a list this tool can read"

    items: list[tuple[int, str]] = []
    for i in range(start + 1, end):
        if _is_blank_or_comment(lines[i]):
            continue
        match = _BLOCK_ITEM_RE.match(lines[i])
        value = _unquote(match.group("value")) if match else None
        if value is None:
            return text, STATUS_UNPARSEABLE, "on.push.branches has an entry this tool cannot read"
        items.append((i, value))
    drop = {i for i, value in items if value in REMOVED_PATTERNS}
    if not drop:
        return text, STATUS_UNCHANGED, ""
    if not any(not value.startswith("!") for i, value in items if i not in drop):
        return text, STATUS_UNPARSEABLE, "removing the patterns would leave no branch to build"
    return "\n".join(line for i, line in enumerate(lines) if i not in drop), STATUS_CHANGED, ""


_CI_SECTION_RE = re.compile(r"^ci:\s*(?:#.*)?$")
_PUSH_BUILDS_RE = re.compile(r"""^\s+push-builds:\s*["']?deduplicated["']?\s*(?:#.*)?$""")
_CI_FLOW_RE = re.compile(r"""^ci:\s*\{[^}]*\bpush-builds:\s*["']?deduplicated["']?""")


def keeps_push_builds(project_yml: Path) -> bool:
    """True if the repository set ``ci.push-builds: deduplicated`` in its project.yml.

    Read by line, not with PyYAML: the release job does not install it, and this
    decision must not silently fall back to a default when the import is missing.
    """
    if not project_yml.is_file():
        return False
    in_ci = False
    for line in project_yml.read_text(encoding="utf-8").splitlines():
        if _CI_FLOW_RE.match(line):
            return True
        if _CI_SECTION_RE.match(line):
            in_ci = True
        elif in_ci and line and not line[0].isspace() and not line.startswith("#"):
            in_ci = False
        elif in_ci and _PUSH_BUILDS_RE.match(line):
            return True
    return False


def normalize_repo(repo_dir: Path) -> tuple[list[str], list[str]]:
    """Normalize every build caller under ``repo_dir/.github/workflows``.

    Returns ``(changed, notes)``: the repo-relative paths that were rewritten, and
    human-readable notes (a caller left untouched because it could not be read).
    A repository that keeps push builds is not touched at all.
    """
    if keeps_push_builds(repo_dir / ".github" / "project.yml"):
        return [], []
    changed: list[str] = []
    notes: list[str] = []
    workflows = repo_dir / ".github" / "workflows"
    for path in sorted([*workflows.glob("*.yml"), *workflows.glob("*.yaml")]):
        text = path.read_text(encoding="utf-8")
        new_text, status, detail = normalize_push_branches(text)
        relative = path.relative_to(repo_dir).as_posix()
        if status == STATUS_CHANGED:
            path.write_text(new_text, encoding="utf-8")
            changed.append(relative)
        elif status == STATUS_UNPARSEABLE:
            notes.append(f"{relative}: {detail}; push trigger left unchanged, edit it by hand")
    return changed, notes
