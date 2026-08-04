#!/usr/bin/env python3
"""Decide whether a Maven release invocation may proceed.

``reusable-maven-release.yml`` is ``on: workflow_call``, so its trigger lives in
each calling repository and cannot be centralised. The *decision* can be, and
this is it.

The rule:

* ``workflow_dispatch`` proceeds unconditionally. The deliberate path must stay
  able to force a release, including re-releasing an unchanged version.
* Any other event releases only when ``release.current-version`` in
  ``.github/project.yml`` actually changed on this commit, and no tag for that
  version exists yet.

Why version-changed rather than merged-ness: ``project.yml`` also carries
``maven-build``, ``sonar``, ``pages``, ``github-automation``, ``consumers`` and
``dependency-propagation``. A caller filtering on ``paths: ['.github/project.yml']``
fires on an ordinary Java-version bump too, and a ``merged == true`` guard does
not distinguish the two. On 2026-07-12 that published an irrevocable
``de.cuioss.sheriff.api:*:1.0.0``.

Why the already-tagged refusal is load-bearing rather than belt-and-braces:
``release:prepare`` never writes ``current-version`` back to ``project.yml`` —
the field is human-maintained — so a revert or a re-merge of a version-bump PR
genuinely changes the value between parent and merge commit and would pass the
version-changed test on its own, at a version already released.

Every failure mode here resolves to "do not release": an unreadable config, an
unresolvable parent and an unparseable version all exit non-zero, which skips
the release job and turns the caller's run red. Blocking a release is visible
and recoverable; publishing to Maven Central is not.

Usage:
    release-guard.py --event-name pull_request --merge-sha <sha> [--repo-dir .]

Output:
    key=value lines in GITHUB_OUTPUT format on stdout; diagnostics on stderr.

Exit codes:
    0 - a decision was reached (see the ``proceed`` output)
    1 - the decision could not be made; the release must not proceed
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is pre-installed on GitHub runners
    print("Error: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

# A version is interpolated into shell commands, tag names and GITHUB_OUTPUT
# further down the release. Anything outside this alphabet is rejected rather
# than sanitised away, so a malformed value cannot become a silently different
# release.
VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")

SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{7,40}$")


class GuardError(Exception):
    """The decision could not be made. Never means "release anyway"."""


# --------------------------------------------------------------------------
# git access
# --------------------------------------------------------------------------


def _git(repo_dir: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo_dir),
        capture_output=True,
        text=True,
    )


def commit_exists(repo_dir: Path, sha: str) -> bool:
    """True if ``sha`` names a commit object present in the local clone."""
    return _git(repo_dir, "cat-file", "-e", f"{sha}^{{commit}}").returncode == 0


def ensure_commit(repo_dir: Path, sha: str) -> None:
    """Make ``sha`` available locally, fetching it if the clone is too shallow.

    ``actions/checkout`` defaults to ``fetch-depth: 1``. With depth 1 there is
    no first parent to compare against, so the guard would read "unchanged"
    forever — green for the same reason a deleted test is green. The workflow
    sets the depth explicitly; this is the backstop that turns a mistake there
    into a loud failure rather than a silent one.
    """
    if commit_exists(repo_dir, sha):
        return
    _git(repo_dir, "fetch", "--quiet", "origin", sha)
    if commit_exists(repo_dir, sha):
        return
    raise GuardError(
        f"commit {sha} is not present in the clone and could not be fetched. "
        "Check out with fetch-depth: 0 — the guard needs history to compare against."
    )


def first_parent(repo_dir: Path, sha: str) -> str:
    """Return the first parent of ``sha``."""
    result = _git(repo_dir, "rev-parse", "--verify", "--quiet", f"{sha}^1")
    parent = result.stdout.strip()
    if result.returncode != 0 or not parent:
        raise GuardError(
            f"commit {sha} has no first parent reachable in this clone. "
            "Check out with fetch-depth: 0 so the previous version can be read."
        )
    return parent


def file_at_commit(repo_dir: Path, sha: str, path: str) -> str | None:
    """Return the contents of ``path`` at ``sha``, or None if it did not exist.

    Absence and unreadability are deliberately kept apart. Absence is a real
    state with a defined meaning (the config was introduced on this commit);
    "git could not read a file that is in the tree" is not, and collapsing the
    two would let a read failure be reported as a version change.
    """
    listing = _git(repo_dir, "ls-tree", "--name-only", sha, "--", path)
    if listing.returncode != 0:
        raise GuardError(f"could not read the tree at {sha}")
    if not listing.stdout.strip():
        return None

    result = _git(repo_dir, "show", f"{sha}:{path}")
    if result.returncode != 0:
        raise GuardError(f"{path} is present at {sha} but could not be read")
    return result.stdout


def list_tags(repo_dir: Path) -> list[str]:
    """Return every tag name in the local clone."""
    result = _git(repo_dir, "tag", "--list")
    if result.returncode != 0:
        raise GuardError("could not list tags; check out with fetch-tags: true")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


# --------------------------------------------------------------------------
# decision
# --------------------------------------------------------------------------


def extract_current_version(yaml_text: str, where: str) -> str:
    """Return ``release.current-version`` from project.yml text.

    Raises rather than returning a sentinel. A malformed config is not the same
    thing as a config that does not exist: the absent case has a defined
    meaning (the version was introduced here, so it counts as changed), while
    "unparseable" means the comparison cannot be made at all. Returning None
    for both would let a broken parent config read as a version change and
    release.

    Parsed with ``BaseLoader``, which leaves every scalar a string. YAML's
    normal type resolution reads an unquoted ``1.10`` as the float 1.1, and a
    guard comparing 1.1 against 1.10 is comparing the wrong things.
    """
    try:
        data = yaml.load(yaml_text, Loader=yaml.BaseLoader)  # noqa: S506 - BaseLoader constructs no objects
    except yaml.YAMLError as error:
        raise GuardError(f"project.yml at {where} is not valid YAML: {error}") from error
    if not isinstance(data, dict):
        raise GuardError(f"project.yml at {where} is not a mapping")
    release = data.get("release")
    if not isinstance(release, dict):
        raise GuardError(f"project.yml at {where} has no release block")
    value = release.get("current-version")
    if not isinstance(value, str) or not value.strip():
        raise GuardError(f"project.yml at {where} has no release.current-version")
    return value.strip()


def is_already_tagged(version: str, tags: list[str]) -> bool:
    """True if any existing tag plausibly denotes ``version``.

    cuioss repositories tag the bare version (``2.7.0``), but Maven's default
    ``tagNameFormat`` is ``${artifactId}-${version}`` and ``v``-prefixed tags
    are common elsewhere. All three forms count. A false positive here blocks a
    release — visible and recoverable; a false negative republishes.
    """
    candidates = {version, f"v{version}"}
    suffix = f"-{version}"
    return any(tag in candidates or tag.endswith(suffix) for tag in tags)


def decide(
    event_name: str,
    pull_request_merged: str,
    previous_version: str | None,
    current_version: str,
    tags: list[str],
) -> tuple[bool, str]:
    """Return (proceed, reason) for an invocation.

    ``previous_version`` is None when project.yml did not exist on the parent
    commit, which counts as a change.
    """
    if event_name == "workflow_dispatch":
        return True, "workflow_dispatch: deliberate release, the guard does not apply"

    if event_name == "pull_request" and pull_request_merged.lower() != "true":
        return False, "pull request was closed without being merged"

    if previous_version == current_version:
        return False, f"release.current-version unchanged at {current_version}"

    if is_already_tagged(current_version, tags):
        return (
            False,
            f"release.current-version changed to {current_version}, "
            f"but a tag for {current_version} already exists",
        )

    previous_label = previous_version if previous_version is not None else "(absent)"
    return (
        True,
        f"release.current-version changed {previous_label} -> {current_version} and is untagged",
    )


def _validate_version(value: str, where: str) -> str:
    if not VERSION_PATTERN.match(value):
        raise GuardError(f"release.current-version at {where} is not a usable version: {value!r}")
    return value


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def evaluate(args: argparse.Namespace) -> tuple[bool, str, str, str]:
    """Return (proceed, reason, current_version, previous_version)."""
    if args.event_name == "workflow_dispatch":
        proceed, reason = decide(args.event_name, args.pull_request_merged, None, "", [])
        return proceed, reason, "", ""

    repo_dir = Path(args.repo_dir).resolve()
    if not (repo_dir / ".git").exists():
        raise GuardError(f"{repo_dir} is not a git working tree")

    sha = args.merge_sha.strip()
    if not SHA_PATTERN.match(sha):
        raise GuardError(f"merge-sha is not a commit sha: {sha!r}")

    ensure_commit(repo_dir, sha)
    parent = first_parent(repo_dir, sha)

    current_text = file_at_commit(repo_dir, sha, args.config_path)
    if current_text is None:
        raise GuardError(f"{args.config_path} does not exist at {sha}")
    current = _validate_version(extract_current_version(current_text, sha), sha)

    # An absent parent config is the one None that means something: the config
    # was introduced on this commit, which counts as a change. Anything else
    # about the parent that cannot be read has already raised by now.
    previous_text = file_at_commit(repo_dir, parent, args.config_path)
    previous = (
        None
        if previous_text is None
        else _validate_version(extract_current_version(previous_text, parent), parent)
    )

    proceed, reason = decide(
        args.event_name,
        args.pull_request_merged,
        previous,
        current,
        list_tags(repo_dir),
    )
    return proceed, reason, current, previous or ""


def _write_summary(proceed: bool, reason: str, summary_path: str | None) -> None:
    if not summary_path:
        return
    verdict = "Release proceeding" if proceed else "Release skipped (no-op)"
    icon = ":rocket:" if proceed else ":no_entry_sign:"
    try:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(f"## {icon} {verdict}\n\n{reason}\n\n")
    except OSError:  # pragma: no cover - the summary is diagnostic, never load-bearing
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Decide whether a Maven release may proceed")
    parser.add_argument("--event-name", required=True, help="Triggering event of the calling workflow")
    parser.add_argument("--merge-sha", default="", help="Commit to evaluate")
    parser.add_argument("--pull-request-merged", default="", help="github.event.pull_request.merged")
    parser.add_argument("--repo-dir", default=".", help="Working tree of the repository being released")
    parser.add_argument("--config-path", default=".github/project.yml", help="Path to project.yml")
    parser.add_argument("--summary-path", default=None, help="File to append a step summary to")
    args = parser.parse_args()

    try:
        proceed, reason, current, previous = evaluate(args)
    except GuardError as error:
        print(f"::error::Release guard could not decide: {error}", file=sys.stderr)
        return 1

    verdict = "PROCEED" if proceed else "SKIP"
    print(f"Release guard: {verdict} — {reason}", file=sys.stderr)

    print(f"proceed={'true' if proceed else 'false'}")
    print(f"reason={reason}")
    print(f"current-version={current}")
    print(f"previous-version={previous}")

    _write_summary(proceed, reason, args.summary_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
