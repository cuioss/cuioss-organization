# update-github-actions

Synchronize GitHub Actions workflow files from this organization repository to a target repository.

## Workflow

1. **Select Repository**
   - Invoke the `repo-selection` skill with `$ARGUMENTS`
   - This ensures the local clone exists and is up-to-date
   - Retrieve `repo-name` and `local-path` from the skill output

2. **Identify Caller Templates**
   - List caller templates in this repository: `.github/workflows/examples/*-caller*.yml`
   - These are the workflow files that consumer repos use to call our reusable workflows
   - Templates include SHA-pinned references updated by the release workflow
   - Common templates: `maven-build-caller.yml`, `maven-release-caller.yml`, etc.

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
     - `maven-release-caller.yml` → `release.yml`
     - `scorecards-caller.yml` → `scorecards.yml`
     - `dependency-review-caller.yml` → `dependency-review.yml`
   - For each template:
     - Check if corresponding file exists in target repo at `{local-path}/.github/workflows/`
     - If exists, compare content (ignoring file name differences)
     - Identify: new files, modified files, unchanged files

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
   - If any files were updated, use AskUserQuestion:
     - "Commit and push workflow updates to {repo-name}?"
     - Options: "Yes, commit and push" / "No, keep local changes only"
   - If confirmed:
     - `git -C {local-path} add .github/workflows/ .github/project.yml`
     - `git -C {local-path} commit -m "chore: update GitHub Actions workflows from cuioss-organization"`
     - `git -C {local-path} push`

10. **Update Consumers List**
    - After successful sync, check if `{repo-name}` is in `.github/project.yml` consumers list
    - If not present, add it to the `consumers` list
    - Commit the update: `git add .github/project.yml && git commit -m "chore: add {repo-name} to consumers list"`
    - Push the change

## Arguments

- `$ARGUMENTS` - Optional repository name (passed to repo-selection skill)

## Example Usage

```
/update-github-actions                    # Select repo interactively
/update-github-actions cui-java-tools     # Update workflows in cui-java-tools
```

## Caller Templates

Located in this repository at `.github/workflows/examples/`:
- `maven-build-caller.yml` → Target: `maven.yml` - Calls reusable Maven build workflow
- `maven-build-caller-custom.yml` → Example with custom options (reference only)
- `maven-release-caller.yml` → Target: `release.yml` - Calls reusable Maven release workflow
- `scorecards-caller.yml` → Target: `scorecards.yml` - Calls reusable Scorecard workflow
- `dependency-review-caller.yml` → Target: `dependency-review.yml` - Calls reusable dependency review workflow

These templates contain SHA-pinned references to the reusable workflows, updated automatically by the release workflow.

## project.yml Template

When creating a new project.yml, use this template:

```yaml
name: {repo-name}
description: {description from pom.xml or repo}

release:
  current-version: {version}
  next-version: {version}-SNAPSHOT
  generate-release-notes: false

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
- Target repos should use `secrets: inherit` to access organization secrets
- Some workflows may need repo-specific customization (e.g., Java versions, triggers)
- Configuration can be provided via project.yml OR explicit workflow inputs
- See [docs/project-yml-schema.adoc](../../docs/project-yml-schema.adoc) for full schema reference
- See [.github/actions/read-project-config/README.md](../../.github/actions/read-project-config/README.md) for action details and custom fields
