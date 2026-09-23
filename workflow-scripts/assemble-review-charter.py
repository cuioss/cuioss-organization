#!/usr/bin/env python3
"""Read a consumer repository's cuioss-review-bot declaration and compose its charter.

The reviewer workflow (`.github/workflows/reusable-cuioss-review-bot.yml`) reads the
calling repository's `.github/project.yml` through the contents API at the repository's
DEFAULT branch — never the pull request head, because reading the head would let an
author change the rules that review their own pull request. The workflow performs the
fetch and hands this script the HTTP status and the response body; the script decides
what the answer means.

Three read outcomes, and only three:

- `file-absent`   — the API answered 404: the repository carries no `.github/project.yml`.
- `block-absent`  — the file exists but declares no `cuioss-review-bot` block.
- `block-present` — the file declares a `cuioss-review-bot` block.

Every other answer is a failure, never "absent": an unreadable declaration read as
"nothing declared" would silently discard a declaration its owner believes is live.

A declared block is composed into the reviewer charter from the artifacts published
under `packs/` in the settings repository cuioss/cuioss-review-bot, read at its default
branch: the spine artifact first, always — it is not selectable — then each pack the
block names under `packs:`, in declared order, then the block's `additional_rules`.
Composition is append-only: nothing a repository declares can remove, replace or
precede the spine.

Usage:
    GH_TOKEN=... ./assemble-review-charter.py read \\
        --http-status 200 --body-file project.yml >> "$GITHUB_OUTPUT"
"""

import argparse
import os
import re
import secrets
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

DECLARATION_KEY = "cuioss-review-bot"
HTTP_OK = 200
HTTP_NOT_FOUND = 404

SETTINGS_REPOSITORY = "cuioss/cuioss-review-bot"
SPINE_KEY = "spine"
PACK_URL = "https://api.github.com/repos/{repository}/contents/packs/{key}.md"
FETCH_TIMEOUT = 30

# A pack key names a file under packs/, so it is restricted to the characters an
# artifact stem uses. Anything else — a path separator, "..", a query string — could
# address something other than a published artifact.
PACK_KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# Every published artifact opens with this generated-header comment. It is addressed at
# a human browsing the settings repository, not at the reviewer, so it is stripped.
GENERATED_HEADER_PREFIX = "<!-- GENERATED ARTIFACT"
COMMENT_END = "-->"

ADDITIONAL_RULES_HEADING = "Additional rules for this repository:"

PackFetcher = Callable[[str], str]


class DeclarationError(Exception):
    """The declaration could not be read or composed; the review must fail rather than guess."""


class ReadOutcome(Enum):
    """What the default-branch read established about the declaration."""

    FILE_ABSENT = "file-absent"
    BLOCK_ABSENT = "block-absent"
    BLOCK_PRESENT = "block-present"


@dataclass(frozen=True)
class Declaration:
    """The read outcome, plus the declared block when there is one."""

    outcome: ReadOutcome
    block: Any = None


def read_declaration(http_status: int, body: str) -> Declaration:
    """Interpret the contents-API answer for `.github/project.yml`.

    Args:
        http_status: The HTTP status the contents API answered with.
        body: The raw response body (the file content on 200, ignored otherwise).

    Returns:
        The read outcome, carrying the `cuioss-review-bot` block when it is present.

    Raises:
        DeclarationError: The answer is neither the file nor a 404, or the file is
            not a YAML mapping.
    """
    if http_status == HTTP_NOT_FOUND:
        return Declaration(ReadOutcome.FILE_ABSENT)
    if http_status != HTTP_OK:
        raise DeclarationError(
            f"reading .github/project.yml from the default branch answered HTTP {http_status}; "
            "an unreadable declaration is never treated as absent"
        )

    document = yaml.safe_load(body)
    if document is None:
        return Declaration(ReadOutcome.BLOCK_ABSENT)
    if not isinstance(document, dict):
        raise DeclarationError(".github/project.yml is not a YAML mapping")
    if DECLARATION_KEY not in document:
        return Declaration(ReadOutcome.BLOCK_ABSENT)
    return Declaration(ReadOutcome.BLOCK_PRESENT, document[DECLARATION_KEY])


