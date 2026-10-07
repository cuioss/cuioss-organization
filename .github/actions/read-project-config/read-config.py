#!/usr/bin/env python3
"""Read project.yml and output all fields in GITHUB_OUTPUT format.

This script uses a field registry pattern for easy expandability.
Adding a new field requires only one line in FIELD_REGISTRY.

When the calling reusable workflow hands over its inputs (``toJSON(inputs)``,
read from the environment variable named by --caller-inputs-env), each field is
resolved here, once: project.yml if it sets the key, else the caller input
mapped to it, else the registry default. Workflows then read the output as-is
instead of re-implementing that precedence inline.

Usage:
    python3 read-config.py --config .github/project.yml [--caller-inputs-env CALLER_INPUTS]

Output:
    Writes key=value pairs to stdout in GITHUB_OUTPUT format.
"""

import argparse
import json
import os
import re
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


def _sanitize_token_list(value: Any) -> str:
    """Collapse a space-separated token list destined for GITHUB_OUTPUT.

    Values land in GITHUB_OUTPUT as `key=value` lines, so an embedded newline
    would let a crafted project.yml forge additional action outputs. Collapsing
    every whitespace run to a single space closes that: an injected
    `other-output=evil` stays on the same line and becomes an ordinary token.

    Individual tokens are deliberately NOT filtered here. The consuming workflow
    validates each goal against a strict allowlist and fails the run with a clear
    error, which is more useful than silently dropping a mistyped goal and
    building something the caller did not ask for.
    """
    import re

    s = str(value).strip() if value is not None else ""
    return re.sub(r"\s+", " ", s)


def _sanitize_shell_args(value: Any) -> str:
    """Sanitize free-form arguments appended to a shell command.

    Unlike goals, args have no downstream allowlist to catch them, so this is the
    only checkpoint: a value containing anything outside the safe set is dropped
    entirely rather than partially stripped (partial stripping would silently
    rewrite intent). Mirrors _sanitize_shell_value, but permits spaces and '='
    so multiple flag-style arguments remain expressible.
    """
    import re

    s = str(value).strip() if value is not None else ""
    if not s:
        return ""
    tokens = s.split()
    safe_pattern = re.compile(r"^[a-zA-Z0-9_./:,=\-]+$")
    if not all(safe_pattern.match(t) for t in tokens):
        return ""
    return " ".join(tokens)


# A bare consumer entry names a repository in this organisation.
DEFAULT_CONSUMER_OWNER = "cuioss"

# One consumer entry: [<owner>/]<repo>[:<hint>]. The owner follows GitHub's account-name
# rule (alphanumerics and single inner hyphens), the repository its repository-name rule,
# and the hint is a Maven artifactId or property name. Every part ends up in a command
# line or a URL downstream, so nothing outside these sets is admitted.
_CONSUMER_ENTRY_PATTERN = re.compile(
    r"^(?:(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)/)?"
    r"(?P<repo>[A-Za-z0-9._][A-Za-z0-9._-]*)"
    r"(?::(?P<hint>[A-Za-z0-9_.-]+))?$"
)


def parse_consumer_entry(entry: Any) -> dict[str, str]:
    """Split one `consumers` entry into owner, repository and hint.

    This is the single place the consumer syntax is interpreted; the release workflows
    read the parsed form and hand the owner to the propagation scripts as `--org`.

    Args:
        entry: One item of the `consumers` list: `<repo>`, `<owner>/<repo>`, either with
            an optional `:<hint>` suffix.

    Returns:
        `entry`, `owner`, `repo` and `hint` (empty when there is none). A malformed entry
        is returned under the default owner with an `error` naming it, so that the
        propagation reports it instead of the entry vanishing from the run.
    """
    text = str(entry).strip() if entry is not None else ""
    match = _CONSUMER_ENTRY_PATTERN.fullmatch(text)
    if match is None or match.group("repo") in {".", ".."}:
        return {
            "entry": re.sub(r"[^A-Za-z0-9._/:-]", "?", text),
            "owner": DEFAULT_CONSUMER_OWNER,
            "repo": "",
            "hint": "",
            "error": "not a consumer entry of the form [<owner>/]<repo>[:<hint>]",
        }
    return {
        "entry": text,
        "owner": match.group("owner") or DEFAULT_CONSUMER_OWNER,
        "repo": match.group("repo"),
        "hint": match.group("hint") or "",
    }


