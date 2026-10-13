"""Tests for publish-code-review.py — the second pass's publisher.

The in-image half (`load_runtime`: PR-Agent's settings load, `GithubProvider`, the real
`convert_to_markdown_v2`) runs only inside the pinned image; everything it feeds is
exercised here through a recorded provider and renderer.
"""

import importlib.util
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT

SCRIPT_PATH = PROJECT_ROOT / "workflow-scripts/publish-code-review.py"
WORKFLOW_PATH = PROJECT_ROOT / ".github/workflows/reusable-cuioss-review-bot.yml"

PASS_1_HEADER = "## PR Reviewer Guide 🔍"
PASS_2_HEADER = "## PR Code Review Guide 🧭"
STARTED = datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)
STARTED_TEXT = "2026-05-04T12:00:00Z"
REVIEW = {"estimated_effort_to_review_[1-5]": "2", "security_concerns": "No", "key_issues_to_review": []}
RENDERED = f"{PASS_1_HEADER}\n\n<table>\n<tr><td>Estimated effort to review: 2</td></tr>\n</table>\n"


def _load_module():
    spec = importlib.util.spec_from_file_location("publish_code_review", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load_module()


def _comment(body, updated_at=STARTED):
    return SimpleNamespace(body=body, updated_at=updated_at)


class RecordingProvider:
    """A `GithubProvider` stand-in: records the publish, then serves `after` as the comment listing."""

    def __init__(self, after):
        self.after = after
        self.published = []

    def publish_persistent_comment_full(
        self, pr_comment, initial_header, update_header=True, name="review", final_update_message=True
    ):
        self.published.append(
            {
                "pr_comment": pr_comment,
                "initial_header": initial_header,
                "update_header": update_header,
                "name": name,
                "final_update_message": final_update_message,
            }
        )

    def get_issue_comments(self):
        return list(self.after)


def _runtime(provider, rendered=RENDERED, seen=None):
    def render(output_data):
        if seen is not None:
            seen.append(output_data)
        return rendered

    return mod.Runtime(provider=provider, render=render)


def _updated(published, commit="https://github.com/cuioss/example/commit/abc123"):
    """A comment body as PR-Agent's persistent update writes it (`publish_persistent_comment_full`)."""
    return published.replace(PASS_2_HEADER, f"{PASS_2_HEADER}\n\n#### (Code review updated until commit {commit})\n", 1)


def _persistent_lookup_matches(body, initial_header):
    """PR-Agent's persistent-comment lookup (`GitProvider.publish_persistent_comment_full`)."""
    return body.startswith(initial_header)


def _first_pass_gate_prefix():
    """The prefix the first pass's gate selects its published comment by, read from the workflow."""
    match = re.search(r'select\(\.body \| startswith\("([^"]+)"\)\)', WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert match is not None, "the first pass's gate no longer selects its comment by a body prefix"
    return match.group(1)


class TestHeaderSwap:
    def test_the_leading_header_is_replaced(self):
        assert mod.swap_header(RENDERED) == RENDERED.replace(PASS_1_HEADER, PASS_2_HEADER, 1)

    def test_only_the_leading_header_is_replaced(self):
        body = f"{PASS_1_HEADER}\n\nquoted: {PASS_1_HEADER}\n"
        assert mod.swap_header(body) == f"{PASS_2_HEADER}\n\nquoted: {PASS_1_HEADER}\n"

    def test_the_rest_of_the_rendering_is_untouched(self):
        swapped = mod.swap_header(RENDERED)
        assert swapped[len(PASS_2_HEADER) :] == RENDERED[len(PASS_1_HEADER) :]

    @pytest.mark.parametrize(
        "rendered",
        ["", "## Incremental PR Reviewer Guide 🔍\n\nx", f"\n{PASS_1_HEADER}\n", "## PR Reviewer Guide\n\nx"],
        ids=["empty", "incremental", "leading-newline", "header-without-emoji"],
    )
    def test_an_unexpected_rendering_is_refused(self, rendered):
        with pytest.raises(mod.PublishError, match="does not open with"):
            mod.swap_header(rendered)

    def test_the_constants_are_the_designed_headers(self):
        assert mod.REVIEWER_GUIDE_HEADER == PASS_1_HEADER
        assert mod.CODE_REVIEW_HEADER == PASS_2_HEADER


class TestTheTwoCommentsNeverCollide:
    """Neither pass's lookup can find the other pass's comment, in either direction."""

    PASS_1_BODIES = [
        RENDERED,
        f"{PASS_1_HEADER}\n\n#### (Review updated until commit https://github.com/o/r/commit/abc)\n\nbody",
    ]
    PASS_2_BODIES = [
        mod.swap_header(RENDERED),
        f"{PASS_2_HEADER}\n\n#### (Code review updated until commit https://github.com/o/r/commit/abc)\n\nbody",
    ]

    @pytest.mark.parametrize("body", PASS_1_BODIES, ids=["fresh", "updated"])
    def test_a_first_pass_comment_never_matches_the_second_pass_lookup(self, body):
        assert not mod.is_code_review_comment(body)
        assert not _persistent_lookup_matches(body, PASS_2_HEADER)

    @pytest.mark.parametrize("body", PASS_2_BODIES, ids=["fresh", "updated"])
    def test_a_second_pass_comment_never_matches_the_first_pass_lookup(self, body):
        assert not _persistent_lookup_matches(body, PASS_1_HEADER)
        assert not body.startswith(_first_pass_gate_prefix())

    @pytest.mark.parametrize("body", PASS_2_BODIES, ids=["fresh", "updated"])
    def test_a_second_pass_comment_matches_its_own_lookup(self, body):
        """Non-vacuity: the lookups above fail for the right reason, not because nothing ever matches."""
        assert mod.is_code_review_comment(body)
        assert _persistent_lookup_matches(body, PASS_2_HEADER)

    def test_the_first_pass_gate_prefix_is_read_from_the_workflow(self):
        assert _first_pass_gate_prefix() == "## PR Reviewer Guide"


class TestPublish:
    def test_publishes_the_swapped_rendering_under_the_code_review_header(self):
        fresh = _comment(mod.swap_header(RENDERED), STARTED + timedelta(seconds=5))
        provider = RecordingProvider([fresh])
        seen = []
        assert mod.publish(dict(REVIEW), STARTED, _runtime(provider, seen=seen)) == 1
        assert seen == [{"review": REVIEW}]
        assert provider.published == [
            {
                "pr_comment": mod.swap_header(RENDERED),
                "initial_header": PASS_2_HEADER,
                "update_header": True,
                "name": "code review",
                "final_update_message": False,
            }
        ]

    def test_a_comment_updated_at_the_start_second_is_fresh(self):
        provider = RecordingProvider([_comment(PASS_2_HEADER + "\n\nx", STARTED)])
        assert mod.publish(dict(REVIEW), STARTED, _runtime(provider)) == 1

    def test_a_naive_utc_timestamp_is_compared_as_utc(self):
        """PyGithub returns naive UTC datetimes in the pinned image's version."""
        provider = RecordingProvider([_comment(PASS_2_HEADER, datetime(2026, 5, 4, 12, 0, 1))])
        assert mod.publish(dict(REVIEW), STARTED, _runtime(provider)) == 1

    @pytest.mark.parametrize(
        "after",
        [
            [],
            [_comment(PASS_2_HEADER + "\n\nstale", STARTED - timedelta(seconds=1))],
            [_comment(RENDERED, STARTED + timedelta(minutes=1))],
            [_comment("**[Persistent code review](u)** updated", STARTED + timedelta(minutes=1))],
            [_comment(None, STARTED + timedelta(minutes=1))],
        ],
        ids=["no-comment", "stale-code-review-comment", "only-the-first-pass-comment", "update-notice", "empty-body"],
    )
    def test_no_fresh_code_review_comment_fails(self, after):
        with pytest.raises(
            mod.PublishError, match="no '## PR Code Review Guide 🧭' comment carries this run's review or was updated"
        ):
            mod.publish(dict(REVIEW), STARTED, _runtime(RecordingProvider(after)))

    def test_an_identical_republish_with_an_unchanged_updated_at_passes(self):
        """A re-run on an unchanged commit renders byte-identical text; GitHub may leave updated_at alone."""
        unchanged = _comment(_updated(mod.swap_header(RENDERED)), STARTED - timedelta(hours=2))
        assert mod.publish(dict(REVIEW), STARTED, _runtime(RecordingProvider([unchanged]))) == 1

    def test_an_identical_comment_as_first_created_passes(self):
        unchanged = _comment(mod.swap_header(RENDERED), STARTED - timedelta(days=1))
        assert mod.publish(dict(REVIEW), STARTED, _runtime(RecordingProvider([unchanged]))) == 1

    def test_crlf_line_endings_do_not_break_the_content_match(self):
        body = _updated(mod.swap_header(RENDERED)).replace("\n", "\r\n")
        provider = RecordingProvider([_comment(body, STARTED - timedelta(hours=2))])
        assert mod.publish(dict(REVIEW), STARTED, _runtime(provider)) == 1

    @pytest.mark.parametrize(
        "body",
        [
            _updated(f"{PASS_2_HEADER}\n\n<table>\n<tr><td>an earlier review</td></tr>\n</table>\n"),
            f"{PASS_2_HEADER}\n\n<table>\n<tr><td>an earlier review</td></tr>\n</table>\n",
            mod.swap_header(RENDERED) + "\nappended by someone\n",
            _updated(mod.swap_header(RENDERED)).replace("#### (Code review updated", "#### (Review updated"),
        ],
        ids=["updated-other-content", "created-other-content", "extra-content", "foreign-update-line"],
    )
    def test_a_stale_comment_with_other_content_fails(self, body):
        provider = RecordingProvider([_comment(body, STARTED - timedelta(hours=2))])
        with pytest.raises(mod.PublishError, match="carries this run's review or was updated"):
            mod.publish(dict(REVIEW), STARTED, _runtime(provider))

    def test_the_identical_first_pass_comment_never_counts(self):
        """Content identity is checked only on comments carrying the code-review header."""
        provider = RecordingProvider([_comment(RENDERED, STARTED - timedelta(hours=2))])
        with pytest.raises(mod.PublishError):
            mod.publish(dict(REVIEW), STARTED, _runtime(provider))

    def test_an_empty_rendering_fails_before_publishing(self):
        provider = RecordingProvider([])
        with pytest.raises(mod.PublishError, match="empty review"):
            mod.publish(dict(REVIEW), STARTED, _runtime(provider, rendered="  \n"))
        assert provider.published == []


class TestInputs:
    @pytest.mark.parametrize(
        ("raw", "cause"),
        [
            ("", "REVIEW is empty"),
            ("  \n", "REVIEW is empty"),
            ("{not json", "REVIEW is not JSON"),
            ("[1, 2]", "not a non-empty JSON object"),
            ("{}", "not a non-empty JSON object"),
            ('"text"', "not a non-empty JSON object"),
        ],
        ids=["empty", "blank", "not-json", "list", "empty-object", "string"],
    )
    def test_an_unusable_review_output_fails(self, raw, cause):
        with pytest.raises(mod.PublishError, match=cause):
            mod.parse_review(raw)

    def test_the_review_output_is_parsed(self):
        assert mod.parse_review(json.dumps(REVIEW, ensure_ascii=False)) == REVIEW

    @pytest.mark.parametrize("value", ["", "2026-05-04 12:00:00", "2026-05-04T12:00:00+00:00", "now"])
    def test_an_unusable_start_time_fails(self, value):
        with pytest.raises(mod.PublishError, match="STARTED_AT"):
            mod.parse_started_at(value)

    def test_the_start_time_is_utc(self):
        assert mod.parse_started_at(STARTED_TEXT) == STARTED


def _environ(temp_dir, **overrides):
    environ = {
        "GITHUB_OUTPUT": str(temp_dir / "output"),
        "REVIEW": json.dumps(REVIEW),
        "STARTED_AT": STARTED_TEXT,
        "PR_URL": "https://github.com/cuioss/example/pull/7",
        "GITHUB_TOKEN": "token",
    }
    environ.update(overrides)
    return environ


class TestCommand:
    def test_success_records_published_true(self, temp_dir, capsys):
        provider = RecordingProvider([_comment(PASS_2_HEADER, STARTED + timedelta(seconds=3))])
        loaded = []

        def load(pr_url, token):
            loaded.append((pr_url, token))
            return _runtime(provider)

        assert mod.cmd_publish(_environ(temp_dir), load, sys.stdout) == 0
        assert (temp_dir / "output").read_text(encoding="utf-8") == "published=true\n"
        assert loaded == [("https://github.com/cuioss/example/pull/7", "token")]
        assert "publish-code-review: published as" in capsys.readouterr().out

    def test_no_fresh_comment_records_nothing(self, temp_dir):
        with pytest.raises(mod.PublishError):
            mod.cmd_publish(_environ(temp_dir), lambda pr_url, token: _runtime(RecordingProvider([])), sys.stdout)
        assert not (temp_dir / "output").exists()

    @pytest.mark.parametrize(
        ("override", "cause"),
        [
            ({"GITHUB_OUTPUT": ""}, "GITHUB_OUTPUT is not set"),
            ({"PR_URL": ""}, "PR_URL is not set"),
            ({"REVIEW": ""}, "REVIEW is empty"),
            ({"STARTED_AT": ""}, "STARTED_AT"),
        ],
        ids=["no-output-file", "no-pr-url", "no-review", "no-start"],
    )
    def test_a_missing_input_fails_before_loading_the_runtime(self, temp_dir, override, cause):
        def refuse(pr_url, token):
            raise AssertionError("the runtime was loaded for an unusable input")

        with pytest.raises(mod.PublishError, match=cause):
            mod.cmd_publish(_environ(temp_dir, **override), refuse, sys.stdout)

    def test_a_missing_token_fails(self):
        with pytest.raises(mod.PublishError, match="GITHUB_TOKEN is not set"):
            mod.load_runtime("https://github.com/cuioss/example/pull/7", "")


class TestMain:
    def test_a_publish_failure_is_one_error_annotation_and_exit_1(self, temp_dir, monkeypatch, capsys):
        monkeypatch.setattr(mod.os, "environ", _environ(temp_dir, REVIEW=""))
        assert mod.main() == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.splitlines() == [
            "::error::REVIEW is empty: the code-review pass produced no review output to publish"
        ]

    def test_an_exception_from_pr_agent_is_one_error_annotation_and_exit_1(self, temp_dir, monkeypatch, capsys):
        def broken(pr_url, token):
            raise RuntimeError("API rate limit exceeded\nretry later")

        monkeypatch.setattr(mod.os, "environ", _environ(temp_dir))
        monkeypatch.setattr(mod, "load_runtime", broken)
        assert mod.main() == 1
        err = capsys.readouterr().err
        assert err.splitlines() == [
            "::error::publishing the code review failed: RuntimeError: API rate limit exceeded%0Aretry later"
        ]
        assert "::warning" not in err

    def test_pr_agent_is_not_importable_outside_the_image(self):
        """Outside the pinned image the import fails by name, not with a traceback."""
        try:
            import pr_agent  # noqa: F401
        except ImportError:
            with pytest.raises(mod.PublishError, match="pr_agent could not be imported"):
                mod.load_runtime("https://github.com/cuioss/example/pull/7", "token")
        else:  # pragma: no cover - only inside the image
            pytest.skip("pr_agent is importable here")
