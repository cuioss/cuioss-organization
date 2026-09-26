#!/usr/bin/env python3
"""Decide whether a pull request leaves the cuioss-review-bot reviewer anything to review.

The reviewer workflow (`.github/workflows/reusable-cuioss-review-bot.yml`) ends in a
fail-closed gate: a reviewed `pull_request` run whose reviewer produced no `review` output
fails the job, because PR-Agent's runner exits 0 even when every model call failed. Two
populations reach that gate with an empty output while being legitimately empty:

- (c) a pull request with no files — `PRReviewer.run()` returns before any model call;
- (d) a pull request whose whole diff the runner's own diff-file filter removes —
  `GithubProvider._get_diff_files()` drops every `[ignore]` glob/regex match, then every
  file with an invalid extension or an auto-generated lockfile name, and nothing is left.

The runner emits no marker separating either from a total model failure, so the gate cannot
tell them apart after the fact. This script decides BEFORE the `review` job runs, in the
workflow's `changes` job, and writes `reviewable=false` for both, so `review` is skipped
instead of failing.

The file list is filtered by the runner's OWN code, never by a copy of it: the script runs
inside the same pinned `pragent/pr-agent` image digest the reviewer steps use, applies the
settings exactly the way the action runner does (`apply_repo_settings`, which merges the
image defaults, any extra config, the organization's global `.pr_agent.toml` and the
repository-local one), and asks `GithubProvider.get_diff_files()` for the survivors. A
survivor is a file the reviewer would read. `pr_agent` is imported lazily inside
`load_runner`, so the decision logic imports and is unit-tested without the image.

The decision, over the closed set of outcomes:

- `changed_files == 0`                         -> `reviewable=false` (c)
- the runner's chain resolved, no survivors    -> `reviewable=false` (d)
- the runner's chain resolved, any survivor    -> `reviewable=true`
- the chain could not be resolved              -> `reviewable=true`, fail OPEN

Every anticipated resolution failure fails OPEN into the review: `pr_agent` cannot be
imported, `GITHUB_TOKEN` is unset, the settings load or the GitHub API fails (any exception
PR-Agent's code raises is caught at that one boundary, which also covers an entry point
whose signature moved on a digest bump), `changed_files` exceeds the GitHub file-listing cap
of 3000, or the listing returned fewer files than the pull request changes. A fail-open decision emits exactly one
`::notice::` line with the fixed `classify-review-diff fail-open:` prefix naming the reason;
a resolved decision emits none. Nothing here ever emits `::warning`. An unanticipated
exception in this script's own logic fails the step visibly with a traceback, and the
`review` job still runs, because its `if:` reads an empty output as not-`false`.

Output contract:

- `$GITHUB_OUTPUT` receives exactly one `reviewable=<true|false>` line.
- The FIRST line on stdout is the decision line
  `classify-review-diff: reviewable=<true|false> survivors=<n> settings=<sources>`, so the
  decision, the survivor count and the settings provenance are readable from the head of
  the job log. `survivors=unresolved` marks a decision the chain never resolved, rather
  than a count that was never measured. Everything the runner code prints or logs while
  resolving is buffered and written to stderr AFTER the decision line.

`::error::` is emitted only when the decision cannot be written at all (no
`$GITHUB_OUTPUT`), and is always followed by a non-zero exit.

Usage (inside the pinned PR-Agent image, see the `changes` job):
    GITHUB_TOKEN=... PYTHONPATH=/app python classify-review-diff.py classify \\
        --changed-files 12 --pr-url https://github.com/cuioss/example/pull/7
"""

import argparse
import contextlib
import io
import os
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TextIO

DECISION_PREFIX = "classify-review-diff:"
NOTICE_PREFIX = "classify-review-diff fail-open:"

# GitHub's "list pull request files" endpoint returns at most this many files. Above it the
# runner's filter chain sees a truncated list, so no decision it reaches is about the whole
# pull request.
FILE_LISTING_CAP = 3000

DEFAULT_SETTINGS_SOURCE = "defaults"
UNRESOLVED = "unresolved"


class ResolutionError(Exception):
    """The runner's filter chain could not be resolved; the decision fails open."""


class ClassifierError(Exception):
    """The decision cannot be written at all; the step must fail rather than guess."""


class DiffProvider(Protocol):
    """The part of PR-Agent's `GithubProvider` the classification reads."""

    def get_diff_files(self) -> Sequence[Any]: ...

    def get_files(self) -> Sequence[Any]: ...

    def get_repo_settings(self) -> Any: ...


@dataclass(frozen=True)
class Runner:
    """PR-Agent's own entry points, as the action runner uses them.

    Attributes:
        settings: The runner's settings object (`pr_agent.config_loader.get_settings()`).
        apply_repo_settings: `pr_agent.git_providers.utils.apply_repo_settings`.
        provider: Builds a `GithubProvider` for a pull request URL.
    """

    settings: Any
    apply_repo_settings: Callable[[str], None]
    provider: Callable[[str], DiffProvider]


