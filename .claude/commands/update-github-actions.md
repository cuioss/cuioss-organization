# update-github-actions

Synchronize GitHub Actions workflow files from this organization repository to a target repository.

## Workflow

1. **Select Repository**
   - Invoke the `repo-selection` skill with `$ARGUMENTS`
   - This ensures the local clone exists and is up-to-date
   - Retrieve `repo-name` and `local-path` from the skill output

2. **Identify Caller Templates**
   - List caller templates in this repository: `docs/workflow-examples/*-caller*.yml`
   - These are the workflow files that consumer repos use to call our reusable workflows
   - Templates include SHA-pinned references updated by the release workflow
   - Common templates: `maven-build-caller.yml`, `maven-release-caller.yml`, `pyprojectx-verify-caller.yml`, etc.

3. **Analyze project.yml**
   - Check for `.github/project.yml` in target repo at `{local-path}/.github/project.yml`
   - If exists: validate structure against expected schema
   - Identify missing/outdated fields:
     - Required: `name`, `release.current-version`, `release.next-version`, `sonar.project-key`
     - Optional: `maven-build.*`, `sonar.*`, `pages.*`
   - If missing: prepare to create from template

4. **Compare Workflows**
   - Map caller templates to target workflow names:
     - `maven-build-caller.yml` → `maven.yml` (or `build.yml`)
     - `maven-release-caller.yml` → `release.yml` (check for old name `maven-release.yml`)
     - `scorecards-caller.yml` → `scorecards.yml`
     - `dependency-review-caller.yml` → `dependency-review.yml`
     - `pyprojectx-verify-caller.yml` → `python-verify.yml` (for pyprojectx projects)
   - For each template:
     - Check if corresponding file exists in target repo at `{local-path}/.github/workflows/`
     - Also check for **old naming variants** (e.g., `maven-release.yml` for `release.yml`)
     - If exists, compare content (ignoring file name differences)
     - Identify: new files, modified files, unchanged files, **renamed files**
   - **IMPORTANT - check-changes gate**: The `maven-build-caller.yml` template uses a two-job
     pattern: `check-changes` (gate) → `build`. When comparing, recognize this structure and
     preserve any repo-specific additions to the paths-filter.
   - **IMPORTANT - Rename handling**: When a workflow file needs renaming (e.g., `maven-release.yml` → `release.yml`):
     - Delete the old file: `rm {local-path}/.github/workflows/{old-name}.yml`
     - Create the new file with template content
     - After push, clean up ghost workflow runs from the old file:
       ```
       gh api "repos/cuioss/{repo-name}/actions/workflows" --jq '.workflows[] | select(.path == ".github/workflows/{old-name}.yml") | .id'
       ```
       Then delete all runs for that workflow ID to remove the ghost from the Actions sidebar
     - Note: The new workflow will show as its file path in the Actions sidebar until it has a successful run, at which point GitHub picks up the `name` field from the YAML

5. **Display Diffs**
   - For each workflow that differs or is new:
     - Show the diff (using `diff` command or side-by-side comparison)
     - Indicate whether it's a new file or modification

6. **Update project.yml** (if needed)
   - If project.yml is missing or non-compliant:
     - Use AskUserQuestion: "Create/update project.yml in {repo-name}?"
     - Options: "Yes" / "No"
   - If creating new:
     - Prompt for required values:
       - `release.current-version` - current version from pom.xml or ask user
       - `release.next-version` - derive from current or ask user
       - `sonar.project-key` - typically `cuioss_{repo-name}`
     - Create from template with collected values
   - If updating existing:
     - Preserve existing values
     - Add missing fields with sensible defaults
     - Remove deprecated fields

7. **Confirm Workflow Updates (per file)**
   - For each changed workflow, use AskUserQuestion:
     - "Update {workflow-name}.yml in {repo-name}?"
     - Options: "Yes" / "No" / "Skip all remaining"

8. **Apply Changes**
   - Copy updated workflow files to `{local-path}/.github/workflows/`
   - Write project.yml changes if approved
   - Track which files were modified

