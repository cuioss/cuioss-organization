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

12. **Update Consumers List**
    - In the cuioss-organization repo, update `.github/project.yml`:
      - Check if `{repo-name}` is already in the `consumers` list
      - If not present, add it to the `consumers` list
      - Commit: `git add .github/project.yml && git commit -m "chore: add {repo-name} to consumers list"`
      - Push: `git push`

13. **Scorecard Analysis**
    - Wait for the Scorecard workflow to complete on main (triggered by the merge push)
    - If scorecards didn't trigger automatically, note that it runs on schedule or `push` to main
    - Fetch all open code-scanning alerts:
      ```
      gh api "repos/cuioss/{repo-name}/code-scanning/alerts?state=open" \
        --jq '.[] | {number, rule: .rule.id, severity: (.rule.security_severity_level // .rule.severity), file: (.most_recent_instance.location.path + ":" + (.most_recent_instance.location.start_line|tostring)), message: .most_recent_instance.message.text, tool: .tool.name}'
      ```
    - Present results as a summary table with actionability assessment:

      ```
      ## Scorecard Analysis: cuioss/{repo-name}

      | # | Alert | Severity | Actionable | Details |
      |---|-------|----------|------------|---------|
      | N | AlertID | high/medium/low | Fixed / False positive / Org policy / Will improve / Not actionable | Description |
      ```

    - For each alert, classify as:
      - **Fixed**: If there's a code change that resolves it — apply the fix
      - **False positive**: If the alert is inherent to the workflow design (e.g., scorecards needing `security-events: write`)
      - **Org policy**: If it requires organizational changes (e.g., branch protection, required reviews)
      - **Will improve**: If it improves over time with consistent workflow usage (e.g., SAST coverage, CI test ratio)
      - **Not actionable**: If it requires effort disproportionate to the repo (e.g., fuzzing, OpenSSF badge)
    - If any alerts are classified as **Fixed**, create a follow-up fix branch, apply changes, create PR, wait for CI, and merge
    - Report the final table to the user

14. **SonarCloud Analysis**
    - Determine the SonarCloud project key (typically `cuioss_{repo-name}` with hyphens preserved, e.g., `cuioss_cui-java-module-template`)
    - **A. Clean up stale SARIF analyses**:
      - Fetch all code-scanning analyses for the SonarCloud tool:
        ```
        gh api "repos/cuioss/{repo-name}/code-scanning/analyses" \
          --paginate --jq '[.[] | select(.tool.name == "SonarCloud")] | length'
        ```
      - If stale SonarCloud SARIF analyses exist (from old workflows that uploaded SARIF directly instead of using the reusable workflow which reports to SonarCloud natively):
        - List them: `gh api "repos/cuioss/{repo-name}/code-scanning/analyses" --paginate --jq '.[] | select(.tool.name == "SonarCloud") | {id, created_at, ref}'`
        - Delete each: `gh api -X DELETE "repos/cuioss/{repo-name}/code-scanning/analyses/{id}?confirm_delete=true"`
        - Report how many were cleaned up

    - **B. Fetch SonarCloud security hotspots**:
      ```
      gh api "https://sonarcloud.io/api/hotspots/search?projectKey=cuioss_{repo-name}&branch=main" \
        --jq '.hotspots[] | {key, message, component: .component, line, status, rule: .ruleKey, vulnerabilityProbability}'
      ```
    - **C. Present results as a summary table**:

      ```
      ## SonarCloud Analysis: cuioss/{repo-name}

      ### Stale Analyses
      Deleted N stale SonarCloud SARIF analyses from GitHub code scanning.

      ### Security Hotspots
      | # | Rule | Severity | File | Status | Actionable | Details |
      |---|------|----------|------|--------|------------|---------|
      | N | ruleKey | HIGH/MEDIUM/LOW | file:line | TO_REVIEW/REVIEWED | Classification | Description |
      ```

    - **D. For each hotspot, classify as**:
      - **Fixed**: If there's a code change that resolves it — apply the fix
        - Common fix: `secrets: inherit` (rule `githubactions:S7635`) → replace with explicit secret references matching what the reusable workflow needs
        - Common fix: Missing `permissions` block → add restrictive top-level permissions
      - **False positive**: If the hotspot is inherent to the workflow design (e.g., scorecards requiring `security-events: write`)
      - **Org policy**: If it requires organizational changes
      - **Not actionable**: If it requires effort disproportionate to the repo
    - If any hotspots are classified as **Fixed**, create a follow-up fix branch, apply changes, create PR, wait for CI, and merge
    - Report the final table to the user

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
