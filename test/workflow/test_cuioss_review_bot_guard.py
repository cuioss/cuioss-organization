"""Regression tests for the cuioss-review-bot empty-review guard's trigger scope.

The guard in `.github/workflows/reusable-cuioss-review-bot.yml` fails the job when the
reviewer produced no structured output. That assertion is only sound on runs the runner
is contractually obliged to review, so the guard's `if:` mirrors PR-Agent's own
`GITHUB_ACTION_CONFIG.PR_ACTIONS` allow-list rather than selecting on the event alone.

These tests pin the things that must not be silently undone: the narrowed trigger scope,
the fail-closed `exit 1`, the in-file enumeration of the populations that are legitimately
empty, and the upstream skip that keeps two of them — a pull request with no files, and one
whose whole diff the reviewer's own filter chain removes — from reaching the gate at all.
That skip lives in the `changes` job: its `reviewable` output, the fail-open way `review`
reads it, the image digest and script revision it shares with `review`, and the org skip
terms it copies from `review` are all pinned here, each with a negative control.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT

WORKFLOW_PATH = ".github/workflows/reusable-cuioss-review-bot.yml"
DOCS_PATH = "docs/Workflows.adoc"
MIRROR_WORKFLOW_PATH = ".github/workflows/mirror-pr-agent-image.yml"
# The reviewer image is pulled from the ghcr.io mirror, never from Docker Hub: the runner pulls
# a `docker://` image anonymously during job setup, and Docker Hub rate-limits that pull.
REVIEWER_IMAGE_PREFIX = "docker://ghcr.io/cuioss/pr-agent-mirror@sha256:"
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

    Anchored on the reviewer template's own `name:`, because Workflows.adoc documents several
    caller templates and an unanchored search binds to whichever `pull_request:` block appears
    first — a different workflow's, whose `types:` has nothing to do with this guard.
    """
    template = re.search(
        r"^name: cuioss-review-bot Review$.*?^  pull_request:\n    types: \[(.*?)\]$",
        docs_text,
        re.MULTILINE | re.DOTALL,
    )
    assert template is not None, "the cuioss-review-bot Review caller template was not found"
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


UPSTREAM_SKIP_WORDING = "skipped upstream by `changes`"


def _comment_paragraphs(block):
    """The block's paragraphs, split on its blank `#` lines, each joined into one line of prose."""
    paragraphs, current = [], []
    for line in block.splitlines():
        text = line.strip().lstrip("#").strip()
        if text:
            current.append(text)
        elif current:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


def _upstream_placement_violations(block):
    """How the block fails to place (c) and (d) upstream: they must sit under the upstream-skip
    wording, and nothing may still call them an accepted residual of the gate."""
    violations = []
    if not any("(c) and (d)" in p and UPSTREAM_SKIP_WORDING in p for p in _comment_paragraphs(block)):
        violations.append("(c) and (d) are not placed under the upstream-skip wording")
    if "accepted residual" in block:
        violations.append("the block still calls a population an accepted residual")
    return violations


def test_comment_block_places_c_and_d_upstream_of_the_gate(guard_comment_block):
    assert _upstream_placement_violations(guard_comment_block) == []


class TestUpstreamPlacementGuardBites:
    """Negative controls: the placement predicate fails on each regression of the wording."""

    def test_restoring_the_accepted_residual_wording_is_detected(self, guard_comment_block):
        block = guard_comment_block + "\n# (c) and (d) stay inside the gated population as a known, accepted residual."
        assert "the block still calls a population an accepted residual" in _upstream_placement_violations(block)

    def test_dropping_the_upstream_wording_is_detected(self, guard_comment_block):
        block = guard_comment_block.replace(UPSTREAM_SKIP_WORDING, "handled elsewhere")
        assert "(c) and (d) are not placed under the upstream-skip wording" in _upstream_placement_violations(block)


# ---------------------------------------------------------------------------
# Charter injection — the composed charter reaches the assembled reviewer step ONLY
# ---------------------------------------------------------------------------

CHARTER_ENV_KEY = "PR_REVIEWER.EXTRA_INSTRUCTIONS"
CENTRAL_STEP_ID = "review_central"
ASSEMBLED_STEP_ID = "review_assembled"
CODE_REVIEW_JOB_ID = "code-review"
CODE_STEP_ID = "review_code"
PUBLISH_STEP_ID = "publish_code"


@pytest.fixture
def workflow(workflow_text):
    return yaml.safe_load(workflow_text)


def _steps_by_id(workflow, job_id=None):
    """Steps keyed by id — in one job, or across jobs with the FIRST job declaring an id winning.

    `review` and `code-review` share step ids (`review-token`, `declaration`, `gcp-creds`, …),
    so the cross-job view resolves a shared id to `review`'s step, which every pre-existing
    assertion targets; `code-review`'s steps are addressed with `job_id`.
    """
    jobs = [workflow["jobs"][job_id]] if job_id else list(workflow["jobs"].values())
    steps = {}
    for job in jobs:
        for step in job.get("steps", []):
            if "id" in step:
                steps.setdefault(step["id"], step)
    return steps


def _steps_declaring_the_charter_key(workflow):
    """The id of every step, in any job, whose own `env:` names the charter key — the guard's one predicate."""
    return sorted(
        step["id"]
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if CHARTER_ENV_KEY in step.get("env", {})
    )


def test_the_charter_key_is_declared_on_the_charter_reviewer_steps_alone(workflow):
    """A Docker action receives only its own `env:`; on the central step the key would override the charter.

    Exactly two steps carry it: the first pass's assembled reviewer and the second pass's reviewer.
    """
    assert _steps_declaring_the_charter_key(workflow) == [ASSEMBLED_STEP_ID, CODE_STEP_ID]


def test_the_assembled_step_injects_the_composed_charter(workflow):
    value = _steps_by_id(workflow)[ASSEMBLED_STEP_ID]["env"][CHARTER_ENV_KEY]
    assert value == "${{ steps.declaration.outputs.charter }}"


def test_both_reviewer_steps_run_the_same_pinned_reviewer(workflow):
    steps = _steps_by_id(workflow)
    assert steps[ASSEMBLED_STEP_ID]["uses"] == steps[CENTRAL_STEP_ID]["uses"]
    assert steps[CENTRAL_STEP_ID]["uses"].startswith(REVIEWER_IMAGE_PREFIX)


