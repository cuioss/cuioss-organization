#!/usr/bin/env python3
"""Read project.yml and output all fields in GITHUB_OUTPUT format.

This script uses a field registry pattern for easy expandability.
Adding a new field requires only one line in FIELD_REGISTRY.

Usage:
    python3 read-config.py --config .github/project.yml

Output:
    Writes key=value pairs to stdout in GITHUB_OUTPUT format.
"""

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

# Try to import yaml, which is pre-installed on GitHub runners
try:
    import yaml
except ImportError:
    print("Error: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


# Type alias for transform functions
TransformFn = Callable[[Any], Any] | None

def _sanitize_shell_value(value: Any) -> str:
    """Sanitize a string value that may be used in shell commands.

    Enforces a strict allowlist of characters suitable for Maven module names,
    profiles, and path segments. Rejects any value containing shell
    metacharacters to prevent command injection via GITHUB_OUTPUT.
    """
    import re
    s = str(value).strip() if value is not None else ""
    if not s:
        return ""
    safe_pattern = re.compile(r"^[a-zA-Z0-9_./:,\-]+$")
    if safe_pattern.match(s):
        return s
    return ""


def _sanitize_glob_list(value: Any) -> str:
    """Sanitize a list of glob patterns into a safe space-separated string.

    Strips newlines, shell metacharacters, and converts all items to strings
    to prevent output injection via GITHUB_OUTPUT and command injection in
    shell steps that iterate over the result.
    """
    if not isinstance(value, list):
        return ""
    import re
    safe_pattern = re.compile(r"^[a-zA-Z0-9_./*?\-\[\]{},]+$")
    parts = []
    for item in value:
        s = str(item).strip()
        if s and safe_pattern.match(s):
            parts.append(s)
    return " ".join(parts)


# Field registry: (yaml_path, output_name, default, transform_fn)
# To add a new field, simply append a tuple to this list
FIELD_REGISTRY: list[tuple[list[str], str, Any, TransformFn]] = [
    # maven-build section
    (["maven-build", "java-versions"], "java-versions", '["21","25"]', None),
    (["maven-build", "java-version"], "java-version", "21", None),
    (["maven-build", "enable-snapshot-deploy"], "enable-snapshot-deploy", True, None),
    (["maven-build", "maven-profiles-snapshot"], "maven-profiles-snapshot", "release-snapshot,javadoc", None),
    (["maven-build", "maven-profiles-release"], "maven-profiles-release", "release,javadoc", None),
    (["maven-build", "npm-cache"], "npm-cache", False, None),
    (["maven-build", "skip-on-docs-only"], "skip-on-docs-only", True, None),
    (["maven-build", "paths-ignore-extra"], "paths-ignore-extra", [], _sanitize_glob_list),
    # sonar section
    (["sonar", "enabled"], "sonar-enabled", True, None),
    (["sonar", "skip-on-dependabot"], "sonar-skip-on-dependabot", True, None),
    (["sonar", "project-key"], "sonar-project-key", "", None),
    # release section
    (["release", "current-version"], "current-version", "", None),
    (["release", "next-version"], "next-version", "", None),
    (["release", "create-github-release"], "create-github-release", False, None),
    # pages section
    (["pages", "reference"], "pages-reference", "", None),
    (["pages", "deploy-at-release"], "deploy-site", True, None),
    # npm-build section
    (["npm-build", "node-version"], "npm-node-version", "22", None),
    (["npm-build", "registry-url"], "npm-registry-url", "https://registry.npmjs.org", None),
    # pyprojectx section
    (["pyprojectx", "python-version"], "pyprojectx-python-version", "", None),
    (["pyprojectx", "cache-dependency-glob"], "pyprojectx-cache-dependency-glob", "uv.lock", None),
    (["pyprojectx", "upload-artifacts-on-failure"], "pyprojectx-upload-artifacts-on-failure", False, None),
    (["pyprojectx", "verify-command"], "pyprojectx-verify-command", "./pw verify", None),
    # integration-tests section (string fields sanitized — used in shell commands)
    (["integration-tests", "test-type"], "it-test-type", "", _sanitize_shell_value),
    (["integration-tests", "maven-module"], "it-maven-module", "", _sanitize_shell_value),
    (["integration-tests", "maven-profiles"], "it-maven-profiles", "integration-tests", _sanitize_shell_value),
    (["integration-tests", "timeout-minutes"], "it-timeout-minutes", 20, None),
    (["integration-tests", "deploy-reports"], "it-deploy-reports", False, None),
    (["integration-tests", "reports-subfolder"], "it-reports-subfolder", "", _sanitize_shell_value),
    # github-automation section
    (["github-automation", "auto-merge-build-versions"], "auto-merge-build-versions", True, None),
    # consumers list (special case: transform list to space-separated string)
    (["consumers"], "consumers", [], lambda x: " ".join(x) if isinstance(x, list) else ""),
]


def extract_custom_outputs(data: dict) -> dict[str, str]:
    """Extract custom namespace fields as individual outputs.

    The 'custom' section allows downstream repos to define arbitrary
    key-value pairs without modifying this script.

    Example project.yml:
        custom:
          my-flag: true
          my-setting: some-value

    Outputs:
        custom-my-flag=true
        custom-my-setting=some-value
        custom-keys=my-flag my-setting  (space-separated list of keys)
    """
    outputs = {}
    custom = data.get("custom", {})

    if not isinstance(custom, dict):
        outputs["custom-keys"] = ""
        return outputs

    keys = []
    for key, value in custom.items():
        output_key = f"custom-{key}"
        outputs[output_key] = to_output_value(value)
        keys.append(key)

    outputs["custom-keys"] = " ".join(keys)
    return outputs


def get_nested(data: dict, *keys) -> Any:
    """Safely get nested dictionary value, returning None if not found."""
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
        if current is None:
            return None
    return current


def to_output_value(value: Any) -> str:
    """Convert a value to string suitable for GITHUB_OUTPUT."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ""
    return str(value)


def read_config(config_path: Path) -> tuple[dict, bool]:
    """Read and parse the project.yml file.

    Returns:
        Tuple of (config_data, config_found)
    """
    if not config_path.exists():
        return {}, False

    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if isinstance(data, dict):
        return data, True
    return {}, True


def extract_outputs(data: dict) -> dict[str, str]:
    """Extract all output values from config data using the field registry."""
    outputs = {}

    for yaml_path, output_name, default, transform in FIELD_REGISTRY:
        # Get value from config
        value = get_nested(data, *yaml_path)

        # Apply default if value is None
        # For boolean fields, we need to check explicitly for None
        # because False is a valid value
        if value is None:
            value = default

        # Apply transform function if provided
        if transform is not None:
            value = transform(value)

        # Convert to output string
        outputs[output_name] = to_output_value(value)

    return outputs


def print_config_summary(outputs: dict[str, str], config_found: bool, config_path: Path) -> None:
    """Print configuration summary to stderr for workflow logs.

    Uses GitHub Actions ::group:: syntax for collapsible output.
    Prints to stderr so it doesn't interfere with GITHUB_OUTPUT on stdout.
    """
    print("::group::Active Configuration (project.yml)", file=sys.stderr)

    if not config_found:
        print(f"  Config file not found: {config_path}", file=sys.stderr)
        print("  Using default values", file=sys.stderr)
    else:
        print(f"  Config file: {config_path}", file=sys.stderr)

    print("", file=sys.stderr)

    # Group outputs by section
    sections = {
        "Maven Build": ["java-versions", "java-version", "enable-snapshot-deploy",
                       "maven-profiles-snapshot", "maven-profiles-release", "npm-cache",
                       "skip-on-docs-only", "paths-ignore-extra"],
        "npm Build": ["npm-node-version", "npm-registry-url"],
        "Sonar": ["sonar-enabled", "sonar-skip-on-dependabot", "sonar-project-key"],
        "Release": ["current-version", "next-version", "create-github-release"],
        "Pages": ["pages-reference", "deploy-site"],
        "Integration Tests": ["it-test-type", "it-maven-module", "it-maven-profiles",
                              "it-timeout-minutes", "it-deploy-reports", "it-reports-subfolder"],
        "Pyprojectx": ["pyprojectx-python-version", "pyprojectx-cache-dependency-glob",
                       "pyprojectx-upload-artifacts-on-failure", "pyprojectx-verify-command"],
        "GitHub Automation": ["auto-merge-build-versions"],
        "Other": ["consumers"],
    }

    for section_name, keys in sections.items():
        section_outputs = {k: v for k, v in outputs.items() if k in keys and v}
        if section_outputs:
            print(f"  [{section_name}]", file=sys.stderr)
            for key, value in section_outputs.items():
                print(f"    {key}: {value}", file=sys.stderr)

    # Print custom fields if any
    custom_keys = outputs.get("custom-keys", "")
    if custom_keys:
        print("  [Custom]", file=sys.stderr)
        for key in custom_keys.split():
            value = outputs.get(f"custom-{key}", "")
            print(f"    {key}: {value}", file=sys.stderr)

    print("::endgroup::", file=sys.stderr)


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
    data, config_found = read_config(config_path)
    outputs = extract_outputs(data)

    # Add custom namespace outputs
    custom_outputs = extract_custom_outputs(data)
    outputs.update(custom_outputs)

    # Print summary to stderr (visible in workflow logs)
    print_config_summary(outputs, config_found, config_path)

    # Output in GITHUB_OUTPUT format (to stdout)
    for key, value in outputs.items():
        print(f"{key}={value}")

    # Output config-found status
    print(f"config-found={'true' if config_found else 'false'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
