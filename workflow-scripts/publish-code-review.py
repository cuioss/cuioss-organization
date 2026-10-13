#!/usr/bin/env python3
"""Publish the cuioss-review-bot code review — the workflow's second pass — as its own comment.

The reviewer workflow (`.github/workflows/reusable-cuioss-review-bot.yml`) runs PR-Agent
twice when a repository opts in to the second pass with `cuioss-review-bot.code_review`:
once under the security charter, as before, and once under the composed code-review
charter. Both are `/review` runs, and PR-Agent publishes every review under one persistent
header, `## PR Reviewer Guide 🔍`, updating the comment that starts with it in place. Left
to itself the second pass would therefore overwrite the first pass's comment.

So the second pass runs with `CONFIG.PUBLISH_OUTPUT=false` and publishes nothing itself;
it still writes its structured `review` output, which PR-Agent emits before the publish
decision. This script renders that output with the image's own `convert_to_markdown_v2`,
replaces the leading `## PR Reviewer Guide 🔍` header with `## PR Code Review Guide 🧭`, and
publishes it through `GithubProvider.publish_persistent_comment_full` under the new header —
so it creates, or updates in place, a comment of its own. The two headers share no prefix
either way, so neither pass's persistent-comment lookup can find the other's comment.

`publish_persistent_comment_full` catches its own failures and falls back to a fresh comment
without reporting either outcome, so the script does not trust it: it reads the pull
request's comments back and fails unless one opens with the new header and carries exactly
the review this run rendered, once the provider's `#### (Code review updated until commit …)`
line is set aside and line endings are normalised. Content is the only proof. A timestamp is
not: comment-triggered runs are not serialised (one concurrency group per comment, nothing
cancelled), so an overlapping run's update can leave a fresh comment that carries another
run's review. Content identity also holds when a re-run on an unchanged commit renders
byte-identical text and GitHub leaves `updated_at` alone. Only then does it write
`published=true` to `$GITHUB_OUTPUT`.

Environment (the step runs inside the pinned PR-Agent image, like `classify-review-diff.py`):

- `REVIEW`       — the second pass's `review` output: the review mapping as one JSON object.
- `PR_URL`       — the pull request's HTML URL.
- `GITHUB_TOKEN` — the reviewer's App token; the comment is published under its identity.

Every failure exits 1 with one `::error::` annotation naming the cause; nothing is ever
downgraded to a warning. `pr_agent` is imported lazily inside `load_runtime`, so the logic
imports and is unit-tested without the image.

Usage (inside the pinned PR-Agent image, see the `code-review` job):
    REVIEW=... PR_URL=... GITHUB_TOKEN=... PYTHONPATH=/app \\
        python publish-code-review.py
"""

import json
import os
import re
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TextIO

# The header PR-Agent renders every review under (`PRReviewHeader.REGULAR` + " 🔍" in the
# pinned image), and the one the second pass publishes under instead.
REVIEWER_GUIDE_HEADER = "## PR Reviewer Guide 🔍"
CODE_REVIEW_HEADER = "## PR Code Review Guide 🧭"
# `publish_persistent_comment_full` names the comment in its "updated until commit" line.
COMMENT_NAME = "code review"
# The line `publish_persistent_comment_full` inserts after the header when it updates an
# existing comment: f"{initial_header}\n\n#### ({name.capitalize()} updated until commit {url})\n".
UPDATE_LINE = re.compile(
    re.escape(CODE_REVIEW_HEADER)
    + r"\n\n#### \("
    + re.escape(COMMENT_NAME.capitalize())
    + r" updated until commit [^\n]*\)\n"
)


class PublishError(Exception):
    """The code review could not be rendered, published or verified; the step must fail."""


class Comment(Protocol):
    """The part of a PyGithub `IssueComment` the read-back check reads."""

    body: str


class Provider(Protocol):
    """The part of PR-Agent's `GithubProvider` this script uses."""

    def publish_persistent_comment_full(
        self,
        pr_comment: str,
        initial_header: str,
        update_header: bool = True,
        name: str = "review",
        final_update_message: bool = True,
    ) -> Any:
        """Update the comment opening with `initial_header` in place, or publish a new one."""

    def get_issue_comments(self) -> Iterable[Comment]:
        """The pull request's issue comments, read from the API."""


@dataclass(frozen=True)
class Runtime:
    """PR-Agent's own entry points, as the action runner uses them.

    Attributes:
        provider: Builds a `GithubProvider` for a pull request URL, after the settings load.
        render: `pr_agent.algo.utils.convert_to_markdown_v2`, bound to that provider.
    """

    provider: Provider
    render: Callable[[dict[str, Any]], str]


def parse_review(raw: str) -> dict[str, Any]:
    """Parse the second pass's `review` output.

    Raises:
        PublishError: The output is empty, not JSON, or not a non-empty JSON object.
    """
    if not raw.strip():
        raise PublishError("REVIEW is empty: the code-review pass produced no review output to publish")
    try:
        review = json.loads(raw)
    except json.JSONDecodeError as e:
        raise PublishError(f"REVIEW is not JSON: {e}") from e
    if not isinstance(review, dict) or not review:
        raise PublishError(f"REVIEW is not a non-empty JSON object: {type(review).__name__}")
    return review


