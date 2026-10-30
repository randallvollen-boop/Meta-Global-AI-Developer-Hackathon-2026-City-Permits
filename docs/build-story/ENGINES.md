# Build story: who built what

Source material for the final article. It records which AI engines and tools produced each part of ACME City Permits, with the screens captured along the way. Every row is taken from `BUILD_LOG.md`, `EVIDENCE_LOG.md` and the session records, except the Krea 2 row, which comes from the project audit and has no `BUILD_LOG.md` entry. Nothing is estimated.

## Engines

| Engine | Provider and access | Role | What it produced |
|---|---|---|---|
| GPT-5.6 Sol (fast), with GPT-6 Astra | OpenAI, through the Codex subscription and a local Claude Code gateway | Lead orchestrator, 2026-10-26 evening to 10-27 early morning | Requirements outline (57 IDs), the parent plan plus five child plans (22 tasks), integration of every slice, parent fixes, acceptance runs, the first live Muse attempt, status record and architecture-page updates, user-test guide and handoff |
| MiniMax M3 | MiniMax subscription, as headless Claude Code executors | Implementation slices, each reviewed by the orchestrator | Governed foundation (F1–F4), registry and stewardship (R1–R4), permits, rules, finance and issuance (P1–P5), Muse core (M1–M2), eight-screen UI and browser slice, acceptance core, and the first architecture page build |
| Claude Opus 5.5 | Anthropic, Claude Code | Lead from 2026-10-27 morning | Diagnosed and fixed the live Muse failure (output budget, field-name schema), reran all gates, moved the status to as built, the redesign mockup, Muse integration in the gateway, the baseline commit, and review of Muse's build. Six review fixes: icon access for every persona, seed icons at reset, a vacuous scanner gate, schema upgrade on reset, the Muse-run lookup bug from the original build, and visual polish |
| Muse Spark 1.3 | Meta Model API, Standard mode | Runtime model inside the app | Structured extraction of permit-application documents, record match proposals, applicant help, the policy briefing, explanation and proposal; proposals only, validated by the app and decided by people. Live Muse is off on the public demo |
| Muse Wonder 1.0 | Meta Model API, Standard mode, through the gateway | Design reviewer, then builder | A cited review of the original prototype against the built app (42 steps, about $2.50). Then the UI redesign and the permit-type icon feature: about 2,170 lines changed across 26 files, 3 new modules, a migration and 14 new tests. It took three runs: the first thrashed on a 200k context limit and was stopped; the second stopped after step 1; the resumed third finished in 48 minutes. About $21 measured. Then build 2: persona-scoped navigation, the simulated ePermit intake portal, the five-step agent triage with a deterministic recommendation, and the operations runbook, user stories and fence use case (286 turns, $21.71) |
| Muse Image 1.0 | Meta Model API | Image generation | 25 test icons ($0.25). Randall kept only the permit-type icons for work-queue rows, and the build adds Administrator-only icon generation per permit type |
| MiniMax M3 (later work) | MiniMax subscription, as headless Claude Code executors | Coder from 2026-10-27 11:05 | Parity phases 1 to 3 and the later lanes, for example the two wake and sleep agents with dependency graphs, the P3a lifecycle work and the Administration screens, each merged after lead review. One run ran out of credits during the full suite |
| Sonnet agents | Anthropic, Claude Code | Executors and gate runners | Ran the suite and gates when M3 ran out of credits, resumed a parity part after a machine crash, and built the City of Acme website |
| GPT-6 Astra (Codex) | OpenAI, through the Codex subscription | Brief reviewer | Reviewed the P3a operations brief before M3 built it |
| Claude Opus | Anthropic, Claude Code | Lead and reviewer after 2026-10-27 | Reviewed each merge, re-ran all 10 gates on merged main and fixed what review found, for example the Muse Wonder builds. `BUILD_LOG.md` calls the later reviewer the lead and the earlier one the parent (Claude Opus) |
| Muse Image 1.0 (seed icons) | Meta Model API | Image generation, 2026-10-28 | 14 permit-type icons, so every one of the 17 types has an icon after a reset (14 calls, $0.14) |
| Krea 2 | Not recorded in `BUILD_LOG.md` | Image generation at build time | The 17 town map tiles in `static/map-tiles` |

## Tools

FastAPI, SQLAlchemy and Alembic on SQLite; Jinja2 server-rendered pages with vanilla JavaScript; pytest and Playwright (2741 tests collected); uv; a local Claude Code gateway (any-gateway) that routes Claude Code to OpenAI, MiniMax and Meta models; the Vollen solution-architecture page kit; and the private AVA Library.

## Screens along the way

| Stage | Folder | What it shows |
|---|---|---|
| v1, original build (10-27, before redesign) | `screens/v1-original/` | The as-built eight-screen app: persona selector, work queue, permit workspace, steward review, applicants, properties, reconciliation, governance, rules and fees |
| v2, approved mockup (10-27) | `screens/v2-mockup/` | The redesign Randall approved, in light and dark: queue, permit workspace with the Muse run and findings, steward review, applicant tracker, reconciliation |
| v3, Muse Wonder build plus review fixes | `screens/v3-redesign/` | The redesigned app running with real data, in light and dark |

`capture_screens.py` recaptures the running app for any stage.

## Costs recorded so far

- Meta: three live Muse Spark extraction calls (about $0.02), the Muse Wonder review (about $2.50), 25 Muse Image icons ($0.25), the redesign build (about $21 measured, plus the stopped first run, which had no usage record), and build 2 ($21.71).
- Meta, later: the 14 seed icons (14 calls, $0.14). Later live Muse calls are not recorded in `BUILD_LOG.md` or `EVIDENCE_LOG.md`, and no later Meta total is recorded here.
- OpenAI, MiniMax and Anthropic work ran on subscriptions; no per-call charge is recorded for them.
