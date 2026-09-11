"""Tests for check-quarkus-alignment.py.

The behaviours that matter here are the ones a mistake would make invisible: the
check must *skip* for a non-Quarkus project, must *fail* rather than pass when it
cannot determine alignment, and must catch a split family and not only a uniformly
wrong one.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add parent to path to access conftest
sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import PROJECT_ROOT  # noqa: E402

SCRIPT_PATH = PROJECT_ROOT / "workflow-scripts/check-quarkus-alignment.py"

QUARKUS_BOM_POM = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <properties>
    <smallrye-config.version>3.17.2</smallrye-config.version>
  </properties>
  <dependencyManagement>
    <dependencies>
      <dependency>
        <groupId>io.smallrye.config</groupId>
        <artifactId>smallrye-config</artifactId>
        <version>${smallrye-config.version}</version>
      </dependency>
    </dependencies>
  </dependencyManagement>
</project>
"""


def _load_module():
    """Load check-quarkus-alignment.py as a module for unit testing."""
    spec = importlib.util.spec_from_file_location("check_quarkus_alignment", SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=["mvn"], returncode=returncode, stdout=stdout, stderr=stderr)


def _listing(*coordinates):
    """A dependency:list output file body."""
    return "\nThe following files have been resolved:\n" + "".join(f"   {c}\n" for c in coordinates)


class TestEvaluateProperty:
    """version.quarkus must come from the effective POM, absent != broken."""

    def test_returns_value_from_effective_pom(self, tmp_path):
        mod = _load_module()
        with patch.object(mod, "_run_maven", return_value=_completed(stdout="3.39.2\n")):
            assert mod.evaluate_property(tmp_path, "version.quarkus", 60) == "3.39.2"

    def test_returns_none_for_undefined_property(self, tmp_path):
        mod = _load_module()
        out = _completed(stdout="null object or invalid expression\n")
        with patch.object(mod, "_run_maven", return_value=out):
            assert mod.evaluate_property(tmp_path, "version.quarkus", 60) is None

    def test_returns_none_when_maven_prints_nothing(self, tmp_path):
        mod = _load_module()
        with patch.object(mod, "_run_maven", return_value=_completed(stdout="")):
            assert mod.evaluate_property(tmp_path, "version.quarkus", 60) is None

    def test_nonzero_exit_is_undetermined_not_absent(self, tmp_path):
        """A broken build must never be read as 'not a Quarkus project'."""
        mod = _load_module()
        out = _completed(returncode=1, stdout="[ERROR] The build could not read 1 project\n")
        with patch.object(mod, "_run_maven", return_value=out), pytest.raises(mod.Undetermined) as excinfo:
            mod.evaluate_property(tmp_path, "version.quarkus", 60)
        assert "could not read 1 project" in str(excinfo.value)


class TestMavenDiagnostics:
    """Maven prints its [ERROR] block to stdout, so stderr alone says nothing."""

    def test_prefers_error_lines_from_stdout(self):
        mod = _load_module()
        out = _completed(
            returncode=1,
            stdout="[INFO] Scanning\n[ERROR] 'dependencies.dependency.version' is missing\n",
            stderr="",
        )
        detail = mod._maven_diagnostics(out)
        assert "dependencies.dependency.version" in detail
        assert "[INFO] Scanning" not in detail

    def test_falls_back_to_whole_output_without_error_lines(self):
        mod = _load_module()
        detail = mod._maven_diagnostics(_completed(returncode=1, stderr="killed"))
        assert "killed" in detail

    def test_never_returns_empty(self):
        mod = _load_module()
        assert mod._maven_diagnostics(_completed(returncode=1)) == "(no output)"


class TestQuarkusSmallryeVersion:
    """The expected version is read from the published quarkus-bom."""

    @patch("urllib.request.urlopen")
    def test_dereferences_a_property_version(self, mock_urlopen):
        mod = _load_module()
        response = MagicMock()
        response.read.return_value = QUARKUS_BOM_POM.encode()
        response.__enter__ = MagicMock(return_value=response)
        response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = response
        assert mod.quarkus_smallrye_version("3.39.2") == "3.17.2"

    @patch("time.sleep")
    @patch("urllib.request.urlopen", side_effect=OSError("connection reset"))
    def test_unreachable_central_is_undetermined(self, _urlopen, _sleep):
        mod = _load_module()
        with pytest.raises(mod.Undetermined) as excinfo:
            mod.quarkus_smallrye_version("3.39.2")
        assert "could not fetch" in str(excinfo.value)

    @patch("time.sleep")
    @patch("urllib.request.urlopen", side_effect=OSError("flaky"))
    def test_retries_before_giving_up(self, _urlopen, _sleep):
        mod = _load_module()
        with pytest.raises(mod.Undetermined):
            mod.quarkus_smallrye_version("3.39.2")
        assert _urlopen.call_count == mod.FETCH_ATTEMPTS


class TestCoordinateParsing:
    """dependency:list emits coordinates with and without a classifier."""

    def test_parses_five_field_coordinate(self):
        mod = _load_module()
        parsed = mod._coordinate("   io.smallrye.config:smallrye-config:jar:3.17.2:compile")
        assert parsed == ("io.smallrye.config", "smallrye-config", "3.17.2")

    def test_parses_six_field_coordinate_with_classifier(self):
        mod = _load_module()
        parsed = mod._coordinate("   io.smallrye.config:smallrye-config:jar:tests:3.17.2:test")
        assert parsed == ("io.smallrye.config", "smallrye-config", "3.17.2")

    def test_ignores_non_coordinate_lines(self):
        mod = _load_module()
        assert mod._coordinate("The following files have been resolved:") is None
        assert mod._coordinate("") is None