def swap_header(markdown: str) -> str:
    """Replace the rendered review's leading reviewer-guide header with the code-review one.

    Raises:
        PublishError: The rendered review does not open with the reviewer-guide header —
            the rendering is not the one this script was verified against, so publishing it
            under a guessed header could collide with the first pass's comment.
    """
    if not markdown.startswith(REVIEWER_GUIDE_HEADER):
        raise PublishError(
            f"the rendered review does not open with {REVIEWER_GUIDE_HEADER!r}; "
            "the pinned image's rendering changed, so the header cannot be replaced safely"
        )
    return CODE_REVIEW_HEADER + markdown[len(REVIEWER_GUIDE_HEADER) :]


def is_code_review_comment(body: str) -> bool:
    """Whether a comment is the second pass's: the same prefix test the persistent lookup applies."""
    return body.startswith(CODE_REVIEW_HEADER)


def published_content(body: str) -> str:
    """A comment body with the provider's "updated until commit" line removed, line endings normalised."""
    body = body.replace("\r\n", "\n")
    match = UPDATE_LINE.match(body)
    return body if match is None else CODE_REVIEW_HEADER + body[match.end() :]


def carries_review(body: str, published: str) -> bool:
    """Whether a comment body is the markdown this run published, as created or as updated in place."""
    return published_content(body).rstrip() == published.replace("\r\n", "\n").rstrip()


def verified_code_review_comments(comments: Iterable[Comment], published: str) -> list[Comment]:
    """The code-review comments carrying exactly the markdown this run published.

    Only content proves the comment is this run's: a comment updated by an overlapping run is
    as fresh as this run's own, and a byte-identical re-publish may not move `updated_at`.
    """
    return [
        comment
        for comment in comments
        if is_code_review_comment(comment.body or "") and carries_review(comment.body or "", published)
    ]


def publish(review: dict[str, Any], runtime: Runtime) -> int:
    """Render, publish and verify the code review.

    Returns:
        How many code-review comments the read-back verified (at least one).

    Raises:
        PublishError: The rendering is empty or unexpected, or no comment carries this run's
            review.
    """
    markdown = runtime.render({"review": review})
    if not markdown.strip():
        raise PublishError("the image's renderer produced an empty review from a non-empty review output")
    published = swap_header(markdown)
    runtime.provider.publish_persistent_comment_full(
        published,
        initial_header=CODE_REVIEW_HEADER,
        update_header=True,
        name=COMMENT_NAME,
        final_update_message=False,
    )
    verified = verified_code_review_comments(runtime.provider.get_issue_comments(), published)
    if not verified:
        raise PublishError(
            f"no {CODE_REVIEW_HEADER!r} comment carries this run's review; the publish failed, or "
            "another run's review replaced it — read this step's log for PR-Agent's own error"
        )
    return len(verified)


def load_runtime(pr_url: str, token: str) -> Runtime:
    """Import PR-Agent's own entry points from the pinned image and bind them to the pull request.

    Mirrors `github_action_runner.run_action()`: the token is set as the user token of a
    `user` deployment, then `apply_repo_settings` merges every settings source, so the review
    is rendered under the settings the reviewer ran with.

    Raises:
        PublishError: The token is missing or `pr_agent` is not importable.
    """
    if not token:
        raise PublishError("GITHUB_TOKEN is not set, so the code review cannot be published")
    try:
        from pr_agent.algo.utils import convert_to_markdown_v2
        from pr_agent.config_loader import get_settings
        from pr_agent.git_providers.github_provider import GithubProvider
        from pr_agent.git_providers.utils import apply_repo_settings
    except ImportError as e:
        raise PublishError(
            f"pr_agent could not be imported ({e}); the publisher must run inside the pinned image with PYTHONPATH=/app"
        ) from e
    settings = get_settings()
    settings.set("GITHUB.USER_TOKEN", token)
    settings.set("GITHUB.DEPLOYMENT_TYPE", "user")
    apply_repo_settings(pr_url)
    provider = GithubProvider(pr_url)

    def render(output_data: dict[str, Any]) -> str:
        return str(
            convert_to_markdown_v2(
                output_data,
                provider.is_supported("gfm_markdown"),
                None,
                git_provider=provider,
                files=provider.get_diff_files(),
            )
        )

    return Runtime(provider=provider, render=render)


def annotation_escape(message: str) -> str:
    """Escape a workflow-command message so a multi-line cause stays one annotation."""
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def cmd_publish(
    environ: Mapping[str, str],
    load: Callable[[str, str], Runtime],
    stdout: TextIO,
) -> int:
    """Publish the code review and record `published=true` once the read-back confirms it.

    Raises:
        PublishError: Any input is missing or malformed, or the publish could not be verified.
    """
    output_path = environ.get("GITHUB_OUTPUT", "")
    if not output_path:
        raise PublishError("GITHUB_OUTPUT is not set, so the published decision cannot be written")
    review = parse_review(environ.get("REVIEW", ""))
    pr_url = environ.get("PR_URL", "")
    if not pr_url:
        raise PublishError("PR_URL is not set, so there is no pull request to publish to")
    verified = publish(review, load(pr_url, environ.get("GITHUB_TOKEN", "")))
    with Path(output_path).open("a", encoding="utf-8") as output:
        output.write("published=true\n")
    stdout.write(f"publish-code-review: published as {CODE_REVIEW_HEADER!r} ({verified} verified comment(s))\n")
    return 0


def main() -> int:
    try:
        return cmd_publish(os.environ, load_runtime, sys.stdout)
    except PublishError as e:
        print(f"::error::{annotation_escape(str(e))}", file=sys.stderr)
        return 1
    except Exception as e:
        # PR-Agent's own code raised (the GitHub API, the settings load): still one named error.
        print(
            f"::error::{annotation_escape(f'publishing the code review failed: {type(e).__name__}: {e}')}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
