# Build story: who built what

Source material for the final article. It records which AI engines and tools produced each part of ACME City Permits, with the screens captured along the way. Every row is taken from `BUILD_LOG.md`, `EVIDENCE_LOG.md` and the session records; nothing is estimated.

## Engines

| Engine | Provider and access | Role | What it produced |
|---|---|---|---|
| GPT-5.6 Sol (fast), with GPT-6 Astra | OpenAI, through the Codex subscription and a local Claude Code gateway | Lead orchestrator, 2026-10-26 evening to 10-27 early morning | Requirements outline (57 IDs), the parent plan plus five child plans (22 tasks), integration of every slice, parent fixes, acceptance runs, the first live Muse attempt, status record and architecture-page updates, user-test guide and handoff |
| MiniMax M3 | MiniMax subscription, as headless Claude Code executors | Implementation slices, each reviewed by the orchestrator | Governed foundation (F1–F4), registry and stewardship (R1–R4), permits, rules, finance and issuance (P1–P5), Muse core (M1–M2), eight-screen UI and browser slice, acceptance core, and the first architecture page build |
| Claude Opus 5.5 | Anthropic, Claude Code | Lead from 2026-10-27 morning | Diagnosed and fixed the live Muse failure (output budget, field-name schema), reran all gates, moved the status to as built, the redesign mockup, Muse integration in the gateway, the baseline commit, and review of Muse's work |
| Muse Spark 1.3 | Meta Model API, Standard mode | Runtime model inside the app | Structured extraction of permit-application documents; proposals only, validated by the app and decided by people |
| Muse Wonder 1.0 | Meta Model API, Standard mode, through the gateway | Design reviewer, then builder | A cited review of the original prototype against the built app (42 steps, about $2.50), then the one-pass UI redesign build |
| Muse Image 1.0 | Meta Model API | Image generation | 25 test icons ($0.25). Randall kept only the permit-type icons for work-queue rows, and the build adds Administrator-only icon generation per permit type |

## Tools

FastAPI, SQLAlchemy and Alembic on SQLite; Jinja2 server-rendered pages with vanilla JavaScript; pytest and Playwright (659 tests); uv; a local Claude Code gateway (any-gateway) that routes Claude Code to OpenAI, MiniMax and Meta models; the Vollen solution-architecture page kit; and the private AVA Library.

## Screens along the way

| Stage | Folder | What it shows |
|---|---|---|
| v1, original build (10-27, before redesign) | `screens/v1-original/` | The as-built eight-screen app: persona selector, work queue, permit workspace, steward review, applicants, properties, reconciliation, governance, rules and fees |
| v2, approved mockup (10-27) | `screens/v2-mockup/` | The redesign Randall approved, in light and dark: queue, permit workspace with the Muse run and findings, steward review, applicant tracker, reconciliation |
| v3, Muse Wonder build | `screens/v3-redesign/` (after acceptance) | The redesigned app running with real data |

`capture_screens.py` recaptures the running app for any stage.

## Costs recorded so far

- Meta: three live Muse Spark extraction calls (about $0.02), the Muse Wonder review (about $2.50), 25 Muse Image icons ($0.25), plus the redesign build (recorded when it finishes).
- OpenAI, MiniMax and Anthropic work ran on subscriptions; no per-call charge is recorded for them.
