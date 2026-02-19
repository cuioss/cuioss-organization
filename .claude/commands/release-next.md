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

5. **Monitor Release Workflow**
   - Find the run: `gh run list --workflow=release.yml --branch=main --limit 1 --json databaseId,status,conclusion -q '.[0]'`
   - If no run found, wait 30s and retry (up to 3 retries)
   - Watch: `gh run watch {run-id}`

6. **Analyze Release Output**
   - `gh run view {run-id} --json jobs -q '.jobs[] | {name, conclusion, steps: [.steps[] | select(.conclusion != "success" and .conclusion != "skipped") | {name, conclusion}]}'`
   - If any job failed: fetch logs with `gh run view {run-id} --log-failed`, report and stop
   - If all jobs succeeded, report success

7. **Check Consumer PRs**
   - Read `.github/project.yml` → `consumers` list
   - Wait 2 minutes for workflow-reference-update PRs to be created
   - For each consumer, check for open PRs from cuioss-release-bot:
     `gh pr list --repo cuioss/{consumer} --search "author:app/cuioss-release-bot" --json number,title,state -q '.[]'`

8. **Report**
   - Display summary:
     ```
     ## Release Summary: cuioss-organization {new-version}
     - Release workflow: {success/failed} ({run-url})
     - Consumer PRs:
       | Consumer | PR | Status |
       |----------|----|--------|
       | {consumer} | #{number} | Merged / Open / Not found |
     ```
   - `git checkout main`

## Important Notes

- **NEVER manually tag or create releases** — always use this workflow so `update-workflow-references.py` runs correctly
- The release workflow is triggered by merging a PR that touches `.github/project.yml`
