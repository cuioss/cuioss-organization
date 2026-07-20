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
- `workflow` - Workflow scripts (.github/actions/*, workflow-scripts/*)
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

### Verify Organization Integration
```bash
cd repo-settings
./verify-org-integration.py --repo cui-java-tools --diff   # Show issues
./verify-org-integration.py --repo cui-java-tools --apply  # Apply fixes
```

Checks and fixes:
- Repo-level secrets that should be org-level (GPG_*, OSS_SONATYPE_*, etc.)
- Duplicate community health files (CODE_OF_CONDUCT.md, CONTRIBUTING.md, SECURITY.md)

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
| `reusable-maven-integration-tests.yml` | Integration/E2E tests with optional report deployment |
| `reusable-scorecards.yml` | OpenSSF Scorecard security analysis |
| `reusable-dependency-review.yml` | Dependency vulnerability scanning on PRs |

Caller repos pass explicit secret references (e.g., `SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}`). Organization-level secrets are inherited automatically.

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

**Organization-level** (shared): `RELEASE_APP_ID`, `RELEASE_APP_PRIVATE_KEY`, `OSS_SONATYPE_USERNAME`, `OSS_SONATYPE_PASSWORD`, `GPG_PRIVATE_KEY`, `GPG_PASSPHRASE`, `SONAR_TOKEN`

## Git Workflow

All cuioss repositories have branch protection on `main`. Direct pushes to `main` are never allowed. Always use this workflow:

1. Create a feature branch: `git checkout -b <branch-name>`
2. Commit changes: `git add <files> && git commit -m "<message>"`
3. Push the branch: `git push -u origin <branch-name>`
4. Create a PR: `gh pr create --repo cuioss/<repo> --head <branch-name> --base main --title "<title>" --body "<body>"`
5. Wait for CI + Gemini review (waits until checks complete): `gh pr checks --watch`
6. **Handle Gemini review comments** — fetch with `gh api repos/cuioss/<repo>/pulls/<pr-number>/comments` and for each:
   - If clearly valid and fixable: fix it, commit, push, then reply explaining the fix and resolve the comment
   - If disagree or out of scope: reply explaining why, then resolve the comment
   - If uncertain (not 100% confident): **ask the user** before acting
   - Every comment MUST get a reply (reason for fix or reason for not fixing) and MUST be resolved
7. Do **NOT** enable auto-merge unless explicitly instructed. Wait for user approval.
8. Return to main: `git checkout main && git pull`

This applies to both this repository and all consumer repositories.

## Action Reference Pinning Rules

All `uses:` references in workflows and actions MUST be SHA-pinned with a version comment. Verify every reference before committing.

### Internal references (cuioss/cuioss-organization)

- Must be a full 40-char SHA with a version comment: `@2e471f8bf63cdfef28a2e65a1fca1eff7b24e26b # v0.12.0`
- Never use version tags (`@v0.3.5`) or branch refs (`@main`). A consumer pins us at a SHA; if that commit's own refs are mutable, moving a tag silently changes the code they execute, and OpenSSF Scorecard flags it.
- **Two internal SHAs coexist after a release, by design** — do not "reconcile" them:
  - *Executed* composite-action refs inside `.github/workflows/reusable-*.yml` point at the **release commit**, so that the tagged commit is itself fully pinned. A commit cannot contain its own SHA, so it pins its parent — which holds identical action source.
  - *Consumer-facing* refs (docs, `docs/workflow-examples/`, README, commented usage examples) point at the **release tag**, which is what consumers should pin.
- When adding or modifying an internal `uses:` reference, match the SHA already used by others **of the same kind**.

### External references (e.g., actions/checkout, actions/setup-java)

- Must be SHA-pinned with version comment (e.g., `@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2`)
- When adding a reference to an action already used elsewhere in the repo, use the **same SHA/version** as existing usages — grep first to find it
- When adding a **new** external action (not yet referenced anywhere), look up the latest release SHA before adding: `gh api repos/{owner}/{action}/releases/latest --jq '.tag_name'` then get the SHA for that tag

### Verification

Before committing changes to workflow files, always verify consistency:
- `python3 workflow-scripts/check-internal-pinning.py` — fails if any executed `cuioss-organization` ref in `.github/workflows/` is not a 40-char SHA. Also runs on every PR (`./pw verify workflow`) and blocks the release before tagging.
- `grep -r 'cuioss-organization/' .github/ docs/ --include='*.yml' --include='*.adoc'` — expect at most two SHAs (release commit for executed action refs, tag for consumer-facing refs); anything else is a mistake
- For any external action you touched, grep to confirm the same SHA is used everywhere

## Related Repository

https://github.com/cuioss/.github - Organization-wide community health files (SECURITY.md, CONTRIBUTING.md, issue templates) automatically inherited by all repos.
