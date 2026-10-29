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
    assert all_reusable - covered == set(), f"no caller example for: {sorted(all_reusable - covered)}"


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
            pytest.fail(f"{reusable.name} needs {scope}: write but {example.name} grants read")


def test_the_check_can_actually_fail():
    """Negative control: a guard that cannot fail is worthless."""
    granted = {"contents": "read"}
    requested = {"contents": "read", "actions": "read"}
    assert sorted(s for s in requested if s not in granted) == ["actions"]


# --- Push trigger of the build callers --------------------------------------------
#
# A branch is built by its pull_request run. A caller that lists feature, fix or
# chore branches in `on.push.branches` starts a run on the first push, before any PR
# exists, and that run builds the commit a second time once the PR run starts. The
# gate backs this up (project.yml ci.push-builds), but the trigger is the cheapest
# layer: no run starts at all.

BUILD_REUSABLES = ("reusable-maven-build.yml", "reusable-npm-build.yml", "reusable-pyprojectx-verify.yml")
WORKING_BRANCH_PREFIXES = ("feature/", "fix/", "chore/", "bugfix/", "hotfix/")


def _push_branches(doc):
    on = doc.get("on", doc.get(True)) or {}
    push = on.get("push") if isinstance(on, dict) else None
    return list((push or {}).get("branches") or [])


def _build_callers():
    callers = []
    for example in sorted(EXAMPLES.glob("*.yml")):
        doc = _load(example)
        uses = [j.get("uses", "") for j in (doc.get("jobs") or {}).values() if isinstance(j, dict)]
        if any(u.split("/")[-1].split("@")[0] in BUILD_REUSABLES for u in uses):
            callers.append((example, doc))
    return callers


def _working_branch_patterns(branches):
    return [b for b in branches if b.lstrip("!").startswith(WORKING_BRANCH_PREFIXES)]


def test_there_are_build_callers_to_check():
    """Guards against the glob matching nothing and the test below passing vacuously."""
    assert {c[0].name for c in _build_callers()} >= {
        "maven-build-caller.yml",
        "npm-build-caller.yml",
        "pyprojectx-verify-caller.yml",
    }


@pytest.mark.parametrize("example,doc", _build_callers(), ids=lambda v: v.name if hasattr(v, "name") else "doc")
def test_build_caller_does_not_push_trigger_working_branches(example, doc):
    branches = _push_branches(doc)
    assert "main" in branches, f"{example.name} must keep building pushes to main"
    assert _working_branch_patterns(branches) == [], (
        f"{example.name} lists {_working_branch_patterns(branches)} in on.push.branches: "
        "a branch is built by its pull_request run, and a push run on the first push races the PR"
    )


def test_the_working_branch_check_can_actually_fail():
    """Negative control: the patterns the check exists to catch are caught, others are not."""
    assert _working_branch_patterns(["main", "feature/*", "fix/*", "chore/*", "!chore/orchestrator-ledger"]) == [
        "feature/*",
        "fix/*",
        "chore/*",
        "!chore/orchestrator-ledger",
    ]
    assert _working_branch_patterns(["main", "release/*", "dependabot/**"]) == []


def _pull_request_branches(doc):
    on = doc.get("on", doc.get(True)) or {}
    pull_request = on.get("pull_request") if isinstance(on, dict) else None
    return (pull_request or {}).get("branches")


def _covers_release_pull_requests(push_branches, pull_request_branches):
    """A caller that builds pushes to `release/*` must also build PRs into it.

    Feature branches are not in the push list, so a PR from one into a maintenance
    branch such as release/v1_EE8 is built by its pull_request run or not at all.
    No `branches` filter on pull_request means every base, which covers it.
    """
    if "release/*" not in push_branches:
        return True
    return pull_request_branches is None or "release/*" in pull_request_branches


@pytest.mark.parametrize("example,doc", _build_callers(), ids=lambda v: v.name if hasattr(v, "name") else "doc")
def test_build_caller_builds_pull_requests_into_release_branches(example, doc):
    assert _covers_release_pull_requests(_push_branches(doc), _pull_request_branches(doc)), (
        f"{example.name} builds pushes to release/* but its pull_request trigger does not match release/*: "
        "a PR from a feature branch into a maintenance branch would get no build at all"
    )


def test_the_release_pull_request_check_can_actually_fail():
    """Negative control, and the two accepted shapes."""
    assert not _covers_release_pull_requests(["main", "release/*"], ["main"])
    assert _covers_release_pull_requests(["main", "release/*"], ["main", "release/*"])
    assert _covers_release_pull_requests(["main", "release/*"], None)
    assert _covers_release_pull_requests(["main", "dependabot/**"], ["main"])
