#!/usr/bin/env python3
"""Verify a Maven snapshot deploy actually published a new artifact.

`mvn deploy` exiting 0 only proves Maven finished without error - not that a
newer snapshot reached the repository. TokenSheriff run 34214468714 published
nothing for four days while `deploy-snapshot` reported green or cancelled
(cuioss-organization#278); the deadlock that caused that is fixed separately
(#263), but nothing checked the *result* of a deploy that runs to completion
without one.

This script reads one representative artifact's version-level
`maven-metadata.xml` from the Central Publishing snapshot repository, once
before `mvn deploy` and once after, and fails when the published
`<versioning><snapshot><timestamp>` did not advance past the pre-deploy value
and past the moment the deploy started. The project's own root groupId /
artifactId is always a safe choice of "representative artifact": it is part
of every reactor build regardless of packaging.

Usage:
    # Immediately before `mvn deploy` (writes before-timestamp/deploy-start):
    ./check-snapshot-published.py record \\
        --group-id de.cuioss --artifact-id my-parent \\
        --version 1.2-SNAPSHOT >> "$GITHUB_OUTPUT"

    # Immediately after `mvn deploy`:
    ./check-snapshot-published.py verify \\
        --group-id de.cuioss --artifact-id my-parent \\
        --version 1.2-SNAPSHOT \\
        --before-timestamp "$BEFORE" --deploy-start "$START"
"""

import argparse
import datetime
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

SNAPSHOT_METADATA_URL = (
    "https://central.sonatype.com/repository/maven-snapshots/{group_path}/{artifact_id}/{version}/maven-metadata.xml"
)
FETCH_ATTEMPTS = 3
FETCH_TIMEOUT = 30


def _metadata_url(group_id: str, artifact_id: str, version: str) -> str:
    return SNAPSHOT_METADATA_URL.format(group_path=group_id.replace(".", "/"), artifact_id=artifact_id, version=version)


def fetch_snapshot_timestamp(group_id: str, artifact_id: str, version: str) -> str | None:
    """Read <versioning><snapshot><timestamp> from the version-level metadata.

    Returns None when the metadata does not exist yet (HTTP 404) - expected the
    first time a new module or a freshly bumped -SNAPSHOT version is deployed,
    since there is nothing to compare a "before" reading against.
    """
    url = _metadata_url(group_id, artifact_id, version)
    last: Exception | None = None
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT) as resp:
                root = ET.fromstring(resp.read())
            timestamp = root.findtext("./versioning/snapshot/timestamp")
            return timestamp.strip() if timestamp else None
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = e
        except (urllib.error.URLError, ET.ParseError, TimeoutError) as e:
            last = e
        if attempt < FETCH_ATTEMPTS:
            print(f"::warning::could not read {url} (attempt {attempt}/{FETCH_ATTEMPTS}): {last}", file=sys.stderr)
    raise RuntimeError(f"could not fetch {url} after {FETCH_ATTEMPTS} attempts: {last}")


def _as_comparable(timestamp: str) -> str:
    """'20260921.132033' -> '20260921132033' - fixed-width, so a plain string compare orders it."""
    return timestamp.replace(".", "")


def cmd_record(args: argparse.Namespace) -> int:
    before = fetch_snapshot_timestamp(args.group_id, args.artifact_id, args.version)
    deploy_start = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
    # `record`'s stdout is captured straight into $GITHUB_OUTPUT (see the module
    # docstring) — only the two key=value lines may go there. Everything else, here
    # and in fetch_snapshot_timestamp above, goes to stderr.
    print(
        f"Pre-deploy snapshot timestamp for {args.group_id}:{args.artifact_id}:{args.version}: "
        f"{before or '(none published yet)'}",
        file=sys.stderr,
    )
    print(f"before-timestamp={before or ''}")
    print(f"deploy-start={deploy_start}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    coordinate = f"{args.group_id}:{args.artifact_id}:{args.version}"
    after = fetch_snapshot_timestamp(args.group_id, args.artifact_id, args.version)
    if not after:
        print(f"::error::no snapshot metadata found for {coordinate} after deploy — nothing was published")
        return 1

    after_cmp = _as_comparable(after)
    if after_cmp < args.deploy_start:
        print(
            f"::error::{coordinate} snapshot timestamp {after} predates the deploy start "
            f"({args.deploy_start}) — the published metadata is stale, not from this run"
        )
        return 1

    if args.before_timestamp and after_cmp <= _as_comparable(args.before_timestamp):
        print(
            f"::error::{coordinate} snapshot timestamp did not advance "
            f"(before: {args.before_timestamp}, after: {after})"
        )
        return 1

    print(f"Verified {coordinate} published: snapshot timestamp {after}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--group-id", required=True, help="Maven groupId (e.g., de.cuioss)")
    common.add_argument("--artifact-id", required=True, help="Maven artifactId of the representative artifact")
    common.add_argument("--version", required=True, help="The -SNAPSHOT version being deployed")

    sub.add_parser("record", parents=[common], help="Read the pre-deploy metadata (run before `mvn deploy`)")

    verify = sub.add_parser("verify", parents=[common], help="Confirm the deploy published a newer snapshot")
    verify.add_argument("--before-timestamp", default="", help="`record`'s before-timestamp output (may be empty)")
    verify.add_argument("--deploy-start", required=True, help="`record`'s deploy-start output")

    args = parser.parse_args()
    try:
        if args.command == "record":
            return cmd_record(args)
        return cmd_verify(args)
    except RuntimeError as e:
        # stderr unconditionally: `record`'s stdout is captured into $GITHUB_OUTPUT
        # (see the module docstring), and this exception can surface from either command.
        print(f"::error::{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
