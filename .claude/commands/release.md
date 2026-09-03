# release

Trigger a release of cuioss-organization by bumping `current-version` in `project.yml`, merging the PR, and monitoring the release workflow.

## Arguments

- `$ARGUMENTS` - Bump type or explicit version (optional, default: `minor`)
  - Examples: `patch`, `minor`, `major`, `X.Y.Z`

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
     - Explicit version (e.g., `X.Y.Z`) → use as-is
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
   - Wait and re-check until all PRs are merged (poll every 45s for up to 20 minutes — see the CI-duration table below; 5 minutes is far too short for the integration/e2e consumers)
   - **Do NOT diagnose a stuck PR from `mergeStateStatus` + `autoMergeRequest`.** `UNSTABLE` + `autoMergeRequest == null` is **not** evidence that auto-merge was refused. That exact pair is also what a perfectly healthy PR reports while it is mid-flight, and — critically — what a PR reports once it has **entered a merge queue**, because entering the queue consumes the auto-merge request and nulls the field. In the v0.22.0 release every consumer PR passed through this state and every one of them merged on its own; reading it as the #192 scenario produced a false diagnosis and a pointless escalation to the user.
   - **Give CI time before concluding anything.** Consumers differ by ~5x in wall-clock because of which extra workflows they run. Measured at v0.22.0:

     | Consumer profile | Extra workflows | Slowest check |
     |------------------|-----------------|---------------|
     | build-only (most repos, e.g. `cui-java-tools`, `cui-http`) | CodeQL | ~2 min |
     | `nifi-extensions` | `integration-tests`, `e2e-tests` | ~11 min |
     | `TokenSheriff` | `integration-tests`, `e2e-tests`, JMH benchmarks | ~9 min + JMH |
     | `API-Sheriff` | `integration-tests` | **~15 min** |

     Poll for at least **20 minutes** before treating any PR as needing intervention. A PR with pending checks is not stuck, it is slow.
   - **When a PR really has been green and idle past that window, probe with the merge command itself — do not pre-judge.** `gh pr merge` is idempotent and self-diagnosing: it either lands the PR or tells you the PR was already on its way.
     ```
     gh pr merge {pr} --repo cuioss/{consumer} --squash
     ```
     - `"already queued to merge"` → auto-merge was working all along; the #192 diagnosis was wrong. Poll `state` until `MERGED`, do not re-issue.
     - Merge succeeds → this was a genuine #192 case (auto-merge refused for an unstable status and never re-enabled).
     - **Omit `--delete-branch`.** On a repo with a merge queue `gh` rejects the whole command with `Cannot use -d or --delete-branch when merge queue enabled`. The queue deletes the branch itself.
   - **`gh pr merge` may be blocked by the permission classifier.** If it is, do not try to grant yourself the permission — writing `.claude/settings.local.json` is blocked via both Bash and the Write tool by design. Report the blocked PRs to the user with links and let them decide. Given the point above, they are usually merging on their own anyway, so re-poll before escalating.
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
- **Consumer PRs merge themselves. Assume that first.** The default and overwhelmingly common outcome is that every consumer PR lands via its own auto-merge / merge queue with no help. Slow consumers (`API-Sheriff`, `nifi-extensions`, `TokenSheriff`) just take up to ~15 minutes because they run integration/e2e suites. Patience is the correct action; intervention is the exception.
- **`UNSTABLE` + `autoMergeRequest == null` does not mean auto-merge was refused.** It is the normal reading for a PR mid-flight *and* for a PR that has already entered a merge queue (queue entry nulls the field). The genuine #192 case — auto-merge refused for an unstable status and never re-enabled — can only be confirmed by running `gh pr merge --squash` and seeing it actually merge, rather than answer `"already queued to merge"`. Never report a stuck PR, and never escalate to the user, on the state pair alone.
- **Do not self-grant permissions.** If `gh pr merge` is denied by the permission classifier, writing `.claude/settings.local.json` is also blocked, via Bash *and* the Write tool. That guard is deliberate. Re-poll (the PR is probably merging anyway), then report the remaining PRs with links for the user to handle.
- **Since #193, the release ships two internal SHAs by design.** The tagged commit pins executed composite-action refs to the *release* commit (so the artifact is fully SHA-pinned); consumer-facing refs point at the *tag*. The release workflow's "Verify commit to be tagged is fully SHA-pinned" step (`workflow-scripts/check-internal-pinning.py`) guards this — if it ever fails, the release stops before tagging and the fix is a sequencing bug, not something to bypass.
