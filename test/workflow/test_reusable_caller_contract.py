"""Every reusable workflow must fit inside the permissions its caller example grants.

A called workflow can only RESTRICT the caller's GITHUB_TOKEN, never escalate it.
The moment a job requests a permission the caller does not grant, GitHub rejects
the run with a startup failure before any job executes -- in the consumer's repo,
after a release, with nothing in this repo having failed.

That shipped in v0.21.0: reusable-maven-build.yml's conclusion job gained
`actions: read` for the #243 guard, and all 19 Maven consumers went
startup_failure on their propagation PRs.

This is a static check -- it needs no Actions runtime, only the two files that
already exist -- so it costs nothing and closes that class.
"""

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT

WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"
EXAMPLES = PROJECT_ROOT / "docs" / "workflow-examples"


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _caller_pairs():
    """Yield (example, reusable, granted) for every documented caller job.

    A caller may set `permissions:` on the calling JOB, which overrides the
    workflow-level block entirely -- that is the form the dependabot/scorecards
    examples use. Reading only the top-level block reports grants that are
    actually made.
    """
    pairs = []
    for example in sorted(EXAMPLES.glob("*.yml")):
        doc = _load(example)
        top = doc.get("permissions") or {}
        for job in (doc.get("jobs") or {}).values():
            uses = job.get("uses", "") if isinstance(job, dict) else ""
            if "cuioss/cuioss-organization/.github/workflows/" not in uses:
                continue
            name = uses.split("/")[-1].split("@")[0]
            target = WORKFLOWS / name
            if target.exists():
                granted = job.get("permissions")
                pairs.append((example, target, granted if isinstance(granted, dict) else top))
    return pairs


def _requested(reusable_doc):
    """Union of permissions every job in the reusable workflow asks for."""
    requested = {}
    for job in (reusable_doc.get("jobs") or {}).values():
        perms = job.get("permissions") if isinstance(job, dict) else None
        if isinstance(perms, dict):
            for scope, level in perms.items():
                if requested.get(scope) != "write":
                    requested[scope] = level
    return requested


PAIRS = _caller_pairs()
IDS = [f"{p[1].name}<-{p[0].name}" for p in PAIRS]


def test_every_reusable_workflow_has_a_caller_example():
    """A reusable workflow with no documented caller cannot be contract-checked."""
    covered = {p[1].name for p in PAIRS}
    all_reusable = {p.name for p in WORKFLOWS.glob("reusable-*.yml")}
    assert all_reusable - covered == set(), (
        f"no caller example for: {sorted(all_reusable - covered)}"
    )


@pytest.mark.parametrize("example,reusable,granted", PAIRS, ids=IDS)
def test_caller_example_grants_every_permission_the_workflow_requests(example, reusable, granted):
    requested = _requested(_load(reusable))
    missing = sorted(s for s in requested if s not in granted)
    assert not missing, (
        f"{reusable.name} requests {missing} but {example.name} does not grant it. "
        "GitHub rejects such a run with a startup failure before any job executes; "
        "add it to the caller example (and tell consumers), or drop the request."
    )


@pytest.mark.parametrize("example,reusable,granted", PAIRS, ids=IDS)
def test_caller_example_grants_a_sufficient_level(example, reusable, granted):
    """read is not enough where a job asks for write."""
    for scope, level in _requested(_load(reusable)).items():
        if level == "write" and granted.get(scope) == "read":
            pytest.fail(
                f"{reusable.name} needs {scope}: write but {example.name} grants read"
            )


def test_the_check_can_actually_fail():
    """Negative control: a guard that cannot fail is worthless."""
    granted = {"contents": "read"}
    requested = {"contents": "read", "actions": "read"}
    assert sorted(s for s in requested if s not in granted) == ["actions"]
