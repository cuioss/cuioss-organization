"""Regression tests for the PR-Agent empty-review guard's trigger scope.

The guard in `.github/workflows/reusable-pr-agent-review.yml` fails the job when the
reviewer produced no structured output. That assertion is only sound on runs the runner
is contractually obliged to review, so the guard's `if:` mirrors PR-Agent's own
`GITHUB_ACTION_CONFIG.PR_ACTIONS` allow-list rather than selecting on the event alone.

These tests pin the three things that must not be silently undone: the narrowed trigger
scope, the fail-closed `exit 1`, and the in-file enumeration of the populations that are
legitimately empty and therefore excluded.
"""

import json
import re

import pytest
import yaml

WORKFLOW_PATH = ".github/workflows/reusable-pr-agent-review.yml"
DOCS_PATH = "docs/Workflows.adoc"
GUARD_STEP_NAME = "Verify the reviewer actually produced a review"
REVIEWED_ACTIONS = ("opened", "reopened", "ready_for_review", "review_requested")

# Every population that legitimately produces no review output, keyed by the group letter
# the workflow's own EXCLUDED comment block uses. Asserted as one parametrized set so that
# dropping any single group — including (a), the population that motivates the change —
# fails the suite rather than passing silently.
EXCLUDED_POPULATIONS = {
    "a_synchronize_with_push_trigger_off": (
        "synchronize",
        "handle_push_trigger",
        "Skipping action",
    ),
    "b_run_action_early_returns": (
        "before == after",
        "unchanged SHA",
        "merge commit",
        "Bot",
        "push_commands",
    ),
    "c_pull_request_with_no_files": ("no files",),
    "d_empty_diff_after_filtering": ("empty diff",),
}


@pytest.fixture
def workflow_text(project_root):
    """Raw workflow source, including the comments `yaml.safe_load` discards."""
    return (project_root / WORKFLOW_PATH).read_text(encoding="utf-8")


@pytest.fixture
def guard_step(workflow_text):
    """The parsed guard step, located by name across every job in the workflow."""
    workflow = yaml.safe_load(workflow_text)
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            if step.get("name") == GUARD_STEP_NAME:
                return step
    raise AssertionError(f"guard step not found: {GUARD_STEP_NAME}")


@pytest.fixture
def guard_comment_block(workflow_text):
    """The contiguous `#` comment block immediately above the guard step.

    Scoped to that block rather than the whole file so a token surviving somewhere
    unrelated cannot make the enumeration assertions pass vacuously.
    """
    lines = workflow_text.splitlines()
    anchor = next(
        (index for index, line in enumerate(lines) if line.strip() == f"- name: {GUARD_STEP_NAME}"),
        None,
    )
    assert anchor is not None, f"guard step not found: {GUARD_STEP_NAME}"

    block = []
    cursor = anchor - 1
    while cursor >= 0 and lines[cursor].strip().startswith("#"):
        block.append(lines[cursor])
        cursor -= 1
    assert block, "the guard step carries no explanatory comment block"
    return "\n".join(reversed(block))


@pytest.fixture
def docs_text(project_root):
    """Raw Workflows.adoc source, including the caller template's YAML block."""
    return (project_root / DOCS_PATH).read_text(encoding="utf-8")


def _guard_allow_list(condition):
    """The guard's action allow-list, parsed out of its `fromJSON('[…]')` literal."""
    match = re.search(r"fromJSON\('(\[.*?\])'\)", condition, re.DOTALL)
    assert match is not None, "the guard's action allow-list is no longer a fromJSON array"
    return json.loads(match.group(1))


@pytest.mark.parametrize("action", REVIEWED_ACTIONS)
def test_if_allow_lists_every_reviewed_action(guard_step, action):
    """Each action in the runner's PR_ACTIONS default stays inside the guard's scope."""
    assert f'"{action}"' in guard_step["if"]


