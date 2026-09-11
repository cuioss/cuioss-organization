#!/usr/bin/env python3
"""Assert the resolved smallrye-config family matches the release Quarkus was built against.

Why this exists
---------------
``java-ee-10-bom`` pins ``io.smallrye.config:*``, and those pins beat the
``io.quarkus:quarkus-bom`` a consumer imports. The resolved version therefore has to
equal the smallrye-config release Quarkus itself was built against. A *newer* one is
not safe: Quarkus' deployment classes are compiled against one specific release, so
even an internally coherent newer stack fails augmentation with

    failed to access io.smallrye.config.ConfigMappingLoader$ConfigMappingImplementation
    from io.quarkus.deployment.configuration.ConfigMappingUtils

The ``requireSameVersions`` enforcer guard cannot catch this: nothing is split, so it
is correctly silent. Neither can a parent-side gate in ``cuioss-parent-pom``, for two
reasons that are consumer-side facts by construction:

* **Consumers compose their own BOMs.** Which BOMs a reactor imports, and in which
  order, is decided in the consumer's POMs. A consumer BOM that pulls in
  ``java-ee-10-bom`` re-introduces the smallrye pins downstream of anything the parent
  can see.
* **Overriding ``version.quarkus`` is supported.** ``cui-quarkus-parent`` explicitly
  allows a consumer to pin ``version.quarkus`` for an emergency fix. That moves
  ``quarkus-bom`` but *not* ``java-ee-10-bom``'s inherited smallrye pin — so a
  supported, documented action produces exactly the split this check hunts for, while
  the parent-side gate still passes.

How it decides
--------------
``version.quarkus`` is read from the **effective** POM (``help:evaluate``), never by
scanning ``pom.xml`` text. Consumers inherit it from ``cui-quarkus-parent`` and declare
it nowhere, so a text scan reports "not declared anywhere" and the check becomes the
one people wave through.

The reactor is installed in the same invocation as ``dependency:list`` so that modules
depending on a sibling at ``${project.version}`` resolve it from the build rather than from
a repository; see the comment in ``resolved_versions`` (cuioss-organization#274).

The assertion is made against the **resolved classpath** (``dependency:list``), not
against a declared property. That catches a *split* family (two smallrye versions in
one reactor) as well as a uniformly wrong one, and it sees what the build will actually
put on the augmentation classpath rather than what a POM intended.

Exit codes
----------
0 aligned, or cleanly skipped (``version.quarkus`` undefined — not a Quarkus project);
1 misaligned; 2 could not determine — blocking by design, never a pass.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

NS = "{http://maven.apache.org/POM/4.0.0}"
QUARKUS_BOM_URL = "https://repo1.maven.org/maven2/io/quarkus/quarkus-bom/{v}/quarkus-bom-{v}.pom"
QUARKUS_PROP = "version.quarkus"
SMALLRYE_GROUP = "io.smallrye.config"
SMALLRYE_ANCHOR = "smallrye-config"
QUARKUS_CORE = "io.quarkus:quarkus-core"

# Maven Central is occasionally slow to answer rather than genuinely unavailable, and
# this check fails closed. A couple of retries keeps a hiccup from blocking every
# consumer's build without ever turning a real "cannot determine" into a pass.
FETCH_ATTEMPTS = 3
FETCH_BACKOFF_SECONDS = 5


class Undetermined(Exception):
    """The check could not run. Never report this as a pass."""


def _mvn(repo: Path) -> str:
    """The wrapper if the project ships one, so the check uses the project's Maven."""
    mvnw = repo / "mvnw"
    return str(mvnw) if mvnw.exists() else "mvn"


def _run_maven(repo: Path, goal_args: list[str], timeout: int) -> subprocess.CompletedProcess:
    # -T1 is load-bearing and must stay LAST-wins on the command line. A consuming
    # repository may set a parallel default in .mvn/maven.config (TokenSheriff sets
    # -T1C), and Maven treats maven.config as prepended to the command line. Under a
    # parallel reactor the per-module dependency:list output is appended to one file
    # from several threads at once, which interleaves the lines this parses.
    cmd = [_mvn(repo), "-B", "-q", "-T1", *goal_args]
    try:
        return subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        raise Undetermined(f"{goal_args[0]} failed to run: {exc}") from exc


