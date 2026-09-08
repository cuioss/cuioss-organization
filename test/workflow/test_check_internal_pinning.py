"""Tests for check-internal-pinning.py - release-time mutable reference guard."""

import sys
from pathlib import Path

# Add parent to path to access conftest
sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT, run_script

SCRIPT_PATH = PROJECT_ROOT / "workflow-scripts/check-internal-pinning.py"

VALID_SHA = "abcdef1234567890abcdef1234567890abcdef12"
# The self-checkout that puts workflow-scripts/ on the runner. Its `ref:` is an
# executed reference — it selects which revision of those scripts runs — but is
# not spelled `uses:`, which is how it escaped both the rewriter and the guard.
SELF_CHECKOUT = """
jobs:
  propagate:
    steps:
      - uses: actions/checkout@1111111111111111111111111111111111111111 # v7.0.1
        with:
          repository: cuioss/cuioss-organization
          ref: {ref}
          sparse-checkout: workflow-scripts
"""

ACTION_REF = """
jobs:
  build:
    steps:
      - uses: cuioss/cuioss-organization/.github/actions/read-project-config@{sha} # v1.0.0
"""


def write_workflow(temp_dir, name, body):
    workflows_dir = temp_dir / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    path = workflows_dir / name
    path.write_text(body)
    return path


class TestDetectsMutableReferences:
    """The defect this guard exists for: a released commit referencing a tag."""

    def test_rejects_version_tag_reference(self, temp_dir):
        """A @v{version} ref is mutable — moving the tag changes executed code."""
        write_workflow(temp_dir, "reusable-build.yml", """
jobs:
  build:
    steps:
      - uses: cuioss/cuioss-organization/.github/actions/read-project-config@v0.12.0
""")

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 1
        assert "read-project-config@v0.12.0" in result.stderr

    def test_rejects_branch_reference(self, temp_dir):
        write_workflow(temp_dir, "reusable-build.yml", """
jobs:
  build:
    steps:
      - uses: cuioss/cuioss-organization/.github/actions/read-project-config@main
""")

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 1
        assert "@main" in result.stderr

    def test_reports_every_violation(self, temp_dir):
        """Must not stop at the first file — the defect spanned six workflows."""
        for name in ("reusable-maven-build.yml", "reusable-npm-build.yml"):
            write_workflow(temp_dir, name, """
jobs:
  build:
    steps:
      - uses: cuioss/cuioss-organization/.github/actions/read-project-config@v0.12.0
""")

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 1
        assert "reusable-maven-build.yml" in result.stderr
        assert "reusable-npm-build.yml" in result.stderr
        assert "found 2 unsafe" in result.stderr

    def test_rejects_quoted_mutable_reference(self, temp_dir):
        """YAML allows a quoted value; a quoted tag must not evade the guard."""
        write_workflow(temp_dir, "reusable-build.yml", """
jobs:
  build:
    steps:
      - uses: "cuioss/cuioss-organization/.github/actions/read-project-config@v0.12.0"
""")

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 1
        assert "read-project-config@v0.12.0" in result.stderr

    def test_rejects_single_quoted_mutable_reference(self, temp_dir):
        write_workflow(temp_dir, "reusable-build.yml", """
jobs:
  build:
    steps:
      - uses: 'cuioss/cuioss-organization/.github/actions/read-project-config@main'
""")

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 1
        assert "@main" in result.stderr

    def test_reports_line_numbers(self, temp_dir):
        write_workflow(temp_dir, "reusable-build.yml", """jobs:
  build:
    steps:
      - uses: cuioss/cuioss-organization/.github/actions/read-project-config@v0.12.0
""")

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 1
        assert "reusable-build.yml:4" in result.stderr


class TestAcceptsPinnedReferences:
    """Legitimate content must not fail the release."""

    def test_accepts_sha_pinned_reference(self, temp_dir):
        write_workflow(temp_dir, "reusable-build.yml", f"""
jobs:
  build:
    steps:
      - uses: cuioss/cuioss-organization/.github/actions/read-project-config@{VALID_SHA} # v1.0.0
""")

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 0

    def test_ignores_commented_usage_example(self, temp_dir):
        """Commented examples are documentation, not executed references.

        reusable-dependabot-auto-merge.yml carries exactly such a comment.
        """
        write_workflow(temp_dir, "reusable-build.yml", f"""
# Usage:
#   jobs:
#     build:
#       uses: cuioss/cuioss-organization/.github/workflows/reusable-build.yml@v0.12.0
jobs:
  build:
    steps:
      - uses: cuioss/cuioss-organization/.github/actions/read-project-config@{VALID_SHA} # v1.0.0
""")

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 0

    def test_ignores_template_expression_reference(self, temp_dir):
        """release.yml resolves its ref at runtime — not statically checkable."""
        write_workflow(temp_dir, "release.yml", """
jobs:
  build:
    uses: cuioss/cuioss-organization/.github/workflows/reusable-maven-build.yml@${{ steps.sha.outputs.sha }}
""")

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 0

    def test_ignores_third_party_actions(self, temp_dir):
        """Only cuioss-organization self-references are in scope here."""
        write_workflow(temp_dir, "reusable-build.yml", """
jobs:
  build:
    steps:
      - uses: actions/checkout@v4
""")

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 0

    def test_accepts_missing_workflows_directory(self, temp_dir):
        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 0


