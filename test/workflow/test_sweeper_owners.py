"""The Dependabot sweeper covers every owner whose repositories consume these workflows.

The sweep script searches one owner per run (`--owner`), and a release App is installed on one
account only. So the sweeper is a matrix with one leg per owner, each with its own App secrets,
and a leg whose secrets are absent reports it and does nothing instead of failing the others.
"""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT

SWEEPER = PROJECT_ROOT / ".github" / "workflows" / "dependabot-sweeper.yml"


def _job():
    return yaml.safe_load(SWEEPER.read_text())["jobs"]["sweep"]


def test_one_leg_per_owner_with_its_own_app_secrets():
    owners = {entry["name"]: entry for entry in _job()["strategy"]["matrix"]["owner"]}

    assert set(owners) == {"cuioss", "plan-marshall"}
    assert owners["cuioss"]["app-id-secret"] == "RELEASE_APP_ID"
    # the names release.yml derives for a foreign owner: RELEASE_APP_ID_<OWNER>
    assert owners["plan-marshall"]["app-id-secret"] == "RELEASE_APP_ID_PLAN_MARSHALL"
    assert owners["plan-marshall"]["private-key-secret"] == "RELEASE_APP_PRIVATE_KEY_PLAN_MARSHALL"


def test_a_broken_owner_does_not_stop_the_others():
    assert _job()["strategy"]["fail-fast"] is False


def test_missing_credentials_skip_the_leg_instead_of_failing_it():
    steps = {step.get("name", ""): step for step in _job()["steps"]}
    guarded = [name for name, step in steps.items() if step.get("if") == "steps.app.outputs.present == 'true'"]

    assert any(name.startswith("Generate Release Token") for name in guarded)
    assert any(name.startswith("Sweep labelled Dependabot PRs") for name in guarded)


def test_the_sweep_is_limited_to_the_legs_owner():
    run = next(step["run"] for step in _job()["steps"] if step.get("name", "").startswith("Sweep labelled"))

    assert '--owner "${{ matrix.owner.name }}"' in run
