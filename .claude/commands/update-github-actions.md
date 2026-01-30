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

3. **Compare Workflows**
   - Map caller templates to target workflow names:
     - `maven-build-caller.yml` → `maven.yml` (or `build.yml`)
     - `maven-release-caller.yml` → `release.yml`
     - `scorecards-caller.yml` → `scorecards.yml`
     - `dependency-review-caller.yml` → `dependency-review.yml`
   - For each template:
     - Check if corresponding file exists in target repo at `{local-path}/.github/workflows/`
     - If exists, compare content (ignoring file name differences)
     - Identify: new files, modified files, unchanged files

4. **Display Diffs**
   - For each workflow that differs or is new:
     - Show the diff (using `diff` command or side-by-side comparison)
     - Indicate whether it's a new file or modification

5. **Confirm Updates (per file)**
   - For each changed workflow, use AskUserQuestion:
     - "Update {workflow-name}.yml in {repo-name}?"
     - Options: "Yes" / "No" / "Skip all remaining"

6. **Apply Changes**
   - Copy updated workflow files to `{local-path}/.github/workflows/`
   - Track which files were modified

7. **Commit and Push**
   - If any files were updated, use AskUserQuestion:
     - "Commit and push workflow updates to {repo-name}?"
     - Options: "Yes, commit and push" / "No, keep local changes only"
   - If confirmed:
     - `git -C {local-path} add .github/workflows/`
     - `git -C {local-path} commit -m "chore: update GitHub Actions workflows from cuioss-organization"`
     - `git -C {local-path} push`

8. **Update Consumers List**
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

## Notes

- Caller templates contain SHA-pinned references (e.g., `@ab9c15...# v0.1.0`)
- SHA references are updated automatically when a new release is created
- Target repos should use `secrets: inherit` to access organization secrets
- Some workflows may need repo-specific customization (e.g., Java versions, triggers)
