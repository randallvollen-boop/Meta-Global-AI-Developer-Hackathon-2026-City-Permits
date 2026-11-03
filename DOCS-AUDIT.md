# Documentation audit — 2026-11-02

Scope: the requested README, submission material, operations/deployment material,
architecture fact sheet and rendered architecture page, in-app help content, and
documents that state live counts. This is a report only: no audited document was
edited.

## Current facts used for comparison

- The selector has exactly four selectable personas: Applicant, Data Steward,
  Permit Reviewer, and City Administrator. Service identities are not personas;
  configuration authority does not imply business approval authority.
- `Check my application` is the pre-submit review. It has a Muse badge and can
  request its bounded feedback path; `Submit application` deliberately calls the
  deterministic review with `muse=False`. A Must fix result holds submission at
  `#presubmit`; Submit anyway requires a reason and records the held-case flag.
- Data identity and parcel work is Data follow-up, not a decision blocker. The
  agent recommends from checked rules. Missing applicant information returns to
  the applicant. The payer link and reconciled fee remain issue blockers.
- Approval against a failed rule is a recorded exception and requires its reason.
  The real clock is the default; no scenario-clock auto setting is enabled.
- Tours fill the resident form; a missing tour case has a recovery page.
  Applicant notices, queue Stage/Next action/search/agent tags, manual close
  with a reason, collapsible workspace sections, and the Last action panel are
  current UI behavior.
- Per the task brief, the current permission count is 85. The checked
  `repo/config/actors.json` still advertises five selectable personas and yields
  only 82 distinct `permission_id` values, so it is a source/configuration
  conflict that needs reconciliation before changing any numeric documentation.

## Findings

