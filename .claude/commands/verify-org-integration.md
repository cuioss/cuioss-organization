# verify-org-integration

Verify and fix organization integration for existing cuioss repositories.

Identifies and removes:
- Repo-level secrets that should be org-level (GPG_*, OSS_SONATYPE_*, etc.)
- Duplicate community health files (CODE_OF_CONDUCT.md, CONTRIBUTING.md, SECURITY.md)

Identifies and adds:
- Missing GitHub labels referenced by `.github/dependabot.yml`

Identifies and removes:
- Redundant repo-level `.github/FUNDING.yml` (inherited from org-level `cuioss/.github`)

## Workflow

1. **Select Repository**
   - Use `$ARGUMENTS` as repo name
   - Ensure the local clone exists at `~/git/{repo-name}` and is up-to-date
   - If not exists, clone it: `gh repo clone cuioss/{repo-name} ~/git/{repo-name}`
   - If exists, pull latest: `git -C ~/git/{repo-name} pull`

2. **Preview Issues**
   - Run `./repo-settings/verify-org-integration.py --repo {repo-name} --local-path ~/git/{repo-name} --diff`
   - Parse the JSON output to identify issues

3. **Handle Secrets**
   - If `secrets.action_needed` is true:
     - Display secrets that should be org-level:
       ```
       Repo-level secrets that should be org-level:
       - GPG_PRIVATE_KEY
       - OSS_SONATYPE_USERNAME
       ```
     - AskUserQuestion: "Delete these repo-level secrets? (They will be inherited from the organization)"
     - Options: "Yes, delete all" / "No, keep them"

4. **Handle Duplicate Files**
   - If `community_files.action_needed` is true:
     - AskUserQuestion with multiSelect: "Which duplicate files should be removed? (These are inherited from cuioss/.github)"
     - Options: List each file as an option + "Keep all files"
     - Default recommendation: Select all for removal

5. **Check for `.adoc` Variants of Community Health Files**
   - The Python script only detects `.md` duplicates, but repos may have `.adoc` equivalents that are equally redundant
   - Check for: `SECURITY.adoc`, `CONTRIBUTING.adoc`, `CODE_OF_CONDUCT.adoc` in the repo root
     ```bash
     ls ~/git/{repo-name}/SECURITY.adoc ~/git/{repo-name}/CONTRIBUTING.adoc ~/git/{repo-name}/CODE_OF_CONDUCT.adoc 2>/dev/null
     ```
   - If any are found:
     - AskUserQuestion with multiSelect: "These `.adoc` community health files are redundant (org-level provides `.md` versions). Remove them?"
     - Options: List each file as an option
     - If confirmed, delete the files: `rm ~/git/{repo-name}/{file}`