class TestResolvedVersions:
    """The assertion is made against what the reactor actually resolves."""

    def _run(self, mod, tmp_path, body, returncode=0):
        def fake_run(repo, goal_args, timeout):
            target = next(a for a in goal_args if a.startswith("-DoutputFile=")).split("=", 1)[1]
            if returncode == 0:
                Path(target).write_text(body)
            return _completed(returncode=returncode, stdout=body)

        with patch.object(mod, "_run_maven", side_effect=fake_run):
            return mod.resolved_versions(tmp_path, 60)

    def test_collects_smallrye_family_and_quarkus_core(self, tmp_path):
        mod = _load_module()
        found, core = self._run(
            mod,
            tmp_path,
            _listing(
                "io.smallrye.config:smallrye-config:jar:3.17.2:compile",
                "io.smallrye.config:smallrye-config-core:jar:3.17.2:compile",
                "io.quarkus:quarkus-core:jar:3.39.2:compile",
                "org.junit.jupiter:junit-jupiter:jar:5.14.0:test",
            ),
        )
        assert found == {"smallrye-config": {"3.17.2"}, "smallrye-config-core": {"3.17.2"}}
        assert core == {"3.39.2"}

    def test_records_a_split_family_as_multiple_versions(self, tmp_path):
        """Two versions of one artifact across the reactor is the split this hunts for."""
        mod = _load_module()
        found, _ = self._run(
            mod,
            tmp_path,
            _listing(
                "io.smallrye.config:smallrye-config:jar:3.17.2:compile",
                "io.smallrye.config:smallrye-config:jar:3.16.0:compile",
            ),
        )
        assert found == {"smallrye-config": {"3.17.2", "3.16.0"}}

    def test_failed_resolution_is_undetermined(self, tmp_path):
        mod = _load_module()
        with pytest.raises(mod.Undetermined) as excinfo:
            self._run(mod, tmp_path, "[ERROR] could not read project\n", returncode=1)
        assert "could not read project" in str(excinfo.value)


class TestCheck:
    """End-to-end decisions, with Maven and Maven Central stubbed out."""

    def _check(self, tmp_path, quarkus, expected, resolved, core):
        mod = _load_module()
        with (
            patch.object(mod, "evaluate_property", return_value=quarkus),
            patch.object(mod, "quarkus_smallrye_version", return_value=expected),
            patch.object(mod, "resolved_versions", return_value=(resolved, core)),
        ):
            return mod.check(tmp_path, 60, 60)

    def test_skips_cleanly_for_a_non_quarkus_project(self, tmp_path, capsys):
        assert self._check(tmp_path, None, None, {}, set()) == 0
        assert "not a Quarkus project" in capsys.readouterr().out

    def test_aligned_family_passes(self, tmp_path):
        resolved = {"smallrye-config": {"3.17.2"}, "smallrye-config-core": {"3.17.2"}}
        assert self._check(tmp_path, "3.39.2", "3.17.2", resolved, {"3.39.2"}) == 0

    def test_wrong_family_fails(self, tmp_path, capsys):
        resolved = {"smallrye-config": {"3.16.0"}}
        assert self._check(tmp_path, "3.39.2", "3.17.2", resolved, {"3.39.2"}) == 1
        assert "resolves to 3.16.0, expected 3.17.2" in capsys.readouterr().err

    def test_split_family_fails_even_when_one_side_is_correct(self, tmp_path, capsys):
        resolved = {"smallrye-config": {"3.17.2", "3.16.0"}}
        assert self._check(tmp_path, "3.39.2", "3.17.2", resolved, {"3.39.2"}) == 1
        assert "3.16.0, 3.17.2" in capsys.readouterr().err

    def test_quarkus_core_drift_fails(self, tmp_path, capsys):
        """version.quarkus drives the plugin; the artifacts come from the imported BOM."""
        resolved = {"smallrye-config": {"3.17.2"}}
        assert self._check(tmp_path, "3.39.2", "3.17.2", resolved, {"3.38.0"}) == 1
        assert "drifted apart" in capsys.readouterr().err

    def test_quarkus_project_without_smallrye_on_the_classpath_passes(self, tmp_path, capsys):
        assert self._check(tmp_path, "3.39.2", "3.17.2", {}, {"3.39.2"}) == 0
        assert "no io.smallrye.config artifacts" in capsys.readouterr().out


class TestMainExitCodes:
    """Cannot-determine must block. Exit 2 is not a pass."""

    def test_undetermined_exits_two(self, tmp_path, monkeypatch, capsys):
        mod = _load_module()
        monkeypatch.setattr(sys, "argv", ["check-quarkus-alignment.py", "--repo", str(tmp_path)])

        def boom(*_args, **_kwargs):
            raise mod.Undetermined("maven unavailable")

        monkeypatch.setattr(mod, "check", boom)
        assert mod.main() == 2
        captured = capsys.readouterr()
        assert "CANNOT DETERMINE" in captured.err
        assert "::error::" in captured.out
