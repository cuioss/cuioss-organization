#!/usr/bin/env python3
"""Assemble test report directories and log files into a timestamped output.

Collects report directories and optional log files into a single timestamped
directory suitable for deployment to GitHub Pages.

Usage:
    python3 assemble-reports.py \
        --report-name e-2-e-playwright \
        --reports-folder $'dir1\ndir2' \
        --output-dir .test-reports

Output (GITHUB_OUTPUT format on stdout):
    report-dir=<output-dir>/<timestamped-name>
    report-dirname=<timestamped-name>
"""

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


def _parse_newline_list(value: str) -> list[str]:
    """Parse a newline-separated string into a list, stripping blanks."""
    if not value:
        return []
    return [line.strip() for line in value.strip().splitlines() if line.strip()]


def _make_timestamped_name(report_name: str) -> str:
    """Generate a timestamped directory name: <name>-YYYY-MM-DD-HHmm-SSSS.

    The trailing 4-digit field is seconds * 10 + a sub-digit, providing
    enough resolution to avoid collisions in practice.
    """
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%d-%H%M")
    # Use seconds with zero-padding for uniqueness
    secs = f"{now.second:02d}{now.microsecond // 100000:01d}0"
    return f"{report_name}-{ts}-{secs}"


def _unique_leaf(dest_parent: Path, leaf: str) -> Path:
    """Return a unique path under dest_parent for the given leaf name.

    If dest_parent/leaf already exists, appends -2, -3, etc.
    """
    candidate = dest_parent / leaf
    if not candidate.exists():
        return candidate
    counter = 2
    while True:
        candidate = dest_parent / f"{leaf}-{counter}"
        if not candidate.exists():
            return candidate
        counter += 1


def assemble_reports(
    report_name: str,
    reports_folder: list[str],
    report_logs: list[str],
    output_dir: Path,
) -> tuple[Path, str]:
    """Assemble report directories and logs into a timestamped output.

    Args:
        report_name: Base name for the report (e.g. 'e-2-e-playwright')
        reports_folder: List of directories to copy
        report_logs: List of log files to collect
        output_dir: Parent directory for the timestamped output

    Returns:
        Tuple of (full report path, directory name)

    Raises:
        SystemExit: If no report directories are found at all
    """
    dirname = _make_timestamped_name(report_name)
    report_path = output_dir / dirname
    report_path.mkdir(parents=True, exist_ok=True)

    # Copy report directories
    found_any = False
    for folder_str in reports_folder:
        folder = Path(folder_str)
        if not folder.is_dir():
            print(f"::warning::Reports folder not found, skipping: {folder}", file=sys.stderr)
            continue
        leaf = folder.name
        dest = _unique_leaf(report_path, leaf)
        shutil.copytree(folder, dest)
        found_any = True
        print(f"  Copied {folder} -> {dest.name}", file=sys.stderr)

    if not found_any:
        print("::error::No report directories found — nothing to assemble", file=sys.stderr)
        sys.exit(1)

    # Copy log files
    if report_logs:
        logs_dir = report_path / "logs"
        logs_dir.mkdir(exist_ok=True)
        for log_str in report_logs:
            log_file = Path(log_str)
            if not log_file.is_file():
                print(f"::warning::Log file not found, skipping: {log_file}", file=sys.stderr)
                continue
            dest = _unique_leaf(logs_dir, log_file.name)
            shutil.copy2(log_file, dest)
            print(f"  Copied log {log_file} -> logs/{dest.name}", file=sys.stderr)

    return report_path, dirname


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Assemble test reports into a timestamped directory"
    )
    parser.add_argument(
        "--report-name",
        required=True,
        help="Base name for the report directory",
    )
    parser.add_argument(
        "--reports-folder",
        required=True,
        help="Newline-separated list of directories to copy",
    )
    parser.add_argument(
        "--report-logs",
        default="",
        help="Newline-separated list of log files to collect",
    )
    parser.add_argument(
        "--output-dir",
        default=".test-reports",
        help="Parent directory for output (default: .test-reports)",
    )
    args = parser.parse_args()

    reports_folder = _parse_newline_list(args.reports_folder)
    report_logs = _parse_newline_list(args.report_logs)

    if not reports_folder:
        print("::error::--reports-folder is empty (no directories specified)", file=sys.stderr)
        return 1

    print("::group::Assembling test reports", file=sys.stderr)

    report_path, dirname = assemble_reports(
        report_name=args.report_name,
        reports_folder=reports_folder,
        report_logs=report_logs,
        output_dir=Path(args.output_dir),
    )

    print("::endgroup::", file=sys.stderr)

    # Output in GITHUB_OUTPUT format (stdout)
    print(f"report-dir={report_path}")
    print(f"report-dirname={dirname}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
