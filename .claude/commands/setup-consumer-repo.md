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

5. **Check Sidebar Sections**
   - The apply-repo-settings step already checks sidebar sections and emits warnings
   - If warnings mention "Packages" or "Environments" sidebar items:
     - Report the unwanted sections to the user
     - Provide direct link: `https://github.com/cuioss/{repo-name}` → gear icon on About section
     - Note: These toggles have no API and must be changed manually in the web UI

6. **Update GitHub Actions**
   - Run `/update-github-actions {repo-name}`
   - This synchronizes: workflow files from caller templates, project.yml configuration
   - Follow the interactive prompts to confirm each workflow update

7. **Apply Branch Protection**
   - Run `/apply-branch-protection {repo-name}`
   - This configures: branch protection ruleset with status checks and review requirements
   - Follow the interactive prompts to select checks and review count
   - **IMPORTANT**: Since workflows were just changed from inline to reusable callers in step 6, the check names reported by `--list-checks` will be the OLD names (e.g., `build (21)`, `sonar-build`). The reusable workflow produces PREFIXED names: `build / build (21)`, `build / build (25)`, `build / sonar-build`. Use the prefixed names to avoid the PR being unmergeable in step 11.

8. **Update CLAUDE.md Git Workflow**
   - Check if `{local-path}/CLAUDE.md` exists
   - If it exists, check if it contains a `## Git Workflow` section
     - If the section exists, replace it with the standard cuioss Git Workflow:
       ```
       ## Git Workflow

       All cuioss repositories have branch protection on `main`. Direct pushes to `main` are never allowed. Always use this workflow:

       1. Create a feature branch: `git checkout -b <branch-name>`
       2. Commit changes: `git add <files> && git commit -m "<message>"`
       3. Push the branch: `git push -u origin <branch-name>`
       4. Create a PR: `gh pr create --repo cuioss/{repo-name} --head <branch-name> --base main --title "<title>" --body "<body>"`
       5. Wait for CI + Gemini review (waits until checks complete): `gh pr checks --repo cuioss/{repo-name} <pr-number> --watch`
       6. **Handle Gemini review comments** — fetch with `gh api repos/cuioss/{repo-name}/pulls/<pr-number>/comments` and for each:
          - If clearly valid and fixable: fix it, commit, push, then reply explaining the fix and resolve the comment
          - If disagree or out of scope: reply explaining why, then resolve the comment
          - If uncertain (not 100% confident): **ask the user** before acting
          - Every comment MUST get a reply (reason for fix or reason for not fixing) and MUST be resolved
       7. Do **NOT** enable auto-merge unless explicitly instructed. Wait for user approval.
       8. Return to main: `git checkout main && git pull`
       ```
     - If the section does NOT exist, append it before the last section or at the end of the file
   - If CLAUDE.md does not exist, skip this step (CLAUDE.md is repo-specific and should not be created by this command)

9. **Commit and Push**
   - In the target repo at `{local-path}`:
     - Stage all changes: `git -C {local-path} add -A`
     - Commit: `git -C {local-path} commit -m "fix: incorporate cuioss organization settings and workflows"`
     - Push: `git -C {local-path} push -u origin feature/incorporate_cuioss_org`

