"""A job downstream of an always() job must not rely on implicit success().

A job `if:` without a status function (always/success/failure/cancelled) is
evaluated as `success() && <expr>`, and success() is false whenever ANY
transitive ancestor was skipped -- not just the direct `needs`. A job that uses
always() to run past a skipped dependency does not clear that for its own
descendants: they still see the skipped ancestor and are skipped themselves.

That shipped in v0.29.0: reusable-maven-build.yml's `config` job gained
always() to run past the (usually skipped) `covering-run-check`, but
`check-changes` below it kept a bare `if:`. It was then skipped on every
pull_request, its `should-build` output read as '' (!= 'false'), and the full
build ran on docs-only PRs -- skip-on-docs-only silently stopped working (#289).

The rule checked here: once any transitive ancestor of a job uses always(),
the skip it tolerates is visible downstream, so every descendant with an
`if:` must carry an explicit status function other than success() -- an
explicit success() is exactly the implicit one, and falls into the same trap.
failure()/cancelled() (including `!cancelled()`) state a deliberate intent and
are accepted. A descendant without any `if:`
is exempt: it is always skipped along with a skipped parent, which it cannot
tell apart from a real skip anyway, so it cannot silently fail open.
"""

import re
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT

WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"
# success() is deliberately absent: it is false on a skipped ancestor, exactly
# like the implicit form, so it does not count as handling the skip.
STATUS_FUNCTION = re.compile(r"\b(always|failure|cancelled)\s*\(\s*\)")


def _needs(job):
    needs = job.get("needs") or []
    return [needs] if isinstance(needs, str) else list(needs)


def _ancestors(jobs, name, seen=None):
    seen = set() if seen is None else seen
    for parent in _needs(jobs[name]):
        if parent not in seen:
            seen.add(parent)
            _ancestors(jobs, parent, seen)
    return seen


def _uses_always(job):
    return "always()" in str(job.get("if", ""))


def violations(doc):
    """Return the jobs below an always() ancestor whose `if:` still skips on a skip."""
    jobs = doc.get("jobs") or {}
    found = []
    for name, job in jobs.items():
        condition = job.get("if")
        if condition is None or STATUS_FUNCTION.search(str(condition)):
            continue
        tolerant = sorted(a for a in _ancestors(jobs, name) if _uses_always(jobs[a]))
        if tolerant:
            found.append((name, tolerant))
    return found


@pytest.mark.parametrize("workflow", sorted(WORKFLOWS.glob("*.yml")), ids=lambda p: p.name)
def test_no_bare_if_below_an_always_job(workflow):
    """Should give every job below an always() ancestor an explicit status function."""
    found = violations(yaml.safe_load(workflow.read_text(encoding="utf-8")))
    assert not found, (
        f"{workflow.name}: {found} -- these jobs have an `if:` with no status "
        f"function (or only success()), so an ancestor skip that the always() job(s) tolerate still "
        f"skips them. Add `always() && needs.<parent>.result == 'success' && ...`."
    )


def test_the_check_can_actually_fail():
    """Should flag the exact #289 shape, so the guard is not vacuous."""
    doc = {
        "jobs": {
            "gate": {},
            "optional": {"needs": "gate", "if": "github.event_name == 'push'"},
            "config": {"needs": ["gate", "optional"], "if": "always() && true"},
            "check-changes": {"needs": "config", "if": "inputs.skip-on-docs-only"},
            "build": {"needs": ["config", "check-changes"], "if": "always() && x"},
            "explicit-success": {"needs": "config", "if": "success() && x"},
            "on-failure": {"needs": "config", "if": "failure()"},
            "not-cancelled": {"needs": "config", "if": "!cancelled() && x"},
            "plain": {"needs": "config"},
        }
    }
    assert violations(doc) == [("check-changes", ["config"]), ("explicit-success", ["config"])]