RELEASE_APP_ID_SECRET = "RELEASE_APP_ID"
RELEASE_APP_PRIVATE_KEY_SECRET = "RELEASE_APP_PRIVATE_KEY"


def release_app_secret_names(owner: str) -> tuple[str, str]:
    """Name the two secrets holding the release App that propagates to `owner`'s consumers.

    cuioss consumers are reached with cuioss-release-bot, whose credentials carry the
    plain names. Every other owner has its OWN private release App, installed only on
    that account, and its credentials are stored in cuioss under the plain names plus a
    suffix derived from the owner: upper-cased, with every character outside `[A-Z0-9]`
    replaced by `_` (`plan-marshall` -> `PLAN_MARSHALL`).

    A foreign owner never resolves to the plain names — its suffix is never empty — so a
    missing foreign secret cannot fall back to the cuioss App.

    Returns:
        `(app-id secret name, private-key secret name)`.
    """
    if owner.lower() == DEFAULT_CONSUMER_OWNER:
        return RELEASE_APP_ID_SECRET, RELEASE_APP_PRIVATE_KEY_SECRET
    suffix = re.sub(r"[^A-Z0-9]", "_", owner.upper())
    return f"{RELEASE_APP_ID_SECRET}_{suffix}", f"{RELEASE_APP_PRIVATE_KEY_SECRET}_{suffix}"


def _consumer_matrix(value: Any) -> str:
    """Group the `consumers` list by owner, as the JSON a job matrix iterates.

    An installation token of a GitHub App is valid for one account, so the release
    workflows run one matrix leg — and mint one token — per owner. Owners keep the order
    of their first entry, consumers the order they are listed in. GitHub account names
    are case-insensitive, so `Plan-Marshall/x` and `plan-marshall/y` share a group.

    Each group also names the two secrets its leg mints that token from (see
    release_app_secret_names), so the workflows index the `secrets` context by them
    instead of deriving the names a second time.

    Returns:
        Compact JSON: `[{"owner", "app-id-secret", "private-key-secret",
        "consumers": [{"entry", "repo", "hint"}, ...]}]`, or `[]` when there are no
        consumers.
    """
    groups: dict[str, dict[str, Any]] = {}
    for item in value if isinstance(value, list) else []:
        parsed = parse_consumer_entry(item)
        owner = parsed.pop("owner")
        if owner.lower() not in groups:
            app_id_secret, private_key_secret = release_app_secret_names(owner)
            groups[owner.lower()] = {
                "owner": owner,
                "app-id-secret": app_id_secret,
                "private-key-secret": private_key_secret,
                "consumers": [],
            }
        group = groups[owner.lower()]
        group["consumers"].append(parsed)
    return json.dumps(list(groups.values()), separators=(",", ":"))


