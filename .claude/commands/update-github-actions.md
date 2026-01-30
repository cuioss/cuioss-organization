    # update-github-actions

Synchronize GitHub Actions workflow files from this organization repository to a target repository.

## Workflow

1. **Select Repository**
   - Invoke the `repo-selection` skill with `$ARGUMENTS`
   - This ensures the local clone exists and is up-to-date
   - Retrieve `repo-name` and `local-path` from the skill output

2. **Identify Workflow Files**
   - List workflow files in this repository: `.github/workflows/*.yml`
   - These are the source/reference workflows for cuioss repositories
   - Common workflows: `maven-build.yml`, `maven-release.yml`, etc.

3. **Compare Workflows**
   - For each workflow file in this org repo:
     - Check if corresponding file exists in target repo at `{local-path}/.github/workflows/`
     - If exists, compare content
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

## Arguments

- `$ARGUMENTS` - Optional repository name (passed to repo-selection skill)

## Example Usage

```
/update-github-actions                    # Select repo interactively
/update-github-actions cui-java-tools     # Update workflows in cui-java-tools
```

## Source Workflows

Located in this repository at `.github/workflows/`:
- `maven-build.yml` - Multi-version Java build, Sonar analysis, snapshot deploy
- `maven-release.yml` - Release to Maven Central with GPG signing
- `scorecards.yml` - OpenSSF Scorecard security analysis
- `dependency-review.yml` - Dependency vulnerability scanning on PRs

## Notes

- Workflow files are templates that call reusable workflows from this org repo
- Target repos should use `secrets: inherit` to access organization secrets
- Some workflows may need repo-specific customization (e.g., Java versions)