def fetch_pack(key: str, token: str) -> str:
    """Read one published artifact from the settings repository's default branch.

    Args:
        key: The artifact stem (`spine`, or a domain pack key).
        token: A token with read access to the settings repository.

    Returns:
        The raw artifact text.

    Raises:
        DeclarationError: The key names no published artifact, or the read failed.
    """
    request = urllib.request.Request(
        PACK_URL.format(repository=SETTINGS_REPOSITORY, key=key),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.raw+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == HTTP_NOT_FOUND:
            raise DeclarationError(
                f"unknown pack key {key!r}: {SETTINGS_REPOSITORY} publishes no packs/{key}.md"
            ) from e
        raise DeclarationError(f"pack {key!r} could not be fetched from {SETTINGS_REPOSITORY}: HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise DeclarationError(f"pack {key!r} could not be fetched from {SETTINGS_REPOSITORY}: {e}") from e


def strip_generated_header(artifact: str) -> str:
    """Drop the generated-header comment an artifact opens with, keeping its body."""
    text = artifact.lstrip()
    if text.startswith(GENERATED_HEADER_PREFIX):
        end = text.find(COMMENT_END)
        if end == -1:
            raise DeclarationError("a published artifact opens a generated header that never closes")
        text = text[end + len(COMMENT_END) :]
    return text.strip()


def resolve_pack_keys(packs: Sequence[str]) -> list[str]:
    """Validate the declared pack keys, keeping their declared order.

    Raises:
        DeclarationError: A key names the spine, or is not a well-formed artifact stem.
    """
    for key in packs:
        if key == SPINE_KEY:
            raise DeclarationError(
                f"packs: names {SPINE_KEY!r}; the spine is always applied first and is not selectable"
            )
        if not isinstance(key, str) or not PACK_KEY_PATTERN.fullmatch(key):
            raise DeclarationError(f"unknown pack key {key!r}: not a published artifact name")
    return list(packs)


def compose_charter(spine: str, packs: Sequence[str], additional_rules: Sequence[str]) -> str:
    """Join the charter parts, spine first, then packs in order, then the repository's rules.

    Args:
        spine: The spine artifact body.
        packs: The selected pack bodies, in declared order.
        additional_rules: The repository's own rules, appended after every pack.

    Returns:
        The composed charter text.
    """
    sections = [spine, *packs]
    if additional_rules:
        sections.append("\n".join([ADDITIONAL_RULES_HEADING, *(f"- {rule}" for rule in additional_rules)]))
    return "\n\n".join(sections)


def assemble_charter(block: dict[str, Any], fetch: PackFetcher) -> str:
    """Compose the charter a declared block selects.

    Args:
        block: The `cuioss-review-bot` block.
        fetch: Reads one published artifact by key.

    Returns:
        The composed charter text.
    """
    keys = resolve_pack_keys(block.get("packs") or [])
    spine = strip_generated_header(fetch(SPINE_KEY))
    packs = [strip_generated_header(fetch(key)) for key in keys]
    return compose_charter(spine, packs, block.get("additional_rules") or [])


def github_output_multiline(name: str, value: str) -> str:
    """Render a multi-line GITHUB_OUTPUT entry under a random, collision-free delimiter."""
    delimiter = f"EOF_{secrets.token_hex(16)}"
    while delimiter in value:
        delimiter = f"EOF_{secrets.token_hex(16)}"
    return f"{name}<<{delimiter}\n{value}\n{delimiter}\n"


def cmd_read(args: argparse.Namespace) -> int:
    body = Path(args.body_file).read_text(encoding="utf-8") if args.http_status == HTTP_OK else ""
    declaration = read_declaration(args.http_status, body)
    # stdout is captured into $GITHUB_OUTPUT (see the module docstring), so only
    # output entries go there; everything a reader should see goes to stderr.
    print(f"Review declaration on the default branch: {declaration.outcome.value}", file=sys.stderr)
    output = [f"declaration={declaration.outcome.value}\n"]
    if declaration.outcome is ReadOutcome.BLOCK_PRESENT:
        token = os.environ.get("GH_TOKEN", "")
        charter = assemble_charter(declaration.block, lambda key: fetch_pack(key, token))
        output.append(github_output_multiline("charter", charter))
    sys.stdout.write("".join(output))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    read = sub.add_parser("read", help="Interpret the default-branch read of .github/project.yml")
    read.add_argument("--http-status", type=int, required=True, help="HTTP status of the contents-API read")
    read.add_argument("--body-file", required=True, help="File holding the response body")

    args = parser.parse_args()
    try:
        return cmd_read(args)
    except DeclarationError as e:
        print(f"::error::{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