9. **Commit and Push**
   - **Skip this step when called from `/setup-consumer-repo`** — the parent orchestrator handles commit/push in its own step
   - If running standalone and files were updated:
     - All cuioss repos have branch protection — cannot push directly to main
     - Create a branch: `git -C {local-path} checkout -b chore/update-github-actions`
     - Stage and commit: `git -C {local-path} add .github/workflows/ .github/project.yml && git -C {local-path} commit -m "chore: update GitHub Actions workflows from cuioss-organization"`
     - Push: `git -C {local-path} push -u origin chore/update-github-actions`
     - Create PR: `gh pr create --repo cuioss/{repo-name} --head chore/update-github-actions --base main --title "chore: update GitHub Actions workflows" --body "..."`
     - Enable auto-merge: `gh pr merge --repo cuioss/{repo-name} --auto --squash --delete-branch`
     - Wait for merge (check every ~60s): `while gh pr view --repo cuioss/{repo-name} --json state -q '.state' | grep -q OPEN; do sleep 60; done`
     - Return to main: `git -C {local-path} checkout main && git -C {local-path} pull`

10. **Update Consumers List**
    - After successful sync, check if `{repo-name}` is in `.github/project.yml` consumers list in cuioss-organization
    - If not present, add it to the `consumers` list
    - **Note**: cuioss-organization has branch protection requiring PRs — cannot push directly to main
    - Create a branch: `git checkout -b chore/add-{repo-name}-consumer`
    - Commit the update: `git add .github/project.yml && git commit -m "chore: add {repo-name} to consumers list"`
    - Push: `git push -u origin chore/add-{repo-name}-consumer`
    - Create PR, enable auto-merge (`gh pr merge --auto --squash --delete-branch`), wait for merge, then switch back to main

## Arguments

- `$ARGUMENTS` - Optional repository name (passed to repo-selection skill)

## Example Usage

```
/update-github-actions                    # Select repo interactively
/update-github-actions cui-java-tools     # Update workflows in cui-java-tools
```

## Caller Templates

Located in this repository at `docs/workflow-examples/`:
- `maven-build-caller.yml` → Target: `maven.yml` - Calls reusable Maven build workflow with path filtering (check-changes gate job)
- `maven-build-caller-custom.yml` → Example with custom options (reference only)
- `maven-release-caller.yml` → Target: `release.yml` - Calls reusable Maven release workflow
- `scorecards-caller.yml` → Target: `scorecards.yml` - Calls reusable Scorecard workflow
- `dependency-review-caller.yml` → Target: `dependency-review.yml` - Calls reusable dependency review workflow
- `pyprojectx-verify-caller.yml` → Target: `python-verify.yml` - Calls reusable pyprojectx verification workflow

These templates contain SHA-pinned references to the reusable workflows, updated automatically by the release workflow.

### Old File Name Mappings

When migrating from legacy inline workflows, watch for these old file names:
- `maven-release.yml` → should become `release.yml`
- `master-build.yml` or `ci.yml` → should become `maven.yml`

## project.yml Template

When creating a new project.yml, use this template:

```yaml
name: {repo-name}
description: {description from pom.xml or repo}

release:
  current-version: {version}
  next-version: {version}-SNAPSHOT
  create-github-release: true  # Creates GitHub Release with auto-generated notes

maven-build:
  java-versions: '["21","25"]'
  java-version: '21'
  enable-snapshot-deploy: true
  maven-profiles-snapshot: 'release-snapshot,javadoc'
  maven-profiles-release: 'release,javadoc'
  npm-cache: false

sonar:
  project-key: cuioss_{repo-name}
  enabled: true
  skip-on-dependabot: true

pages:
  reference: {repo-name}
  deploy-at-release: true

github-automation:
  auto-merge-build-versions: true
  auto-merge-build-timeout: 300
```

## Custom Fields Extension