@dataclass(frozen=True)
class Resolution:
    """What the runner's own filter chain made of the pull request's file list.

    Attributes:
        listed: How many files the file listing returned.
        survivors: The files left after the whole filter chain, in listing order.
        settings: The settings sources the runner's loader read, in precedence order.
    """

    listed: int
    survivors: tuple[str, ...]
    settings: tuple[str, ...]


@dataclass(frozen=True)
class Decision:
    """Whether `review` runs, plus the evidence the decision line reports.

    Attributes:
        reviewable: False only for (c) and (d); every uncertain path is True.
        survivors: The survivor count, or None when the chain was never resolved.
        settings: The settings sources behind a resolved decision.
        notice: The fail-open reason, set exactly when the decision failed open.
    """

    reviewable: bool
    survivors: int | None
    settings: tuple[str, ...] = ()
    notice: str | None = None


Resolver = Callable[[], Resolution]


def fail_open(reason: str) -> Decision:
    """A decision that runs the review because the chain could not be trusted."""
    return Decision(reviewable=True, survivors=None, notice=reason)


def classify(changed_files: int, resolve: Resolver) -> Decision:
    """Decide whether the pull request leaves the reviewer anything to review.

    Args:
        changed_files: The pull request's `changed_files` count from the event payload.
        resolve: Runs the runner's filter chain; called only when the count is in range.

    Returns:
        The decision. It is `reviewable=False` only for a pull request with no files, or
        one whose survivors are empty after a resolution that saw every changed file.
    """
    if changed_files == 0:
        return Decision(reviewable=False, survivors=0)
    if changed_files > FILE_LISTING_CAP:
        return fail_open(
            f"the pull request changes {changed_files} files, above the GitHub file-listing cap of "
            f"{FILE_LISTING_CAP}, so the runner's filter chain cannot see all of them"
        )
    try:
        resolution = resolve()
    except ResolutionError as e:
        return fail_open(str(e))
    if resolution.listed < changed_files:
        return fail_open(
            f"the file listing returned {resolution.listed} of {changed_files} changed files, "
            "so the survivors were computed over an incomplete list"
        )
    return Decision(
        reviewable=bool(resolution.survivors),
        survivors=len(resolution.survivors),
        settings=resolution.settings,
    )


def settings_provenance(settings: Any, repo_settings: Any) -> tuple[str, ...]:
    """Name the settings sources the runner's loader read, in precedence order.

    Args:
        settings: The runner's settings object, after `apply_repo_settings`.
        repo_settings: What `GithubProvider.get_repo_settings()` returns — empty, one local
            file's content, or a list of `(category, content)` pairs such as `global`/`local`.

    Returns:
        `defaults` first, then `extra` when an extra config URL is set, then each repository
        settings category the provider found, when repository settings are in use.
    """
    sources = [DEFAULT_SETTINGS_SOURCE]
    extra = settings.get("CONFIG.EXTRA_CONFIG_URL", None)
    if isinstance(extra, str) and extra.strip():
        sources.append("extra")
    if settings.get("CONFIG.USE_REPO_SETTINGS_FILE", True) and repo_settings:
        if isinstance(repo_settings, (bytes, str)):
            sources.append("local")
        else:
            sources.extend(str(category) for category, _ in repo_settings)
    return tuple(sources)


def load_runner() -> Runner:
    """Import PR-Agent's own entry points from the pinned image.

    Raises:
        ResolutionError: `pr_agent` is not importable (the image or `PYTHONPATH` is wrong),
            or its settings could not be loaded.
    """
    try:
        from pr_agent.config_loader import get_settings
        from pr_agent.git_providers.github_provider import GithubProvider
        from pr_agent.git_providers.utils import apply_repo_settings
    except ImportError as e:
        raise ResolutionError(
            f"pr_agent could not be imported ({e}); the classifier must run inside the pinned image with PYTHONPATH=/app"
        ) from e
    try:
        settings = get_settings()
    except Exception as e:
        raise ResolutionError(f"pr_agent's settings could not be loaded: {type(e).__name__}: {e}") from e
    return Runner(settings=settings, apply_repo_settings=apply_repo_settings, provider=GithubProvider)