def _maven_diagnostics(out: subprocess.CompletedProcess) -> str:
    """The part of a failed Maven run worth putting in the failure message.

    Maven prints its ``[ERROR]`` block to **stdout**, not stderr, so reporting stderr
    alone yields an empty diagnostic — observed as a bare "dependency:list exited 1:"
    that says nothing about the unreadable POM behind it. Prefer the [ERROR] lines, and
    fall back to whatever output there was.
    """
    combined = f"{out.stdout}\n{out.stderr}"
    errors = [ln for ln in combined.splitlines() if "[ERROR]" in ln]
    detail = "\n".join(errors) if errors else combined.strip()
    return detail[-2000:] if detail else "(no output)"


def evaluate_property(repo: Path, name: str, timeout: int) -> str | None:
    """Read a property from the *effective* POM, so inherited values are visible too.

    Returns None when the property is not defined anywhere in the parent chain; Maven
    prints a ``null object or invalid expression`` marker for that case rather than
    failing, so an absent property must not be confused with a broken build.
    """
    out = _run_maven(repo, ["help:evaluate", f"-Dexpression={name}", "-DforceStdout", "-N"], timeout)
    if out.returncode != 0:
        raise Undetermined(f"help:evaluate {name} exited {out.returncode}:\n{_maven_diagnostics(out)}")
    lines = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    if not lines:
        return None
    value = lines[-1]
    return None if "null object or invalid expression" in value else value


def _properties(root: ET.Element) -> dict[str, str]:
    node = root.find(NS + "properties")
    return {} if node is None else {e.tag.replace(NS, ""): (e.text or "").strip() for e in node}


def _deref(value: str, props: dict[str, str]) -> str:
    """Resolve a single ${...} indirection; BOMs express versions either way."""
    seen: set[str] = set()
    while value.startswith("${") and value.endswith("}"):
        key = value[2:-1]
        if key in seen or key not in props:
            break
        seen.add(key)
        value = props[key].strip()
    return value


def quarkus_smallrye_version(quarkus_version: str) -> str:
    """The smallrye-config release ``io.quarkus:quarkus-bom:<version>`` manages."""
    url = QUARKUS_BOM_URL.format(v=quarkus_version)
    last: Exception | None = None
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                root = ET.fromstring(resp.read())
            break
        except Exception as exc:  # network, 404, malformed — all are "cannot determine"
            last = exc
            if attempt < FETCH_ATTEMPTS:
                print(f"::warning::could not fetch {url} (attempt {attempt}/{FETCH_ATTEMPTS}): {exc}")
                time.sleep(FETCH_BACKOFF_SECONDS)
    else:
        raise Undetermined(f"could not fetch {url}: {last}")

    props = _properties(root)
    for dep in root.iter(NS + "dependency"):
        if dep.findtext(NS + "groupId") == SMALLRYE_GROUP and dep.findtext(NS + "artifactId") == SMALLRYE_ANCHOR:
            version = _deref((dep.findtext(NS + "version") or "").strip(), props)
            if version:
                return version
    raise Undetermined(f"quarkus-bom {quarkus_version} does not manage {SMALLRYE_GROUP}:{SMALLRYE_ANCHOR}")


def _coordinate(line: str) -> tuple[str, str, str] | None:
    """Parse one ``dependency:list`` line into (group, artifact, version).

    Both shapes Maven emits are handled — with and without a classifier —
    and a trailing JPMS ``-- module ...`` note is ignored along with the scope.
    """
    fields = line.strip().split(":")
    if len(fields) == 5:
        group, artifact, _type, version, _scope = fields
    elif len(fields) == 6:
        group, artifact, _type, _classifier, version, _scope = fields
    else:
        return None
    return group, artifact, version


