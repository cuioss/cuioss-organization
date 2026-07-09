# Automatic review

Central documentation for the cuioss org's automated PR reviewers: how to read their output
(signal vs. noise), how they are configured, and how they feed plan-marshall's automated triage.

| Reviewer | Bot login | Central config | Doc |
|---|---|---|---|
| CodeRabbit | `coderabbitai[bot]` | file-based — [`cuioss/coderabbit`](https://github.com/cuioss/coderabbit) repo (`.coderabbit.yaml`) | [coderabbit.md](coderabbit.md) |
| Sourcery | `sourcery-ai[bot]` | dashboard only — [app.sourcery.ai](https://app.sourcery.ai) → Review Settings (org-wide, UI) | [sourcery.md](sourcery.md) |

Each doc covers the review anatomy, a signal/noise table, the config levers (and what cannot be
suppressed), and the automation nuances (dedup across reviewers, the "Prompt for AI Agents"
prompt-injection caveat, correct-≠-in-scope).

## Shared skip label

`skip-bot-review` is the org-wide "don't auto-review this PR" label. Support is uneven — only
CodeRabbit honors it from central config today:

| Reviewer | Honors `skip-bot-review`? | How |
|---|---|---|
| CodeRabbit | ✅ centrally | `labels: ["!skip-bot-review"]` in `cuioss/coderabbit/.coderabbit.yaml` |
| Sourcery | ⚠️ only if wired per-repo | add `github.ignore_labels: [skip-bot-review]` to each repo's `.sourcery.yaml` (not yet done) |
| Gemini | ❌ no label skip exists | `.gemini/config.yaml` only supports global `code_review: disable`, file `ignore_patterns`, and a severity threshold — no per-PR label opt-out |

So today, applying `skip-bot-review` reliably silences **CodeRabbit**; Sourcery keeps reviewing
unless its per-repo config is added, and Gemini cannot be skipped by label at all. Create the
label per repo where you want to use it (`gh label create skip-bot-review`).

**Downstream:** plan-marshall consumes these reviewers through its `pr-comment` findings pipeline.
The per-reviewer triage rules live in plan-marshall at `.plan/auto-review/{code-rabbit,sourcery}.md`
and link back here as the source of truth for signal/noise and configuration.