def test_the_two_env_blocks_differ_only_by_the_charter_key(workflow):
    """Everything else the reviewer is told must be identical, whichever step runs."""
    steps = _steps_by_id(workflow)
    assembled = {key: value for key, value in steps[ASSEMBLED_STEP_ID]["env"].items() if key != CHARTER_ENV_KEY}
    assert assembled == steps[CENTRAL_STEP_ID]["env"]


def test_the_reviewer_steps_are_selected_by_the_enabled_decision(workflow):
    """Only the `assembled` decision runs the assembled step; every other value runs the central one.

    The two conditions are exact complements, so a successful declaration step runs exactly
    one reviewer — and an unexpected value falls back to the central charter, never to none.
    """
    steps = _steps_by_id(workflow)
    assert steps[ASSEMBLED_STEP_ID]["if"] == "steps.declaration.outputs.charter-source == 'assembled'"
    assert steps[CENTRAL_STEP_ID]["if"] == "steps.declaration.outputs.charter-source != 'assembled'"


def test_the_gate_reads_whichever_reviewer_step_ran(guard_step):
    assert guard_step["env"]["REVIEW_OUTPUT"] == (
        "${{ steps.review_assembled.outputs.review || steps.review_central.outputs.review }}"
    )


class TestCharterKeyGuardBites:
    """Negative controls: the placement predicate fails on each violating mutation."""

    def test_moving_the_key_to_the_central_step_is_detected(self, workflow):
        steps = _steps_by_id(workflow)
        steps[CENTRAL_STEP_ID]["env"][CHARTER_ENV_KEY] = steps[ASSEMBLED_STEP_ID]["env"].pop(CHARTER_ENV_KEY)
        assert _steps_declaring_the_charter_key(workflow) == [CENTRAL_STEP_ID, CODE_STEP_ID]

    def test_adding_the_key_to_the_central_step_is_detected(self, workflow):
        steps = _steps_by_id(workflow)
        steps[CENTRAL_STEP_ID]["env"][CHARTER_ENV_KEY] = ""
        assert _steps_declaring_the_charter_key(workflow) == [ASSEMBLED_STEP_ID, CENTRAL_STEP_ID, CODE_STEP_ID]

    def test_dropping_the_key_from_the_assembled_step_is_detected(self, workflow):
        del _steps_by_id(workflow)[ASSEMBLED_STEP_ID]["env"][CHARTER_ENV_KEY]
        assert _steps_declaring_the_charter_key(workflow) == [CODE_STEP_ID]

    def test_dropping_the_key_from_the_code_review_step_is_detected(self, workflow):
        del _steps_by_id(workflow, CODE_REVIEW_JOB_ID)[CODE_STEP_ID]["env"][CHARTER_ENV_KEY]
        assert _steps_declaring_the_charter_key(workflow) == [ASSEMBLED_STEP_ID]

    def test_adding_the_key_to_the_publisher_is_detected(self, workflow):
        _steps_by_id(workflow, CODE_REVIEW_JOB_ID)[PUBLISH_STEP_ID]["env"][CHARTER_ENV_KEY] = ""
        assert _steps_declaring_the_charter_key(workflow) == [PUBLISH_STEP_ID, ASSEMBLED_STEP_ID, CODE_STEP_ID]


# ---------------------------------------------------------------------------
# Fail, never warn — a failure anywhere in the workflow fails the job
# ---------------------------------------------------------------------------

DECLARATION_STEP_ID = "declaration"
GCP_CREDS_STEP_ID = "gcp-creds"

# A shell idiom that turns a failing command into a passing one.
SWALLOWED_FAILURE = re.compile(r"\|\|\s*(?:true|:|exit\s+0)(?=\s|;|$)|\bset\s+\+e\b", re.MULTILINE)

# A step `if:` naming one of these is evaluated even after an earlier step failed.
STATUS_FUNCTIONS = ("always()", "failure()", "cancelled()")


def _label(step):
    return step.get("id") or step.get("name")


def _fail_not_warn_violations(workflow):
    """Every place a workflow step could report a failure without failing the job.

    A step that emits `::error::` must end in `exit 1` right after it; no step may emit
    `::warning`, swallow a failing command, or set `continue-on-error`.
    """
    violations = []
    for job_id, job in workflow["jobs"].items():
        if job.get("continue-on-error"):
            violations.append(f"job {job_id}: continue-on-error")
        for step in job.get("steps", []):
            label = _label(step)
            if step.get("continue-on-error"):
                violations.append(f"{label}: continue-on-error")
            run = step.get("run", "")
            if "::warning" in run:
                violations.append(f"{label}: emits ::warning")
            if SWALLOWED_FAILURE.search(run):
                violations.append(f"{label}: swallows a failing command")
            lines = [line.strip() for line in run.splitlines() if line.strip()]
            for index, line in enumerate(lines):
                if "::error::" in line and lines[index + 1 : index + 2] != ["exit 1"]:
                    violations.append(f"{label}: ::error:: is not followed by exit 1")
    return violations


def _steps_running_past_a_failed_declaration(workflow, job_id="review"):
    """The steps after the declaration read whose `if:` would run them even though it failed."""
    steps = workflow["jobs"][job_id]["steps"]
    declaration = next(index for index, step in enumerate(steps) if step.get("id") == DECLARATION_STEP_ID)
    return [
        _label(step)
        for step in steps[declaration + 1 :]
        if any(function in str(step.get("if", "")) for function in STATUS_FUNCTIONS)
    ]


def test_no_failure_is_downgraded_or_swallowed(workflow):
    assert _fail_not_warn_violations(workflow) == []


def test_the_guard_inspects_every_step_that_reports_an_error(workflow):
    """Non-vacuity: the steps that emit `::error::` exist, so the exit-1 rule is exercised."""
    reporting = {
        _label(step)
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if "::error::" in step.get("run", "")
    }
    assert {GCP_CREDS_STEP_ID, GUARD_STEP_NAME, CODE_GATE_STEP_NAME} <= reporting


@pytest.mark.parametrize("job_id", ["review", CODE_REVIEW_JOB_ID])
def test_a_failed_declaration_stops_every_later_step(workflow, job_id):
    """The reviewer steps, the publisher and the gates must not run after the declaration read failed."""
    assert _steps_running_past_a_failed_declaration(workflow, job_id) == []


