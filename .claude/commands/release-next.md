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
   - Ensure the `skip-bot-review` label exists (create if missing, ignore error if it already does): `gh label create skip-bot-review --description "Skip automated bot review" --color ededed 2>/dev/null || true`
   - `gh pr create --title "release: prepare {new-version}" --body "Bump version to {new-version} for release." --label skip-bot-review`
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
   - **Ignore `license/cla` when triaging OPEN PRs — it is expected noise, not a blocker.** The cla-assistant check sits `pending` ("Contributor License Agreement is not signed yet") on *every* cuioss-release-bot PR org-wide, because a GitHub App bot never signs a CLA. It is **not a required check**, so PRs merge with it pending (confirmed: `cui-http`, `plan-marshall`, and others have merged this way). When deciding whether a PR is genuinely blocked vs. still running, filter it out:
     ```
     gh pr checks {pr} --repo cuioss/{consumer} | awk -F'\t' '$2!="pass" && $2!="skipping"' | grep -v 'license/cla'
     ```
     Treating `license/cla` as blocking wastes a full poll cycle making green PRs look stuck — do not wait on it and do not report it as a problem.
   - If any PRs are still OPEN, check their status checks (minus `license/cla`, per above). If a required check failed with an infrastructure error (not a real build failure), re-run it: `gh run rerun {run-id} --repo cuioss/{consumer} --failed`
   - Wait and re-check until all PRs are merged (up to 5 minutes, polling every 30s)
   - **Nudge auto-merge-refused PRs (`UNSTABLE` + auto-merge off):** A PR whose `mergeStateStatus` is `UNSTABLE` with `autoMergeRequest == null`, but whose only non-green check is `license/cla`, is the scenario #192 addressed: the release bot's auto-merge was refused for the unstable status and never re-enabled. It will **not** self-resolve. Merge it directly once its real checks are green:
     ```
     gh pr merge {pr} --repo cuioss/{consumer} --squash --delete-branch
     ```
     If the repo has a merge queue, this reports "already queued to merge" and the PR lands via the queue a few minutes later — poll `state` until `MERGED` rather than re-issuing the merge.
   - **Detect stuck PRs (missing push event):** For any PR still OPEN after polling, check if the `build` check is `SKIPPED` and no `push`-event Maven Build run exists for the branch:
     ```
     gh run list --repo cuioss/{consumer} --branch {head-branch} --json event,name,conclusion -q '.[] | select(.name == "Maven Build" and .event == "push")'
     ```
     If empty (no push-event build), the PR is stuck because GitHub dropped the `push` event — a known transient platform issue. The caller `maven.yml` skips the build on `pull_request` for internal branches (fork-detection `if`), relying on the `push` event which never fired.
   - Collect these stuck PRs separately — do NOT keep retrying, they won't self-resolve.
   - In the final report, list each stuck PR with a direct link so the user can manually trigger the build via `workflow_dispatch` or merge via admin bypass in the GitHub UI

8. **Verify Consumer SHA References**
   - Get the release tag SHA: `git rev-parse v{new-version}^{commit}`
   - For each consumer from the `consumers` list, verify all `.github/workflows/*.yml` files on main reference the correct SHA and version comment:
     - Fetch the file tree: `gh api repos/cuioss/{consumer}/git/trees/main?recursive=1 --jq '.tree[] | select(.path | startswith(".github/workflows/")) | select(.path | endswith(".yml")) | .path'`
     - For each workflow file, fetch content and grep for `cuioss-organization`: `gh api repos/cuioss/{consumer}/contents/{path} --jq '.content' | base64 -d | grep "cuioss-organization"`
     - Every `uses:` reference must contain `@{tag-sha} # v{new-version}`
   - Report mismatches per repo. If a consumer still shows old SHA, its PR likely hasn't merged yet — wait and retry.
   - **Note on the tag SHA:** since #193, the *consumer-facing* ref (what consumers pin) is the **tag** commit, which is one commit *after* the release commit. `git rev-parse v{new-version}^{commit}` returns the correct value to match against. Do not expect it to equal the `release: prepare` commit SHA — the tag deliberately lands on the later `pin internal action references` commit.
   - **Prefer a small Python script over a shell one-liner for this fan-out.** Base64-decoding, regex-matching a SHA, skipping commented `uses:` lines, and running ~21 repos concurrently is fragile as a nested-quoted Bash pipe (it silently produced no output in one run). A `ThreadPoolExecutor` over `gh api` calls that flags any ref whose SHA ≠ the tag SHA is more reliable and easier to read.

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
   - If there are stuck PRs (missing push event), add a separate section:
     ```
     ### Stuck PRs (GitHub dropped push event)
     These PRs need manual intervention — the `push` event never fired so the
     required build checks were never created. Open the link and trigger the
     build via the GitHub UI (Actions → Maven Build → Run workflow → select the PR branch).
     - {consumer}: {pr-url}
     ```
   - `git checkout main`

## Important Notes

- **NEVER manually tag or create releases** — always use this workflow so `update-workflow-references.py` runs correctly
- The release workflow is `workflow_dispatch` — it must be triggered explicitly after the version PR merges
- Use parallel Task agents for batch-checking consumer repos to speed up verification
- **`license/cla` is permanent noise on release-bot PRs** — it is `pending` on every cuioss-release-bot PR (a bot cannot sign a CLA), is not a required check, and never blocks merge. Never wait on it or report it as a problem. If you want it to stop being noise, allowlist `cuioss-release-bot` in cla-assistant — but that is a repo-config change, out of scope for the release itself.
- **A consumer PR may need a manual merge nudge.** When auto-merge is refused for an `UNSTABLE` status (per #192) it does not re-enable; once real checks are green, `gh pr merge --squash` completes it (via the merge queue if the repo has one). This is expected, not a failure of the release.
- **Since #193, the release ships two internal SHAs by design.** The tagged commit pins executed composite-action refs to the *release* commit (so the artifact is fully SHA-pinned); consumer-facing refs point at the *tag*. The release workflow's "Verify commit to be tagged is fully SHA-pinned" step (`workflow-scripts/check-internal-pinning.py`) guards this — if it ever fails, the release stops before tagging and the fix is a sequencing bug, not something to bypass.