def resolve_with_runner(pr_url: str, token: str, load: Callable[[], Runner]) -> Resolution:
    """Run the action runner's settings load and diff-file filter chain for one pull request.

    Mirrors `github_action_runner.run_action()`: the token is set as the user token of a
    `user` deployment, then `apply_repo_settings` merges every settings source, then the
    provider's `get_diff_files()` applies the `[ignore]` filter and the invalid-extension /
    lockfile filter exactly as the reviewer will.

    Args:
        pr_url: The pull request's HTML URL.
        token: The token the provider authenticates with.
        load: Supplies the runner's entry points (`load_runner` in production).

    Returns:
        The listed file count, the survivors, and the settings sources read.

    Raises:
        ResolutionError: The token is missing, `pr_agent` is not importable, or the runner
            code raised — any exception at this boundary is a resolution failure.
    """
    if not token:
        raise ResolutionError("GITHUB_TOKEN is not set, so the pull request's files cannot be listed")
    runner = load()
    try:
        runner.settings.set("GITHUB.USER_TOKEN", token)
        runner.settings.set("GITHUB.DEPLOYMENT_TYPE", "user")
        runner.apply_repo_settings(pr_url)
        provider = runner.provider(pr_url)
        survivors = tuple(str(file.filename) for file in provider.get_diff_files())
        listed = len(provider.get_files())
        sources = settings_provenance(runner.settings, provider.get_repo_settings())
    except Exception as e:
        raise ResolutionError(f"the runner's filter chain could not be resolved: {type(e).__name__}: {e}") from e
    return Resolution(listed=listed, survivors=survivors, settings=sources)


def route_loguru(buffer: io.StringIO) -> Callable[[], None]:
    """Route loguru's handlers into the buffer, returning the call that routes them back.

    PR-Agent logs through loguru, whose default handler is bound to the real stderr at
    import time and so escapes a plain stream redirect. Outside the image loguru is not
    installed, and there is nothing to route.
    """
    try:
        from loguru import logger
    except ImportError:
        return lambda: None
    logger.remove()
    handler = logger.add(buffer, colorize=False)

    def restore() -> None:
        logger.remove(handler)
        logger.add(sys.stderr)

    return restore


@contextlib.contextmanager
def buffered_runner_output(buffer: io.StringIO) -> Iterator[None]:
    """Hold back everything the runner code prints or logs, so the decision line comes first."""
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        restore = route_loguru(buffer)
        try:
            yield
        finally:
            restore()


def annotation_escape(message: str) -> str:
    """Escape a workflow-command message so a multi-line cause stays one annotation."""
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def render_decision_line(decision: Decision) -> str:
    """The fixed-prefix line naming the decision, the survivor count and the settings sources."""
    survivors = UNRESOLVED if decision.survivors is None else str(decision.survivors)
    settings = "+".join(decision.settings) or "none"
    return f"{DECISION_PREFIX} reviewable={str(decision.reviewable).lower()} survivors={survivors} settings={settings}"


def render_stdout(decision: Decision) -> str:
    """The decision line, then — on a fail-open decision only — the one fail-open notice."""
    lines = [render_decision_line(decision)]
    if decision.notice is not None:
        lines.append(f"::notice::{annotation_escape(f'{NOTICE_PREFIX} {decision.notice}')}")
    return "".join(f"{line}\n" for line in lines)


def write_output(path: str, decision: Decision) -> None:
    """Append the one `reviewable=` entry to `$GITHUB_OUTPUT`."""
    with Path(path).open("a", encoding="utf-8") as output:
        output.write(f"reviewable={str(decision.reviewable).lower()}\n")


def cmd_classify(
    args: argparse.Namespace,
    environ: Mapping[str, str],
    load: Callable[[], Runner],
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """Classify the pull request, write the decision, and report it.

    Raises:
        ClassifierError: `$GITHUB_OUTPUT` is not set, so the decision has nowhere to go.
    """
    output_path = environ.get("GITHUB_OUTPUT", "")
    if not output_path:
        raise ClassifierError("GITHUB_OUTPUT is not set, so the reviewable decision cannot be written")
    token = environ.get("GITHUB_TOKEN", "")
    runner_log = io.StringIO()
    try:
        with buffered_runner_output(runner_log):
            decision = classify(args.changed_files, lambda: resolve_with_runner(args.pr_url, token, load))
    except BaseException:
        # An unanticipated failure: release what the runner logged before the traceback.
        stderr.write(runner_log.getvalue())
        raise
    write_output(output_path, decision)
    stdout.write(render_stdout(decision))
    stdout.flush()
    stderr.write(runner_log.getvalue())
    return 0


def non_negative_int(value: str) -> int:
    """Parse a file count, which is never negative."""
    count = int(value)
    if count < 0:
        raise argparse.ArgumentTypeError(f"a file count cannot be negative: {count}")
    return count


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    classify_parser = sub.add_parser("classify", help="Decide whether the pull request is reviewable")
    classify_parser.add_argument(
        "--changed-files", type=non_negative_int, required=True, help="The event's pull_request.changed_files"
    )
    classify_parser.add_argument("--pr-url", required=True, help="The event's pull_request.html_url")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return cmd_classify(args, os.environ, load_runner, sys.stdout, sys.stderr)
    except ClassifierError as e:
        print(f"::error::{annotation_escape(str(e))}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