9. **Create Pull Request**
   - Create PR using gh CLI (must specify `--head` and `--base` explicitly):
     ```
     gh pr create --repo cuioss/{repo-name} \
       --head feature/incorporate_cuioss_org \
       --base main \
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

10. **Enable Auto-Merge**
   - Enable auto-merge: `gh pr merge --repo cuioss/{repo-name} --auto --squash --delete-branch`
   - Wait for merge (check every ~60s): `while gh pr view --repo cuioss/{repo-name} --json state -q '.state' | grep -q OPEN; do sleep 60; done`
   - If checks fail and auto-merge is cancelled: report failures and stop for manual intervention

11. **Post-Merge Verification**
    - Wait for main branch CI to trigger
    - Monitor: `gh run list --repo cuioss/{repo-name} --branch main --limit 3`
    - Report final status

12. **Update Consumers List**
    - In the cuioss-organization repo, update `.github/project.yml`:
      - Check if `{repo-name}` is already in the `consumers` list
      - If not present, add it to the `consumers` list
      - **Note**: cuioss-organization has branch protection requiring PRs — cannot push directly to main
      - Create a branch: `git checkout -b chore/add-{repo-name}-consumer`
      - Commit: `git add .github/project.yml && git commit -m "chore: add {repo-name} to consumers list"`
      - Push: `git push -u origin chore/add-{repo-name}-consumer`
      - Create PR: `gh pr create --repo cuioss/cuioss-organization --title "chore: add {repo-name} to consumers list" --body "Add {repo-name} to consumers list after workflow migration"`
      - Enable auto-merge: `gh pr merge --repo cuioss/cuioss-organization --auto --squash --delete-branch`
      - Wait for merge: `while gh pr view --repo cuioss/cuioss-organization --json state -q '.state' | grep -q OPEN; do sleep 60; done`
      - Switch back: `git checkout main && git pull`

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
    - **Auto-dismiss known false positives**:
      - After presenting the scorecard table, automatically dismiss alerts that are inherent to the cuioss workflow design:
        - `TokenPermissionsID` on `scorecards.yml` (line containing `security-events: write`) — the Scorecard action requires this permission to upload SARIF results. This is a [known Scorecard limitation](https://github.com/ossf/scorecard/issues/4762).
      - For each matching alert:
        ```
        gh api --method PATCH \
          "repos/cuioss/{repo-name}/code-scanning/alerts/{alert-number}" \
          -f state='dismissed' \
          -f dismissed_reason='false positive' \
          -f dismissed_comment='security-events:write is required by the Scorecard action to upload SARIF results. Known limitation: ossf/scorecard#4762'
        ```
      - Report dismissed alerts in the summary table with classification "Auto-dismissed (false positive)"
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

15. **CodeQL Cleanup**
    - Check for stale CodeQL analyses from previous default setup or manual configurations:
      ```
      gh api "repos/cuioss/{repo-name}/code-scanning/analyses?tool_name=CodeQL&per_page=100" \
        --paginate --jq 'length'
      ```
    - If stale CodeQL analyses exist:
      - SonarCloud already covers Java security analysis, so CodeQL is redundant for cuioss Java repos
      - Delete all stale analyses:
        ```
        gh api "repos/cuioss/{repo-name}/code-scanning/analyses?tool_name=CodeQL&per_page=100" \
          --paginate --jq '.[].id' | while read id; do
          gh api -X DELETE "repos/cuioss/{repo-name}/code-scanning/analyses/$id?confirm_delete=true"
        done
        ```
      - Report how many were cleaned up
    - If no CodeQL analyses exist, skip this step

16. **Ghost Workflow Cleanup**
    - Check for ghost workflow entries from renamed or deleted workflow files:
      ```
      gh api "repos/cuioss/{repo-name}/actions/workflows" \
        --jq '.workflows[] | select(.state == "disabled_manually" or .path == null or (.name | test("^[.]github"))) | {id, name, path, state}'
      ```
    - Also check for old workflow names that were replaced during migration:
      - `maven-release.yml` (replaced by `release.yml`)
      - `master-build.yml` or `ci.yml` (replaced by `maven.yml`)
    - For each ghost workflow found:
      - Delete all its runs:
        ```
        gh api "repos/cuioss/{repo-name}/actions/workflows/{workflow_id}/runs" \
          --paginate --jq '.workflow_runs[].id' | while read run_id; do
          gh api -X DELETE "repos/cuioss/{repo-name}/actions/runs/$run_id"
        done
        ```
      - Report which ghost workflows were cleaned up
    - If no ghost workflows exist, skip this step

## Arguments

- `$ARGUMENTS` - Optional repository name (passed to repo-selection skill)

## Example Usage

```
/setup-consumer-repo                        # Select repo interactively
/setup-consumer-repo cui-java-tools         # Full setup for cui-java-tools
/setup-consumer-repo cui-java-module-template  # Full setup for template repo
```

## GitHub Automation Configuration

Consumer repos can configure auto-merge behavior for workflow update PRs in their `.github/project.yml`:

```yaml
github-automation:
  auto-merge-build-versions: true   # Auto-merge when CI passes (default: true)
```

When auto-merge is enabled, the release workflow uses `gh pr merge --auto --squash --delete-branch` to enable GitHub's native auto-merge. GitHub merges automatically once all required status checks pass. If checks fail, the PR is left open for manual review.

## Prerequisites

- `gh` CLI authenticated with admin access
- Python 3.10+ for setup scripts
- Local git configuration for commits
