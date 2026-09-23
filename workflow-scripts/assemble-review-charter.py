#!/usr/bin/env python3
"""Read a consumer repository's cuioss-review-bot declaration.

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

Usage:
    ./assemble-review-charter.py read --http-status 200 --body-file project.yml >> "$GITHUB_OUTPUT"
"""

import argparse
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

DECLARATION_KEY = "cuioss-review-bot"
HTTP_OK = 200
HTTP_NOT_FOUND = 404


class DeclarationError(Exception):
    """The declaration could not be read; the review must fail rather than guess."""


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


def cmd_read(args: argparse.Namespace) -> int:
    body = Path(args.body_file).read_text(encoding="utf-8") if args.http_status == HTTP_OK else ""
    declaration = read_declaration(args.http_status, body)
    # stdout is captured into $GITHUB_OUTPUT (see the module docstring), so only
    # key=value lines go there; everything a reader should see goes to stderr.
    print(f"Review declaration on the default branch: {declaration.outcome.value}", file=sys.stderr)
    print(f"declaration={declaration.outcome.value}")
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
