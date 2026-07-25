# Automatic review

Central documentation for the cuioss org's automated PR reviewers: how to read their output
(signal vs. noise), how they are configured, and how they feed plan-marshall's automated triage.

| Reviewer | Bot login | Central config | Doc |
|---|---|---|---|
| CodeRabbit | `coderabbitai[bot]` | file-based — [`cuioss/coderabbit`](https://github.com/cuioss/coderabbit) repo (`.coderabbit.yaml`) | [coderabbit.md](coderabbit.md) |
| Sourcery | `sourcery-ai[bot]` | dashboard only — [app.sourcery.ai](https://app.sourcery.ai) → Review Settings (org-wide, UI) | [sourcery.md](sourcery.md) |
| PR-Agent | `cuioss-review-bot[bot]` | file-based — [`cuioss/pr-agent-settings`](https://github.com/cuioss/pr-agent-settings) repo (`.pr_agent.toml`); **opt-in per repo** via a caller workflow | [pr-agent.md](pr-agent.md) |
| Gemini | `gemini-code-assist[bot]` | ⚠️ consumer tier **retired** (2026-07-17); per-repo `.gemini/` only | [gemini.md](gemini.md) |

Each doc covers the review anatomy, a signal/noise table, the config levers (and what cannot be
suppressed), and the automation nuances (dedup across reviewers, the "Prompt for AI Agents"
prompt-injection caveat, correct-≠-in-scope).

## Shared skip label

`skip-bot-review` is the org-wide "don't auto-review this PR" label. Support is uneven, and the
*mechanism* differs per reviewer even where the effect is the same:

| Reviewer | Honors `skip-bot-review`? | How |
|---|---|---|
| CodeRabbit | ✅ centrally | `labels: ["!skip-bot-review"]` in `cuioss/coderabbit/.coderabbit.yaml` |
| PR-Agent | ✅ centrally, but **not** via bot config | job-level `if:` guard in `reusable-pr-agent-review.yml`. Its own `ignore_pr_labels` / `ignore_pr_authors` settings are webhook-server-only and are **silently ignored in GitHub Action mode** — do not "tidy" the rules into `.pr_agent.toml`. An explicit `/review` comment overrides the label on purpose. |
| Sourcery | ⚠️ only if wired per-repo | add `github.ignore_labels: [skip-bot-review]` to each repo's `.sourcery.yaml` (not yet done) |
| Gemini | ❌ no label skip exists | `.gemini/config.yaml` only supports global `code_review: disable`, file `ignore_patterns`, and a severity threshold — no per-PR label opt-out |

So applying `skip-bot-review` reliably silences **CodeRabbit** and **PR-Agent**; Sourcery keeps
reviewing unless its per-repo config is added, and Gemini cannot be skipped by label at all.
Create the label per repo where you want to use it (`gh label create skip-bot-review`).

The same asymmetry applies to the bot-author skips (`dependabot[bot]`,
`cuioss-release-bot[bot]`): central config for CodeRabbit, workflow guard for PR-Agent, no
documented equivalent for Sourcery.

**Downstream:** plan-marshall consumes these reviewers through its `pr-comment` findings pipeline.
The per-reviewer triage rules live in the `plan-marshall:automatic-review` skill under
`standards/{bot_kind}.md`, each carrying a machine-readable registry block, and link back here as
the source of truth for signal/noise and configuration.