@pytest.mark.parametrize("job_id", ["review", CODE_REVIEW_JOB_ID])
def test_the_declaration_step_ends_in_the_script_whose_exit_it_reports(workflow, job_id):
    """The script is the step's last command, so its exit status is the step's, under any shell flags."""
    run = _steps_by_id(workflow, job_id)[DECLARATION_STEP_ID]["run"]
    last = [line.strip() for line in run.splitlines() if line.strip()][-2:]
    assert last[0].startswith("python3 .cuioss-organization/workflow-scripts/assemble-review-charter.py read")
    assert last[1] == '--http-status "$status" --body-file "$RUNNER_TEMP/project.yml" >> "$GITHUB_OUTPUT"'


def test_both_jobs_read_the_declaration_identically(workflow):
    """The second pass reads the same declaration, the same way, as the first."""
    review = _steps_by_id(workflow, "review")[DECLARATION_STEP_ID]
    code_review = _steps_by_id(workflow, CODE_REVIEW_JOB_ID)[DECLARATION_STEP_ID]
    assert code_review == review


class TestFailNotWarnGuardBites:
    """Negative controls: each downgrade of a failure is detected."""

    def test_downgrading_the_gate_to_a_warning_is_detected(self, workflow):
        step = next(step for step in workflow["jobs"]["review"]["steps"] if step.get("name") == GUARD_STEP_NAME)
        step["run"] = step["run"].replace("::error::", "::warning::")
        assert f"{GUARD_STEP_NAME}: emits ::warning" in _fail_not_warn_violations(workflow)

    def test_an_error_without_exit_1_is_detected(self, workflow):
        step = _steps_by_id(workflow)[GCP_CREDS_STEP_ID]
        step["run"] = step["run"].replace("exit 1", ":", 1)
        assert f"{GCP_CREDS_STEP_ID}: ::error:: is not followed by exit 1" in _fail_not_warn_violations(workflow)

    @pytest.mark.parametrize("swallow", [" || true", " || :", " || exit 0"])
    def test_swallowing_the_declaration_failure_is_detected(self, workflow, swallow):
        step = _steps_by_id(workflow)[DECLARATION_STEP_ID]
        step["run"] = step["run"].rstrip("\n") + swallow + "\n"
        assert f"{DECLARATION_STEP_ID}: swallows a failing command" in _fail_not_warn_violations(workflow)

    def test_continue_on_error_on_the_declaration_is_detected(self, workflow):
        _steps_by_id(workflow)[DECLARATION_STEP_ID]["continue-on-error"] = True
        assert f"{DECLARATION_STEP_ID}: continue-on-error" in _fail_not_warn_violations(workflow)

    @pytest.mark.parametrize("function", STATUS_FUNCTIONS)
    def test_a_reviewer_step_running_past_a_failure_is_detected(self, workflow, function):
        step = _steps_by_id(workflow)[CENTRAL_STEP_ID]
        step["if"] = f"{function} && {step['if']}"
        assert _steps_running_past_a_failed_declaration(workflow) == [CENTRAL_STEP_ID]

    def test_a_warning_in_the_changes_job_is_detected(self, workflow):
        """Non-vacuity for the `changes` job: the fail-not-warn scan reaches its steps too."""
        _steps_by_id(workflow)[ZERO_FILES_STEP_ID]["run"] += '\necho "::warning::no files"\n'
        assert f"{ZERO_FILES_STEP_ID}: emits ::warning" in _fail_not_warn_violations(workflow)

    def test_downgrading_the_code_review_gate_to_a_warning_is_detected(self, workflow):
        """Non-vacuity for the `code-review` job: the fail-not-warn scan reaches its steps too."""
        step = _code_gate(workflow)
        step["run"] = step["run"].replace("::error::", "::warning::")
        assert f"{CODE_GATE_STEP_NAME}: emits ::warning" in _fail_not_warn_violations(workflow)

    def test_an_error_without_exit_1_in_the_code_review_job_is_detected(self, workflow):
        step = _steps_by_id(workflow, CODE_REVIEW_JOB_ID)[GCP_CREDS_STEP_ID]
        step["run"] = step["run"].replace("exit 1", ":", 1)
        assert f"{GCP_CREDS_STEP_ID}: ::error:: is not followed by exit 1" in _fail_not_warn_violations(workflow)

    def test_continue_on_error_on_the_publisher_is_detected(self, workflow):
        _steps_by_id(workflow, CODE_REVIEW_JOB_ID)[PUBLISH_STEP_ID]["continue-on-error"] = True
        assert f"{PUBLISH_STEP_ID}: continue-on-error" in _fail_not_warn_violations(workflow)

    @pytest.mark.parametrize("function", STATUS_FUNCTIONS)
    @pytest.mark.parametrize("step_id", [CODE_STEP_ID, PUBLISH_STEP_ID])
    def test_a_code_review_step_running_past_a_failure_is_detected(self, workflow, function, step_id):
        step = _steps_by_id(workflow, CODE_REVIEW_JOB_ID)[step_id]
        step["if"] = f"{function} && {step['if']}"
        assert _steps_running_past_a_failed_declaration(workflow, CODE_REVIEW_JOB_ID) == [step_id]


# ---------------------------------------------------------------------------
# The upstream skip — `changes` decides, `review` reads the decision fail-open
# ---------------------------------------------------------------------------

ZERO_FILES_STEP_ID = "zero-files"
CLASSIFY_STEP_ID = "classify"
REVIEWABLE_TERM = "needs.changes.outputs.reviewable != 'false'"
PULL_REQUEST_EVENT_TERM = "github.event_name == 'pull_request'"
SELF_REPOSITORY = "cuioss/cuioss-organization"
ORG_SKIP_TERMS = {
    "github.event.pull_request.head.repo.fork == false",
    "github.event.pull_request.user.login != 'dependabot[bot]'",
    "github.event.pull_request.user.login != 'cuioss-release-bot[bot]'",
    "github.event.pull_request.user.login != format('{0}-release-bot[bot]', github.repository_owner)",
    "!contains(github.event.pull_request.labels.*.name, 'skip-bot-review')",
}

