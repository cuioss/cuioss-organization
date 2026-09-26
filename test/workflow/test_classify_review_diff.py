"""Tests for classify-review-diff.py.

The classifier's runner-facing half runs PR-Agent's own code inside the pinned image, so
these tests exercise it through an injected fake runner and provider: no test needs the
image or the network. Whether the in-image resolution actually resolves is observed live,
on a consumer pull request, not here.
"""

import importlib.util
import io
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT, run_script

SCRIPT_PATH = PROJECT_ROOT / "workflow-scripts/classify-review-diff.py"
PR_URL = "https://github.com/cuioss/example/pull/7"
TOKEN = "ghs_example"
NOTICE_PREFIX = "::notice::classify-review-diff fail-open:"


def _load_module():
    spec = importlib.util.spec_from_file_location("classify_review_diff", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


crd = _load_module()


@dataclass(frozen=True)
class FakeFile:
    filename: str


class FakeSettings:
    """The slice of PR-Agent's settings object the classifier touches."""

    def __init__(self, values: dict[str, Any] | None = None):
        self.values = dict(values or {})

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.values[key] = value


@dataclass
class FakeProvider:
    """A GithubProvider whose file listing and filter-chain survivors are given, not fetched."""

    listed: list[str]
    survivors: list[str]
    repo_settings: Any = ""
    error: Exception | None = None

    def get_diff_files(self):
        if self.error is not None:
            raise self.error
        return [FakeFile(name) for name in self.survivors]

    def get_files(self):
        return [FakeFile(name) for name in self.listed]

    def get_repo_settings(self):
        return self.repo_settings


@dataclass
class FakeRunner:
    """Records the order in which the runner's entry points are driven."""

    provider: FakeProvider
    settings: FakeSettings = field(default_factory=FakeSettings)
    calls: list[str] = field(default_factory=list)
    log_line: str = ""

    def apply_repo_settings(self, pr_url: str) -> None:
        if self.log_line:
            print(self.log_line)
        self.calls.append(f"apply_repo_settings {pr_url}")

    def build_provider(self, pr_url: str) -> FakeProvider:
        self.calls.append(f"provider {pr_url}")
        return self.provider

    def as_runner(self):
        return crd.Runner(
            settings=self.settings, apply_repo_settings=self.apply_repo_settings, provider=self.build_provider
        )


def _resolution(listed: int, survivors: tuple[str, ...]) -> Any:
    return crd.Resolution(listed=listed, survivors=survivors, settings=("defaults", "global"))


def _never_called():
    raise AssertionError("the runner's filter chain must not be resolved here")


def _raise(error: Exception):
    def resolve():
        raise error

    return resolve


class TestClassify:
    """The closed set of decision outcomes."""

    def test_zero_files_is_not_reviewable_without_resolving(self):
        decision = crd.classify(0, _never_called)
        assert decision == crd.Decision(reviewable=False, survivors=0)

    def test_empty_survivors_after_a_full_listing_is_not_reviewable(self):
        decision = crd.classify(2, lambda: _resolution(2, ()))
        assert (decision.reviewable, decision.survivors, decision.notice) == (False, 0, None)

    def test_any_survivor_is_reviewable(self):
        decision = crd.classify(3, lambda: _resolution(3, ("src/main.py",)))
        assert (decision.reviewable, decision.survivors, decision.notice) == (True, 1, None)
        assert decision.settings == ("defaults", "global")

    @pytest.mark.parametrize(
        ("changed_files", "resolve", "reason"),
        [
            (crd.FILE_LISTING_CAP + 1, _never_called, "file-listing cap"),
            (4, _raise(crd.ResolutionError("pr_agent could not be imported")), "pr_agent could not be imported"),
            (4, _raise(crd.ResolutionError("settings API answered 500")), "settings API answered 500"),
            (4, lambda: _resolution(3, ()), "returned 3 of 4 changed files"),
        ],
        ids=["above-listing-cap", "import-failure", "settings-or-api-failure", "listing-short"],
    )
    def test_every_anticipated_failure_fails_open(self, changed_files, resolve, reason):
        decision = crd.classify(changed_files, resolve)
        assert decision.reviewable is True
        assert decision.survivors is None
        assert reason in decision.notice

    def test_a_short_listing_never_reads_as_empty(self):
        """Survivors computed over an incomplete list prove nothing about the rest of the diff."""
        decision = crd.classify(5, lambda: _resolution(3, ()))
        assert decision.reviewable is True


class TestSettingsProvenance:
    @pytest.mark.parametrize(
        ("values", "repo_settings", "expected"),
        [
            ({}, "", ("defaults",)),
            ({}, b"[pr_reviewer]\n", ("defaults", "local")),
            ({}, [("global", b"a"), ("local", b"b")], ("defaults", "global", "local")),
            ({"CONFIG.EXTRA_CONFIG_URL": "https://example.test/x.toml"}, "", ("defaults", "extra")),
            ({"CONFIG.USE_REPO_SETTINGS_FILE": False}, [("global", b"a")], ("defaults",)),
        ],
        ids=["defaults-only", "local-only", "global-and-local", "extra-config", "repo-settings-off"],
    )
    def test_names_the_sources_the_loader_read(self, values, repo_settings, expected):
        assert crd.settings_provenance(FakeSettings(values), repo_settings) == expected


class TestResolveWithRunner:
    """The runner-facing function, driven through an injected fake runner."""

    def test_applies_settings_before_building_the_provider(self):
        fake = FakeRunner(
            FakeProvider(listed=[".gitignore", "a.py"], survivors=["a.py"], repo_settings=[("global", b"")])
        )
        resolution = crd.resolve_with_runner(PR_URL, TOKEN, fake.as_runner)
        assert fake.calls == [f"apply_repo_settings {PR_URL}", f"provider {PR_URL}"]
        assert resolution == crd.Resolution(listed=2, survivors=("a.py",), settings=("defaults", "global"))

    def test_authenticates_as_the_action_runner_does(self):
        fake = FakeRunner(FakeProvider(listed=["a.py"], survivors=["a.py"]))
        crd.resolve_with_runner(PR_URL, TOKEN, fake.as_runner)
        assert fake.settings.values["GITHUB.USER_TOKEN"] == TOKEN
        assert fake.settings.values["GITHUB.DEPLOYMENT_TYPE"] == "user"

    def test_a_missing_token_is_a_resolution_failure(self):
        with pytest.raises(crd.ResolutionError, match="GITHUB_TOKEN is not set"):
            crd.resolve_with_runner(PR_URL, "", _never_called)

    def test_any_runner_exception_is_a_resolution_failure(self):
        fake = FakeRunner(FakeProvider(listed=["a.py"], survivors=[], error=RuntimeError("rate limited")))
        with pytest.raises(crd.ResolutionError, match="RuntimeError: rate limited") as caught:
            crd.resolve_with_runner(PR_URL, TOKEN, fake.as_runner)
        assert isinstance(caught.value.__cause__, RuntimeError)

    def test_load_runner_without_pr_agent_is_a_resolution_failure(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "pr_agent", None)
        with pytest.raises(crd.ResolutionError, match="pr_agent could not be imported"):
            crd.load_runner()


@pytest.fixture
def github_output(tmp_path):
    return tmp_path / "github_output"


def _run(fake: FakeRunner | None, changed_files: int, github_output: Path, token: str = TOKEN, load=None):
    """Drive cmd_classify with real parsed arguments; returns (exit code, stdout, stderr)."""
    args = crd.build_parser().parse_args(["classify", "--changed-files", str(changed_files), "--pr-url", PR_URL])
    environ = {"GITHUB_OUTPUT": str(github_output), "GITHUB_TOKEN": token}
    stdout, stderr = io.StringIO(), io.StringIO()
    if load is None:
        load = fake.as_runner if fake is not None else _never_called
    code = crd.cmd_classify(args, environ, load, stdout, stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def _unimportable():
    raise crd.ResolutionError("pr_agent could not be imported (No module named 'pr_agent')")


# Every anticipated resolution failure, as (changed_files, runner, token, load, reason).
FAIL_OPEN_CASES = {
    "import-failure": (1, None, TOKEN, _unimportable, "pr_agent could not be imported"),
    "missing-token": (1, None, "", _never_called, "GITHUB_TOKEN is not set"),
    "settings-or-api-failure": (
        1,
        FakeRunner(FakeProvider(listed=["a.py"], survivors=[], error=RuntimeError("API down"))),
        TOKEN,
        None,
        "RuntimeError: API down",
    ),
    "listing-short": (2, FakeRunner(FakeProvider(listed=["a.py"], survivors=[])), TOKEN, None, "returned 1 of 2"),
    "above-listing-cap": (crd.FILE_LISTING_CAP + 1, None, TOKEN, _never_called, "file-listing cap"),
}


class TestCmdClassify:
    """The output contract: one GITHUB_OUTPUT entry, the decision line first, notices only on fail-open."""

    def test_resolved_decision_writes_one_entry_and_no_notice(self, github_output):
        fake = FakeRunner(
            FakeProvider(listed=["a.py", ".plan/x.md"], survivors=["a.py"], repo_settings=[("global", b"")])
        )
        code, stdout, _ = _run(fake, 2, github_output)
        assert code == 0
        assert github_output.read_text(encoding="utf-8") == "reviewable=true\n"
        assert stdout == "classify-review-diff: reviewable=true survivors=1 settings=defaults+global\n"

    def test_emptied_diff_writes_false(self, github_output):
        fake = FakeRunner(FakeProvider(listed=[".gitignore", ".plan/x.md"], survivors=[]))
        _, stdout, _ = _run(fake, 2, github_output)
        assert github_output.read_text(encoding="utf-8") == "reviewable=false\n"
        assert stdout.startswith("classify-review-diff: reviewable=false survivors=0 ")

    def test_zero_files_writes_false_without_the_runner(self, github_output):
        _, stdout, _ = _run(None, 0, github_output)
        assert github_output.read_text(encoding="utf-8") == "reviewable=false\n"
        assert stdout == "classify-review-diff: reviewable=false survivors=0 settings=none\n"

    @pytest.mark.parametrize(
        ("changed_files", "fake", "token", "load", "reason"),
        FAIL_OPEN_CASES.values(),
        ids=FAIL_OPEN_CASES.keys(),
    )
    def test_every_fail_open_writes_true_with_exactly_one_notice(
        self, github_output, changed_files, fake, token, load, reason
    ):
        code, stdout, stderr = _run(fake, changed_files, github_output, token=token, load=load)
        lines = stdout.splitlines()
        assert code == 0
        assert github_output.read_text(encoding="utf-8") == "reviewable=true\n"
        assert lines[0] == "classify-review-diff: reviewable=true survivors=unresolved settings=none"
        assert len(lines) == 2 and lines[1].startswith(NOTICE_PREFIX)
        assert reason in lines[1]
        assert "::warning" not in stdout + stderr

    def test_runner_output_is_held_back_until_after_the_decision_line(self, github_output):
        fake = FakeRunner(FakeProvider(listed=["a.py"], survivors=["a.py"]), log_line="Applying repo settings")
        _, stdout, stderr = _run(fake, 1, github_output)
        assert stdout.splitlines()[0].startswith("classify-review-diff: reviewable=true")
        assert "Applying repo settings" not in stdout
        assert "Applying repo settings" in stderr

    @pytest.mark.parametrize("survivors", [["a.py"], []], ids=["reviewable", "emptied"])
    def test_a_resolved_decision_emits_neither_notice_nor_warning(self, github_output, survivors):
        fake = FakeRunner(FakeProvider(listed=["a.py"], survivors=survivors))
        _, stdout, stderr = _run(fake, 1, github_output)
        assert "::notice" not in stdout + stderr
        assert "::warning" not in stdout + stderr

    def test_a_missing_github_output_fails(self):
        args = crd.build_parser().parse_args(["classify", "--changed-files", "1", "--pr-url", PR_URL])
        with pytest.raises(crd.ClassifierError, match="GITHUB_OUTPUT is not set"):
            crd.cmd_classify(args, {"GITHUB_TOKEN": TOKEN}, _never_called, io.StringIO(), io.StringIO())


class TestScript:
    """CLI plumbing, run as the workflow runs it — here, without the image."""

    def test_without_pr_agent_the_script_fails_open(self, github_output):
        env = {**os.environ, "GITHUB_OUTPUT": str(github_output), "GITHUB_TOKEN": TOKEN}
        result = run_script(SCRIPT_PATH, "classify", "--changed-files", "3", "--pr-url", PR_URL, env=env)
        assert result.returncode == 0
        assert github_output.read_text(encoding="utf-8") == "reviewable=true\n"
        assert (
            result.stdout.splitlines()[0] == "classify-review-diff: reviewable=true survivors=unresolved settings=none"
        )
        assert result.stdout.splitlines()[1].startswith(f"{NOTICE_PREFIX} pr_agent could not be imported")

    def test_without_github_output_the_script_errors_and_exits_non_zero(self):
        env = {key: value for key, value in os.environ.items() if key != "GITHUB_OUTPUT"}
        result = run_script(SCRIPT_PATH, "classify", "--changed-files", "3", "--pr-url", PR_URL, env=env)
        assert result.returncode == 1
        assert "::error::GITHUB_OUTPUT is not set" in result.stderr

    def test_a_negative_file_count_is_rejected(self):
        with pytest.raises(SystemExit):
            crd.build_parser().parse_args(["classify", "--changed-files", "-1", "--pr-url", PR_URL])
