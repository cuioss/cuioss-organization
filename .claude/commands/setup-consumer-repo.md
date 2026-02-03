# setup-consumer-repo

Orchestrate the full setup of a cuioss consumer repository by running all four setup commands in sequence.

## Workflow

1. **Select Repository**
   - Invoke the `repo-selection` skill with `$ARGUMENTS`
   - This ensures the local clone exists and is up-to-date
   - Retrieve `repo-name` and `local-path` from the skill output

2. **Create Feature Branch**
   - In the target repo at `{local-path}`:
     - `git -C {local-path} checkout main && git -C {local-path} pull`
     - `git -C {local-path} checkout -b feature/incorporate_cuioss_org`

3. **Verify Organization Integration**
   - Run `/verify-org-integration {repo-name}`
   - This checks and fixes: repo-level secrets that should be org-level, duplicate community health files
   - Follow the interactive prompts to confirm deletions

4. **Apply Repository Settings**
   - Run `/apply-repo-settings {repo-name}`
   - This applies: features, merge options, security settings
   - Follow the interactive prompts to confirm changes

5. **Update GitHub Actions**
   - Run `/update-github-actions {repo-name}`
   - This synchronizes: workflow files from caller templates, project.yml configuration
   - Follow the interactive prompts to confirm each workflow update

6. **Apply Branch Protection**
   - Run `/apply-branch-protection {repo-name}`
   - This configures: branch protection ruleset with status checks and review requirements
   - Follow the interactive prompts to select checks and review count

7. **Commit and Push**
   - In the target repo at `{local-path}`:
     - Stage all changes: `git -C {local-path} add -A`
     - Commit: `git -C {local-path} commit -m "fix: incorporate cuioss organization settings and workflows"`
     - Push: `git -C {local-path} push -u origin feature/incorporate_cuioss_org`

8. **Create Pull Request**
   - Create PR using gh CLI:
     ```
     gh pr create --repo cuioss/{repo-name} \
       --title "fix: incorporate cuioss organization settings and workflows" \
       --body "## Summary
     - Updated GitHub Actions workflows from cuioss-organization templates
     - Added scorecards permissions for supply-chain security
     - Updated project configuration for org-level secrets

     ## Changes Applied
     - verify-org-integration: cleaned up repo-level secrets and duplicate files
     - apply-repo-settings: applied standard repository settings
     - update-github-actions: synchronized workflow files from organization templates
     - apply-branch-protection: configured branch protection rulesets"
     ```

9. **Wait for CI**
   - Monitor PR checks: `gh pr checks --repo cuioss/{repo-name} --watch`
   - Report status of each check

10. **Merge PR**
    - If all checks pass:
      - AskUserQuestion: "All CI checks passed. Merge the PR?"
      - Options: "Yes, merge" / "No, wait"
    - If confirmed: `gh pr merge --repo cuioss/{repo-name} --squash --delete-branch`
    - If checks fail: report failures and stop for manual intervention

11. **Post-Merge Verification**
    - Wait for main branch CI to trigger
    - Monitor: `gh run list --repo cuioss/{repo-name} --branch main --limit 3`
    - Report final status

## Arguments

- `$ARGUMENTS` - Optional repository name (passed to repo-selection skill)

## Example Usage

```
/setup-consumer-repo                        # Select repo interactively
/setup-consumer-repo cui-java-tools         # Full setup for cui-java-tools
/setup-consumer-repo cui-java-module-template  # Full setup for template repo
```

## Prerequisites

- `gh` CLI authenticated with admin access
- Python 3.10+ for setup scripts
- Local git configuration for commits
