#!/usr/bin/env python3
"""Read project.yml and output all fields in GITHUB_OUTPUT format.

This script replaces the inline yq parsing in reusable workflows with a
single, maintainable Python solution.

Usage:
    python3 read-project-config.py --config .github/project.yml
    curl -sL https://raw.githubusercontent.com/.../read-project-config.py | python3 - --config .github/project.yml

Output:
    Writes key=value pairs to stdout in GITHUB_OUTPUT format.
"""

import argparse
import sys
from pathlib import Path

# Try to import yaml, which is pre-installed on GitHub runners
try:
    import yaml
except ImportError:
    print("Error: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


# Default values matching workflow input defaults
DEFAULTS = {
    # maven-build section
    "java-versions": '["21","25"]',
    "java-version": "21",
    "enable-snapshot-deploy": "true",
    "maven-profiles-snapshot": "release-snapshot,javadoc",
    "maven-profiles-release": "release,javadoc",
    "npm-cache": "false",
    # sonar section
    "sonar-enabled": "true",
    "sonar-skip-on-dependabot": "true",
    "sonar-project-key": "",
    # release section
    "current-version": "",
    "next-version": "",
    "generate-release-notes": "false",
    # pages section
    "pages-reference": "",
    "deploy-site": "true",
}


def get_nested(data: dict, *keys, default=None):
    """Safely get nested dictionary value."""
    for key in keys:
        if not isinstance(data, dict):
            return default
        data = data.get(key)
        if data is None:
            return default
    return data


def to_output_value(value) -> str:
    """Convert a value to string suitable for GITHUB_OUTPUT."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def read_config(config_path: Path) -> dict:
    """Read and parse the project.yml file."""
    if not config_path.exists():
        return {}

    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return data if isinstance(data, dict) else {}


def extract_outputs(data: dict) -> dict[str, str]:
    """Extract all output values from config data with defaults."""
    outputs = {}

    # maven-build section
    maven_build = data.get("maven-build", {}) or {}
    outputs["java-versions"] = to_output_value(
        maven_build.get("java-versions") or DEFAULTS["java-versions"]
    )
    outputs["java-version"] = to_output_value(
        maven_build.get("java-version") or DEFAULTS["java-version"]
    )
    outputs["enable-snapshot-deploy"] = to_output_value(
        maven_build.get("enable-snapshot-deploy")
        if maven_build.get("enable-snapshot-deploy") is not None
        else DEFAULTS["enable-snapshot-deploy"]
    )
    outputs["maven-profiles-snapshot"] = to_output_value(
        maven_build.get("maven-profiles-snapshot") or DEFAULTS["maven-profiles-snapshot"]
    )
    outputs["maven-profiles-release"] = to_output_value(
        maven_build.get("maven-profiles-release") or DEFAULTS["maven-profiles-release"]
    )
    outputs["npm-cache"] = to_output_value(
        maven_build.get("npm-cache")
        if maven_build.get("npm-cache") is not None
        else DEFAULTS["npm-cache"]
    )

    # sonar section
    sonar = data.get("sonar", {}) or {}
    outputs["sonar-enabled"] = to_output_value(
        sonar.get("enabled") if sonar.get("enabled") is not None else DEFAULTS["sonar-enabled"]
    )
    outputs["sonar-skip-on-dependabot"] = to_output_value(
        sonar.get("skip-on-dependabot")
        if sonar.get("skip-on-dependabot") is not None
        else DEFAULTS["sonar-skip-on-dependabot"]
    )
    outputs["sonar-project-key"] = to_output_value(
        sonar.get("project-key") or DEFAULTS["sonar-project-key"]
    )

    # release section
    release = data.get("release", {}) or {}
    outputs["current-version"] = to_output_value(
        release.get("current-version") or DEFAULTS["current-version"]
    )
    outputs["next-version"] = to_output_value(
        release.get("next-version") or DEFAULTS["next-version"]
    )
    outputs["generate-release-notes"] = to_output_value(
        release.get("generate-release-notes")
        if release.get("generate-release-notes") is not None
        else DEFAULTS["generate-release-notes"]
    )

    # pages section
    pages = data.get("pages", {}) or {}
    outputs["pages-reference"] = to_output_value(
        pages.get("reference") or DEFAULTS["pages-reference"]
    )
    outputs["deploy-site"] = to_output_value(
        pages.get("deploy-at-release")
        if pages.get("deploy-at-release") is not None
        else DEFAULTS["deploy-site"]
    )

    # consumers list (special case for release.yml)
    consumers = data.get("consumers", [])
    if isinstance(consumers, list):
        outputs["consumers"] = " ".join(consumers)
    else:
        outputs["consumers"] = ""

    return outputs


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Read project.yml and output in GITHUB_OUTPUT format"
    )
    parser.add_argument(
        "--config",
        default=".github/project.yml",
        help="Path to project.yml (default: .github/project.yml)",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    data = read_config(config_path)
    outputs = extract_outputs(data)

    # Output in GITHUB_OUTPUT format
    for key, value in outputs.items():
        print(f"{key}={value}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