For most cases, the standard `project.yml` fields are sufficient. However, downstream repos may need repo-specific configuration without modifying the central reusable workflows.

The `custom` namespace allows arbitrary key-value pairs that are passed through as outputs:

```yaml
# In consumer repo's .github/project.yml
name: my-special-repo

# Standard fields
sonar:
  project-key: cuioss_my-special-repo

# Custom fields - no changes to cuioss-organization required
custom:
  skip-e2e: true
  deploy-target: staging
  extra-maven-args: -DskipITs
```

These become outputs prefixed with `custom-`:
- `custom-skip-e2e` → `true`
- `custom-deploy-target` → `staging`
- `custom-extra-maven-args` → `-DskipITs`
- `custom-keys` → `skip-e2e deploy-target extra-maven-args`

**Usage in custom workflow steps:**
```yaml
- run: ./mvnw verify ${{ steps.config.outputs.custom-extra-maven-args }}
  if: steps.config.outputs.custom-skip-e2e != 'true'
```

This approach avoids forking the reusable workflows for minor repo-specific needs.

## Notes

- Caller templates contain SHA-pinned references (e.g., `@ab9c15...# v0.1.0`)
- SHA references are updated automatically when a new release is created
- Target repos should pass explicit secret references (not `secrets: inherit`) to avoid SonarCloud hotspot S7635
- Some workflows may need repo-specific customization (e.g., Java versions, triggers)
- Configuration can be provided via project.yml OR explicit workflow inputs
- See [docs/project-yml-schema.adoc](../../docs/project-yml-schema.adoc) for full schema reference
- See [.github/actions/read-project-config/README.adoc](../../.github/actions/read-project-config/README.adoc) for action details and custom fields

## Critical: maven.yml Branch Patterns and Path Filtering

The `maven.yml` push trigger MUST include `release/*` branches in addition to the standard patterns:

```yaml
on:
  push:
    branches: [main, "feature/*", "fix/*", "chore/*", "release/*", "dependabot/**"]
```

Without `release/*`, release PRs won't get CI checks on push, and branch protection required checks won't be satisfied.

### Path Filtering (check-changes Gate Job)

The template includes a `check-changes` gate job using `dorny/paths-filter` that skips
the build when only documentation or config files changed. This is used instead of
workflow-level `paths-ignore` because `paths-ignore` prevents the workflow from running
entirely, causing required status checks to never report — which blocks PR merges.

With the gate job pattern, skipped jobs report as "skipped" which satisfies branch protection.

The `build` job depends on `check-changes` via:
- `needs: check-changes`
- `if: needs.check-changes.outputs.should-run == 'true'`

The duplicate-prevention condition lives on `check-changes`, not on `build`.

## Repo-Specific Path Ignore Customization

Consumer repos with extra non-code directories can extend the default ignore list in their
`maven.yml`. For example, nifi-extensions has `e-2-e-playwright/docs/` that should be excluded.

When updating workflows, check the target repo for directories that contain only documentation
or non-code assets and add them to the paths-filter. Additional exclusions go in the `code`
filter block:

    code:
      - '!**/*.adoc'
      - '!**/*.md'
      ... (defaults)
      - '!e-2-e-playwright/docs/**'   # repo-specific addition

## Critical: Workflow Naming After File Rename

When a workflow file is renamed (e.g., `maven-release.yml` → `release.yml`), GitHub creates a **new workflow entry**. The new workflow displays as its file path (e.g., `.github/workflows/release.yml`) in the Actions sidebar until it has a **successful run**, at which point GitHub picks up the `name` field from the YAML.

To ensure the display name resolves correctly:
1. The release workflow will naturally get a successful run when the next release is triggered
2. For other workflows, the first push/PR after migration should produce a successful run
3. If the old workflow has ghost entries in the sidebar, delete all its runs:
   ```
   gh api "repos/cuioss/{repo-name}/actions/workflows" --jq '.workflows[] | select(.path | contains("{old-name}")) | .id'
   # Then delete runs for that workflow ID
   ```
