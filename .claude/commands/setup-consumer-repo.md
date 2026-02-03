# setup-consumer-repo

Orchestrate the full setup of a cuioss consumer repository by running all setup commands in sequence, then verify with Scorecard and SonarCloud analysis.

## Arguments

- `$ARGUMENTS` - Optional repository name (passed to repo-selection skill)

## Example Usage

```
/setup-consumer-repo                           # Select repo interactively
/setup-consumer-repo cui-java-tools            # Full setup for cui-java-tools
/setup-consumer-repo cui-java-module-template  # Full setup for template repo
```

## Prerequisites

- `gh` CLI authenticated with admin access
- Python 3.10+ for setup scripts
- Local git configuration for commits

## Workflow

### Phase 1: Setup

1. **Select Repository**
   - Invoke the `repo-selection` skill with `$ARGUMENTS`
   - Retrieve `repo-name` and `local-path` from the skill output

2. **Create Feature Branch**
   - `git -C {local-path} checkout main && git -C {local-path} pull`
   - `git -C {local-path} checkout -b feature/incorporate_cuioss_org`

3. **Run Setup Commands** (in order)

   | # | Command | What it does |
   |---|---------|-------------|
   | a | `/verify-org-integration {repo-name}` | Remove repo-level secrets that should be org-level, delete duplicate community health files |
   | b | `/apply-repo-settings {repo-name}` | Apply features, merge options, security settings |
   | c | `/update-github-actions {repo-name}` | Synchronize workflow files from caller templates, update project.yml |
   | d | `/apply-branch-protection {repo-name}` | Configure branch protection ruleset with status checks and review requirements |

   Follow the interactive prompts for each command.

### Phase 2: PR Workflow

4. **Commit and Push**
   - `git -C {local-path} add -A`
   - `git -C {local-path} commit -m "fix: incorporate cuioss organization settings and workflows"`
   - `git -C {local-path} push -u origin feature/incorporate_cuioss_org`

5. **Create Pull Request**
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

6. **Wait for CI, Merge**
   - Monitor: `gh pr checks --repo cuioss/{repo-name} --watch`
   - If all pass → AskUserQuestion: "All CI checks passed. Merge the PR?" (Options: "Yes, merge" / "No, wait")
   - Merge: `gh pr merge --repo cuioss/{repo-name} --squash --delete-branch`
   - If checks fail: report failures and stop for manual intervention

### Phase 3: Post-Merge Verification

7. **Verify Main Branch CI**
   - Monitor: `gh run list --repo cuioss/{repo-name} --branch main --limit 3`
   - Report final status

8. **Scorecard Analysis**
   - Wait for the Scorecard workflow to complete on main (triggered by the merge push)
   - Fetch all open code-scanning alerts:
     ```
     gh api "repos/cuioss/{repo-name}/code-scanning/alerts?state=open" \
       --jq '.[] | {number, rule: .rule.id, severity: (.rule.security_severity_level // .rule.severity), file: (.most_recent_instance.location.path + ":" + (.most_recent_instance.location.start_line|tostring)), message: .most_recent_instance.message.text, tool: .tool.name}'
     ```
   - Present as summary table, classify each alert (see [Alert Classification](#alert-classification))
   - If any alerts are classified as **Fixed**, create a follow-up fix branch, apply changes, create PR, wait for CI, and merge

9. **SonarCloud Analysis**
   - Project key: `cuioss_{repo-name}` (hyphens preserved, e.g., `cuioss_cui-java-module-template`)
   - **A. Clean up stale SARIF analyses** (from old workflows that uploaded SARIF directly):
     ```
     gh api "repos/cuioss/{repo-name}/code-scanning/analyses" \
       --paginate --jq '[.[] | select(.tool.name == "SonarCloud")] | length'
     ```
     If found, delete each: `gh api -X DELETE "repos/cuioss/{repo-name}/code-scanning/analyses/{id}?confirm_delete=true"`
   - **B. Fetch security hotspots**:
     ```
     gh api "https://sonarcloud.io/api/hotspots/search?projectKey=cuioss_{repo-name}&branch=main" \
       --jq '.hotspots[] | {key, message, component: .component, line, status, rule: .ruleKey, vulnerabilityProbability}'
     ```
   - Present as summary table, classify each hotspot (see [Hotspot Classification](#hotspot-classification))
   - If any hotspots are classified as **Fixed**, create a follow-up fix branch, apply changes, create PR, wait for CI, and merge

10. **Report Final Summary**
    - Present combined results from Scorecard and SonarCloud analyses to the user

## Alert Classification

For Scorecard code-scanning alerts:

| Classification | When to use | Action |
|---------------|-------------|--------|
| **Fixed** | A code change resolves it | Apply the fix |
| **False positive** | Inherent to workflow design (e.g., scorecards needing `security-events: write`) | Document |
| **Org policy** | Requires organizational changes (e.g., branch protection, required reviews) | Note |
| **Will improve** | Improves over time with consistent workflow usage (e.g., SAST coverage, CI test ratio) | Note |
| **Not actionable** | Disproportionate effort for the repo (e.g., fuzzing, OpenSSF badge) | Skip |

## Hotspot Classification

For SonarCloud security hotspots:

| Classification | When to use | Action |
|---------------|-------------|--------|
| **Fixed** | A code change resolves it | Apply the fix |
| **False positive** | Inherent to workflow design (e.g., scorecards requiring `security-events: write`) | Document |
| **Org policy** | Requires organizational changes | Note |
| **Not actionable** | Disproportionate effort for the repo | Skip |

Common fixes:
- `secrets: inherit` (rule `githubactions:S7635`) → replace with explicit secret references matching what the reusable workflow needs
- Missing `permissions` block → add restrictive top-level `permissions: contents: read`
