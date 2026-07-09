# Gemini review: signal vs. noise

Short reference for [Gemini Code Assist](https://developers.google.com/gemini-code-assist)
(`gemini-code-assist[bot]`). Kept brief because the free tier is being retired — see below.

## ⚠️ Consumer version is being sunset

Google is shutting down the **free/consumer** Gemini Code Assist GitHub app:

- **2026-06-18** — deprecated; no new org installations.
- **2026-07-17** — **all code-review activity ends.**

Only the free tier is affected; the paid **Enterprise/Standard** tier continues. There is no
in-place migration — see [Enterprise](#enterprise-version) below. Source:
[consumer code-review sunset](https://developers.google.com/gemini-code-assist/docs/deprecations/consumer-code-review).

**Org decision:** let the consumer version lapse on 2026-07-17. It is redundant with CodeRabbit
(free for OSS, strong) and Sourcery. The one thing lost is Gemini's security depth (it was the
sharpest security reviewer of the three in practice) — cover that gap by leaning on CodeRabbit's
`🔒 Security & Privacy` findings.

## Central config

- **Per-repo files only** — `.gemini/config.yaml` + `.gemini/styleguide.md` in a `.gemini/`
  folder at each repo root. **No config-repo, no org-`.github`, no dashboard** (less central than
  Sourcery).
- Fields: `code_review.disable`, `code_review.comment_severity_threshold`
  (LOW/MEDIUM/HIGH/CRITICAL), `code_review.max_review_comments`,
  `code_review.pull_request_opened.{summary,code_review,help}`, `ignore_patterns` (file globs).
- **No label-based skip** — cannot honor the shared `skip-bot-review` label. To silence it before
  sunset, use `code_review: { disable: true }` per repo.

## Signal vs. noise

The leanest of the three bots — a summary + findings, with **no marketing/share footer, no
tips/commands, no walkthrough diagrams**.

| | |
|---|---|
| **Signal** | Inline findings tagged with **severity badges** (`security-high`, `high`, `security-medium`, `medium` — a clean classifier), each with a concrete fix and often a GitHub ` ```suggestion ` block. The `## Code Review` summary is concise and useful. |
| **Noise** | The **sunset banner** appended to every review (now the dominant, and terminal, noise). Severity badges are SVG-image markup — verbose raw, but render as small icons. |

## Enterprise version

Same review *surface* (same summary + severity-badged inline findings), but a structurally
different, **paid** setup — not just a license flip:

- Requires a **Google Cloud project + billing**; repos are connected via **Developer Connect**
  (region `us-east1`) and managed in the **Google Cloud console** (Gemini Code Assist →
  Agents & Tools → Source Code Management).
- Adds what the consumer tier lacked: **centralized multi-repo control** (via the connection),
  a **shared style guide** across repos, persistent **review memory**, higher quotas, and
  GitHub Enterprise Cloud/Server support.

Only worth it if a paid, centrally-managed, memory-enabled reviewer becomes a deliberate want.
If migrating, verify the enterprise bot still posts as `gemini-code-assist[bot]` (plan-marshall's
`_AUTHOR_LOGIN_TO_BOT_KIND` assumes that login). Sources:
[Standard & Enterprise overview](https://docs.cloud.google.com/gemini/docs/codeassist/overview) ·
[Set up on GitHub (Cloud)](https://docs.cloud.google.com/gemini/docs/code-review/set-up-code-assist-github).
