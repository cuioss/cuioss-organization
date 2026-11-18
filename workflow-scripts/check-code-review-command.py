#!/usr/bin/env python3
"""Refuse a `/review` comment that carries options, before the code-review pass runs it.

The code-review pass (`code-review` job of `.github/workflows/reusable-cuioss-review-bot.yml`)
runs PR-Agent with `CONFIG.PUBLISH_OUTPUT=false`, because PR-Agent would otherwise publish
its review under the security review's persistent header and overwrite that comment. On a
comment-triggered run, PR-Agent parses the comment as a command line and applies every
`--section.key=value` token with `get_settings().set` AFTER the environment — so
`/review --config.publish_output=true` would switch publishing back on, and any other
`--…=…` token could rewrite how the pass runs (its charter included). PR-Agent's own
forbidden-argument list does not cover these keys.

So the pass admits `/review` without options. This script tokenises the comment exactly as
the pinned PR-Agent does (`comment_body.strip().lower()`, every `'` escaped, then `shlex`
in POSIX mode with whitespace splitting — `github_action_runner.run_action` and
`PRAgent._handle_request`) and fails unless the first token is `/review` and no later token
is an option (starts with `-`, before or after stripping quotes). `-i` (incremental review)
is refused too: it renders under a different header, which the publisher would refuse anyway.
A comment PR-Agent could not tokenise is refused as well.

A refusal is one `::error::` annotation and exit 1, failing the job before the reviewer runs.
Free text after the command (`/review please look at the parser`) is accepted: PR-Agent
passes such tokens to the tool as positional arguments, which `/review` ignores.

Usage (the comment body comes from the event, through the environment):
    COMMENT_BODY="$BODY" python3 check-code-review-command.py
"""

import os
import shlex
import sys
from collections.abc import Mapping

COMMAND = "/review"
QUOTES = "\"'"


class CommandError(Exception):
    """The comment is not a plain `/review` command; the code-review pass must not run it."""


def tokenize(body: str) -> list[str]:
    """Split a comment into PR-Agent's command tokens, the way the pinned PR-Agent does.

    Raises:
        CommandError: PR-Agent's tokenizer would reject the comment.
    """
    request = body.strip().lower().replace("'", "\\'")
    lexer = shlex.shlex(request, posix=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError as e:
        raise CommandError(f"the comment cannot be parsed as a command line ({e})") from e


def check_command(body: str) -> None:
    """Accept `/review` with no options; refuse everything else.

    Raises:
        CommandError: The comment is not `/review`, or carries an option token.
    """
    tokens = tokenize(body)
    if not tokens or tokens[0] != COMMAND:
        first = tokens[0] if tokens else ""
        raise CommandError(f"the code-review pass runs only {COMMAND!r}, not {first!r}")
    options = [token for token in tokens[1:] if token.strip(QUOTES).startswith("-")]
    if options:
        raise CommandError(
            f"the code-review pass accepts {COMMAND!r} without options, and this comment carries "
            f"{', '.join(repr(option) for option in options)}: PR-Agent applies option tokens after "
            "the workflow's settings, so they could re-enable publishing over the security review "
            f"or change the code-review charter. Comment a plain {COMMAND!r} to review both passes"
        )


def annotation_escape(message: str) -> str:
    """Escape a workflow-command message so a multi-line cause stays one annotation."""
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def run(environ: Mapping[str, str]) -> int:
    try:
        check_command(environ.get("COMMENT_BODY", ""))
    except CommandError as e:
        print(f"::error::{annotation_escape(str(e))}", file=sys.stderr)
        return 1
    print(f"check-code-review-command: a plain {COMMAND!r}; the code-review pass runs it")
    return 0


def main() -> int:
    return run(os.environ)


if __name__ == "__main__":
    sys.exit(main())