class TestRepositoryInvariant:
    """Run the guard against the real repository.

    This is what makes the sequencing fix self-enforcing: every PR re-checks
    that no mutable internal reference has crept back in.
    """

    def test_repository_has_no_mutable_internal_references(self):
        result = run_script(SCRIPT_PATH, "--path", str(PROJECT_ROOT))

        assert result.returncode == 0, (
            f"Repository contains mutable internal references:\n{result.stderr}"
        )


class TestSelfCheckoutRef:
    """The `repository:` + `ref:` form of an executed reference."""

    def test_rejects_tag_as_self_checkout_ref(self, temp_dir):
        write_workflow(temp_dir, "reusable-release.yml", SELF_CHECKOUT.format(ref="v0.24.0"))

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 1
        assert "cuioss/cuioss-organization@v0.24.0" in result.stderr

    def test_rejects_branch_as_self_checkout_ref(self, temp_dir):
        write_workflow(temp_dir, "reusable-release.yml", SELF_CHECKOUT.format(ref="main"))

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 1
        assert "@main" in result.stderr

    def test_rejects_quoted_mutable_self_checkout_ref(self, temp_dir):
        write_workflow(temp_dir, "reusable-release.yml", SELF_CHECKOUT.format(ref="'main'"))

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 1
        assert "@main" in result.stderr

    def test_rejects_self_checkout_without_ref(self, temp_dir):
        """No `ref:` is the worst case: checkout resolves to the default branch."""
        write_workflow(temp_dir, "reusable-release.yml", """
jobs:
  propagate:
    steps:
      - uses: actions/checkout@1111111111111111111111111111111111111111 # v7.0.1
        with:
          repository: cuioss/cuioss-organization
          sparse-checkout: workflow-scripts
""")

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 1
        assert "default branch" in result.stderr

    def test_finds_ref_separated_by_a_comment(self, temp_dir):
        """A comment does not end a YAML mapping, so it must not hide the ref."""
        write_workflow(temp_dir, "reusable-release.yml", """
jobs:
  propagate:
    steps:
      - uses: actions/checkout@1111111111111111111111111111111111111111 # v7.0.1
        with:
          repository: cuioss/cuioss-organization
          # release-managed pin
          ref: main
          sparse-checkout: workflow-scripts
""")

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 1
        assert "@main" in result.stderr

    def test_finds_ref_declared_before_repository(self, temp_dir):
        """Mapping keys are unordered; the ref may precede the repository."""
        write_workflow(temp_dir, "reusable-release.yml", """
jobs:
  propagate:
    steps:
      - uses: actions/checkout@1111111111111111111111111111111111111111 # v7.0.1
        with:
          ref: v0.24.0
          repository: cuioss/cuioss-organization
""")

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 1
        assert "@v0.24.0" in result.stderr

    def test_ignores_ref_of_a_foreign_checkout(self, temp_dir):
        """Only checkouts of this repository select code we are responsible for."""
        write_workflow(temp_dir, "reusable-release.yml", f"""
jobs:
  propagate:
    steps:
      - uses: actions/checkout@1111111111111111111111111111111111111111 # v7.0.1
        with:
          repository: cuioss/some-other-repo
          ref: main
      - uses: cuioss/cuioss-organization/.github/actions/read-project-config@{VALID_SHA} # v1.0.0
""")

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 0

    def test_accepts_sha_pinned_self_checkout(self, temp_dir):
        write_workflow(
            temp_dir, "reusable-release.yml",
            SELF_CHECKOUT.format(ref=f"{VALID_SHA} # v1.0.0")
            + ACTION_REF.format(sha=VALID_SHA)
        )

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 0


