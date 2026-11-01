# Build story: who built what

Source material for the final article. It records which AI engines and tools produced each part of ACME City Permits, with the screens captured along the way. Rows come from `BUILD_LOG.md`, `EVIDENCE_LOG.md` and the session records. Models other than Muse are described by role, as local and other frontier models.

## Engines

| Engine | Access | Role | What it produced |
|---|---|---|---|
| Muse Spark 1.3 | Meta Model API, Standard mode | Runtime model inside the app | Structured extraction of permit-application documents, record match proposals, applicant help, the policy briefing, explanation and proposal; proposals only, validated by the app and decided by people. Live Muse is on for the public demo, with a daily cap of 100 live calls |
| Muse Wonder 1.0 | Meta Model API, Standard mode | Design reviewer, then builder | A cited review of the original prototype against the built app (42 steps, about $2.50). Then the UI redesign and the permit-type icon feature: about 2,170 lines changed across 26 files, 3 new modules, a migration and 14 new tests, finished on the third run in 48 minutes (about $21 measured). Then build 2: persona-scoped navigation, the simulated ePermit intake portal, the five-step agent triage with a deterministic recommendation, and the operations runbook, user stories and fence use case (286 turns, $21.71) |
| Muse Image 1.0 | Meta Model API | Image generation | 25 test icons ($0.25), then 14 seed permit-type icons on 2026-10-28 (14 calls, $0.14), so every one of the 17 types has an icon after a reset. The build adds Administrator-only icon generation per permit type |
| Local and other frontier models | Subscriptions and local models | Planning, orchestration, implementation slices, review and gates | The requirements outline (57 IDs) and the 22-task plan, the governed foundation, registry and stewardship, permits, rules, finance and issuance, the parity phases and later lanes, merge reviews and the 10 gates on merged main |
| Local image model | Local | Image generation at build time | The 17 town map tiles in `static/map-tiles` |

## Tools

FastAPI, SQLAlchemy and Alembic on SQLite; Jinja2 server-rendered pages with vanilla JavaScript; pytest and Playwright; uv; a local model gateway; the Vollen solution-architecture page kit; and the private AVA Library.

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
- Work by local and other frontier models ran on subscriptions or locally; no per-call charge is recorded for it.
