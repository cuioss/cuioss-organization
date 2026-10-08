#!/usr/bin/env python3
"""Validate project.yml against the cuioss organization schema.

Validates .github/project.yml files against schema.json using JSON Schema
Draft 2020-12. Supports validating local files and remote repository
default branches via the GitHub CLI (gh).

Usage:
    # Validate local project.yml
    python3 validate-project-config.py .github/project.yml

    # Validate default branch of remote repositories via gh
    python3 validate-project-config.py --repo API-Sheriff TokenSheriff cui-http

    # Validate against custom schema
    python3 validate-project-config.py --schema custom-schema.json .github/project.yml

Exit code:
    0 if all files/repositories are valid.
    1 if any validation errors, missing files, or schema violations are found.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

try:
    from jsonschema.validators import Draft202012Validator
except ImportError:
    Draft202012Validator = None  # type: ignore[assignment,misc]

DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.json"
EXTRA_PROP_RE = re.compile(r"'([^']+)' was unexpected")


def load_schema(schema_path: Path) -> dict[str, Any]:
    """Load JSON Schema from disk.

    Args:
        schema_path: Path to the schema JSON file.

    Returns:
        Loaded schema dictionary.

    Raises:
        FileNotFoundError: If the schema file does not exist.
        json.JSONDecodeError: If schema contains invalid JSON.
    """
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")
    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)
    if not isinstance(schema, dict):
        raise ValueError(f"Schema must be a JSON object, got {type(schema).__name__}")
    return schema


def format_key_path(base_path: Sequence[str | int], prop: str | None = None) -> str:
    """Format JSON path as dot-separated string."""
    parts = [str(p) for p in base_path]
    if prop:
        parts.append(prop)
    return ".".join(parts) if parts else "(root)"


def validate_project_config(
    content: str | dict[str, Any],
    schema: dict[str, Any],
    source_name: str = "",
) -> list[tuple[str, str]]:
    """Validate project.yml content against schema.json.

    Args:
        content: Raw YAML string or already parsed dictionary.
        schema: Parsed JSON schema dictionary.
        source_name: Label for the input source (e.g., file path or repo name).

    Returns:
        List of (key_path, rule_broken) tuples. Empty list if validation passes.
    """
    violations: list[tuple[str, str]] = []

    if Draft202012Validator is None:
        raise RuntimeError("jsonschema not installed. Run through ./pw or run: pip install jsonschema")

    if isinstance(content, str):
        if yaml is None:
            raise RuntimeError("PyYAML not installed. Run through ./pw or run: pip install pyyaml")
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            return [("(root)", f"YAML parsing error: {exc}")]
    else:
        data = content

    if data is None:
        return [("(root)", "Empty project configuration file")]
    if not isinstance(data, dict):
        return [("(root)", f"Top-level project configuration must be a mapping, got {type(data).__name__}")]

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: (list(e.path), e.message))

    for err in errors:
        base_path = [str(p) for p in err.path]
        if err.validator == "additionalProperties":
            # Extract unexpected property names
            matches = EXTRA_PROP_RE.findall(err.message)
            if matches:
                for unexpected_prop in matches:
                    key_path = format_key_path(base_path, unexpected_prop)
                    violations.append((key_path, f"Unknown key not permitted by schema: {unexpected_prop}"))
            else:
                key_path = format_key_path(base_path)
                violations.append((key_path, err.message))
        elif err.validator == "required":
            match = re.search(r"'([^']+)' is a required property", err.message)
            missing_prop = match.group(1) if match else None
            key_path = format_key_path(base_path, missing_prop)
            violations.append((key_path, f"Required field missing: {missing_prop or err.message}"))
        elif err.validator == "pattern":
            key_path = format_key_path(base_path)
            violations.append((key_path, f"Value '{err.instance}' violates pattern: {err.validator_value}"))
        else:
            key_path = format_key_path(base_path)
            violations.append((key_path, err.message))

    return violations


def fetch_remote_project_config(repo: str, org: str = "cuioss") -> str:
    """Fetch .github/project.yml from remote repository default branch via gh CLI.

    Args:
        repo: Repository name (or org/repo).
        org: Default organization if repo does not specify one.

    Returns:
        Raw content of .github/project.yml.

    Raises:
        RuntimeError: If gh CLI fails or file cannot be fetched.
    """
    full_repo = repo if "/" in repo else f"{org}/{repo}"
    endpoint = f"repos/{full_repo}/contents/.github/project.yml"

    cmd = ["gh", "api", endpoint]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to fetch {endpoint} via gh CLI (exit {result.returncode}): {result.stderr.strip()}")

    try:
        response_json = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON returned by gh api for {full_repo}: {exc}") from exc

    if "content" not in response_json:
        raise RuntimeError(f"No content field in GitHub API response for {full_repo}")

    encoding = response_json.get("encoding", "base64")
    raw_content = response_json["content"]
    if encoding == "base64":
        return base64.b64decode(raw_content).decode("utf-8")
    return str(raw_content)


def main(argv: list[str] | None = None) -> int:
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Validate project.yml against the cuioss organization schema.")
    parser.add_argument(
        "files",
        nargs="*",
        help="Path(s) to project.yml file(s) to validate (default: .github/project.yml if no --repo)",
    )
    parser.add_argument(
        "-c",
        "--config",
        dest="config_path",
        help="Explicit path to a single project.yml file",
    )
    parser.add_argument(
        "-s",
        "--schema",
        dest="schema_path",
        default=str(DEFAULT_SCHEMA_PATH),
        help=f"Path to schema.json (default: {DEFAULT_SCHEMA_PATH})",
    )
    parser.add_argument(
        "--repo",
        "--repos",
        nargs="+",
        dest="repos",
        help="Validate default branch of remote repository/repositories via gh CLI",
    )
    parser.add_argument(
        "--org",
        default="cuioss",
        help="Default organization for remote repos (default: cuioss)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress summary output, printing only errors",
    )

    args = parser.parse_args(argv)

    schema_file = Path(args.schema_path)
    try:
        schema = load_schema(schema_file)
    except Exception as exc:
        print(f"Error loading schema: {exc}", file=sys.stderr)
        return 1

    targets: list[tuple[str, str | Path, bool]] = []  # (display_name, target, is_remote)

    if args.config_path:
        targets.append((args.config_path, Path(args.config_path), False))

    if args.files:
        for f in args.files:
            targets.append((f, Path(f), False))

    if args.repos:
        for r in args.repos:
            targets.append((f"remote:{r}", r, True))

    if not targets:
        # Default fallback
        default_file = Path(".github/project.yml")
        targets.append((str(default_file), default_file, False))

    total_violations = 0
    total_checked = 0

    for display_name, target, is_remote in targets:
        total_checked += 1
        if is_remote:
            repo_name = str(target)
            try:
                content = fetch_remote_project_config(repo_name, org=args.org)
            except Exception as exc:
                print(f"{display_name}: (fetch): {exc}", file=sys.stderr)
                total_violations += 1
                continue
        else:
            file_path = Path(target)
            if not file_path.exists():
                print(f"{display_name}: (file): File does not exist: {file_path}", file=sys.stderr)
                total_violations += 1
                continue
            try:
                content = file_path.read_text(encoding="utf-8")
            except Exception as exc:
                print(f"{display_name}: (read): Failed to read file: {exc}", file=sys.stderr)
                total_violations += 1
                continue

        violations = validate_project_config(content, schema, source_name=display_name)
        if violations:
            for key_path, rule_broken in violations:
                print(f"{display_name}:{key_path}: {rule_broken}")
                total_violations += 1
        else:
            if not args.quiet:
                print(f"{display_name}: OK")

    if total_violations > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