# The gate step exactly as it stands on main @ e5ddcd5. The upstream skip changes which runs
# reach the gate, never the gate itself.
GATE_IF = (
    "${{ (github.event_name == 'pull_request'\n"
    "     && inputs.auto-review\n"
    '     && contains(fromJSON(\'["opened", "reopened", "ready_for_review", "review_requested"]\'),\n'
    "                 github.event.action))\n"
    "    || (github.event_name == 'issue_comment'\n"
    "        && startsWith(github.event.comment.body, '/review')) }}"
)
GATE_RUN = """\
if [[ -z "$REVIEW_OUTPUT" ]]; then
  echo "::error::PR-Agent produced no review for this run. Its action exits 0 even when every model call fails — read the log of whichever 'Review pull request' step ran for the real cause (look for 'Error during LLM inference' / 'Failed to generate prediction with any model')."
  exit 1
fi
echo "Reviewer produced a review: ${REVIEW_OUTPUT}"
# Informational only. A review with no findings is deliberately not published, so the
# absence of a comment is a legitimate outcome and must never fail the job.
gh api "repos/${REPO}/issues/${PR_NUMBER}/comments" --paginate > comments.json
fresh="$(jq --arg since "$STARTED_AT" '
  [ .[]
    | select(.user.login | startswith("cuioss-review-bot"))
    | select(.body | startswith("## PR Reviewer Guide"))
    | select(.updated_at >= $since)
  ] | length' comments.json)"
if [[ "${fresh:-0}" -ge 1 ]]; then
  echo "Published as a review comment on the pull request."
else
  echo "Nothing published — the review carried no findings worth a comment."
fi
"""


def test_the_gate_step_is_unchanged_byte_for_byte(guard_step):
    assert guard_step["if"] == GATE_IF
    assert guard_step["run"] == GATE_RUN


def _reviewable_contract_violations(workflow, workflow_text):
    """Every way the `changes` -> `review` hand-off could stop meaning "skip only on 'false'"."""
    violations = []
    changes, review = workflow["jobs"]["changes"], workflow["jobs"]["review"]
    if set(changes.get("outputs", {})) != {"reviewable"}:
        violations.append(f"changes exposes {sorted(changes.get('outputs', {}))}, not exactly reviewable")
    if "always()" not in review["if"]:
        violations.append("review lost always(), so a skipped changes job would skip it too")
    if REVIEWABLE_TERM not in " ".join(review["if"].split()):
        violations.append("review does not read the reviewable output fail-open (!= 'false')")
    if "non_plan" in workflow_text:
        violations.append("the retired non_plan output is still referenced")
    if any("paths-filter" in str(step.get("uses", "")) for step in changes["steps"]):
        violations.append("changes still carries a hand-maintained paths filter")
    return violations


def test_review_reads_the_reviewable_decision_fail_open(workflow, workflow_text):
    assert _reviewable_contract_violations(workflow, workflow_text) == []


PR_AGENT_STEP_IDS = (CLASSIFY_STEP_ID, CENTRAL_STEP_ID, ASSEMBLED_STEP_ID, CODE_STEP_ID, PUBLISH_STEP_ID)


def _pinned_reviewer_images(workflow):
    """The image each step running PR-Agent pins: the classifier, the three reviewer steps, the publisher."""
    steps = _steps_by_id(workflow)
    return {step_id: steps[step_id]["uses"] for step_id in PR_AGENT_STEP_IDS}


def _docker_step_ids(workflow):
    """The id of every `docker://` step, in any job."""
    return {
        step.get("id")
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if str(step.get("uses", "")).startswith("docker://")
    }


def test_the_classifier_runs_the_reviewers_exact_image(workflow):
    """One digest for all five sites, so the filter chain classified is the one the reviewer applies,
    and the publisher renders with the code the reviewer ran."""
    images = set(_pinned_reviewer_images(workflow).values())
    assert len(images) == 1
    assert next(iter(images)).startswith(REVIEWER_IMAGE_PREFIX)


def test_every_docker_step_is_one_of_the_pinned_sites(workflow):
    """Non-vacuity: no `docker://` step escapes the one-digest comparison above."""
    assert _docker_step_ids(workflow) == set(PR_AGENT_STEP_IDS)


def _image_the_mirror_workflow_publishes(project_root):
    """The image name mirror-pr-agent-image.yml pushes to, in the form a `docker://` step names it."""
    mirror = yaml.safe_load((project_root / MIRROR_WORKFLOW_PATH).read_text(encoding="utf-8"))
    return "docker://" + mirror["jobs"]["mirror"]["env"]["MIRROR_IMAGE"] + "@sha256:"


def test_the_reviewer_image_is_the_one_the_mirror_workflow_publishes(project_root):
    """A bump mirrors first, then repins; the two files must agree on where the image lives."""
    assert _image_the_mirror_workflow_publishes(project_root) == REVIEWER_IMAGE_PREFIX


def _images_not_pulled_from_the_mirror(workflow):
    """Every `docker://` image, in any job, that names anything but the mirror."""
    steps = [step for job in workflow["jobs"].values() for step in job.get("steps", [])]
    images = [str(step.get("uses", "")) for step in steps]
    return [image for image in images if image.startswith("docker://") and not image.startswith(REVIEWER_IMAGE_PREFIX)]


def test_no_step_pulls_an_image_from_docker_hub(workflow):
    """A `docker://` reference without a registry host resolves to Docker Hub and its anonymous rate limit."""
    assert _images_not_pulled_from_the_mirror(workflow) == []


def _self_checkout_refs(workflow):
    """The `ref:` of every checkout of this repository, keyed by the job it runs in."""
    return {
        job_id: step["with"]["ref"]
        for job_id, job in workflow["jobs"].items()
        for step in job.get("steps", [])
        if step.get("with", {}).get("repository") == SELF_REPOSITORY
    }


def test_every_job_runs_the_same_revision_of_the_scripts(workflow):
    refs = _self_checkout_refs(workflow)
    assert set(refs) == {"changes", "review", CODE_REVIEW_JOB_ID}
    assert len(set(refs.values())) == 1


def _split_top_level(expression, operator):
    """Split a GitHub expression on `operator` outside parentheses and quoted strings."""
    parts, depth, start, index, quoted = [], 0, 0, 0, False
    while index < len(expression):
        char = expression[index]
        if char == "'":
            quoted = not quoted
        elif not quoted and char in "()":
            depth += 1 if char == "(" else -1
        elif not quoted and depth == 0 and expression.startswith(operator, index):
            parts.append(expression[start:index])
            index += len(operator)
            start = index
            continue
        index += 1
    parts.append(expression[start:])
    return [" ".join(part.split()) for part in parts]