6. **Remove Redundant FUNDING.yml**
   - Check if `.github/FUNDING.yml` exists in the local repo at `~/git/{repo-name}/.github/FUNDING.yml`
   - If present, remove it — FUNDING.yml is inherited from the org-level `cuioss/.github` repo
   - Note: The sponsor button requires the cuioss GitHub Sponsors listing to be public (configured at https://github.com/sponsors/cuioss/dashboard)

7. **Ensure Dependabot Labels**
   - Check if `.github/dependabot.yml` exists in the local repo at `~/git/{repo-name}/.github/dependabot.yml`
   - If it exists, parse all `labels` entries from every `updates` block
   - Fetch existing labels: `gh label list --repo cuioss/{repo-name} --json name --jq '.[].name'`
   - For each referenced label that doesn't exist, create it:
     - `dependencies`: `gh label create "dependencies" --repo cuioss/{repo-name} --description "Pull requests that update dependencies" --color "0366d6"`
     - `github-actions`: `gh label create "github-actions" --repo cuioss/{repo-name} --description "Pull requests that update GitHub Actions" --color "000000"`
     - `java`: `gh label create "java" --repo cuioss/{repo-name} --description "Pull requests that update Java dependencies" --color "b07219"`
     - For any other label not in the list above, use a neutral color: `gh label create "{label}" --repo cuioss/{repo-name} --color "ededed"`
   - Report which labels were created

8. **Apply Changes**
   - If user confirmed any changes:
     - Build the apply command with the confirmed items:
       ```
       ./repo-settings/verify-org-integration.py --repo {repo-name} --apply \
         --local-path ~/git/{repo-name} \
         --delete-secrets "{comma-separated-secrets}" \
         --remove-files "{comma-separated-files}"
       ```
     - Parse the JSON output for results

9. **Commit & Push** (if files were changed)
   - **Skip this step when called from `/setup-consumer-repo`** — the parent orchestrator handles commit/push in its own step after all sub-commands have run
   - If running standalone and files were removed or added:
     - All cuioss repos have branch protection — cannot push directly to main
     - Create a branch: `git -C ~/git/{repo-name} checkout -b chore/align-org-health-files`
     - Stage and commit: `git -C ~/git/{repo-name} add -A && git -C ~/git/{repo-name} commit -m "chore: align with org-level community health files"`
     - Push: `git -C ~/git/{repo-name} push -u origin chore/align-org-health-files`
     - Create PR: `gh pr create --repo cuioss/{repo-name} --head chore/align-org-health-files --base main --title "chore: align with org-level community health files" --body "..."`
     - Wait for CI: `gh pr checks --repo cuioss/{repo-name} --watch`
     - AskUserQuestion: "Merge the PR?"
     - If yes: `gh pr merge --repo cuioss/{repo-name} --squash --delete-branch`
     - Return to main: `git -C ~/git/{repo-name} checkout main && git -C ~/git/{repo-name} pull`

10. **Report Summary**
   - Display final status:
     ```
     Organization Integration: cuioss/{repo-name}

     Secrets:
       GPG_PRIVATE_KEY deleted (was repo-level, now org-level)
       SONAR_TOKEN deleted (was repo-level, now org-level)

     Community Files:
       CODE_OF_CONDUCT.md removed (using org-level)
       SECURITY.md removed (using org-level)
       CONTRIBUTING.md not present (correct)

     Status: Integration complete
     ```

## Arguments

- `$ARGUMENTS` - Repository name (required)

## Example Usage

```
/verify-org-integration cui-java-tools     # Verify and fix cui-java-tools
/verify-org-integration cui-test-generator # Verify and fix cui-test-generator
```

## Script Location

The verification script is located at: `repo-settings/verify-org-integration.py`

## What Gets Checked

### Secrets Policy
- **Should be org-level** (will be flagged for deletion if found at repo-level):
  - `GPG_PRIVATE_KEY`, `GPG_PASSPHRASE`
  - `OSS_SONATYPE_USERNAME`, `OSS_SONATYPE_PASSWORD`
  - `PAGES_DEPLOY_TOKEN`
  - `RELEASE_APP_ID`, `RELEASE_APP_PRIVATE_KEY`
  - `SONAR_TOKEN`

### Community Health Files
Files inherited from `cuioss/.github` (duplicates will be flagged by script):
- `CODE_OF_CONDUCT.md`
- `CONTRIBUTING.md`
- `SECURITY.md`

**Note**: The script only detects `.md` variants. Step 5 additionally checks for `.adoc` variants:
- `CODE_OF_CONDUCT.adoc`
- `CONTRIBUTING.adoc`
- `SECURITY.adoc`

Files that should remain repo-specific (never flagged):
- `LICENSE`
- `README.md` / `README.adoc`
- `CLAUDE.md`
- `.github/dependabot.yml`

### FUNDING.yml
FUNDING.yml is inherited from the org-level `cuioss/.github` repo. Repo-level copies are redundant and should be removed.
Note: The sponsor button additionally requires the cuioss GitHub Sponsors listing to be public.

### Dependabot Labels
If `.github/dependabot.yml` exists, all labels referenced in `labels` entries must exist on the repo.
Missing labels will be created automatically with predefined colors for known labels (`dependencies`, `github-actions`, `java`).
