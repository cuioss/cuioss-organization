#!/usr/bin/env python3
"""Build script with module filtering support.

Provides canonical commands (compile, test, quality-gate, verify)
with optional module filtering.

Usage:
    ./pw build compile                      # All production sources
    ./pw build compile workflow             # Single module (workflow scripts)
    ./pw build test                         # All tests
    ./pw build test repo-admin              # Single test directory
    ./pw build verify                       # Full verification
"""

import argparse
import subprocess
import sys
from pathlib import Path

# Module definitions - maps module names to their source paths
MODULES = {
    "workflow": [
        ".github/actions/read-project-config/read-config.py",
        ".github/actions/assemble-test-reports/assemble-reports.py",
        ".github/actions/assemble-test-reports/generate-overview-index.py",
        "workflow-scripts/update-workflow-references.py",
        "workflow-scripts/update-consumer-repo.py",
        "workflow-scripts/verify-consumer-prs.py",
    ],
    "repo-admin": [
        "repo-settings/setup-repo-settings.py",
        "branch-protection/setup-branch-protection.py",
    ],
}

# All source paths for full compilation
ALL_SOURCES = [
    ".github/actions/read-project-config/read-config.py",
    ".github/actions/assemble-test-reports/assemble-reports.py",
    ".github/actions/assemble-test-reports/generate-overview-index.py",
    "workflow-scripts/update-workflow-references.py",
    "workflow-scripts/update-consumer-repo.py",
    "workflow-scripts/verify-consumer-prs.py",
    "repo-settings/setup-repo-settings.py",
    "branch-protection/setup-branch-protection.py",
]

TEST_DIR = Path("test")


def run(cmd: list[str], description: str) -> int:
    """Run a command and return exit code."""
    print(f">>> {description}")
    print(f'    {" ".join(cmd)}')
    result = subprocess.run(cmd)
    return result.returncode


def get_module_sources(module: str | None) -> list[str]:
    """Get source paths, optionally filtered by module."""
    if module:
        if module not in MODULES:
            print(f"Error: Unknown module '{module}'", file=sys.stderr)
            print(f"Available modules: {', '.join(MODULES.keys())}", file=sys.stderr)
            sys.exit(1)
        return MODULES[module]
    return ALL_SOURCES


def get_test_path(module: str | None) -> str:
    """Get test path, optionally filtered by module."""
    if module:
        path = TEST_DIR / module
        if not path.exists():
            print(f"Error: Test directory not found: {path}", file=sys.stderr)
            sys.exit(1)
        return str(path)
    return str(TEST_DIR)


def cmd_compile(module: str | None) -> int:
    """Run mypy on production sources."""
    sources = get_module_sources(module)
    return run(["uv", "run", "mypy"] + sources, f'compile: mypy {" ".join(sources)}')


def cmd_test(module: str | None) -> int:
    """Run pytest on test sources."""
    path = get_test_path(module)
    return run(["uv", "run", "pytest", path], f"test: pytest {path}")


def cmd_quality_gate(module: str | None) -> int:
    """Run ruff check on sources."""
    sources = get_module_sources(module)
    test_path = get_test_path(module) if module else str(TEST_DIR)

    paths = sources.copy()
    if Path(test_path).exists():
        paths.append(test_path)

    return run(["uv", "run", "ruff", "check"] + paths, f'quality-gate: ruff check {" ".join(paths)}')


def cmd_verify(module: str | None) -> int:
    """Run full verification: compile + quality-gate + test."""
    print(f'=== verify: {"all" if not module else module} ===')

    exit_code = cmd_compile(module)
    if exit_code != 0:
        print("verify: compile failed", file=sys.stderr)
        return exit_code

    exit_code = cmd_quality_gate(module)
    if exit_code != 0:
        print("verify: quality-gate failed", file=sys.stderr)
        return exit_code

    exit_code = cmd_test(module)
    if exit_code != 0:
        print("verify: test failed", file=sys.stderr)
        return exit_code

    print("=== verify: SUCCESS ===")
    return 0


def cmd_clean() -> int:
    """Clean build artifacts."""
    dirs = [".venv", ".pytest_cache", ".mypy_cache", ".ruff_cache"]
    for d in dirs:
        path = Path(d)
        if path.exists():
            print(f"Removing {d}")
            import shutil

            shutil.rmtree(path)
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Build script with module filtering",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s compile                    # mypy all sources
  %(prog)s compile workflow           # mypy workflow module only
  %(prog)s test                       # pytest test/
  %(prog)s test repo-admin            # pytest test/repo-admin
  %(prog)s verify                     # Full verification

Modules:
  workflow    - Workflow scripts (.github/actions/*, workflow-scripts/*)
  repo-admin  - Repository admin scripts (repo-settings/*, branch-protection/*)
""",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # compile
    p = subparsers.add_parser("compile", help="mypy on production sources")
    p.add_argument("module", nargs="?", help="Module name (workflow, repo-admin)")

    # test
    p = subparsers.add_parser("test", help="pytest on test sources")
    p.add_argument("module", nargs="?", help="Test directory (workflow, repo-admin)")

    # quality-gate
    p = subparsers.add_parser("quality-gate", help="ruff check on sources")
    p.add_argument("module", nargs="?", help="Module name (workflow, repo-admin)")

    # verify
    p = subparsers.add_parser("verify", help="Full verification (compile + quality-gate + test)")
    p.add_argument("module", nargs="?", help="Module name (workflow, repo-admin)")

    # clean
    subparsers.add_parser("clean", help="Remove build artifacts")

    args = parser.parse_args()

    if args.command == "compile":
        sys.exit(cmd_compile(args.module))
    elif args.command == "test":
        sys.exit(cmd_test(args.module))
    elif args.command == "quality-gate":
        sys.exit(cmd_quality_gate(args.module))
    elif args.command == "verify":
        sys.exit(cmd_verify(args.module))
    elif args.command == "clean":
        sys.exit(cmd_clean())


if __name__ == "__main__":
    main()