def _closing_paren_index(text):
    """Index of the parenthesis closing the one `text` opens with, outside quoted strings."""
    depth, quoted = 0, False
    for index, char in enumerate(text):
        if char == "'":
            quoted = not quoted
        elif not quoted and char in "()":
            depth += 1 if char == "(" else -1
            if depth == 0:
                return index
    return -1


def _strip_outer_parens(term):
    """Drop parentheses that enclose the whole term."""
    term = term.strip()
    while term.startswith("(") and _closing_paren_index(term) == len(term) - 1:
        term = term[1:-1].strip()
    return term


def _review_pull_request_terms(review_if):
    """The conjuncts of `review`'s pull_request branch."""
    for conjunct in _split_top_level(review_if, "&&"):
        for arm in _split_top_level(_strip_outer_parens(conjunct), "||"):
            terms = _split_top_level(_strip_outer_parens(arm), "&&")
            if PULL_REQUEST_EVENT_TERM in terms:
                return set(terms)
    raise AssertionError("the review job's pull_request branch was not found")


def _skip_term_drift(workflow):
    """(terms `review` has that `changes` lacks, terms `changes` has that `review` lacks)."""
    changes = set(_split_top_level(workflow["jobs"]["changes"]["if"], "&&"))
    review = _review_pull_request_terms(workflow["jobs"]["review"]["if"]) - {REVIEWABLE_TERM}
    return review - changes, changes - review


def test_changes_copies_the_org_skip_terms_of_review(workflow):
    """A skipped `changes` is harmless only while it skips exactly the pull requests `review` skips."""
    assert _skip_term_drift(workflow) == (set(), set())
    assert set(_split_top_level(workflow["jobs"]["changes"]["if"], "&&")) == ORG_SKIP_TERMS | {PULL_REQUEST_EVENT_TERM}


class TestUpstreamSkipGuardBites:
    """Negative controls: each drift of the upstream skip's contract is detected."""

    def test_a_renamed_output_is_detected(self, workflow, workflow_text):
        outputs = workflow["jobs"]["changes"]["outputs"]
        outputs["non_plan"] = outputs.pop("reviewable")
        assert "changes exposes ['non_plan'], not exactly reviewable" in _reviewable_contract_violations(
            workflow, workflow_text
        )

    def test_a_fail_closed_reading_is_detected(self, workflow, workflow_text):
        review = workflow["jobs"]["review"]
        review["if"] = review["if"].replace(REVIEWABLE_TERM, "needs.changes.outputs.reviewable == 'true'")
        assert "review does not read the reviewable output fail-open (!= 'false')" in (
            _reviewable_contract_violations(workflow, workflow_text)
        )

    def test_dropping_always_is_detected(self, workflow, workflow_text):
        review = workflow["jobs"]["review"]
        review["if"] = review["if"].replace("always() && ", "", 1)
        assert "review lost always(), so a skipped changes job would skip it too" in (
            _reviewable_contract_violations(workflow, workflow_text)
        )

    def test_a_digest_bump_missing_the_classifier_is_detected(self, workflow):
        _steps_by_id(workflow)[CLASSIFY_STEP_ID]["uses"] = REVIEWER_IMAGE_PREFIX + "0" * 64
        assert len(set(_pinned_reviewer_images(workflow).values())) == 2

    def test_a_step_pulling_from_docker_hub_is_detected(self, workflow):
        hub_image = "docker://pragent/pr-agent@sha256:" + "0" * 64
        _steps_by_id(workflow)[CENTRAL_STEP_ID]["uses"] = hub_image
        assert _images_not_pulled_from_the_mirror(workflow) == [hub_image]

    def test_a_diverging_script_revision_is_detected(self, workflow):
        checkout = next(step for step in workflow["jobs"]["changes"]["steps"] if "with" in step)
        checkout["with"]["ref"] = "0" * 40
        refs = _self_checkout_refs(workflow)
        assert refs["changes"] != refs["review"]

    @pytest.mark.parametrize("step_id", [CODE_STEP_ID, PUBLISH_STEP_ID])
    def test_a_digest_bump_missing_a_code_review_step_is_detected(self, workflow, step_id):
        _steps_by_id(workflow, CODE_REVIEW_JOB_ID)[step_id]["uses"] = REVIEWER_IMAGE_PREFIX + "0" * 64
        assert len(set(_pinned_reviewer_images(workflow).values())) == 2

    def test_a_diverging_code_review_script_revision_is_detected(self, workflow):
        checkout = next(
            step
            for step in workflow["jobs"][CODE_REVIEW_JOB_ID]["steps"]
            if step.get("with", {}).get("repository") == SELF_REPOSITORY
        )
        checkout["with"]["ref"] = "0" * 40
        assert len(set(_self_checkout_refs(workflow).values())) == 2

    def test_dropping_a_term_from_review_alone_is_detected(self, workflow):
        review = workflow["jobs"]["review"]
        review["if"] = review["if"].replace("github.event.pull_request.user.login != 'dependabot[bot]' &&", "", 1)
        assert _skip_term_drift(workflow) == (set(), {"github.event.pull_request.user.login != 'dependabot[bot]'"})

    def test_an_extra_term_in_changes_alone_is_detected(self, workflow):
        changes = workflow["jobs"]["changes"]
        changes["if"] += " && github.actor != 'renovate[bot]'"
        assert _skip_term_drift(workflow) == (set(), {"github.actor != 'renovate[bot]'"})

    def test_dropping_a_term_from_changes_alone_is_detected(self, workflow):
        changes = workflow["jobs"]["changes"]
        changes["if"] = changes["if"].replace(" && github.event.pull_request.head.repo.fork == false", "", 1)
        assert _skip_term_drift(workflow) == ({"github.event.pull_request.head.repo.fork == false"}, set())


# ---------------------------------------------------------------------------
# The decision the `changes` job computes, over recorded survivor lists
# ---------------------------------------------------------------------------

CLASSIFIER_PATH = PROJECT_ROOT / "workflow-scripts/classify-review-diff.py"
API_SHERIFF_340_FILES_PATH = PROJECT_ROOT / "test/fixtures/api-sheriff-340-changed-files.txt"
REVIEWABLE_SOURCE_FILE = "src/main/java/de/cuioss/sheriff/api/Gateway.java"


