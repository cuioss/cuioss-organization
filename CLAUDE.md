# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Purpose

This is the cuioss organization infrastructure repository containing:
- Reusable GitHub Actions workflows for Maven builds and releases
- Scripts to apply consistent repository settings and branch protection across all cuioss repos
- Documentation for the cuioss-release-bot GitHub App and secrets management

## Key Commands

### Python Build (pyprojectx)

```bash
# Full verification (compile + quality-gate + tests)
./pw verify

# Individual commands
./pw compile          # mypy type checking
./pw quality-gate     # ruff linting
./pw test             # pytest execution
./pw clean            # Remove build artifacts

# Module filtering
./pw verify workflow      # Verify workflow module only
./pw test repo-admin      # Test repo-admin module only
```

Modules:
- `workflow` - Workflow scripts (.github/actions/*, scripts/*)
- `repo-admin` - Repository admin scripts (repo-settings/*, branch-protection/*)

### Apply Repository Settings
```bash
cd repo-settings
./setup-repo-settings.py              # Uses config.json by default
./setup-repo-settings.py custom.json  # Use custom config
```

### Apply Branch Protection Rulesets
```bash
cd branch-protection
./setup-branch-protection.py              # Uses config.json by default
./setup-branch-protection.py custom.json  # Use custom config
```

### Prerequisites
Both scripts require:
- Python 3.10+
- `gh` CLI authenticated with admin access

```bash
gh auth login
```

### Verify Settings After Running Scripts
```bash
# Check vulnerability reporting
gh api repos/cuioss/<repo>/private-vulnerability-reporting

# Check repo settings
gh api repos/cuioss/<repo> --jq '{has_issues, has_wiki, delete_branch_on_merge}'
```

## Architecture

### Reusable Workflows (`.github/workflows/`)

Centralized workflows called by individual cuioss repositories:

| Workflow | Purpose |
|----------|---------|
| `reusable-maven-build.yml` | Multi-version Java build, Sonar analysis, snapshot deploy |
| `reusable-maven-release.yml` | Release to Maven Central with GPG signing |
| `reusable-scorecards.yml` | OpenSSF Scorecard security analysis |
| `reusable-dependency-review.yml` | Dependency vulnerability scanning on PRs |

Caller repos use `secrets: inherit` to access organization-level secrets.

### Configuration Scripts

| Directory | Purpose |
|-----------|---------|
| `repo-settings/` | Applies security, features, and merge settings via GitHub API |
| `branch-protection/` | Creates/updates branch protection rulesets with cuioss-release-bot bypass |

Both use `config.json` to define:
- Target repositories list
- Settings to apply
- Bypass actors (for rulesets)

### Secrets Model

**Organization-level** (shared): `RELEASE_APP_ID`, `RELEASE_APP_PRIVATE_KEY`, `OSS_SONATYPE_USERNAME`, `OSS_SONATYPE_PASSWORD`, `GPG_PRIVATE_KEY`, `GPG_PASSPHRASE`, `PAGES_DEPLOY_TOKEN`

**Repository-level** (per-repo): `SONAR_TOKEN`

## Related Repository

https://github.com/cuioss/.github - Organization-wide community health files (SECURITY.md, CONTRIBUTING.md, issue templates) automatically inherited by all repos.