# Field registry: (yaml_path, output_name, default, transform_fn, input_name)
# To add a new field, simply append a tuple to this list
#
# input_name is the reusable-workflow input the field resolves against when the
# caller passes --caller-inputs-env, or None if no workflow input maps to it. The
# mapping is global: an input name must mean the same field in every workflow.
#
# Defaults are the real effective values. A mapped field's default MUST equal the
# `default:` of its workflow input (test_mapped_input_defaults_match_the_registry
# enforces it): a reusable workflow always hands the input over, so there the
# input default applies; the registry default serves callers that pass no
# caller-inputs (direct use of the action, release.yml).
FIELD_REGISTRY: list[tuple[list[str], str, Any, TransformFn, str | None]] = [
    # maven-build section
    (["maven-build", "java-versions"], "java-versions", '["21","25"]', None, "java-versions"),
    (["maven-build", "java-version"], "java-version", "21", None, "java-version"),
    (["maven-build", "enable-snapshot-deploy"], "enable-snapshot-deploy", True, None, "enable-snapshot-deploy"),
    (
        ["maven-build", "maven-profiles-snapshot"],
        "maven-profiles-snapshot",
        "release-snapshot,javadoc",
        None,
        "maven-profiles-snapshot",
    ),
    (["maven-build", "maven-profiles-release"], "maven-profiles-release", "release,javadoc", None, "maven-profiles"),
    (["maven-build", "npm-cache"], "npm-cache", False, None, "npm-cache"),
    (["maven-build", "skip-on-docs-only"], "skip-on-docs-only", True, None, "skip-on-docs-only"),
    (["maven-build", "paths-ignore-extra"], "paths-ignore-extra", [], _sanitize_glob_list, "paths-ignore-extra"),
    (["maven-build", "snapshot-deploy-timeout"], "snapshot-deploy-timeout", 30, None, "snapshot-deploy-timeout"),
    (["maven-build", "build-timeout"], "build-timeout", 45, None, "build-timeout"),
    # sonar section
    (["sonar", "enabled"], "sonar-enabled", True, None, "enable-sonar"),
    (["sonar", "skip-on-dependabot"], "sonar-skip-on-dependabot", True, None, "skip-sonar-on-dependabot"),
    (["sonar", "project-key"], "sonar-project-key", "", None, None),
    # release section
    (["release", "current-version"], "current-version", "", None, None),
    (["release", "next-version"], "next-version", "", None, None),
    (["release", "create-github-release"], "create-github-release", False, None, None),
    # pages section
    (["pages", "reference"], "pages-reference", "", None, None),
    (["pages", "deploy-at-release"], "deploy-site", True, None, "deploy-site"),
    # npm-build section
    (["npm-build", "node-version"], "npm-node-version", "22", None, "node-version"),
    (["npm-build", "registry-url"], "npm-registry-url", "https://registry.npmjs.org", None, None),
    # pyprojectx section
    (["pyprojectx", "python-version"], "pyprojectx-python-version", "", None, "python-version"),
    (
        ["pyprojectx", "cache-dependency-glob"],
        "pyprojectx-cache-dependency-glob",
        "uv.lock",
        None,
        "cache-dependency-glob",
    ),
    (
        ["pyprojectx", "upload-artifacts-on-failure"],
        "pyprojectx-upload-artifacts-on-failure",
        False,
        None,
        "upload-artifacts-on-failure",
    ),
    (["pyprojectx", "verify-goals"], "pyprojectx-verify-goals", "verify", _sanitize_token_list, "verify-goals"),
    (["pyprojectx", "verify-args"], "pyprojectx-verify-args", "", _sanitize_shell_args, "verify-args"),
    # Pre-verify hook: goals run before verify-goals in the same job and workspace,
    # for consumers whose tests assert over generated artifacts. Same sanitizers
    # as their verify-* siblings; the empty default makes the hook a no-op.
    (["pyprojectx", "pre-verify-goals"], "pyprojectx-pre-verify-goals", "", _sanitize_token_list, "pre-verify-goals"),
    (["pyprojectx", "pre-verify-args"], "pyprojectx-pre-verify-args", "", _sanitize_shell_args, "pre-verify-args"),
    # github-automation section
    (["github-automation", "auto-merge-build-versions"], "auto-merge-build-versions", True, None, None),
    # consumers list (special case: transform list to space-separated string)
    (["consumers"], "consumers", [], lambda x: " ".join(x) if isinstance(x, list) else "", None),
    # The same list, parsed and grouped by owner (see _consumer_matrix)
    (["consumers"], "consumer-matrix", [], _consumer_matrix, None),
    # dependency-propagation section
    (["dependency-propagation", "group-id"], "dep-prop-group-id", "", None, None),
    (["dependency-propagation", "artifact-id"], "dep-prop-artifact-id", "", None, None),
    (["dependency-propagation", "scope"], "dep-prop-scope", "parent", None, None),
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


def _normalize_input(value: Any, default: Any) -> Any:
    """Bring a JSON caller-input value into the shape the yaml side would have.

    A list field (e.g. paths-ignore-extra) is a list in project.yml but a
    space-separated string as a workflow input. A number input may arrive as an
    integral float from toJSON; render it as the int the workflow meant.
    """
    if isinstance(default, list) and isinstance(value, str):
        return value.split()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def resolve_fields(data: dict, caller_inputs: dict | None = None) -> dict[str, tuple[str, str]]:
    """Resolve every registry field to (output value, source).

    Precedence: project.yml if it sets the key, else the caller input mapped to
    the field, else the registry default. Source is "project.yml", "input" or
    "default", for the log summary.
    """
    caller_inputs = caller_inputs or {}
    resolved = {}

    for yaml_path, output_name, default, transform, input_name in FIELD_REGISTRY:
        # None means "not set": False is a valid explicit value
        value = get_nested(data, *yaml_path)
        source = "project.yml"
        if value is None and input_name is not None and input_name in caller_inputs:
            value = _normalize_input(caller_inputs[input_name], default)
            source = "input"
        if value is None:
            value = default
            source = "default"

        if transform is not None:
            value = transform(value)

        resolved[output_name] = (to_output_value(value), source)

    return resolved


def extract_outputs(data: dict, caller_inputs: dict | None = None) -> dict[str, str]:
    """Extract all output values from config data using the field registry."""
    return {name: value for name, (value, _) in resolve_fields(data, caller_inputs).items()}


def read_caller_inputs(env_name: str | None) -> dict:
    """Parse the caller's toJSON(inputs) from the named environment variable.

    Unset or empty means "no caller inputs" (direct use of the action). Anything
    else must be a JSON object: a malformed value is an error, never a silent
    fallback to defaults the caller did not ask for.
    """
    raw = os.environ.get(env_name, "") if env_name else ""
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"caller inputs in ${env_name} are not valid JSON: {e}") from e
    if not isinstance(parsed, dict):
        raise ValueError(f"caller inputs in ${env_name} must be a JSON object, got {type(parsed).__name__}")
    return parsed