| File:line | Old claim | Correct current fact |
|---|---|---|
| `README.md:31` | “Agent operators” are a user group that wakes and runs agents. | Agent operation is not a selectable persona; document the four selectable personas and any agent work as an explicit service identity / authorized action. |
| `README.md:32` | Data stewards “clear the findings that block a case.” | Steward data work is Data follow-up; the agent recommends only on checked rules. Missing applicant information returns to the applicant, while payer link and fee block issue. |
| `README.md:47`, `README.md:73`, `README.md:110` | Pre-submit prose says only that Muse explains the result. | State the visible Muse badge on Check my application and, critically, that Submit application makes no Muse call. Preserve the Must fix/Submit anyway/reason/`#presubmit` behavior. |
| `README.md:56`, `README.md:58`, `README.md:76`, `README.md:89` | Five selectable personas, including Agent Operator. | Exactly four selectable personas; Agent Operator must not be presented as a selectable human persona. |
| `README.md:125` | “3,414 tests … all pass” is current. | This is a dated historical count, not a current claim. Replace it with a dated evidence reference after the final collection/run; do not carry it as current status. |
| `docs/submission/JUDGE_WALKTHROUGH.md:29` | Check my application “asks Muse for feedback.” | The step must show the Muse badge and say Submit makes no Muse call; the deterministic pre-submit result still groups Must fix, Should check, and Looks good. |
| `docs/submission/JUDGE_WALKTHROUGH.md:35`, `:69-70`, `:75` | A judge switches to and acts as Agent Operator. | The walkthrough must use only the four selectable personas and describe agent operation without introducing a fifth dropdown actor. |
| `docs/submission/SUBMISSION_DRAFT.md:5`, `:30-32`, `:38`, `:66`, `:127-128`, `:138`, `:140`, `:148` | The hosted demo has five personas and an Agent Operator persona. | Exactly four selectable personas; replace persona-switch and walkthrough instructions accordingly. |
| `docs/submission/SUBMISSION_DRAFT.md:28`, `:54`, `:83`, `:134`, `:142` | Pre-submit wording omits the badge and incorrectly leaves the Submit/Muse boundary implicit. | Check my application bears the Muse badge and may use the bounded feedback path; Submit application makes no Muse call. Must fix holds at `#presubmit`; Submit anyway needs a reason and is recorded. |
| `docs/submission/SUBMISSION_DRAFT.md:113` | “3,414 tests … all pass” is current. | Use a dated final-run/collection result rather than this prior count. |
| `docs/operations/RUNBOOK.md:78`, `:82-86`, `:162-169`, `:184`, `:318`, `:358`, `:618`, `:807` | Agent Operator is the only selectable persona that wakes/runs agents; the runbook also says exactly five selectable personas. | Four personas are selectable. Retain the explicit action grants and service identities, but remove Agent Operator from the selectable-persona and walkthrough model. |
| `docs/operations/DEPLOY_RENDER.md:5`, `:112` | Public deployment permits acting as any of five personas and exposes Agent Operator as a persona route. | Deployment documentation must describe the four-persona selector and the revised handling of agent work. |
| `docs/operations/DEPLOY_RENDER.md:82`, `:121`, `:137`, `:160` | Hosted live Muse allowance/cap is 100 calls and deployment enables a live pre-submit Muse path. | This is deployment-state dependent and cannot be asserted from the repository. Confirm the deployed caps/settings, then state the separate behavior: Check is badged; Submit makes no Muse call. |
| `docs/solution-architecture/acme-city-permits/facts.md:42-50`, `:187`, `:254` | “Five selectable personas”; Agent Operator is a built persona. | The architecture fact sheet must show four selectable personas and model agent work as a non-persona identity/action. |
| `docs/solution-architecture/acme-city-permits/facts.md:120`, `:126`, `:139`, `:155`, `:186`, `:193-194`, `:203`, `:206`, `:228`, `:261` | Historical live-call, image-call, verification, and test-count figures are intermingled with present-tense architecture facts. | Keep the historical evidence as dated records, but move it out of present-tense claims. Reconcile the current permission total to 85 before publishing a new count. |
| `docs/solution-architecture/acme-city-permits/vollen_acme-city-permits_solution-architecture_2026-10-26.html:760`, `:1003`, `:1367` | The rendered diagram and embedded page data say five signed-in/selectable personas and include Agent Operator as a persona node. | Regenerate the architecture page from corrected facts/data: four selectable personas, no Agent Operator persona, and explicit service identities/grants. |
| `repo/config/help_content.json:11`, `:36`, `:99-131`, `:147`, `:453` | Tutorial/help text presents Agent Operator as a persona; the technical note says the architecture iframe blocks every script and is static. | Help must name four selectable personas and revise the tour flow. The architecture note must say its explicitly flagged iframe allows scripts in an opaque sandbox; its response CSP allows only inline scripts and blocks network access. |
| `repo/config/help_content.json:38` | “No model is called when you follow these steps.” | This is too broad: Check my application invokes its bounded Muse feedback path when configured. The help must distinguish it from Submit application, which never makes that call. |
| `repo/config/help_content.json:231`, `:382` | A 100-call daily Muse allowance is a current, unconditional demo fact. | Treat provider allowance as deployment configuration; verify it before claiming a number. |
| `repo/config/ui_glossary.json:308` | Agent Operator is the actor that wakes/processes intake cases. | Do not present it as a selectable persona; route users through the four-persona model and explicit authorized actions. |

## Documents checked with no behavior finding in the requested topics

- `docs/operations/DEPLOY_RENDER.md:18` correctly says the deployed setting
  leaves `ACME_SCENARIO_CLOCK` empty, so the demonstration uses the real clock.
- `docs/operations/RUNBOOK.md:169`, `:696` correctly preserve Data follow-up,
  recorded rule exceptions, and payer/fee issue blockers, apart from their
  surrounding stale fifth-persona model.
- `docs/submission/JUDGE_WALKTHROUGH.md:85-103` correctly describes Data
  follow-up, exception reasoning, payer/fee issue blockers, and applicant
  notices.

## Required follow-up order

1. Resolve the selector/config contradiction (the active four-persona rule vs.
   `actors.json` and documents claiming five) before changing implementation
   counts or release facts.
2. Regenerate the architecture source/page after its facts and data are aligned.
3. Refresh every deployment-dependent Muse number from observed deployment
   configuration and update test totals only from a final, dated run.
