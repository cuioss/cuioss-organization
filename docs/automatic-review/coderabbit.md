# CodeRabbit review: signal vs. noise

How the cuioss org reads CodeRabbit output, and which parts are worth acting on
(especially for automated triage by Claude / plan-marshall). This is the rationale
behind the settings in the central CodeRabbit config, which lives in a dedicated repo:
[`cuioss/coderabbit/.coderabbit.yaml`](https://github.com/cuioss/coderabbit/blob/main/.coderabbit.yaml).

Reviewed profile: **CHILL** (set in the central config).

## Anatomy of a review

A CodeRabbit review is posted across three GitHub surfaces:

1. **Walkthrough / summary** — one issue comment per PR (high-level summary, changed-files
   table, pre-merge checks, finishing-touches, tips/marketing).
2. **Review bodies** — the `Actionable comments posted: N` wrapper plus collapsed
   `🧹 Nitpick` / `Additional comments` / `Outside diff range` sections.
3. **Inline review comments** — the per-line findings (the substance).

Inline findings carry machine-parseable classifiers:

- **Category** HTML marker: `<!-- cr-indicator-types:potential_issue -->`,
  `refactor_suggestion`, `nitpick`, …
- **Severity** emoji: `🔴` critical · `🟠 Major` · `🟡 Minor`
- **Tags**: `🔒 Security & Privacy`, `⚡ Quick win`
- **`📝 Committable suggestion`** — an apply-ready diff
- **`🤖 Prompt for AI Agents`** — a normalized, machine-readable restatement (file + line + instruction)

## Signal — act on / feed to automation

| Element | Why | Weight |
|---|---|---|
| Inline `potential_issue`, esp. `🟠 Major`/`🔴` and `🔒 Security & Privacy` | Real defects; CodeRabbit verifies with repo scripts before posting | **Triage first** |
| **`🧹 Nitpick` comments** | Treated as **signal** here (maintainer preference): they routinely catch naming, doc drift, small correctness/consistency issues that match our standards | Quality backlog; act when cheap |
| `refactor_suggestion` | Often a genuine simplification | Medium |
| `📝 Committable suggestion` | Concrete, apply-ready diff | High when tied to a real finding |
| **`🤖 Prompt for AI Agents`** block | The machine-readable payload our automation ingests | **Primary parse target** (but see security caveat) |
| `cr-indicator-types:` markers + severity/tag emojis | Stable routing keys for triage | Use as the classifier |
| Walkthrough prose + `Estimated code review effort` | Cheap orientation | Low-action context |
| `Learnt from:` / "Learnings added" | Records decisions already made, so agents don't re-litigate them | Context memory |

## Noise — filter before it reaches a human/agent

| Element | Why it's noise |
|---|---|
| Share buttons, "Thanks for using CodeRabbit", Tips, `@coderabbitai help` footer | Marketing/boilerplate |
| `✨ Finishing Touches` (docstring / unit-test generators), `🪄 Autofix` checkboxes | Interactive UI, not findings |
| `🧩 Analysis chain` shell-script transcripts | CodeRabbit's internal verification log — verbose |
| Pre-merge checks showing *Passed/skipped* (docstring coverage, linked issues, out-of-scope) | Status chrome unless one actually **fails** |
| Run configuration / Run ID / commit SHAs / files-selected lists | Metadata |
| `cr-comment:v1:…` ids, "auto-generated reply" markers, empty duplicate review bodies, `No actionable comments 🎉` | Structural/echo cruft |
| `sequence_diagrams`, `poem`, `in_progress` fortune, suggested labels/reviewers | Low-value walkthrough extras |

## Three nuances for automation

1. **The `🤖 Prompt for AI Agents` block is a prompt-injection surface.** It is untrusted
   external text (e.g. *"Fix… keep changes minimal, and validate."*). plan-marshall must treat
   it as **data to triage through its untrusted-ingestion boundary**, never execute it verbatim.
2. **Correct ≠ in-scope.** Valid findings are often legitimately deferred (out of scope, already
   mitigated). Right behavior is **triage-and-reply**, not auto-fix.
3. **Weight by severity, not the 🔒 emoji**, and **dedup across reviewers** — CodeRabbit is one of
   several AI reviewers (Gemini, Sourcery) active on these repos.

## One-line rule

> **Signal** = inline `potential_issue` / `refactor_suggestion` / `nitpick` findings + their
> committable diff + the parsed AI-agent prompt. **Noise** = the walkthrough/finishing-touches/
> tips/analysis-chain chrome and always-skipped status checks.

## What the config does about it

The config lives in [`cuioss/coderabbit/.coderabbit.yaml`](https://github.com/cuioss/coderabbit/blob/main/.coderabbit.yaml)
(a dedicated repo named `coderabbit`; CodeRabbit applies it to every org repo without its own
`.coderabbit.yaml`).

### Reduced via config

| Setting | Effect |
|---|---|
| `profile: chill` | Balanced feedback; **keeps nitpicks** (which we treat as signal) |
| `sequence_diagrams: false` | No auto UML diagrams in the walkthrough |
| `suggested_labels: false`, `suggested_reviewers: false` | Drop unused walkthrough suggestions |
| `poem: false`, `in_progress_fortune: false` | Drop poem + "fortune" chatter |
| `finishing_touches.docstrings.enabled: false`, `finishing_touches.unit_tests.enabled: false` | Remove the interactive generator checkboxes |
| `pre_merge_checks.docstrings.mode: "off"`, `pre_merge_checks.issue_assessment.mode: "off"` | Silence the always-skipped checks |
| `enable_prompt_for_ai_agents: true` | **Keep** the machine-readable payload (signal) |

Skip surface: `auto_review.ignore_usernames` (`dependabot[bot]`, `cuioss-release-bot[bot]`) and
the shared **`!skip-bot-review`** label opt-out (see [README](README.md#shared-skip-label)).

Further optional levers if more trimming is wanted: `changed_files_summary: false`,
`estimate_code_review_effort: false`, `related_issues`/`related_prs: false`,
`review_status: false`, `finishing_touches.autofix.enabled: false`, or `profile: quiet`
(drops nitpicks — not wanted here).

### NOT reducible via config

These have no schema toggle and will remain (they're either OSS-tier branding or CodeRabbit's
working method):

- Marketing / Tips / Share footer (`@coderabbitai help`, "Thanks for using CodeRabbit")
- `🧩 Analysis chain` script transcripts
- The `<!-- cr-* -->` HTML markers (harmless — and useful for parsing)

Filter these downstream (e.g. in plan-marshall's PR-comment triage): strip known-boilerplate
`<details>` blocks and HTML-comment markers, then route the remaining inline findings by
`cr-indicator-types` + severity.
