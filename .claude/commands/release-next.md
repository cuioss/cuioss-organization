# release-next

Trigger a release of cuioss-organization by bumping `current-version` in `project.yml`, merging the PR, and monitoring the release workflow.

## Arguments

- `$ARGUMENTS` - Bump type or explicit version (optional, default: `minor`)
  - Examples: `patch`, `minor`, `major`, `0.6.0`

## Workflow

1. **Read Current Version**
   - Read `.github/project.yml`, extract `release.current-version`
   - Display current version to user

2. **Calculate New Version**
   - Parse `$ARGUMENTS` (default: `minor`)
   - Given current version `X.Y.Z`:
     - `patch` → `X.Y.(Z+1)`
     - `minor` → `X.(Y+1).0`
     - `major` → `(X+1).0.0`
     - Explicit version (e.g., `0.6.0`) → use as-is
   - Display: "Bumping cuioss-organization: {old-version} → {new-version}"

3. **Create Branch, Update, PR**
   - `git checkout main && git pull`
   - `git checkout -b release/{new-version}`
   - Edit `.github/project.yml`: set `release.current-version` to `{new-version}`
   - Verify the edit by reading the file back
   - `git add .github/project.yml`
   - `git commit -m "release: prepare {new-version}"`
   - `git push -u origin release/{new-version}`
   - `gh pr create --title "release: prepare {new-version}" --body "Bump version to {new-version} for release."`
   - `gh pr merge --auto --squash --delete-branch`

4. **Wait for PR Merge**
   - `sleep 120`
   - Check PR state with `gh pr view --json state -q '.state'`
   - If still OPEN, wait 60s and retry (up to 5 retries)
   - If merge fails, report and stop
   - `git checkout main && git pull`

5. **Trigger and Monitor Release Workflow**
   - The release workflow is `workflow_dispatch`: `gh workflow run release.yml --ref main`
   - Wait 15s, then find the run: `gh run list --workflow=release.yml --branch=main --limit 1 --json databaseId,status,conclusion -q '.[0]'`
   - If no run found, wait 30s and retry (up to 3 retries)
   - Watch: `gh run watch {run-id}`

6. **Analyze Release Output**
   - `gh run view {run-id} --json jobs -q '.jobs[] | {name, conclusion, steps: [.steps[] | select(.conclusion != "success" and .conclusion != "skipped") | {name, conclusion}]}'`
   - If any job failed: fetch logs with `gh run view {run-id} --log-failed`, report and stop
   - If all jobs succeeded, report success

7. **Check Consumer PRs**
   - Read `.github/project.yml` → `consumers` list
   - Wait 2 minutes for workflow-reference-update PRs to be created
   - For each consumer, check for open/merged PRs from cuioss-release-bot:
     `gh pr list --repo cuioss/{consumer} --search "author:app/cuioss-release-bot" --json number,title,state -q '.[]'`
   - If any PRs are still OPEN, check their status checks. If a required check failed with an infrastructure error (not a real build failure), re-run it: `gh run rerun {run-id} --repo cuioss/{consumer} --failed`
   - Wait and re-check until all PRs are merged (up to 5 minutes, polling every 30s)

8. **Verify Consumer SHA References**
   - Get the release tag SHA: `git rev-parse v{new-version}^{commit}`
   - For each consumer from the `consumers` list, verify all `.github/workflows/*.yml` files on main reference the correct SHA and version comment:
     - Fetch the file tree: `gh api repos/cuioss/{consumer}/git/trees/main?recursive=1 --jq '.tree[] | select(.path | startswith(".github/workflows/")) | select(.path | endswith(".yml")) | .path'`
     - For each workflow file, fetch content and grep for `cuioss-organization`: `gh api repos/cuioss/{consumer}/contents/{path} --jq '.content' | base64 -d | grep "cuioss-organization"`
     - Every `uses:` reference must contain `@{tag-sha} # v{new-version}`
   - Report mismatches per repo. If a consumer still shows old SHA, its PR likely hasn't merged yet — wait and retry.

9. **Report**
   - Display summary:
     ```
     ## Release Summary: cuioss-organization {new-version}
     - Release workflow: {success/failed} ({run-url})
     - Tag SHA: {tag-sha}
     - Consumer PRs:
       | Consumer | PR | Status | SHA Verified |
       |----------|----|--------|--------------|
       | {consumer} | #{number} | Merged / Open / Not found | OK / MISMATCH |
     ```
   - `git checkout main`

## Important Notes

- **NEVER manually tag or create releases** — always use this workflow so `update-workflow-references.py` runs correctly
- The release workflow is `workflow_dispatch` — it must be triggered explicitly after the version PR merges
- Use parallel Task agents for batch-checking consumer repos to speed up verification
