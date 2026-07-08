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

**Downstream:** plan-marshall consumes these reviewers through its `pr-comment` findings pipeline.
The per-reviewer triage rules live in plan-marshall at `.plan/auto-review/{code-rabbit,sourcery}.md`
and link back here as the source of truth for signal/noise and configuration.