class TestPinsMustAgree:
    """The ordering defect: every executed ref must name the same commit.

    A SHA-shaped ref is not enough. v0.22.0 through v0.25.0 each tagged a
    commit whose `uses:` refs named the release commit while the self-checkout
    `ref:` still named the *previous* release, so the tag ran the previous
    release's workflow-scripts/.
    """

    OTHER_SHA = "1234567890abcdef1234567890abcdef12345678"

    def test_rejects_self_checkout_pinned_to_a_different_commit(self, temp_dir):
        write_workflow(
            temp_dir, "reusable-release.yml",
            ACTION_REF.format(sha=VALID_SHA)
            + SELF_CHECKOUT.format(ref=f"{self.OTHER_SHA} # v0.24.0")
        )

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 1
        assert "disagrees" in result.stderr
        assert self.OTHER_SHA in result.stderr

    def test_rejects_pins_that_are_not_the_commit_being_tagged(self, temp_dir):
        """--expect-sha is what the release job runs before creating the tag."""
        write_workflow(
            temp_dir, "reusable-release.yml",
            ACTION_REF.format(sha=VALID_SHA)
            + SELF_CHECKOUT.format(ref=f"{VALID_SHA} # v1.0.0")
        )

        result = run_script(
            SCRIPT_PATH, "--path", str(temp_dir), "--expect-sha", self.OTHER_SHA
        )

        assert result.returncode == 1
        assert "does not match the commit being tagged" in result.stderr

    def test_accepts_pins_that_are_the_commit_being_tagged(self, temp_dir):
        write_workflow(
            temp_dir, "reusable-release.yml",
            ACTION_REF.format(sha=VALID_SHA)
            + SELF_CHECKOUT.format(ref=f"{VALID_SHA} # v1.0.0")
        )

        result = run_script(
            SCRIPT_PATH, "--path", str(temp_dir), "--expect-sha", VALID_SHA
        )

        assert result.returncode == 0

    def test_ignores_caller_workflows_pinned_to_the_release_tag(self, temp_dir):
        """This repo consumes its own released tag; that SHA differs by design.

        dependabot-auto-merge.yml is a caller, not a reusable workflow, and is
        repinned to the tag *after* it exists. Folding it into the agreement
        set would fail every release.
        """
        write_workflow(
            temp_dir, "reusable-release.yml",
            ACTION_REF.format(sha=VALID_SHA)
            + SELF_CHECKOUT.format(ref=f"{VALID_SHA} # v1.0.0")
        )
        write_workflow(temp_dir, "dependabot-auto-merge.yml", f"""
jobs:
  auto-merge:
    uses: cuioss/cuioss-organization/.github/workflows/reusable-dependabot-auto-merge.yml@{self.OTHER_SHA} # v1.0.0
""")

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 0

    def test_rejects_a_malformed_expect_sha(self, temp_dir):
        result = run_script(SCRIPT_PATH, "--path", str(temp_dir), "--expect-sha", "v0.25.0")

        assert result.returncode == 1
        assert "40-character" in result.stderr


class TestNegativeControlAgainstShippedTags:
    """Reproduce the v0.25.0 tagged tree and prove the guard rejects it.

    A guard that passes on known-bad input is worthless. The shape below is the
    one v0.22.0-v0.25.0 actually shipped: composite actions pinned to the
    release commit, the workflow-scripts checkout still on the previous
    release's tag SHA.
    """

    RELEASE_COMMIT = "ad9a01ad6cbfddde54e62e359e355f4c8f8673a5"   # v0.25.0 release commit
    PREVIOUS_TAG = "f27afe4e6667a4f7b466b2b9858acc25e5281665"     # v0.24.0 tag

    def _write_shipped_tree(self, temp_dir):
        write_workflow(temp_dir, "reusable-maven-release.yml", f"""
jobs:
  release:
    steps:
      - uses: cuioss/cuioss-organization/.github/actions/release-guard@{self.RELEASE_COMMIT} # v0.25.0
      - uses: cuioss/cuioss-organization/.github/actions/read-project-config@{self.RELEASE_COMMIT} # v0.25.0

  wait-for-maven-central:
    steps:
      - uses: actions/checkout@1111111111111111111111111111111111111111 # v7.0.1
        with:
          repository: cuioss/cuioss-organization
          ref: {self.PREVIOUS_TAG} # v0.24.0
          sparse-checkout: workflow-scripts

  propagate-to-consumers:
    steps:
      - uses: actions/checkout@1111111111111111111111111111111111111111 # v7.0.1
        with:
          repository: cuioss/cuioss-organization
          ref: {self.PREVIOUS_TAG} # v0.24.0
          sparse-checkout: workflow-scripts
""")

    def test_guard_rejects_the_shipped_tree(self, temp_dir):
        self._write_shipped_tree(temp_dir)

        result = run_script(SCRIPT_PATH, "--path", str(temp_dir))

        assert result.returncode == 1, (
            "The guard passed on the tree v0.25.0 actually shipped — the defect "
            "it exists to catch would recur."
        )
        assert result.stderr.count(self.PREVIOUS_TAG) == 2

    def test_guard_rejects_the_shipped_tree_against_the_tagged_commit(self, temp_dir):
        self._write_shipped_tree(temp_dir)

        result = run_script(
            SCRIPT_PATH, "--path", str(temp_dir), "--expect-sha", self.RELEASE_COMMIT
        )

        assert result.returncode == 1
        assert "does not match the commit being tagged" in result.stderr
