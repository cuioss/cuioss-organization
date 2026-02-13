#!/usr/bin/env python3
"""Generate an overview index.html for deployed test reports.

Scans a target directory for timestamped report subdirectories, groups them
by report name, and generates an HTML overview page sorted newest-first.

Usage:
    python3 generate-overview-index.py --target-dir <path> --title <name>

Timestamped directory pattern: <name>-YYYY-MM-DD-HHmm-SSSS
(e.g. e-2-e-playwright-2025-01-15-1430-2300)
"""

import argparse
import html
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Matches: <report-name>-<YYYY>-<MM>-<DD>-<HHmm>-<SSSS>
# The report name is a greedy prefix that can contain hyphens.
TIMESTAMP_PATTERN = re.compile(
    r"^(.+)-(\d{4})-(\d{2})-(\d{2})-(\d{4})-(\d{4})$"
)


def parse_timestamped_dir(dirname: str) -> tuple[str, str] | None:
    """Parse a timestamped directory name into (report_name, timestamp_key).

    Returns None if the directory name doesn't match the expected pattern.
    The timestamp_key is sortable (YYYY-MM-DD-HHmm-SSSS).
    """
    match = TIMESTAMP_PATTERN.match(dirname)
    if not match:
        return None
    name = match.group(1)
    ts_key = f"{match.group(2)}-{match.group(3)}-{match.group(4)}-{match.group(5)}-{match.group(6)}"
    return name, ts_key


def format_timestamp(ts_key: str) -> str:
    """Format a timestamp key (YYYY-MM-DD-HHmm-SSSS) for display.

    Returns a human-readable string like '2025-01-15 14:30:23 UTC'.
    """
    # ts_key format: YYYY-MM-DD-HHmm-SSSS
    parts = ts_key.split("-")
    if len(parts) != 5:
        return ts_key
    year, month, day, hhmm, ssss = parts
    hh = hhmm[:2]
    mm = hhmm[2:]
    ss = ssss[:2]
    return f"{year}-{month}-{day} {hh}:{mm}:{ss} UTC"


def scan_reports(target_dir: Path) -> dict[str, list[tuple[str, str, str]]]:
    """Scan target directory for timestamped report directories.

    Returns a dict mapping report_name -> list of (timestamp_key, dirname, display_ts),
    sorted newest-first within each group.
    """
    groups: dict[str, list[tuple[str, str, str]]] = {}

    for entry in sorted(target_dir.iterdir()):
        if not entry.is_dir():
            continue
        parsed = parse_timestamped_dir(entry.name)
        if parsed is None:
            continue
        report_name, ts_key = parsed
        display_ts = format_timestamp(ts_key)
        groups.setdefault(report_name, []).append((ts_key, entry.name, display_ts))

    # Sort each group newest-first
    for name in groups:
        groups[name].sort(key=lambda x: x[0], reverse=True)

    return groups


def generate_html(title: str, groups: dict[str, list[tuple[str, str, str]]]) -> str:
    """Generate the overview index.html content.

    Args:
        title: Page title (HTML-escaped internally)
        groups: Report groups from scan_reports()

    Returns:
        Complete HTML5 document as string
    """
    safe_title = html.escape(title)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    sections = []
    for name in sorted(groups.keys()):
        entries = groups[name]
        safe_name = html.escape(name)
        items = []
        for _ts_key, dirname, display_ts in entries:
            safe_dirname = html.escape(dirname)
            safe_display = html.escape(display_ts)
            items.append(
                f'      <li><a href="./{safe_dirname}/index.html">{safe_dirname}</a>'
                f" <span class=\"ts\">{safe_display}</span></li>"
            )
        items_html = "\n".join(items)
        sections.append(
            f"    <h2>{safe_name}</h2>\n"
            f"    <ul>\n{items_html}\n    </ul>"
        )

    sections_html = "\n".join(sections) if sections else "    <p>No reports found.</p>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title} - Test Reports</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      max-width: 900px;
      margin: 2rem auto;
      padding: 0 1rem;
      color: #e0e0e0;
      background: #1a1a2e;
    }}
    h1 {{ color: #00d4ff; border-bottom: 2px solid #16213e; padding-bottom: 0.5rem; }}
    h2 {{ color: #a0c4ff; margin-top: 2rem; }}
    ul {{ list-style: none; padding: 0; }}
    li {{ padding: 0.4rem 0; }}
    a {{ color: #64b5f6; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .ts {{ color: #888; font-size: 0.85em; margin-left: 0.5em; }}
    footer {{ margin-top: 3rem; color: #555; font-size: 0.8em; border-top: 1px solid #16213e; padding-top: 0.5rem; }}
    @media (prefers-color-scheme: light) {{
      body {{ color: #333; background: #fff; }}
      h1 {{ color: #0066cc; border-bottom-color: #ddd; }}
      h2 {{ color: #0055aa; }}
      a {{ color: #0066cc; }}
      .ts {{ color: #999; }}
      footer {{ color: #aaa; border-top-color: #ddd; }}
    }}
  </style>
</head>
<body>
  <h1>{safe_title} - Test Reports</h1>
{sections_html}
  <footer>Generated {html.escape(now)}</footer>
</body>
</html>
"""


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate overview index.html for deployed test reports"
    )
    parser.add_argument(
        "--target-dir",
        required=True,
        help="Directory containing timestamped report subdirectories",
    )
    parser.add_argument(
        "--title",
        required=True,
        help="Page title (typically the pages-reference name)",
    )
    args = parser.parse_args()

    target_dir = Path(args.target_dir)
    if not target_dir.is_dir():
        print(f"::error::Target directory does not exist: {target_dir}", file=sys.stderr)
        return 1

    print(f"Scanning {target_dir} for report directories...", file=sys.stderr)
    groups = scan_reports(target_dir)

    total = sum(len(v) for v in groups.values())
    print(f"Found {total} report(s) in {len(groups)} group(s)", file=sys.stderr)

    html_content = generate_html(args.title, groups)
    index_path = target_dir / "index.html"
    index_path.write_text(html_content, encoding="utf-8")
    print(f"Wrote {index_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
