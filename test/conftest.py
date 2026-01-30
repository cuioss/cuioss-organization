"""Shared test fixtures for cuioss-organization Python scripts."""

import subprocess
import sys
from collections import namedtuple
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
ScriptResult = namedtuple("ScriptResult", ["returncode", "stdout", "stderr"])


def run_script(script_path: Path, *args, cwd=None, input_data=None, env=None):
    """Execute a Python script and capture output.

    Args:
        script_path: Path to the Python script
        *args: Command line arguments to pass
        cwd: Working directory (defaults to PROJECT_ROOT)
        input_data: Optional input to pass to stdin
        env: Optional environment variables

    Returns:
        ScriptResult with returncode, stdout, stderr
    """
    result = subprocess.run(
        [sys.executable, str(script_path), *args],
        capture_output=True,
        text=True,
        cwd=cwd or PROJECT_ROOT,
        input=input_data,
        env=env,
    )
    return ScriptResult(result.returncode, result.stdout, result.stderr)


@pytest.fixture
def temp_dir(tmp_path):
    """Provide a temporary directory for test files."""
    return tmp_path


@pytest.fixture
def project_root():
    """Provide the project root path."""
    return PROJECT_ROOT