def _load_classifier():
    spec = importlib.util.spec_from_file_location("classify_review_diff", CLASSIFIER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


classifier = _load_classifier()


@pytest.fixture
def api_sheriff_340_files():
    """The 71 files API-Sheriff#340 changed: `.gitignore` plus 70 `.plan/orchestrator/**` paths."""
    lines = API_SHERIFF_340_FILES_PATH.read_text(encoding="utf-8").splitlines()
    files = tuple(line for line in lines if line and not line.startswith("#"))
    assert len(files) == 71 and files[0] == ".gitignore"
    return files


def _recorded(listed, survivors):
    """A resolution replaying a recorded filter-chain outcome rather than computing one."""
    return lambda: classifier.Resolution(
        listed=len(listed), survivors=tuple(survivors), settings=("defaults", "global")
    )


def test_api_sheriff_340_is_not_reviewable(api_sheriff_340_files):
    """The pull request that failed the gate is skipped upstream.

    This pins the DECISION LOGIC over a recorded survivor list: run 35709715234 showed the
    runner's `[ignore]` filter leave `.gitignore` and its invalid-extension filter remove it,
    so no file survived. The 71 paths are provenance and the `changed_files` count; the
    survivors are recorded, not computed. It does not exercise the in-image resolution — the
    docker step, PYTHONPATH=/app, apply_repo_settings, GithubProvider.get_diff_files — which
    runs only inside the pinned image and is observed live on a consumer pull request.
    """
    decision = classifier.classify(len(api_sheriff_340_files), _recorded(api_sheriff_340_files, ()))
    assert (decision.reviewable, decision.survivors, decision.notice) == (False, 0, None)


def test_a_mixed_diff_is_reviewable(api_sheriff_340_files):
    """The same list plus one source file that survives the filter chain must still be reviewed."""
    listed = (*api_sheriff_340_files, REVIEWABLE_SOURCE_FILE)
    decision = classifier.classify(len(listed), _recorded(listed, (REVIEWABLE_SOURCE_FILE,)))
    assert (decision.reviewable, decision.survivors) == (True, 1)


def test_an_unresolvable_filter_chain_fails_open_with_a_notice(api_sheriff_340_files):
    def unresolvable():
        raise classifier.ResolutionError("the settings repository could not be read")

    decision = classifier.classify(len(api_sheriff_340_files), unresolvable)
    rendered = classifier.render_stdout(decision)
    assert decision.reviewable is True
    assert "::notice::classify-review-diff fail-open: the settings repository could not be read" in rendered
    assert "::warning" not in rendered


def test_a_pull_request_with_no_files_is_not_reviewable():
    def never_resolved():
        raise AssertionError("a pull request with no files needs no filter chain")

    assert classifier.classify(0, never_resolved).reviewable is False


class TestCallableFromAnotherOrganisation:
    """Everything that addresses the caller's organisation follows the caller, never a literal."""

    def test_the_token_is_minted_in_the_callers_organisation(self, workflow):
        token = _steps_by_id(workflow)["review-token"]["with"]
        assert token["owner"] == "${{ github.repository_owner }}"
        assert token["repositories"] == "${{ github.event.repository.name }},${{ inputs.settings-repository }}"

    def test_the_settings_repository_input_defaults_to_the_cuioss_one(self, workflow):
        # PyYAML reads the bare `on:` key as the boolean True.
        triggers = workflow.get("on") or workflow[True]
        settings = triggers["workflow_call"]["inputs"]["settings-repository"]
        assert settings["type"] == "string"
        assert settings["required"] is False
        assert settings["default"] == "cuioss-review-bot"

    def test_the_packs_are_read_from_the_callers_settings_repository(self, workflow):
        env = _steps_by_id(workflow)[DECLARATION_STEP_ID]["env"]
        assert env["SETTINGS_REPOSITORY"] == "${{ github.repository_owner }}/${{ inputs.settings-repository }}"


# ---------------------------------------------------------------------------
# The second pass — the `code-review` job
# ---------------------------------------------------------------------------

CODE_GATE_STEP_NAME = "Verify the code reviewer produced and published a review"
ASSEMBLED_TERM = "steps.declaration.outputs.code-review-source == 'assembled'"
ISSUE_COMMENT_EVENT_TERM = "github.event_name == 'issue_comment'"
COMMAND_TERM = re.compile(r"startsWith\(github\.event\.comment\.body, '(/[a-z]+)'\)")

# The second pass's reviewer env, as it differs from the central reviewer's: nothing else may.
CODE_ENV_EXCEPTIONS = {
    "github_action_config.auto_describe": False,
    "github_action_config.auto_improve": False,
    "CONFIG.PUBLISH_OUTPUT": False,
    CHARTER_ENV_KEY: "${{ steps.declaration.outputs.code-review-charter }}",
}

CODE_GATE_IF = (
    "${{ steps.declaration.outputs.code-review-source == 'assembled'\n"
    "    && ((github.event_name == 'pull_request'\n"
    "         && inputs.auto-review\n"
    '         && contains(fromJSON(\'["opened", "reopened", "ready_for_review", "review_requested"]\'),\n'
    "                     github.event.action))\n"
    "        || (github.event_name == 'issue_comment'\n"
    "            && startsWith(github.event.comment.body, '/review'))) }}"
)
CODE_GATE_RUN = """\
if [[ -z "$REVIEW_OUTPUT" ]]; then
  echo "::error::PR-Agent produced no code review for this run. Its action exits 0 even when every model call fails — read the log of the 'Review pull request (code-review charter)' step for the real cause (look for 'Error during LLM inference' / 'Failed to generate prediction with any model')."
  exit 1
fi
echo "Code reviewer produced a review: ${REVIEW_OUTPUT}"
if [[ "$PUBLISHED" != "true" ]]; then
  echo "::error::The code review was not published as a fresh '## PR Code Review Guide 🧭' comment — read the log of the 'Publish the code review' step."
  exit 1
fi
echo "Published as the code-review comment on the pull request."
"""
CODE_GATE_ENV = {
    "REVIEW_OUTPUT": "${{ steps.review_code.outputs.review }}",
    "PUBLISHED": "${{ steps.publish_code.outputs.published }}",
}


def _code_gate(workflow):
    """The second pass's gate step, located by name in the `code-review` job."""
    return next(
        step for step in workflow["jobs"][CODE_REVIEW_JOB_ID]["steps"] if step.get("name") == CODE_GATE_STEP_NAME
    )


def _arm_terms(job_if, event_term):
    """The conjuncts of the arm of a job's `if:` that tests for `event_term`."""
    for conjunct in _split_top_level(job_if, "&&"):
        for arm in _split_top_level(_strip_outer_parens(conjunct), "||"):
            terms = _split_top_level(_strip_outer_parens(arm), "&&")
            if event_term in terms:
                return terms
    raise AssertionError(f"no arm tests {event_term}")


def _pull_request_term_drift(workflow):
    """(terms `review`'s pull_request arm has that `code-review`'s lacks, and the reverse)."""
    review = set(_arm_terms(workflow["jobs"]["review"]["if"], PULL_REQUEST_EVENT_TERM))
    code_review = set(_arm_terms(workflow["jobs"][CODE_REVIEW_JOB_ID]["if"], PULL_REQUEST_EVENT_TERM))
    return review - code_review, code_review - review


def _admitted_commands(job_if):
    """The slash commands the job's issue_comment arm admits."""
    arm = " && ".join(_arm_terms(job_if, ISSUE_COMMENT_EVENT_TERM))
    return set(COMMAND_TERM.findall(arm))


def _issue_comment_who_gate(job_if):
    """The issue_comment arm's terms other than its command match — the WHO gate."""
    return {term for term in _arm_terms(job_if, ISSUE_COMMENT_EVENT_TERM) if not COMMAND_TERM.search(term)}


def _code_env_drift(workflow):
    """How `review_code`'s env differs from the central reviewer's beyond the named exceptions."""
    central = _steps_by_id(workflow, "review")[CENTRAL_STEP_ID]["env"]
    code = _steps_by_id(workflow, CODE_REVIEW_JOB_ID)[CODE_STEP_ID]["env"]
    drift = []
    for key in sorted(set(central) | set(code) | set(CODE_ENV_EXCEPTIONS)):
        if key in CODE_ENV_EXCEPTIONS:
            if code.get(key) != CODE_ENV_EXCEPTIONS[key]:
                drift.append(f"{key}: {code.get(key)!r}, not {CODE_ENV_EXCEPTIONS[key]!r}")
        elif central.get(key) != code.get(key):
            drift.append(f"{key}: {code.get(key)!r} differs from the central {central.get(key)!r}")
    return drift


def _code_gate_violations(workflow):
    """Every way the second pass's gate could stop failing closed."""
    step = _code_gate(workflow)
    violations = []
    if step.get("if") != CODE_GATE_IF:
        violations.append("the gate's if: drifted")
    if step.get("run") != CODE_GATE_RUN:
        violations.append("the gate's run: drifted")
    if step.get("env") != CODE_GATE_ENV:
        violations.append("the gate's env: drifted")
    run = step.get("run", "")
    if '-z "$REVIEW_OUTPUT"' not in run:
        violations.append("the gate does not fail on an empty review")
    if '"$PUBLISHED" != "true"' not in run:
        violations.append("the gate does not fail on an unpublished review")
    if run.count("exit 1") != 2:
        violations.append("the gate does not exit 1 on both failures")
    return violations


def _unguarded_code_review_steps(workflow):
    """The steps after the declaration read that would run for a repository without the second pass."""
    steps = workflow["jobs"][CODE_REVIEW_JOB_ID]["steps"]
    declaration = next(index for index, step in enumerate(steps) if step.get("id") == DECLARATION_STEP_ID)
    return [_label(step) for step in steps[declaration + 1 :] if ASSEMBLED_TERM not in str(step.get("if", ""))]


def test_code_review_runs_on_exactly_the_pull_requests_review_runs_on(workflow):
    assert _pull_request_term_drift(workflow) == (set(), set())
    terms = set(_arm_terms(workflow["jobs"][CODE_REVIEW_JOB_ID]["if"], PULL_REQUEST_EVENT_TERM))
    assert terms == ORG_SKIP_TERMS | {PULL_REQUEST_EVENT_TERM, REVIEWABLE_TERM}


def test_code_review_keeps_always_and_needs_changes(workflow):
    """The same reason as `review`: a skipped `changes` must not skip this job."""
    job = workflow["jobs"][CODE_REVIEW_JOB_ID]
    assert job["needs"] == "changes"
    assert job["if"].startswith("always() && ")


def test_code_review_comment_arm_admits_review_alone(workflow):
    assert _admitted_commands(workflow["jobs"][CODE_REVIEW_JOB_ID]["if"]) == {"/review"}


def test_code_review_comment_arm_keeps_the_who_gate_of_review(workflow):
    assert _issue_comment_who_gate(workflow["jobs"][CODE_REVIEW_JOB_ID]["if"]) == _issue_comment_who_gate(
        workflow["jobs"]["review"]["if"]
    )


def test_the_code_reviewer_env_is_the_central_env_plus_the_named_exceptions(workflow):
    assert _code_env_drift(workflow) == []


def test_the_code_reviewer_keeps_the_security_row(workflow):
    """REQUIRE_SECURITY_REVIEW is deliberately not set anywhere: the central setting stands."""
    keys = [key for job in workflow["jobs"].values() for step in job.get("steps", []) for key in step.get("env", {})]
    assert not [key for key in keys if "require_security_review" in key.lower()]


def test_every_step_after_the_declaration_runs_only_for_the_second_pass(workflow):
    """A repository without the second pass ends the job green after the declaration's one log line."""
    assert _unguarded_code_review_steps(workflow) == []


def test_the_publisher_runs_the_script_in_the_pinned_image(workflow):
    step = _steps_by_id(workflow, CODE_REVIEW_JOB_ID)[PUBLISH_STEP_ID]
    assert step["with"] == {
        "entrypoint": "python",
        "args": "/github/workspace/.cuioss-organization/workflow-scripts/publish-code-review.py",
    }
    assert step["env"]["GITHUB_TOKEN"] == "${{ steps.review-token.outputs.token }}"
    assert step["env"]["PYTHONPATH"] == "/app"
    assert step["env"]["REVIEW"] == "${{ steps.review_code.outputs.review }}"
    assert step["env"]["STARTED_AT"] == "${{ steps.started.outputs.at }}"


def test_the_code_review_gate_is_pinned(workflow):
    assert _code_gate_violations(workflow) == []


def test_the_code_review_gate_scope_is_the_first_gate_scope(workflow, guard_step):
    """The same runs are gated in both passes: the first gate's scope, conjoined with the pass running."""
    scope = " ".join(GATE_IF.removeprefix("${{").removesuffix("}}").split())
    code_scope = " ".join(_code_gate(workflow)["if"].removeprefix("${{").removesuffix("}}").split())
    assert code_scope == f"{ASSEMBLED_TERM} && ({scope})"
    assert guard_step["if"] == GATE_IF


class TestCodeReviewGuardBites:
    """Negative controls: each drift of the second pass's contract is detected."""

    def test_dropping_a_skip_term_from_code_review_is_detected(self, workflow):
        job = workflow["jobs"][CODE_REVIEW_JOB_ID]
        job["if"] = job["if"].replace("!contains(github.event.pull_request.labels.*.name, 'skip-bot-review') &&", "", 1)
        assert _pull_request_term_drift(workflow) == (
            {"!contains(github.event.pull_request.labels.*.name, 'skip-bot-review')"},
            set(),
        )

    def test_dropping_the_reviewable_term_from_code_review_is_detected(self, workflow):
        job = workflow["jobs"][CODE_REVIEW_JOB_ID]
        job["if"] = job["if"].replace(" &&\n  needs.changes.outputs.reviewable != 'false'", "", 1)
        assert _pull_request_term_drift(workflow) == ({REVIEWABLE_TERM}, set())

    def test_an_extra_term_in_code_review_is_detected(self, workflow):
        job = workflow["jobs"][CODE_REVIEW_JOB_ID]
        job["if"] = job["if"].replace(
            "github.event.pull_request.head.repo.fork == false &&",
            "github.event.pull_request.head.repo.fork == false && github.event.pull_request.draft == false &&",
            1,
        )
        assert _pull_request_term_drift(workflow) == (set(), {"github.event.pull_request.draft == false"})

    @pytest.mark.parametrize("command", ["/improve", "/ask", "/describe"])
    def test_admitting_another_command_is_detected(self, workflow, command):
        job = workflow["jobs"][CODE_REVIEW_JOB_ID]
        job["if"] = job["if"].replace(
            "startsWith(github.event.comment.body, '/review')",
            f"(startsWith(github.event.comment.body, '/review') || startsWith(github.event.comment.body, '{command}'))",
            1,
        )
        assert _admitted_commands(job["if"]) == {"/review", command}

    def test_dropping_the_author_association_gate_is_detected(self, workflow):
        job = workflow["jobs"][CODE_REVIEW_JOB_ID]
        job["if"] = job["if"].replace(
            'contains(fromJSON(\'["OWNER", "MEMBER", "COLLABORATOR"]\'), github.event.comment.author_association) &&',
            "",
            1,
        )
        assert _issue_comment_who_gate(job["if"]) != _issue_comment_who_gate(workflow["jobs"]["review"]["if"])

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("github_action_config.auto_improve", "${{ inputs.auto-improve }}"),
            ("github_action_config.auto_describe", "${{ inputs.auto-describe }}"),
            ("CONFIG.PUBLISH_OUTPUT", True),
            ("PR_REVIEWER.REQUIRE_SECURITY_REVIEW", False),
            ("VERTEXAI.VERTEX_LOCATION", "europe-west4"),
        ],
        ids=["improve-follows-input", "describe-follows-input", "publishing-on", "extra-key", "changed-central-key"],
    )
    def test_env_drift_on_the_code_reviewer_is_detected(self, workflow, key, value):
        _steps_by_id(workflow, CODE_REVIEW_JOB_ID)[CODE_STEP_ID]["env"][key] = value
        assert len(_code_env_drift(workflow)) == 1

    def test_dropping_publish_output_is_detected(self, workflow):
        del _steps_by_id(workflow, CODE_REVIEW_JOB_ID)[CODE_STEP_ID]["env"]["CONFIG.PUBLISH_OUTPUT"]
        assert _code_env_drift(workflow) == ["CONFIG.PUBLISH_OUTPUT: None, not False"]

    def test_the_security_row_being_dropped_is_detected(self, workflow):
        _steps_by_id(workflow, CODE_REVIEW_JOB_ID)[CODE_STEP_ID]["env"]["PR_REVIEWER.REQUIRE_SECURITY_REVIEW"] = False
        with pytest.raises(AssertionError):
            test_the_code_reviewer_keeps_the_security_row(workflow)

    def test_an_unguarded_step_after_the_declaration_is_detected(self, workflow):
        step = _steps_by_id(workflow, CODE_REVIEW_JOB_ID)["gcp-auth"]
        del step["if"]
        assert _unguarded_code_review_steps(workflow) == ["gcp-auth"]

    def test_downgrading_the_code_review_gate_is_detected(self, workflow):
        step = _code_gate(workflow)
        step["run"] = step["run"].replace("::error::", "::warning::")
        assert "the gate's run: drifted" in _code_gate_violations(workflow)

    def test_dropping_the_published_check_is_detected(self, workflow):
        step = _code_gate(workflow)
        start = step["run"].index('if [[ "$PUBLISHED"')
        step["run"] = step["run"][:start]
        violations = _code_gate_violations(workflow)
        assert "the gate does not fail on an unpublished review" in violations
        assert "the gate does not exit 1 on both failures" in violations

    def test_reading_the_wrong_reviewer_output_is_detected(self, workflow):
        _code_gate(workflow)["env"]["REVIEW_OUTPUT"] = "${{ steps.review_central.outputs.review }}"
        assert "the gate's env: drifted" in _code_gate_violations(workflow)

    def test_widening_the_gate_scope_is_detected(self, workflow):
        step = _code_gate(workflow)
        step["if"] = step["if"].replace('"review_requested"]', '"review_requested", "synchronize"]')
        assert "the gate's if: drifted" in _code_gate_violations(workflow)

    def test_ungating_the_gate_from_the_pass_is_detected(self, workflow, guard_step):
        step = _code_gate(workflow)
        step["if"] = step["if"].replace(f"{ASSEMBLED_TERM}\n    && ", "", 1)
        with pytest.raises(AssertionError):
            test_the_code_review_gate_scope_is_the_first_gate_scope(workflow, guard_step)
