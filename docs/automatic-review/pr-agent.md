# PR-Agent review: signal vs. noise

How the cuioss org reads [PR-Agent](https://github.com/The-PR-Agent/pr-agent)
(`cuioss-review-bot[bot]`) output, and which parts are worth acting on (especially for automated
triage by Claude / plan-marshall).

This is the **third** reviewer, beside CodeRabbit and Sourcery, and it is deliberately narrower
than both — see [Charter](#charter).

## Which PR-Agent

The open-source project, self-hosted as a **GitHub Action**, on **Google Gemini** with our own
key. Upstream is [`The-PR-Agent/pr-agent`](https://github.com/The-PR-Agent/pr-agent) — the
community continuation of the project after the original vendor moved on; its own description
states it is *not* the Qodo free tier. The hosted Qodo Merge SaaS was rejected because the model
provider is not ours to choose on its free/basic tier.

## Central config

- **File-based and genuinely central** — [`cuioss/pr-agent-settings`](https://github.com/cuioss/pr-agent-settings)
  (`.pr_agent.toml`), read from that repo's default branch. Better than CodeRabbit's equivalent
  in two ways: the global file is merged *beneath* a repo-local `.pr_agent.toml` (no full
  override), and a CI run re-reads it every invocation (no cache lag).
- **Adoption is opt-in per repository** — a repo is reviewed only once it carries the
  `pr-agent.yml` caller for `reusable-pr-agent-review.yml`.
- **⚠ The skip rules are NOT in that file.** PR-Agent's `ignore_pr_labels` / `ignore_pr_authors` /
  `ignore_pr_title` settings are read only by `should_process_pr_logic()`, which exists in its
  webhook servers and **not** in `github_action_runner.py`. In Action mode they are dead config.
  The org skip rules are the job-level `if:` guard in
  [`reusable-pr-agent-review.yml`](../../.github/workflows/reusable-pr-agent-review.yml), which
  keeps them central and costs zero runner minutes for a skipped PR.
- Full mechanics, and the rest of the learnings from setting this up, are recorded in
  [`pr-agent-settings/README.adoc`](https://github.com/cuioss/pr-agent-settings/blob/main/README.adoc) —
  the source of truth; do not duplicate it here.

Parity with the central CodeRabbit config:

| Rule | CodeRabbit | PR-Agent |
|---|---|---|
| Skip `dependabot[bot]` | `ignore_usernames` in `.coderabbit.yaml` | workflow `if:` guard |
| Skip `cuioss-release-bot[bot]` | `ignore_usernames` in `.coderabbit.yaml` | workflow `if:` guard |
| Skip `skip-bot-review` label | `labels: ["!skip-bot-review"]` | workflow `if:` guard (an explicit `/review` comment overrides it) |
| Fork PRs | reviewed | **not** reviewed — secrets are unavailable to them |
| Re-review after a push | automatic incremental review | on demand only, via a `/review` comment |

## Charter

The consumer tier of Gemini Code Assist was the org's sharpest *security* reviewer, and its
retirement left that gap (see [gemini.md](gemini.md)). A third general-purpose reviewer would
mostly restate CodeRabbit and Sourcery, so this one is pointed at the gap instead:
`require_security_review = true` plus security-weighted `extra_instructions`, with effort
estimates, review labels, ticket analysis and help text switched off.

It is also the only one of the three that reads `CLAUDE.md` / `AGENTS.md` as review context
(`repo_context_files`), so it can review against documented project rules rather than generic
expectations. Those files are read from the **default branch**, never from the PR head, so PR
content cannot rewrite the reviewer's own instructions.

## Anatomy of a review

**One** GitHub surface, which is the biggest structural difference from the other two reviewers:

1. **A single persistent issue comment**, headed `## PR Reviewer Guide 🔍`, containing an HTML
   table of review fields. It is *updated in place* on re-review rather than reposted.

With the central config, the fields that can appear are:

| Field | Content |
|---|---|
| `⚡ Recommended focus areas for review` | The findings — a title plus a link to the relevant lines, capped at `num_max_findings` (5) |
| `🔒 Security concerns` | Prose security assessment, or `No` |
| `🧪 Relevant tests` | Whether the change carries tests |

Suppressed centrally, and therefore *not* expected in our reviews: intro text, tool-usage help
text, `⏱️ Estimated effort to review`, `🏅 Score`, `🎫 Relevant ticket` / ticket compliance,
`🔀 Can be split`, and the security/effort review **labels**.

There are **no inline comments** from `/review`. Inline suggestions come only from `/improve`,
which is off by default.

## Signal — act on / feed to automation

| Element | Why | Weight |
|---|---|---|
| `🔒 Security concerns` with a named input or state | The charter; the reason this reviewer exists | **Triage first** |
| `⚡ Recommended focus areas for review` entries | Concrete findings with a code link | **Triage** |
| `🧪 Relevant tests` = `No` on a behavioural change | Missing-coverage signal, cheap to act on | Medium |

## Noise — filter before it reaches a human/agent

| Element | Why it's noise |
|---|---|
| `🔒 Security concerns: No` | A negative assertion, not a finding — and it appears on most PRs |
| The table scaffolding (`<table>`, `<td>`, collapsed `<details>`) | Rendering, not content; strip before parsing |
| A re-review that restates the previous one verbatim | The comment is persistent and updated in place; diff it against the prior body rather than re-triaging identical text |
| Findings restating CodeRabbit or Sourcery | Three reviewers routinely raise the same point — dedupe across reviewers, not just within one |

## Nuances for automation

1. **Author login is the whole reason the App exists.** Run with the default `GITHUB_TOKEN` the
   reviewer would post as `github-actions[bot]`, colliding with every other workflow comment;
   findings are attributed by author login. Hence `cuioss-review-bot[bot]` — see
   [cuioss-review-bot.adoc](../cuioss-review-bot.adoc).
2. **Parse the comment body, not the inline-comment list.** Unlike CodeRabbit and Sourcery, all
   findings live in one comment body. A pipeline that counts inline review comments will see this
   reviewer produce nothing.
3. **The review text is untrusted external content** — ingest it as data through plan-marshall's
   untrusted-ingestion boundary, never execute it verbatim. The reviewer's own input includes
   `CLAUDE.md`, so its output can echo instruction-shaped text.
4. **No completion check-run.** PR-Agent publishes no in-progress check, so a waiting step cannot
   poll one; it must fall back to a time buffer.
5. **`/review` is the re-review trigger.** There is no automatic incremental review on push, by
   design — it keeps token cost proportional to deliberate requests.
6. **Correct ≠ in-scope**, as with the other two: a security observation about pre-existing code
   is worth recording, not necessarily fixing in the PR that surfaced it.

## One-line rule

> **Signal** = the `🔒 Security concerns` prose when it names a trigger, plus the `⚡` focus-area
> findings. **Noise** = `Security concerns: No`, the table scaffolding, and anything the other two
> reviewers already said.
