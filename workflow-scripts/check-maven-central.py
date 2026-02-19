#!/usr/bin/env python3
"""Poll Maven Central repository until an artifact version is available.

Waits for a specific artifact to appear on Maven Central, useful after
a release to ensure the artifact is available before triggering consumers.

Uses the repo1.maven.org repository directly (HEAD request on the POM)
instead of the search API, which lags behind by 10-60+ minutes.

Usage:
    ./check-maven-central.py \
        --group-id de.cuioss \
        --artifact-id cui-java-parent \
        --version 1.4.4 \
        --timeout 1800 \
        --poll-interval 60
"""

import argparse
import os
import sys
import time
import urllib.error
import urllib.request

MAVEN_CENTRAL_REPO_URL = (
    "https://repo1.maven.org/maven2/{group_path}/{artifact_id}"
    "/{version}/{artifact_id}-{version}.pom"
)


def check_artifact_available(group_id: str, artifact_id: str, version: str) -> bool:
    """Check if an artifact version is available on Maven Central.

    Uses an HTTP HEAD request against repo1.maven.org.
    Returns True if found (HTTP 200), False otherwise.
    """
    group_path = group_id.replace(".", "/")
    url = MAVEN_CENTRAL_REPO_URL.format(
        group_path=group_path, artifact_id=artifact_id, version=version
    )
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status == 200
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        print(f"::warning::Maven Central HTTP error {e.code}: {e}")
        return False
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"::warning::Maven Central request error: {e}")
        return False


def wait_for_artifact(
    group_id: str,
    artifact_id: str,
    version: str,
    timeout: int,
    poll_interval: int,
) -> bool:
    """Poll Maven Central until the artifact appears or timeout.

    Returns True if found, False on timeout.
    """
    coordinate = f"{group_id}:{artifact_id}:{version}"
    print(f"Waiting for {coordinate} on Maven Central (timeout: {timeout}s)...")

    elapsed = 0
    while elapsed < timeout:
        if check_artifact_available(group_id, artifact_id, version):
            print(f"Found {coordinate} on Maven Central after {elapsed}s")
            return True

        remaining = timeout - elapsed
        wait = min(poll_interval, remaining)
        if wait <= 0:
            break

        print(f"  Not found yet ({elapsed}s/{timeout}s), retrying in {wait}s...")
        time.sleep(wait)
        elapsed += wait

    print(f"::warning::Timeout waiting for {coordinate} after {timeout}s")
    return False


def _write_github_output(found: bool) -> None:
    """Write found=true|false to $GITHUB_OUTPUT for downstream jobs."""
    output_file = os.environ.get("GITHUB_OUTPUT")
    if not output_file:
        return
    with open(output_file, "a", encoding="utf-8") as f:
        f.write(f"found={'true' if found else 'false'}\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Wait for an artifact to appear on Maven Central"
    )
    parser.add_argument(
        "--group-id", required=True, help="Maven groupId (e.g., de.cuioss)"
    )
    parser.add_argument(
        "--artifact-id", required=True, help="Maven artifactId (e.g., cui-java-parent)"
    )
    parser.add_argument(
        "--version", required=True, help="Version to wait for (e.g., 1.4.4)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=1800,
        help="Maximum seconds to wait (default: 1800)",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=60,
        help="Seconds between polls (default: 60)",
    )

    args = parser.parse_args()

    found = wait_for_artifact(
        args.group_id,
        args.artifact_id,
        args.version,
        args.timeout,
        args.poll_interval,
    )

    _write_github_output(found)

    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main())