def test_if_allow_lists_exactly_the_reviewed_actions(guard_step):
    """The allow-list is that set and nothing more.

    Its sibling above tests membership, which cannot fail when the list GROWS: adding
    `synchronize` to the workflow would keep every one of those cases green while silently
    re-broadening the gate over the exact population this change excludes on purpose. Set
    equality is what makes an added action fail here rather than pass unnoticed.
    """
    assert set(_guard_allow_list(guard_step["if"])) == set(REVIEWED_ACTIONS)


def test_caller_template_subscribes_to_every_reviewed_action(docs_text):
    """The documented caller template triggers on every action the guard admits.

    An action in the allow-list that no caller ever sends is dead scope, and the reverse — a
    subscribed action outside the allow-list — is an ungated run. Both directions are pinned
    here because the two lists live in different files and drift silently otherwise.

    Anchored on the PR-Agent template's own `name:`, because Workflows.adoc documents several
    caller templates and an unanchored search binds to whichever `pull_request:` block appears
    first — a different workflow's, whose `types:` has nothing to do with this guard.
    """
    template = re.search(
        r"^name: PR Agent Review$.*?^  pull_request:\n    types: \[(.*?)\]$",
        docs_text,
        re.MULTILINE | re.DOTALL,
    )
    assert template is not None, "the PR Agent Review caller template was not found"
    subscribed = {entry.strip() for entry in template.group(1).split(",")}
    assert subscribed == set(REVIEWED_ACTIONS)


def test_no_pr_actions_override_in_this_repository(workflow_text, docs_text):
    """Nothing here overrides `github_action_config.pr_actions`.

    The guard's allow-list is only correct while that setting stays at its default, and an
    override is the one local edit that would falsify it without touching either list. Prose
    mentions of the key are expected — the assertion targets an ASSIGNMENT, so documenting the
    contract does not trip the guard that enforces it.
    """
    assignment = re.compile(r"github_action_config\.pr_actions\s*[:=]")
    for label, text in (("workflow", workflow_text), ("docs", docs_text)):
        assert not assignment.search(text), f"{label} assigns github_action_config.pr_actions"


def test_if_discriminates_on_the_event_action(guard_step):
    """The allow-list is applied to `github.event.action`, the field the runner branches on."""
    condition = guard_step["if"]
    assert "github.event.action" in condition
    assert "contains(" in condition
    assert "fromJSON" in condition


def test_if_admits_no_bare_pull_request_arm(guard_step):
    """The specific regression: a pull_request arm with no action check re-broadens the guard.

    Every top-level arm that tests for the pull_request event must also constrain the
    action, otherwise the guard again asserts a precondition the runner's config denies.
    """
    arms = guard_step["if"].split("||")
    pull_request_arms = [arm for arm in arms if "'pull_request'" in arm]

    assert pull_request_arms, "the pull_request arm disappeared from the guard"
    for arm in pull_request_arms:
        assert "github.event.action" in arm, f"unconstrained pull_request arm: {arm.strip()}"


def test_if_retains_the_review_comment_arm(guard_step):
    """The /review path is untouched by the narrowing — it is the only re-review door."""
    condition = guard_step["if"]
    assert "github.event_name == 'issue_comment'" in condition
    assert "startsWith(github.event.comment.body, '/review')" in condition


def test_run_still_fails_closed_on_an_empty_review(guard_step):
    """An attempted-but-empty review on a retained path still fails the job."""
    body = guard_step["run"]
    assert '-z "$REVIEW_OUTPUT"' in body
    assert "exit 1" in body


def test_run_carries_no_warning_downgrade(guard_step):
    """Negative control.

    `::warning` is the prohibited remedy, not a quieter equivalent: the non-zero exit is
    the only signal separating "reviewed, found nothing" from "never reviewed". A future
    "make it less noisy" edit must fail here rather than pass silently.
    """
    assert "::warning" not in guard_step["run"]


@pytest.mark.parametrize(("group", "tokens"), sorted(EXCLUDED_POPULATIONS.items()))
def test_comment_block_enumerates_every_excluded_population(guard_comment_block, group, tokens):
    """The reasoning for each excluded population stays in the file, so no reader re-broadens it."""
    missing = [token for token in tokens if token not in guard_comment_block]
    assert not missing, f"excluded population {group} lost token(s): {missing}"