def check_single_line(outputs: dict[str, str]) -> None:
    """Refuse any value that would span lines in GITHUB_OUTPUT.

    Values are written as `key=value` lines, so an embedded newline would let a
    crafted project.yml or caller input forge additional outputs.
    """
    bad = sorted(k for k, v in outputs.items() if "\n" in v or "\r" in v)
    if bad:
        raise ValueError(f"multi-line values are not allowed in outputs: {', '.join(bad)}")


def print_config_summary(
    outputs: dict[str, str],
    config_found: bool,
    config_path: Path,
    sources: dict[str, str] | None = None,
) -> None:
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
        "Maven Build": [
            "java-versions",
            "java-version",
            "enable-snapshot-deploy",
            "maven-profiles-snapshot",
            "maven-profiles-release",
            "npm-cache",
            "skip-on-docs-only",
            "paths-ignore-extra",
            "snapshot-deploy-timeout",
            "build-timeout",
        ],
        "npm Build": ["npm-node-version", "npm-registry-url"],
        "Sonar": ["sonar-enabled", "sonar-skip-on-dependabot", "sonar-project-key"],
        "Release": ["current-version", "next-version", "create-github-release"],
        "Pages": ["pages-reference", "deploy-site"],
        "Pyprojectx": [
            "pyprojectx-python-version",
            "pyprojectx-cache-dependency-glob",
            "pyprojectx-upload-artifacts-on-failure",
            "pyprojectx-verify-goals",
            "pyprojectx-verify-args",
            "pyprojectx-pre-verify-goals",
            "pyprojectx-pre-verify-args",
        ],
        "GitHub Automation": ["auto-merge-build-versions"],
        "Dependency Propagation": ["dep-prop-group-id", "dep-prop-artifact-id", "dep-prop-scope"],
        "Other": ["consumers", "consumer-matrix"],
    }

    for section_name, keys in sections.items():
        section_outputs = {k: v for k, v in outputs.items() if k in keys and v}
        if section_outputs:
            print(f"  [{section_name}]", file=sys.stderr)
            for key, value in section_outputs.items():
                source = f"  ({sources[key]})" if sources and key in sources else ""
                print(f"    {key}: {value}{source}", file=sys.stderr)

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
    parser = argparse.ArgumentParser(description="Read project.yml and output in GITHUB_OUTPUT format")
    parser.add_argument(
        "--config",
        default=".github/project.yml",
        help="Path to project.yml (default: .github/project.yml)",
    )
    parser.add_argument(
        "--caller-inputs-env",
        default=None,
        help="Name of an environment variable holding the calling workflow's toJSON(inputs)",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    data, config_found = read_config(config_path)
    try:
        caller_inputs = read_caller_inputs(args.caller_inputs_env)
    except ValueError as e:
        print(f"::error::{e}", file=sys.stderr)
        return 2

    resolved = resolve_fields(data, caller_inputs)
    outputs = {name: value for name, (value, _) in resolved.items()}
    sources = {name: source for name, (_, source) in resolved.items()}

    # Add custom namespace outputs
    custom_outputs = extract_custom_outputs(data)
    outputs.update(custom_outputs)

    try:
        check_single_line(outputs)
    except ValueError as e:
        print(f"::error::{e}", file=sys.stderr)
        return 2

    # Print summary to stderr (visible in workflow logs)
    print_config_summary(outputs, config_found, config_path, sources)

    # Output in GITHUB_OUTPUT format (to stdout)
    for key, value in outputs.items():
        print(f"{key}={value}")

    # Output config-found status
    print(f"config-found={'true' if config_found else 'false'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
