#!/usr/bin/env python3
"""Poll Maven Central Search API until an artifact version is indexed.

Waits for a specific artifact to appear on Maven Central, useful after
a release to ensure the artifact is available before triggering consumers.

Usage:
    ./check-maven-central.py \
        --group-id de.cuioss \
        --artifact-id cui-java-parent \
        --version 1.4.4 \
        --timeout 1800 \
        --poll-interval 60
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

MAVEN_CENTRAL_SEARCH_URL = (
    "https://search.maven.org/solrsearch/select"
    "?q=g:{group_id}+AND+a:{artifact_id}+AND+v:{version}&rows=1"
)


def check_artifact_indexed(group_id: str, artifact_id: str, version: str) -> bool:
    """Check if an artifact version is indexed on Maven Central.

    Returns True if found, False otherwise.
    """
    url = MAVEN_CENTRAL_SEARCH_URL.format(
        group_id=group_id, artifact_id=artifact_id, version=version
    )
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
            num_found = data.get("response", {}).get("numFound", 0)
            return num_found > 0
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        print(f"::warning::Maven Central API error: {e}")
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
        if check_artifact_indexed(group_id, artifact_id, version):
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

    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main())