def resolved_versions(repo: Path, timeout: int) -> tuple[dict[str, set[str]], set[str]]:
    """What this project actually resolves: every ``io.smallrye.config`` artifact, and
    the ``io.quarkus:quarkus-core`` version(s).

    ``-q`` suppresses the goal's own console output, so the listing is written to a file
    and appended across the reactor — one combined view of every module's classpath.
    """
    with tempfile.TemporaryDirectory() as tmp:
        listing = Path(tmp) / "dependencies.txt"
        # ``install`` runs in the SAME invocation as dependency:list, and it is what makes
        # this check self-sufficient. A bare dependency:list does not build anything, so a
        # module depending on a sibling at ${project.version} can only resolve it from a
        # repository — and for the current -SNAPSHOT that means the snapshot repository,
        # which is populated by deploy-snapshot, which waits on this check. That is a
        # deadlock, not a slow path: after every release the version moves to a -SNAPSHOT
        # nobody has deployed, so the default branch stays red with no way out
        # (cuioss-organization#274).
        #
        # One invocation, not two: Maven walks the reactor in dependency order and runs
        # both per module, so mod-b's dependency:list sees mod-a's freshly installed
        # artifact. Excluding reactor modules instead would defeat the purpose — their
        # transitive Quarkus and smallrye-config dependencies are precisely what is
        # being measured.
        #
        # -DskipTests, not -Dmaven.test.skip=true: the latter skips test COMPILATION, so a
        # module publishing a test-jar would not produce one and a sibling depending on it
        # would fail to resolve. -DskipITs is required alongside it because Failsafe 3.6.0+
        # ignores -DskipTests.
        out = _run_maven(
            repo,
            [
                "install",
                "-DskipTests",
                "-DskipITs",
                "dependency:list",
                "-DincludeScope=test",
                f"-DoutputFile={listing}",
                "-DappendOutput=true",
            ],
            timeout,
        )
        if out.returncode != 0:
            raise Undetermined(
                f"install + dependency:list exited {out.returncode}:\n{_maven_diagnostics(out)}")
        if not listing.exists():
            raise Undetermined(f"dependency:list produced no listing at {listing}")
        content = listing.read_text(errors="replace")

    found: dict[str, set[str]] = {}
    core: set[str] = set()
    for line in content.splitlines():
        parsed = _coordinate(line)
        if parsed is None:
            continue
        group, artifact, version = parsed
        if group == SMALLRYE_GROUP:
            found.setdefault(artifact, set()).add(version)
        elif f"{group}:{artifact}" == QUARKUS_CORE:
            core.add(version)
    return found, core


def check(repo: Path, evaluate_timeout: int, resolve_timeout: int) -> int:
    quarkus = evaluate_property(repo, QUARKUS_PROP, evaluate_timeout)
    if quarkus is None:
        print(f"{QUARKUS_PROP} is not defined in the effective POM — not a Quarkus project, skipping")
        return 0

    expected = quarkus_smallrye_version(quarkus)
    print(f"quarkus            {quarkus}   (effective POM)")
    print(f"quarkus expects    {SMALLRYE_GROUP} {expected}")

    resolved, core = resolved_versions(repo, resolve_timeout)
    problems: list[str] = []

    # version.quarkus drives quarkus-maven-plugin (a build extension), while the Quarkus
    # *artifacts* come from whichever BOM is imported. Those are separate inputs and can
    # drift apart: cui-reference-documentation once ran plugin 3.38.0 against
    # BOM-supplied 3.39.0, which is how the original outage began. The smallrye
    # comparison alone cannot see this — both sides may still agree on smallrye.
    if core:
        shown = ", ".join(sorted(core))
        print(f"resolved           quarkus-core {shown}")
        if core != {quarkus}:
            problems.append(
                f"quarkus-maven-plugin uses {QUARKUS_PROP}={quarkus} but {QUARKUS_CORE} resolves "
                f"to {shown} — the plugin and the imported BOM have drifted apart"
            )

    if not resolved:
        print(f"resolved           (no {SMALLRYE_GROUP} artifacts on the classpath)")
    for artifact, versions in sorted(resolved.items()):
        shown = ", ".join(sorted(versions))
        print(f"resolved           {artifact} {shown}")
        if versions != {expected}:
            problems.append(f"{artifact} resolves to {shown}, expected {expected}")

    if problems:
        print(f"::error::Quarkus/smallrye-config misalignment: {len(problems)} problem(s) — see below")
        print("\nMISALIGNED — fix before merging:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            f"\nAlign the {SMALLRYE_GROUP} version with what Quarkus {quarkus} manages "
            f"({expected}), or move {QUARKUS_PROP} to the release that manages the version "
            "you want.\nA split or wrong smallrye-config family fails Quarkus augmentation at "
            "runtime, not at compile time.",
            file=sys.stderr,
        )
        return 1

    print("\nALIGNED")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="repository root to check (default: cwd)")
    parser.add_argument(
        "--evaluate-timeout",
        type=int,
        default=900,
        help="seconds allowed for help:evaluate (default: 900)",
    )
    parser.add_argument(
        "--resolve-timeout",
        type=int,
        default=1800,
        help="seconds allowed for dependency:list (default: 1800)",
    )
    args = parser.parse_args()

    try:
        return check(args.repo.resolve(), args.evaluate_timeout, args.resolve_timeout)
    except Undetermined as exc:
        print(f"::error::Quarkus alignment check could not determine alignment: {exc}")
        print(f"CANNOT DETERMINE: {exc}", file=sys.stderr)
        print("Treat this as blocking — an unresolvable check is not a pass.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
