# verify-org-integration

Verify and fix organization integration for existing cuioss repositories.

Identifies and removes:
- Repo-level secrets that should be org-level (GPG_*, OSS_SONATYPE_*, etc.)
- Duplicate community health files (CODE_OF_CONDUCT.md, CONTRIBUTING.md, SECURITY.md)

Identifies and adds:
- Missing `.github/FUNDING.yml` for template repositories (these don't inherit from org `.github` repo)

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

5. **Ensure FUNDING.yml for Template Repos**
   - Check if the repo is a template: `gh api repos/cuioss/{repo-name} --jq '.is_template'`
   - If `true`, check if `.github/FUNDING.yml` exists in the local repo at `~/git/{repo-name}/.github/FUNDING.yml`
   - If missing, create it with content `github: cuioss`
   - Template repos don't inherit community health files (including FUNDING.yml) from the org `.github` repo, so this must be added explicitly

6. **Apply Changes**
   - If user confirmed any changes:
     - Build the apply command with the confirmed items:
       ```
       ./repo-settings/verify-org-integration.py --repo {repo-name} --apply \
         --local-path ~/git/{repo-name} \
         --delete-secrets "{comma-separated-secrets}" \
         --remove-files "{comma-separated-files}"
       ```
     - Parse the JSON output for results

7. **Commit & Push** (if files were changed)
   - If files were removed or added, in the local repo directory:
     - `git -C ~/git/{repo-name} add -A`
     - `git -C ~/git/{repo-name} commit -m "chore: align with org-level community health files"`
   - AskUserQuestion: "Push changes to remote?"
   - If yes: `git -C ~/git/{repo-name} push`

8. **Report Summary**
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
Files inherited from `cuioss/.github` (duplicates will be flagged):
- `CODE_OF_CONDUCT.md`
- `CONTRIBUTING.md`
- `SECURITY.md`

Files that should remain repo-specific (never flagged):
- `LICENSE`
- `README.md` / `README.adoc`
- `CLAUDE.md`
- `.github/dependabot.yml`

### FUNDING.yml (Template Repos Only)
Template repositories (`is_template: true`) don't inherit community health files from the org `.github` repo.
If `.github/FUNDING.yml` is missing, it will be created with `github: cuioss`.
