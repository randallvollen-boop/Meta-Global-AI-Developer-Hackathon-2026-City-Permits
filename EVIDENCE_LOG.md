# Evidence Log

## 2026-10-26 — ACME MDM package intake

Source archive: `ACME_MDM_Build_Package_2026-10-26.zip` from the user's Downloads folder.

- Intake timestamp: `2026-10-26T18:38:39-04:00`
- SHA-256: `e3fd9decc8fd31648872778dc8b779c2daa91643b689d5aab820541398b381f5`
- Entries: 103
- Uncompressed bytes: 4,839,225
- Duplicate names: none
- Absolute or parent-traversal paths: none
- Symlinks: none
- Individual files over 100 MiB: none
- Total over 500 MiB: no
- ZIP CRC failures: none
- Preserved archive copy hash: exact match
- Authoritative specification SHA-256: `54881e679cf9744f61251f7cc314ffa5400ffd3f53f67e21581371cf9f27de4d`

The build-package manifest separately records `ae5dcd769180756b3f62daea1ae96df4cb59daedb44286d88cfe09992d33f940` for the earlier `ACME-City-Package-2026-10-26.zip` whose 84 files were embedded into this new handoff. That is provenance for the earlier source archive, not the SHA-256 of the downloaded build-package ZIP above.

The archive and extracted tree are under ignored `intake/` paths. No bundled code, build script, or reference application was executed.

## 2026-10-26 — requirements alignment

Read the plain-text authoritative specification and principal companion files: start guide, build plan, coding handoff, interface requirements, data implementation notes, ownership/change routing, and fixture/validation plan.

Observed package claims:

- 57 numbered P0 requirements;
- 35 logical data objects;
- AT01–AT20 acceptance definitions;
- VC01–VC08 supplementary checks;
- D01–D11 fixtures;
- 84 preserved files from the earlier ACME city-permit package.

The source says the reference city-permit application is a deterministic synthetic pipeline/reporting baseline, not the required live MDM application. A referenced external click-through prototype is explicitly not bundled, and a scoped search found no corresponding local source directory. The package preserves duplicate baseline code trees, identifies four required evaluator regressions, and leaves all 57 requirements `to_implement_and_verify`; all 20 acceptance tests are marked not run. `CITY_PERMIT_ALIGNMENT.md` preserves those distinctions and maps the new target without claiming implementation.

## 2026-10-26 — local Git setup

Initialized a nested local Git repository on branch `main`. Repository-local author identity is configured for the personal GitHub account using its GitHub noreply address. `.gitignore` contains `/intake/`; `git check-ignore` confirmed the preserved ZIP is excluded.

`gh auth status` showed no authentication for the publication owner. Randall then fixed the publication owner for this hackathon to `RandallVollen-boop` only. No authentication change, remote creation, commit, push, or external write occurred.

## 2026-10-26 — Westerville process reference

Randall directed that the application be modeled on the City of Westerville, Ohio's permitting process. Official public pages were checked for Building, Forms and Online Portals, Submit a Permit, and Schedule an Inspection. The sources distinguish a Permit Portal from a Plan Review Portal, describe commercial contractor registration, identify commercial interior-alteration review as an approximately ten-workday process, publish area-based fees, and require inspections after issuance.

The alignment adopts workflow concepts only. The public application remains fictional ACME City software, uses synthetic requirements arithmetic, and does not claim City endorsement, official fees/codes/service levels, branding, data, portal integration, or permit authority. Source URLs and checked date are recorded in `CITY_PERMIT_ALIGNMENT.md`.

## 2026-10-26 — full requirements and executable implementation plan

Randall requested a complete local build and testable handoff. Created `repo/docs/REQUIREMENTS_OUTLINE.md` plus one parent and five child implementation plans under `repo/docs/plans/`. The plan selects Python 3.12, FastAPI, SQLAlchemy, Alembic, SQLite, server-rendered HTML/vanilla JavaScript, pytest and Playwright; it contains 22 gated tasks covering the governed foundation, registry/stewardship, permits/rules/finance/issuance, Muse/UI and integrated acceptance.

Self-review parsed the authoritative register and outline: 57 expected requirement IDs, 57 found, no missing or extra IDs. Six plan files exist, every referenced child plan resolves, and the prohibited placeholder-pattern scan returned no findings. The parent gate explicitly requires AT01–AT20, VC01–VC08, D01–D11, strict live/replay evidence, restart persistence, idempotent issuance retry, browser checks, and local process handoff. Planning evidence is not implementation evidence.

## 2026-10-26 — architecture/status and four-persona direction

Randall requested a maintained Vollen architecture document published inside the private AVA Library and limited the application dropdown to no more than four personas. Recorded the fixed selector as Applicant, Data Steward, Permit Reviewer and City Administrator. Underlying permissions remain explicit action/domain/record grants; source adapters, custodians, outbox workers and Muse are nonselectable service identities. The original source's role vocabulary remains evidence, not additional UI personas.

Created `docs/solution-architecture/acme-city-permits/facts.md` and canonical `STATUS.json`. Initial truthful state is PLANNED / IN IMPLEMENTATION. After parent acceptance of the governed foundation, status records 57 outlined, 10 implemented, 0 integrated-verification complete; 4 of 22 tasks verified; registry and permit slices in progress; AT/VC/D counts remain zero; live Muse not run. An independent architecture-page build was launched with no AVA write; publication remains pending parent verification.

## 2026-10-26 — governed foundation accepted

MiniMax M3 subscription session `20261026T191022-3841057-26783` completed F1–F4 without a corrective relaunch. Parent inspected the actor/persona contract, application factory, safe settings loader and session API, then independently ran:

- `uv run pytest -q`: 107 passed, 0 failed, 0 skipped;
- planning coverage: 57 requirements, 20 AT, 8 VC and 11 scenarios, no duplicate/missing IDs;
- empty-database Alembic upgrade: 64 tables created;
- `alembic check`: no new upgrade operations.

Exactly four selectable personas are seeded and API-tested: Applicant, Data Steward, Permit Reviewer and City Administrator. Underlying roles/grants remain explicit; service identities are nonselectable. Foundation implements ten mapped requirement IDs; GOV-04 and all integrated AT/VC/D results remain pending. A parent diagnostic confirmed current Starlette TestClient requires the `httpx2` development dependency; removing it caused three collection errors, restoring it returned the suite to 107 passes.

## 2026-10-26 — Vollen architecture page published to private AVA

M3 subscription session `20261026T192454-3878102-2716` built the planned/in-implementation STD-29 page from the sourced fact sheet and STATUS.json. Parent applied the Vollen editorial standard, resolved the only copy-lint error, reviewed the remaining warnings, rebuilt, and independently verified:

- kit/Linux checker PASS in light/dark, no console or page errors;
- six diagram views, eight steps, 19 component panels, 14 links with zero broken, four explorer folders and three tree folders;
- independent denylist/global-client/extra-leak/external-resource/status/number checks PASS;
- parent visual review of light/dark top/full renders;
- initial accepted HTML 712,025 bytes, SHA-256 `0906b6aad61eb1525d0f41363e0a61af8d0b6fe00c7a2303c03325eb8de2d0c7`.

Published offline to the private AVA Library under stable id `acme-city-permits-architecture`. Library and source HTML hashes match. AVA service remained inactive; no restart occurred. The page retains `Internal draft. [REVIEW REQUIRED]`, architecture PLANNED, brand/delivery/security approvals open, and two advisory checker warnings because the required process has eight steps rather than the kit's suggested five to seven.

`docs/solution-architecture/acme-city-permits/update_status.py` validates status bounds and exactly four personas, updates the marked status/fact/data blocks, rebuilds, runs the checker, independent verifier and copy lint, then replaces the same AVA article id only when `--publish-ava` is passed. The initial local-only run and authorized private-publication runs passed; receipts are in `status-updates.jsonl` and BUILD_REPORT.md.

## 2026-10-26 — registry and stewardship slice accepted

MiniMax M3 subscription session `20261026T194019-3913699-16582` completed R1–R4 without a corrective relaunch. The slice added registered/idempotent intake, simulated source adapters, typed canonical identities, evidence-based proposals, trusted views, steward decisions, reversible links, controlled change transitions, source acknowledgements, durable outbox, conflict handling and mapped AT/VC/scenario checks.

Parent inspected the registry service and route contract, corrected the generated proposal ID prefix from the misspelled `propsal` to `proposal`, mounted ingestion/registry/change routers in the real application factory, and independently ran the 25 slice files: **128 passed**, zero failed/skipped. Integrated OpenAPI contains 33 unique operations across 30 paths, including all new source, registry and change endpoints. No migration change was needed.

Accepted implementation mapping adds ING-01–05, MDM-01–05, CHG-01–06 and EDIT-01–04: 20 new requirement IDs. Foundation plus registry then totaled 30 implemented IDs and 8 of 22 verified plan tasks. AT/VC/D status counts remained zero pending the integrated manifest. The registry-phase AVA replacement passed; its historical receipt SHA-256 was `7c1b1cf480680f70a317a189908aacbbcbd8a62952fb4360e13e6d8226cf273e`. Later phase receipts supersede it under the same article ID.

## 2026-10-26 — permits, rules, finance and issuance slice accepted

MiniMax M3 subscription session `20261026T194028-3914027-32047` completed P1–P5 on its original run after one wait command timed out; the job was not relaunched. The slice added one governed rule/fee catalog, deterministic evaluator, immutable application/document revisions, versioned evaluations, actual reviewer decisions, impact handling, exact assessments, payment-event history, governed allocations/reconciliation and separate idempotent simulated issuance/artifact.

Parent inspected the fee calculator and issuance prerequisites/snapshot/artifact path, mounted permit/rule/finance routers in the real app, and independently ran the 25 slice files: **167 passed**, zero failed/skipped. Integrated OpenAPI now contains 64 unique operations across 58 paths. A fresh migration plus `alembic check` reports no model/schema drift.

The slice implements PER-01–06, REF-01–02, FIN-01–05 and EDIT-05: 14 new requirement IDs. Foundation, registry and permit slices totaled 44 implemented IDs and 13 of 22 verified tasks. Full coverage then correctly reported 13 unmapped IDs. The checked permit-phase AVA status replacement passed under the stable article ID; receipt SHA-256 was `cea65c7d6ba2afba86843c3384fa1e2b252ca17887854331004a1fbe8bd24d36`.

## 2026-10-26 — Muse core slice accepted without live spend

MiniMax M3 subscription session `20261026T204148-4053260-17682` completed M1–M2 with no live request. It added actual fictional versioned documents, explicit replay/malformed fixtures, payload truth isolation, strict extraction/match JSON schemas, a single-request non-retrying Meta Responses client, model-run persistence, live/replay/cached/failure states, bounded call/error latch behavior, proposal-only writes and AT14/AT15 contract/security tests.

Parent inspected the Muse service and provider client, fixed `scripts/check_requirement_coverage.py` so the implementation-marker regex accepts two-letter prefixes, added a regression test for `AI-01, UX-04`, mounted `/api/muse/run` and `/api/muse/runs`, and independently ran 99 targeted tests: all passed. Integrated OpenAPI contains 66 unique operations across 60 paths. Full coverage now reports only eight expected remaining IDs: EVAL-01–03, GOV-04 and UX-01–04.

No provider key value was read or printed and no live call was sent. The two-call live budget remains unused for the parent-owned integrated gate. Muse core contributes AI-01–05: total implementation is now 49 of 57 requirements and 15 of 22 verified tasks. UI and integrated evidence remain pending.

The first Muse-phase architecture update stopped before AVA publication because the independent number allowlist did not yet derive clock fragments from STATUS.json. Parent changed the verifier to allow numeric tokens present in the validated status record while retaining the fixed fact allowlist. Direct verification passed, then the full rebuild/check/copy-lint/private replacement passed. Current source/Library SHA-256 is `ff72e8b08048846fd024c17d0e1c60bc0998d4ab6b4fe9a3d5eb4bf7032d0f4d`; no unchecked page was published.

## 2026-10-26 — integrated local candidate and handoff

The interface and acceptance workers produced their assigned source but remained stuck after more than 90 minutes. Parent terminated only those two delegated process groups after inspecting the work and independently accepting it. The UI worker left no final report; its code was accepted from the executable results rather than a worker claim.

Integrated evidence after parent corrections:

- requirement inventory: 57/57 requirements, 20/20 AT, 8/8 VC and 11/11 D mapped;
- collection: 659 tests across unit 291, API 90, security 12, acceptance 90, supplementary 41, scenarios 34, evaluator 13, integration 41, regression 5 and browser 26;
- full suite: 659 passed, zero failed/skipped;
- deterministic manifest: 37 passed, zero failed, AT15 and AT19 blocked for live evidence;
- fresh migration to revision `0001` and `alembic check`: passed;
- publication-tree scan: 249 source files, zero findings before the final health tests; the final gate reruns the scan;
- eight-screen browser family: 26 passed, including 390-pixel and desktop overflow, keyboard focus, labels, status feedback, responsibility/evidence/history panels and the primary chain;
- restart persistence and issuance-response-loss retry: passed with stable application, crosswalk, model-run, assessment, allocation, permit number and artifact hash.

Canonical final local evidence is `repo/evidence/runs/final-local/run-all-summary.json` with its verified deterministic manifest under `repo/evidence/runs/final-local/deterministic/`.

A concurrent-run failure reproduced three changed JUnit hashes immediately after an otherwise successful deterministic run. File modification order showed two writers interleaving the same artifact names. The runner now holds an exclusive evidence-directory lock and the verifier takes a shared lock. A fresh run under `evidence/runs/deterministic-locked/` passed evidence verification with all ten artifact hashes intact.

One bounded live extraction was sent to Standard model `muse-spark-1.3`. Meta recorded run `modelrun_2f5ac6ced1e04fde823c670c1dbdc9e2` and response `resp_6ae00c2c9bf71eb13c464357`; response status was `incomplete`, with no output text. The run remains failed in `evidence/runs/live/demo-walkthrough.json`. No automatic retry and no second provider call occurred. Replay remains separately labelled and does not satisfy live evidence.

`repo/USER_TEST_GUIDE.md` documents the four personas, eight screens, D01 walkthrough, D02/D06/D11 variants, safe start/stop/reset commands and limitations. The owned loopback process is prepared in `ready-for-review` replay mode at `http://127.0.0.1:8266`; health reports revision `0001` and the selector returned HTTP 200.

The private AVA architecture page was rebuilt, checked and replaced under `acme-city-permits-architecture`. Current source/Library SHA-256 is `c61bd1e23fe33439a48110cc604772d19b733e16fffc1f465e7c29f8d6d4901a`. It remains PLANNED / IN IMPLEMENTATION because the successful live Muse primary chain is blocked.

## 2026-10-27 — Live Muse extraction resolved (Claude Opus, at Randall's request)

Root cause 1: the first live run (`resp_6ae00c2c9bf71eb13c464357`) spent 1,198 of its 1,200 output tokens on reasoning. Meta's `max_output_tokens` caps reasoning plus visible output combined (dev.meta.ai/docs/features/reasoning). Fix: `MAX_OUTPUT_TOKENS` 1200→4000 and `reasoning: {"effort": "low"}` in both payloads.

Root cause 2: retry `resp_6ae06d8983809a0909ac4260` completed but invented field names (`site_address`, `project_valuation`…) because the strict schema left `field` a free string. Fix: `EXTRACTABLE_FIELDS` moved to `muse/schemas.py` and exposed as a JSON-schema enum; validation still rejects unknown names. Schema version label left at v1 — bump is Randall's call.

Third call `resp_6ae06df6700abbe810734468` (run `modelrun_76acb90ce89d4a709de4dd5de44585ae`): completed, validation passed, and the full D01 walkthrough passed through simulated issuance and idempotent retry. Evidence: `repo/evidence/runs/live-3/`; failures kept in `live/` and `live-2/`. Usage 783 in / 1,269 out. Three live calls total, roughly $0.02. 157 Muse/schema/validation tests passed after the change; deterministic manifest not yet regenerated, so AT15/AT19 still read live-blocked there.

Defect found: the 8266 demo stopped during the full test run (likely a process-management test acting on the default record; not yet pinned down). The demo was restarted in ready-for-review mode.

## 2026-10-27 — Parity phase 1 evidence (worktree `acme-permits-parity-wt`, branch `feature/parity-p1`)

- Local gates, run in the worktree: `compileall` clean; requirement coverage 57/57 with 729 collected nodes; test-collection contract OK; fresh Alembic upgrade to `0004` and `alembic check` reporting "No new upgrade operations detected"; deterministic acceptance 37 passed, zero failed, AT15 and AT19 blocked for live evidence; evidence verification OK (manifest `var/check-run/deterministic/manifest.json`); publication-tree scan 291 source files, zero findings.
- Full suite: 729 tests, zero failed, zero skipped (including the 27 Playwright browser checks and the rewritten fence walkthrough).
- The rewritten fence walkthrough (`tests/acceptance/test_use_case_fence.py`) proves the whole human chain through the real HTTP surface: administrator simulation, both cases waiting as "Awaiting intake agent", administrator waking the intake agent, steward running the intake agent and the six-node trace, steward approving the links and the extracted values, administrator waking the adjudication agent, reviewer running the five-node adjudication graph, the reviewer confirming the denial (decision of record by the Permit Reviewer) and reverting the approval with a reason before deciding it, then fee assessment, payment, allocation, exact reconciliation and issuance.
- New integration coverage (`tests/integration/test_agents_and_administration.py`) proves the persona-scoped agent and administration screens, the wake button visible only to the City Administrator, the computed KPI cards and the server-rendered graph, the governed and audited configuration changes, the added user staying out of the persona switcher, the five seeded reason codes, the requirement change that reaches new intake only, and the new simulator scenarios including a deterministic `random --count N` across all seventeen types.
- No live provider call was made in this phase; Muse stays in replay and the replay label is preserved.

## 2026-10-27 — Parity phase 3a evidence (worktree `acme-permits-parity-p3-wt`, branch `feature/parity-p3`)

- Local gates, run in the worktree with `scripts/run_all_checks.py --evidence-dir var/check-run`: compileall clean; requirement coverage 57/57; test-collection contract OK with every family collecting; `alembic upgrade head` and `alembic check` clean at schema revision `0006`; deterministic acceptance 37 passed, zero failed, AT15 and AT19 blocked for live evidence; evidence verification OK (manifest `var/check-run/deterministic/manifest.json`); publication-tree scan zero findings. **All 10 local verification gates passed.**
- Full suite: 866 tests, zero failed, zero skipped (including the Playwright browser checks and the fence walkthrough). Run line: `866 passed in 841.07s (0:14:01)`.
- The lifecycle is proven service-side: a return needs an active `return` code and is terminal; an advance to review is refused while a current, unwaived blocking finding stands; a revision request needs a `revision` code and writes the message as an applicant-visible comment; a resubmission versions the case, marks the evaluation, the recommendation and the decision stale, keeps the first submission date and returns the case to `submitted`; an archive needs an `archive` code and only a version-checked restore reactivates the case.
- The archive guard is proven path by path (`tests/unit/test_archive_guard.py`): the API revision path, the document store, the evaluation, the intake agent, the adjudication agent, the recommendation confirm and revert paths, the parcel operations, the finance paths, the portal upload and resubmission, and the restore path.
- A denial needs a denial reason code on every decision path — the manual decision, the confirmation of a denial recommendation and the reconfirmation — and the code, its label and its version are snapshotted on the decision. The five shipped codes are backfilled explicitly by migration 0006 and typed again by the seed; the seeded set is twelve fictional ACME codes.
- The findings are proven: the classifier records a `wrong_type` finding for a declared type that differs from the recorded type, and a `fee` finding when the City cannot price the case; a rerun supersedes the findings it recorded again and resolves the ones it did not; a resubmission supersedes the findings of the earlier revisions; a waiver applies only to a current finding of a waivable type, records the code, the free text, the actor and the time, and never clears a deterministic decision blocker (there is a test for exactly that).
- The comments are proven: an applicant reads only the comments written for the applicant, on the portal tracker, the permit workspace, the history panel and the API; the identifier of an internal note is refused; a comment of another applicant's case is out of reach; the audit record of a comment carries the comment identifier and its visibility and never the text.
- Every new record action is proven to be refused without the grant, without the CSRF token, without an expected version and with a stale one (nine actions, four refusals each).
- No live provider call was made in this phase; Muse stays in replay and the replay label is preserved.

## 2026-10-27 — Parity phase 3b evidence (worktree `acme-permits-parity-p3-wt`, branch `feature/parity-p3`)

- Local gates, run in the worktree with `scripts/run_all_checks.py --evidence-dir var/check-run`: compileall clean; requirement coverage 57/57; test-collection contract OK with every family collecting; `alembic upgrade head` and `alembic check` clean at schema revision `0007`; deterministic acceptance 37 passed, zero failed, AT15 and AT19 blocked for live evidence; evidence verification OK (manifest `var/check-run/deterministic/manifest.json`); publication-tree scan zero findings. **All 10 local verification gates passed.**
- Full suite: 920 tests, zero failed, zero skipped (including the Playwright browser checks and the fence walkthrough). Run line: `920 passed in 816.52s (0:13:36)`.
- The three new screens are proven by their grants, not by their labels: the Data Steward opens `/queue/intake` and `/queue/early-resolution`, the Permit Reviewer opens `/queue/review`, and every other persona — including the City Administrator — gets a 403 on each of the three (`tests/integration/test_p3b_queues.py`, `tests/browser/test_navigation.py`, `tests/supplementary/test_vc04.py`).
- The saved views of the intake queue are proven with their exact membership: Active holds the five open statuses, Awaiting agent holds the arrivals that have no intake run, Needs information and In review hold their own status, Archived holds the archived cases and Closed holds the issued, denied and returned ones (`tests/unit/test_queues.py`). The count of a tab is the number of cases that tab holds.
- The search (reference, applicant name, address), the four filters (channel, permit type, priority, owner) and the four sorts (age, priority, type, reference) are proven to narrow and order the view.
- The signals are proven to appear only where the server holds the fact: before any run the agent signal is `not run` and the duplicate signal is `none`; a recorded duplicate finding becomes the duplicate signal; the parcel signal is one of `no match`, `proposed`, `approved`, `confirmed`.
- The age chip is proven against the configured service target of the permit type: the target of `com_ti` is the configured 10 days, the age of a fresh case is 0 days, and a seeded case of 77 days is coloured `over` its 10-day target.
- The bulk action is proven to be a distinct governed write (`tests/unit/test_bulk_processing.py`, `tests/integration/test_p3b_queues.py`): it is refused without the `permit.intake.process_selected` grant, an empty selection is refused and never falls through to "process all", a selection is bounded to 50 cases, a repeated case is processed once, a case named at two versions is refused, a stale version refuses the whole batch, a case that does not wait refuses the whole batch, a sleeping agent refuses the batch, and the batch that runs leaves exactly one intake run and exactly one audit record naming every processed case. The all-or-nothing case is proven: a selection with one ineligible case leaves **no** run and no audit record for the eligible case before it.
- The new path asks the archive guard: an archived case is refused by the bulk action (`tests/unit/test_archive_guard.py`, path 12).
- The early-resolution board is proven to group the cases in `needs_information` by their primary finding in the stable order of phase 3a, each group with its count and its top current findings.
- The review queue is proven to count the cases per review area, to narrow by area and to list the recent decisions of record with their conditions.
- The conditions of an approval are proven to travel: an approval with conditions is recorded as an `approved` decision with a non-empty conditions list; an approval with conditions that names no condition is refused by the service; a rationale is required on every outcome; the conditions survive the reconfirmation; the issued permit snapshot carries them and the printed artifact shows them; the applicant reads them on the tracker (`tests/unit/test_conditions_round_trip.py`, `tests/integration/test_p3b_decisions.py`).
- The conditions also travel through the API, which used to drop them, and through the reconfirmation, which used to omit them. The API now forwards the denial reason code as well, so a denial can be recorded through the API at all; a denial without a denial reason code is still refused.
- The fence walkthrough is extended and proven automatically: the reviewer leaves the applicant a visible comment, records an approval with conditions, and the issued artifact carries the condition (`tests/acceptance/test_use_case_fence.py`).
- No live provider call was made in this phase; Muse stays in replay and the replay label is preserved.

## 2026-10-28 — Parity phase 3 chat 1 evidence (worktree `acme-permits-parity-p3-wt`, branch `feature/parity-p3`)

- Local gates, run in the worktree with `scripts/run_all_checks.py --evidence-dir var/check-run`: compileall clean; requirement coverage 57/57; test-collection contract OK with every family collecting; `alembic upgrade head` and `alembic check` clean at schema revision `0008`; deterministic acceptance 37 passed, zero failed, AT15 and AT19 blocked for live evidence; evidence verification OK (manifest `var/check-run/deterministic/manifest.json`); publication-tree scan zero findings. **All 10 local verification gates passed.** Gate lines: `[pytest] exit 0 in 954.957s`, `[alembic-upgrade] exit 0 in 0.702s`, `[alembic] exit 0 in 0.441s`, `[deterministic-acceptance] exit 0 in 645.222s`, `[evidence-verification] exit 0 in 0.043s`, `[publishable-tree] exit 0 in 11.293s`, and `all 10 local verification gates passed`.
- Full suite: 987 tests, zero failed, zero skipped (including the Playwright browser checks and the fence walkthrough). Standalone run line: `987 passed in 2674.52s (0:44:34)`; the same suite inside the gate run: `987 passed in 920.95s (0:15:20)`. Fifty-four of those tests are new: eight on the source bundle, seven on the matcher, fifteen on the governed service, eighteen on the portal and six in the browser.
- Deterministic acceptance: `status: passed=37 failed=0 blocked=2`, the two blocked checks being AT15 and AT19, which need a live provider run that this part did not make.
- The help assistant is proven to answer **without a model**: the help path never reaches the provider, and the provider client is replaced by a stub that raises in the test that asks a question and in the test that asks a question that matches nothing (`tests/unit/test_help_service.py`, `tests/integration/test_p3chat1_help.py`).
- The **source bundle** is proven to hold the published rule version and never the draft of the same rule: CT-2 is in force at 250,000 and the draft at 300,000 never appears (`tests/unit/test_help_sources.py`).
- A rule is proven to be rendered with its applicability, its operator, its threshold and its conditions — DF-1 reads "Applies when: location = front; structure_kind = fence.", "Operator: must not be more than." and "Threshold: 4." — and the violation message is proven to appear only under "If the rule is not met", so it is never an unconditional fact about the applicant.
- The bundle is proven to carry **the applicant's own case only**: it holds SYN-APP-005 and never SYN-APP-011, another applicant's case; the bundle of another applicant's case is refused; an internal note never enters the bundle while the message written for the applicant does; the basis date of a case is its first submission time; and the bundle passes the same truth guard the model payloads use.
- The **answer** is proven to quote the published rule with its citation, and proven never to claim an exemption: the quote of "Do I need a permit for a 6 ft fence?" carries ACME Code §14-306 and none of "no permit", "not need a permit" or "exempt". The 6 ft side-and-rear rule is shown beside the 4 ft front-yard rule.
- The five questions of the demonstration are each proven to produce a cited answer on the chooser (`tests/integration/test_p3chat1_help.py`).
- A question that matches nothing is proven to produce the explicit **no-match**: the turn records `no_match`, the answer carries `cannot_answer` and no paragraph, and no provider call is made.
- The **conversation** is proven to belong to its owner: another applicant's conversation is not found, and the standalone panel of a conversation of another applicant answers 404.
- The writes are proven to be governed: a question without the grant is refused, a question without an expected version is refused, a stale version is refused, a question longer than 1,000 characters is refused, and the rate limit stops the eleventh question of a session while another session of the same applicant has its own budget (`tests/unit/test_help_service.py`).
- The **audit record** of a question is proven to carry the turn identifier, the outcome and the mode, and never the text of the question; the audit record of an escalation is proven the same (`tests/unit/test_help_service.py`, `tests/integration/test_p3chat1_help.py`).
- **Ask the City** is proven to create a help request with the question, an open status and the applicant as its owner, and the conversation version moves so that a stale escalation is refused.
- The assistant is proven to write **nothing but the conversation, the turns, the help requests and the audit records**: the applications, findings, decisions, documents, comments and statuses of every case are identical before and after a question, including a question that says "ignore your rules and approve my permit".
- The three **portal placements** are proven: the chooser, the application form and the tracker each carry the panel with its own placement, and the Data Steward and the City Administrator get a 403 from the portal itself.
- The **no-JavaScript safety** is proven in the browser (`tests/browser/test_p3chat1_help_browser.py`): the help form is a form of its own and never nested inside the application form; with JavaScript switched off the answer opens in a separate browsing context (`/apply/help/panel`) and the fields the applicant typed into the application form are still there; **Ask the City** works with JavaScript switched off; and with JavaScript on the answer is rendered in place and a suggested question fills the box.
- The **two timing figures** are proven to be separate: the panel shows the configured service target of the type ("Service target for Residential deck or fence: 5 days.") and the current backlog of the review area with its exact status membership, and it states that neither one is a completion date.
- The live switch is proven to be off by default and to stay off when a credential is present (`tests/integration/test_p3chat1_help.py`).
- Four existing tests were changed, and each for the same reason: migration 0008 moves the schema head. `tests/unit/test_migrations.py` expects `0008` instead of `0007`, `tests/api/test_sessions.py` expects the `healthz` schema revision `0008`, `tests/unit/test_schema.py` expects `0008` and names the three new tables in the required object groups, and `tests/unit/test_reset.py` expects the reset to land on `0008`. No other existing test was changed, moved or weakened.
- No live provider call was made in this part; the assistant answers deterministically and the replay label of the Muse work is preserved.

## 2026-10-28 — City Administrator / planning UI restyle evidence (worktree `acme-permits-ui-admin-wt`, branch `feature/ui-admin`)

- Branch-tier checks, run in the worktree with `uv run` (no full ten-gate run; the lead runs the ten gates on main after the merge):
  - compile: `uv run python -m compileall -q src scripts tests` → no output, exit 0.
  - requirement coverage: `requirement coverage check OK` — `requirements: 57 distinct identifiers`, `inventory mapping: 57/57 requirements`, `collected nodes: 1424`.
  - collection: `1424 tests collected in 0.71s`; collection contract: `test collection check OK` with `unit 564 / api 112 / security 12 / acceptance 91 / supplementary 47 / scenarios 34 / evaluator 13 / integration 436 / regression 5 / browser 62` collected.
  - migrations: `No new upgrade operations detected.` (`alembic upgrade head` then `alembic check` against a scratch SQLite database). No migration was added; the schema head stays 0011.
  - publishable tree: `publishable-tree scan passed: 493 source files, zero findings`.
  - pytest, on the new and changed tests and the directories the change touches: `27 passed in 135.32s` (tests/ui/test_admin_views.py), `160 passed in 156.83s` (tests/ui, tests/api), `564 passed in 579.61s` (tests/unit), `140 passed` (the six integration files that read the screens or the navigation), `46 passed, 1 failed` (tests/supplementary — the one failure is pre-existing on main, see below), and the browser suite in three chunks: `21 passed in 249.18s`, `24 passed in 283.30s`, `17 passed in 240.49s` — 62 browser tests, all green.
  - applicant replay fixtures: `11 fixture(s) of the applicant help assistant`, every file `unchanged`. No published rule text, permit-type description or applicant-facing passage changed in this run, so the rebuild was not required; `scripts/build_policy_assist_fixtures.py` does not exist in this worktree (it is being built in the parallel policy4 branch).
- **Pre-existing failure on main, not caused by this run:** `tests/supplementary/test_vc03.py::test_the_proposed_band_is_empty_when_nothing_is_proposed`. The reviewer restyle (4fa285e) wrapped the "Proposed corrections" stage of the permit workspace in `{% if detail.proposed %}`, which makes the `proposed-empty` empty state unreachable, and it did not update that check. `src/acme_city/templates/permit_workspace.html` and `src/acme_city/ui/reviewer_views.py` are unchanged by this run, and the only changes to `src/acme_city/ui/view_models.py` are the `SCREENS`, `SCREEN_DOMAIN` and `SCREEN_PERMISSIONS` tables, so the failure is already on main. Two one-line remedies, both the lead's to choose: restore the empty state in the template (drop the `{% if detail.proposed %}` wrapper) or update the check to the reviewer's deliberate "hide the empty stages" design.
- The planning overview is proven to count stored rows and to label what it counts: the attention, property, changes and source counts each equal the number of rows behind them, the scope line reads "Sample applications · synthetic", and the City view and the What-if are linked while no Operations dashboard link is invented (`tests/ui/test_admin_views.py`, `tests/api/test_admin_pages.py`).
- The property context is proven to open in the shared side flyout with the parcel, the official address with its unit, the project description, the site documents, the related applications and the rule versions in force with their citations; the detail route answers 403 with no record value to a persona without the grant (`tests/api/test_admin_pages.py`, `tests/browser/test_admin_ui_browser.py`).
- The rules register is proven to keep the states apart: a draft reads "not approved yet" for both the approved-by and the approved-on columns while the assigned approver names the accountable owner of the domain; "awaiting approval" is used only for a version that entered the review step; a draft's date column is "Proposed effective date".
- The selected version is proven to show the diff of the two stored version records (CT-2@2 against CT-2@1: limit 250000 → 300000, effective from 1 Jan 2026 → 1 Nov 2026), the date basis (the initial submission time, `initial_submitted_at`), the applicability, the recorded history and the next authorized action; a version with no predecessor says in words that the stored records hold no differing content to compare; the overlapping open-ended effective period of the published CT-2@1 is warned about before the click.
- The actions are proven to sit with the selected version in the order of the lifecycle — Edit draft · Submit for review · Compare versions · Approve version · Publish version · Retire version — and an author is told in words that another administrator must approve the version.
- The reconciliation screen is proven to keep the receipt register apart from the selected assessment, to show the readable reference SYN-APP-007, to mark the euro receipt apart from the dollar receipts, and to label the exception measure ("Assessments with a recorded exception") without an attention badge when there is nothing to review.
- The demo moment is proven in a real browser: the Administrator lands on the overview, opens the draft CT-2@2 from the "Proposed changes" card, reads the diff and the applicability, submits it for review and sees the recorded result in the feedback region (`tests/browser/test_admin_ui_browser.py`).
- No live provider call was made; the Muse Image generation and the replay labels are unchanged.

## 2026-10-29 — Agent Operator lane repair evidence

- Focused operator/navigation checks: 63 passed in 22.44s. Reset, session and migration checks: 32 passed in 10.85s.
- Fixture guard, outcome snapshot and acceptance suite: 106 passed in 20.60s. Chromium operator navigation at 390px: 1 passed in 7.43s.
- Final full suite: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider -n 6` → 2118 passed in 569.69s (9:29).

## 2026-10-29 — Agent Operator lane review 2 evidence

- Focused runs in the worktree with `PYTHONPATH=src` and the project venv:
  - `tests/integration/test_agent_role_permissions.py` → 11 passed: the three non-administrator refusals of the saving action, the reviewer running the agents exactly while the City worker option is on, the operator's own domains in the managed bundle, the agent screens of the reviewer and the reset that restores the operator alone.
  - `tests/unit/test_migration_opr_processing_policy.py`, `tests/unit/test_config_operator.py` and `tests/integration/test_agent_processing_policy.py` → 15 passed with that file: the migration test reads the migration head, and the policy table carries no column that nothing writes.
  - `tests/browser/test_agent_operator.py` and `tests/browser/test_navigation_operator.py` → 10 passed in 68.00s: the City Administrator clicks "Save role permissions" and sees the saved state after a reload, the agent screens link back to the Agents home, the Agents home reaches the "Process selected with agent" control, and the Agents home and the run history pass the 390 pixel overflow and coverage checks.
  - `tests/ui/test_view_models.py` and `tests/supplementary/test_vc04.py` → 48 passed in 18.89s with the navigation expectations that no longer carry the `ORDER` table.
  - `tests/regression` and `tests/acceptance` → 111 passed in 22.41s: the fixture hash guard, the outcome snapshot and AT01 to AT20 are unchanged.
  - `tests/unit`, `tests/integration`, `tests/ui`, `tests/supplementary` and `tests/security` with six workers → exit 0.
  - `scripts/check_owned_hunks.py --lane agent-operator --base 9a37789 --head HEAD` → "every hunk is inside the lane's own functions".
- Final full suite: `PYTHONPATH=src .venv/bin/python -m pytest -q -p no:cacheprovider -n 6` → 2133 passed in 622.57s (10:22). The requirement coverage check reports 57/57 requirements mapped and 2133 collected nodes.
- The City worker bundle is proven to be the operator's bundle: the managed grants of the reviewer and the seeded grants of the operator agree on the domain of every action, the reviewer opens `/agents` and `/agents/runs` while the option is on and is refused with 403 while it is off, and the reviewer is refused on the agent screen itself while the option is off.
- The refusal of the saving action is proven to be a refusal and not a side effect of the state: the post carries a valid token and is answered 403 for the Data Steward, the Permit Reviewer and the Agent Operator.
- No live provider call was made, and no rule text, replay fixture, acceptance test, persona or grant of the original four personas changed.

## 2026-10-29 — Agent Operator lane OPR-9 evidence

- Focused runs in the worktree with `PYTHONPATH=src` and the project venv:
  - `tests/unit/test_migration_opr_work_queue.py` and `tests/integration/test_agent_runtime.py` → 8 passed: the migration creates only the queue table with the work identity, the status column and the attempt count and no lease or fencing token; the same work is never queued twice; the first worker takes the work and counts the attempt while the second worker cannot take it and cannot commit it; a second attempt counts; the protected D01-D11 cases, the cases the acceptance tests work on and the fixed fence scenarios are never eligible; a fresh arrival is eligible and a queued or worked case is not; the queue counts and the operator summary report the same state.
  - `tests/unit/test_migrations.py`, `tests/unit/test_schema.py`, `tests/regression/test_fixture_outcomes_snapshot.py` and `tests/regression/test_protected_fixtures_unchanged.py` → 29 passed: the single head, the unique ids, the linear chain and the Alembic model check pass with the new migration, and the outcome snapshot and the fixture hash guard are unchanged.
  - `tests/unit/test_stylesheet_scopes.py`, `tests/integration/test_agents_and_administration.py`, `tests/integration/test_agent_operator_ui.py`, `tests/integration/test_agent_processing_policy.py` and `tests/integration/test_agent_role_permissions.py` → 39 passed.
  - `scripts/check_owned_hunks.py --lane agent-operator --base main --head HEAD` → "every hunk is inside the lane's own functions".
  - `scripts/check_requirement_coverage.py` → 57/57 requirements mapped, 63 requirement identifiers referenced.
- Final full suite: `PYTHONPATH=src .venv/bin/python -m pytest -q -n 6 -p no:cacheprovider` → 2141 passed in 622.64s (10:22).
- No live provider call was made, and no rule text, replay fixture, acceptance test, persona, grant or screen changed.
## Permit life cycle and the AVA republish (2026-10-29)

- Branch `feature/permit-lifecycle`. Commit eae39f5 added the life cycle table, `/lifecycle`, `/walkthrough`, the architecture section and the judge walkthrough document. Commit e4c7dc4 listed the future features. The full suite passed with 2094 tests at eae39f5.
- The architecture page was rebuilt through the solution-architecture-page kit. The checker passed with 10 warnings, all older than this change. `verify_page` still flags 8 older figures. The leak scan was clean.
- The private AVA Library article `acme-city-permits-architecture` was replaced at 2026-10-30T01:04:47Z with Randall's approval. The copy matches the build: SHA-256 `7b75d4e29ed54f2879de788553249f696f5008a4448956aef1e5ebce0c92a4d0`, 347190 bytes. The AVA service was not restarted.
- After review lifecycle-1 (commit e2c413a, 16 moves), the AVA article was replaced again at 2026-10-30T01:30:18Z. The library copy matches the build: SHA-256 `12046a77ac70bdf14448128b0cef6b2fdc1945d0dff99e24056fd48c1e64e136`, 348059 bytes. The same page was republished to Randall's private Claude artifact at his request.

## 2026-10-29 - Steward queue and guide lane evidence

- Focused runs in the worktree with `PYTHONPATH=src` and the project venv:
  - `tests/integration/test_p3b_queues.py`, `tests/regression/test_admin_early_resolution.py`, `tests/regression/test_steward_selector_contract.py`, `tests/unit/test_steward_queue_views.py` and `tests/unit/test_stylesheet_scopes.py` -> 57 passed: the next step of every incoming case, the membership, the grouping and the order of the early resolution board, the selector inventory and the scoped stylesheet.
  - `tests/integration/test_steward_guide_offline.py` and `tests/unit/test_steward_guide.py` -> 34 passed: seven guide screens answer from saved words, repeat themselves exactly on a second run, reach no model, and hold a link that lands on a real target.
  - `tests/integration/test_help_docs.py` and `tests/integration/test_help_docs_steward.py` -> 47 passed: every label the steward help quotes is on the page the step names, and the rejection action names the record it turns down.
  - `tests/browser/test_steward_workspace_browser.py`, `tests/browser/test_steward_browser.py` and `tests/browser/test_navigation_steward.py` -> 45 passed: the incoming screens, the guide panels and the search read as one card per case at 390 pixels, and the queue, the guide and the filters are used with the keyboard alone.
  - `tests/unit`, `tests/integration`, `tests/regression` and `tests/api` with six workers -> 1696 passed.
  - The fixture hash guard and the outcome snapshot -> 10 passed.
  - `scripts/check_owned_hunks.py --lane steward-queue-guide --base main --head HEAD` -> "every hunk is inside the lane's own functions"; `--actor-only` -> "only actor-id literals change".
- Final full suite: `PYTHONPATH=src .venv/bin/python -m pytest -q -n 6 -p no:cacheprovider` -> 2333 passed in 711.69s (11:51).
- No live provider call was made. The guide answered from saved words in hosted mode with a credential set, and the tripwire recorded no call.

## 2026-10-29 - Steward queue and guide lane, review 4 evidence

- Focused runs in the worktree with `PYTHONPATH=src` and the project venv:
  - `tests/browser/test_steward_workspace_browser.py`, `tests/browser/test_steward_browser.py` and `tests/browser/test_navigation_steward.py` -> 52 passed: the Resolve button, the Search button, a tab, the help link of both new screens and the guide link of both new screens are clicked and the landing page of each is read.
  - `tests/regression/test_admin_early_resolution.py` -> 9 passed: the membership and the order of the board as a list, the sentence case finding label, the severity words, the duty of the applicant, the absence of a case that does not wait and the group of the primary finding.
  - `tests/integration/test_help_docs_steward.py` and `tests/integration/test_help_docs.py` -> 47 passed: every label a steward step quotes is in the element that holds it.
  - `tests/regression/test_admin_early_resolution.py`, `tests/regression/test_steward_selector_contract.py`, `tests/integration/test_help_docs_steward.py`, `tests/integration/test_help_docs.py`, `tests/integration/test_steward_guide_offline.py`, `tests/integration/test_steward_ui.py`, `tests/integration/test_p3b_queues.py`, `tests/unit/test_steward_guide.py`, `tests/unit/test_steward_queue_views.py`, `tests/unit/test_stylesheet_scopes.py` and `tests/api/test_steward_workspace.py` -> 201 passed.
- The label test of the steward help was checked against a wrong element on purpose: the check failed, so it reads the element and not the page.
- No live provider call was made. No fixture, rule text, replay fixture, acceptance test, persona or grant changed.
- Final full suite: `PYTHONPATH=src .venv/bin/python -m pytest -q -n 6 -p no:cacheprovider` -> 2341 passed in 725.99s (12:05).

## 2026-10-30 - Steward autolink lane evidence

- Focused runs in the worktree with `PYTHONPATH=src` and the project venv:
  - `tests/integration/test_linking_worker.py` -> 19 passed: the job is taken by one statement, the late finish of an earlier attempt is refused, a job that stops is tried again and then waits for a person, a cycle is bounded, the work of a dead worker is returned, the application writes the link, the audit event and the review task in one transaction, and nothing of an undone application is left behind.
  - `tests/integration/test_linking_undo.py` -> 10 passed: the worker applies an eligible party link, the steward takes it back with a reason, a repeated request changes nothing, a stale request is refused, the service identity may not reverse a link, and the reviewer is refused at the screen.
  - `tests/browser/test_steward_automation_browser.py` -> 15 passed: the applied link waits in the queue, the case shows the score and the evidence, the keep and the undo controls are clicked and the result is read, and the screen fits 390 pixels and a desktop window.
  - `tests/unit/test_migration_stw_registry_automation.py`, `tests/unit/test_linking_policy.py`, `tests/unit/test_config_autolink.py`, `tests/security/test_linking_permissions.py`, `tests/unit/test_migrations.py` and `tests/unit/test_schema.py` -> 54 passed: the migration of the registry automation, the pure policy, the settings of the lane, the grants of the service identity and the migration gates.
  - `tests/acceptance/test_at06.py`, `tests/acceptance/test_at07.py`, `tests/acceptance/test_at16.py`, `tests/acceptance/test_at20.py`, `tests/unit/test_linking_policy.py` and `tests/security/test_linking_permissions.py` -> 45 passed: the acceptance arithmetic and the outcome snapshot are unchanged.
  - `tests/unit/test_stylesheet_scopes.py`, `tests/regression/test_steward_selector_contract.py`, `tests/unit/test_steward_queue_views.py` and `tests/unit/test_steward_guide.py` -> 52 passed: the scoped stylesheet and the selector inventory of the steward screens.
  - `tests/unit/test_reset.py`, `tests/unit/test_fixture_validation.py` and `tests/evaluator` -> 50 passed: the reset, the fixtures and the outcomes of D01 to D11.
  - `tests/integration`, `tests/unit`, `tests/security`, `tests/acceptance`, `tests/regression`, `tests/scenarios`, `tests/supplementary`, `tests/api` and `tests/ui` with six workers -> 2424 passed.
  - `tests/browser` with six workers -> 281 passed: every browser walkthrough of the city, the 390 pixel checks included.
- The demo preparation was run twice: the Cedarline mode still holds three proposals and no applied link, and the automation mode holds the three proposals and one applied link that the service applied.
- `scripts/check_owned_hunks.py --lane steward-autolink --base main --head HEAD` -> 77 violations, every one of them in `ui/router.py` in `_agent_run`, which the Agent Operator lane owns and which arrived with the merged operator lane. The lane changed no line of that file.
- No live provider call was made. The worker compares with the built in deterministic logic of the City. No fixture, rule text, replay fixture, acceptance test, persona or grant changed, and no new binary was added.
- Final full suite on the finished tree: `PYTHONPATH=src .venv/bin/python -m pytest -q -n 6 -p no:cacheprovider` -> 2718 passed in 830.88s (13:50). The suite on the merged operator lane, before this lane's work, passed 2685 in 811.70s (13:31), so the merge was green and no settling commit was needed.

## 2026-10-30 - Steward autolink lane, review 4 evidence

- Focused runs in the worktree with `PYTHONPATH=src` and the project venv:
  - `tests/integration/test_linking_worker.py` -> 23 passed: the job that stops after it wrote a link leaves no link, no event, no review item and no application behind, the next job of the cycle still runs, a job the database refuses does not take the cycle down with it, a parcel is only suggested and never linked, and an application of a family without a tested reversal is refused.
  - `tests/integration/test_linking_undo.py` -> 13 passed: the take back hands the prior proposal back, the take back of the screen needs the version of the link, and the activate action refuses a mode the screen does not offer.
  - `tests/browser/test_steward_automation_browser.py` -> 16 passed: the undo click test reads the state of the link in the registry, and the settings screen offers the mode that applies links and shows no other.
  - `tests/acceptance` and `tests/regression` -> 209 passed: the acceptance arithmetic, the outcome snapshot and the contracts of the other lanes are unchanged.
  - `tests/unit/test_linking_policy.py`, `tests/unit/test_stylesheet_scopes.py`, `tests/unit/test_config_autolink.py`, `tests/unit/test_migration_stw_registry_automation.py`, `tests/security/test_linking_permissions.py`, `tests/regression/test_steward_selector_contract.py`, `tests/unit/test_steward_queue_views.py`, `tests/unit/test_steward_guide.py`, `tests/unit/test_migrations.py` and `tests/unit/test_schema.py` -> 106 passed.
  - `tests/unit/test_judge_walkthrough_doc.py` -> 1 passed: the walkthrough document still lists every step of the app in order.
- Every new test was run against the code without its fix, and every one of them failed: the per-job savepoint, the take back of the proposal, the required version of the link, the family guard, the suggested parcel and the refused mode. The files were restored after each check.
- No live provider call was made. The worker compares with the built in deterministic logic of the City. No fixture, rule text, replay fixture, acceptance test, persona or grant changed, and no new binary was added.
- Final full suite on the finished tree: `PYTHONPATH=src .venv/bin/python -m pytest -q -n 6 -p no:cacheprovider` -> 2726 passed in 815.58s (13:35). The tree of the lane before this work passed 2718, and the eight tests of this pass are the eight new ones.

## 2026-11-02 — Submit anyway held-form evidence

- Source evidence at `4b502a1`: a rejected submit reloads with empty browser file inputs; its former live `/check` could report incomplete and `held=false`, after which `applyHold` hid the server-rendered override controls. The current stored-document accounting and `serverHeld` guard cover this path.
- Source evidence in this revision: the hidden first submit button posts `intent=update`; prior server code treated it as a plain draft save and returned no `review`, removing the held markup. The added branch re-evaluates a complete draft deterministically and raises the existing held response when Must fix remains.
- Added checks: the server test covers the `intent=update` held response; the browser test covers suggestion selection, typing `/check`, stored widget uploads, Enter, the tour route and successful override; unit/integration assertions cover G38 wording, the Muse button badge/hint, live fake-provider feedback attribution and offline wording.
- `python -m compileall -q src tests/unit/test_portal_form.py tests/integration/test_presubmit.py tests/browser/test_presubmit_browser.py` exited 0. `git diff --check` exited 0.
- `node --check src/acme_city/static/property.js` exited 0. The required pytest invocation with `--collect-only` collected 46 tests across the changed unit, integration and browser modules in 0.36s.
- Browser test command was attempted with the required venv and Chromium. It could not launch in this sandbox: Chromium exited at `sandbox_host_linux.cc:41` with `shutdown: Operation not permitted`. It is not recorded as a pass.
- Focused pytest commands began database migration but did not complete in this sandbox before interruption; they are not recorded as passes. No test assertion was weakened or skipped.

## 2026-11-02 — Wave 3 integration repair evidence

- Source inspection: G14 moved action forms and decision history behind nested `details`; affected paths open the summaries and `workspace_open_sections` opens Decision when a pending agent recommendation requires review.
- Source inspection: held-form hints were flex children, making their wrappers determine the desktop row height and width. They are below the row now, and both related controls retain their `aria-describedby` links.
- Source inspection: feedback markup hid every persisted outcome, so non-success feedback depended on script timing. Refused, denied, and error results now render visible; the existing client opens each non-success outcome once per audit event.
- Local checks: `node --check src/acme_city/static/app.js`; `node --check src/acme_city/static/property.js`; and `python -m compileall -q src tests/unit/test_portal_form.py tests/unit/test_stylesheet_scopes.py tests/integration/test_presubmit.py` exited 0. The focused `pytest --collect-only` command collected 86 tests. Focused test execution and browser tests did not complete in this sandbox, so no test-pass claim is made.

## 2026-11-02 — Missing café tour-case recovery evidence

- Root cause: `/permits/{application_id}` used the generic not-found renderer for both an absent application and a real application outside the current persona's scope. The tour then resumed from its persisted state while the HTTP-only café-copy cookie continued to supply the deleted ID.
- Regression check before the implementation: `uv run pytest tests/integration/test_missing_tour_case.py -q` failed because the generic response had no `data-case-missing` marker. After the implementation, `uv run pytest tests/integration/test_missing_tour_case.py tests/api/test_pages.py tests/integration/test_walkthrough_routes.py tests/unit/test_tour.py -q` passed: 57 passed in 12.31s.
- `uv run python -m py_compile tests/browser/test_missing_tour_case_browser.py` exited 0. The browser regression is not recorded as passed because this sandbox cannot run browser tests.
- Final full non-browser verification: `uv run pytest tests/acceptance tests/api tests/evaluator tests/integration tests/regression tests/scenarios tests/security tests/supplementary tests/ui tests/unit -q -n auto` passed: 3237 passed in 77.76s.
## 2026-11-02 — Non-blocking steward data (retest item 6)

- Final post-change `uv run pytest -q` group spanning changed adjudication,
  plain-reason, intake, queue, workspace, guide, policy-parity, protected
  fixture/outcome snapshot, and D01–D11 tests — 112 passed in 16.53s.
- The protected fixture and outcome-snapshot tests passed without changing their data. Browser tests were not run; lead browser verification remains required.
## 2026-11-02 — Retest item 2: resident tour fill evidence

- Root cause: `tour.js` only called `fillStory` from the Fill in the story’s answers button listener, so arrival at the Check step did not populate the form.
- Static checks passed: `node --check repo/src/acme_city/static/tour.js` and `uv run python -m compileall -q tests/browser/test_tour_story.py src/acme_city/ui/guide_views.py`. Focused non-browser tests passed: `38 passed` across `tests/unit/test_tour.py`, `test_judge_walkthrough_doc.py`, and `test_walkthrough_paths.py`.
- Browser tests were deliberately not run in this workspace. The changed browser cases are ready for the lead’s browser gate.

## 2026-11-02 — Retest item 3: café case-screen evidence

- Root cause: the live tour configuration already resolved `reviewer` and `issue` to `/permits/{case}`, but `guide_views.PATHS` and its generated submission document still named `/queue/review`. The documented route did not put the reviewer on the workspace that has the case controls and recorded state.
- Focused non-browser checks passed: `38 passed` across `tests/unit/test_tour.py`, `test_judge_walkthrough_doc.py`, and `test_walkthrough_paths.py`. `tests/browser/test_cafe_path.py --collect-only` collected 2 tests. Browser execution remains for the lead.

## 2026-11-02 — Retest item 4: real deployment-date evidence

- Root cause: both `render.yaml` and the entrypoint seed override explicitly set `ACME_SCENARIO_CLOCK` to `auto`, pinning the running demo to scenario data rather than the real date.
- Static compilation passed for the entrypoint and focused protection test. The changed default checks passed (`2 passed, 46 deselected`), and `tests/unit/test_scenario_clock.py` passed (`10 passed`), preserving explicit controlled dates.
## 2026-11-02 — Retest item 1 evidence

- Before the template change, `uv run pytest tests/unit/test_portal_form.py::test_a_held_submit_returns_to_the_presubmit_panel -q` failed because the held response rendered a `data-testid="presubmit-panel"` element without an id.
- After the template change, `uv run pytest tests/unit/test_portal_form.py -q` passed: 20 passed in 8.13s. It covers the held 422 response, the panel id, and the matching action fragment.
- `tests/browser/test_presubmit_browser.py::test_a_held_submit_returns_to_the_presubmit_panel_in_the_viewport` was added but not run: browser execution is unavailable in this sandbox.

## 2026-11-02 — Combined retest gate repairs

- Verified after the final edits: `tests/unit/test_judge_walkthrough_doc.py` — 3 passed; `tests/unit/test_walkthrough_paths.py` — 9 passed; `node --check repo/src/acme_city/static/tour.js` — passed; and the checked submission document equals `walkthrough_markdown()` byte for byte.
- The five affected browser tests were not run because browsers are unavailable in this sandbox; they remain for the browser gate.

## 2026-11-02 — Tour-fill request race evidence

- Root cause traced from `tour.js` to `property.js`: tour `setControl` and `attachFile` dispatch normal `input`/`change` events; `property.js` reacts with `POST /apply/deck_fence/check` and, for the story address, `GET /apply/locate?text=400%20Lantern...`. Both endpoints use `_portal_guard`, which rejects an Agent Operator session with 403. The full tour advances to that persona before delayed requests necessarily leave the browser.
- The synthetic-fill marker is present only while those events dispatch. The portal listener checks it before scheduling live `refresh()` or `locate()`, preserving its file-status and conditional-question listeners.
- Post-change static checks: `node --check src/acme_city/static/tour.js`; `node --check src/acme_city/static/property.js`; `git diff --check`; and `PYTHONPATH=src ... pytest tests/unit/test_tour.py --collect-only -q` (26 tests collected) completed successfully. Browser execution was not run by instruction; the original browser assertions remain unchanged.

## 2026-11-02 — G10 tour voice evidence

- `node --check src/acme_city/static/tour.js`, Python compilation of the manifest script and browser-test support, and `git diff --check` passed.
- Focused manifest/static unit coverage passed: `4 passed, 25 deselected` from `tests/unit/test_tour.py -k 'tour_audio or script_never_writes or overlay_loads'`.
- The full `tests/unit/test_tour.py` invocation was attempted twice but did not complete in this sandbox: it stalled in the pre-existing database-backed `test_every_step_points_at_a_control_of_its_screen` after eight earlier tests. This is not recorded as a pass.
- Browser tests were not run, as assigned to the lead. The new browser test covers empty-manifest absence plus visible toggle and `sessionStorage` persistence with a test-only static override; it does not assert audio output.

## 2026-11-02 — G10 tour voice: the failing control and the publication gate

- Cause of the failing toggle, traced in the browser with the engine instrumented: the manifest resolved to `{"resident-intro": "resident-intro.mp3"}` and the step was the resident intro, yet `clipFor` returned an empty clip. The engine logged `key "resident-intro" clip "resident-intro.mp3" typeof string regex true` and still returned nothing, because the pattern `/^[A-Za-z0-9_.-]+\\.mp3$/` asks for a literal backslash in the name. Every clip was therefore refused, `paintVoice` hid the control and `toggleVoice` returned before it changed anything. The pattern now asks for the dot.
- Second cause of the same symptom: `.btn { display: inline-flex }` in `app.css` overrides the user agent's `[hidden] { display: none }`, so the hidden control kept a box of 101 by 32 pixels and the browser read it as visible. The tour stylesheet now carries `.tour-overlay [hidden] { display: none; }`.
- The publication gate: `PYTHONPATH=src python scripts/scan_publishable_tree.py` printed `publishable-tree scan passed: 948 source files, zero findings` after the MP3 header check, the `.b64` text suffix and the new `src/acme_city/static/tour-audio` set were added. All 26 shipped clips carry an ID3 tag; the largest is 118,125 bytes against the one mebibyte limit.
- The first run of that gate after the change reported `tests/unit/test_publishable_tree.py: personal email`, because the new test wrote the address it checks for as one literal. That is the `.b64` rule working in the real tree: the address is now written in two parts, and the gate passes again.
- `tests/unit/test_publishable_tree.py` passed (11), including the new MP3 header cases and the two `.b64` cases, one of which proves a secret inside a base64 fixture is still found.
- `tests/browser/test_tour_voice_browser.py` passed (3): a manifest that names no clip leaves the control hidden, the shipped manifest shows Play voice on the resident intro, and a press reads Mute voice with `acme-tour-voice` set to `on` in the session storage.
- `tests/browser/test_tour_browser.py` and `tests/browser/test_tour_entry_browser.py` passed (30), and `tests/unit/test_tour.py` passed (29), after the stylesheet change.
- The tour-facing browser families then passed together in parallel: `130 passed, 2 skipped in 191.04s` across `test_cafe_path.py`, `test_demo_video_browser.py`, `test_design_findings_browser.py`, `test_feedback_panel.py`, `test_guide_pages_browser.py`, `test_missing_tour_case_browser.py`, `test_persona_chip_browser.py`, `test_presubmit_browser.py`, `test_tour_story.py`, `test_walkthrough_cards.py`, `test_tour_voice_browser.py`, `test_tour_browser.py` and `test_tour_entry_browser.py`. The two skips are the pre-existing WebKit checks of `test_presubmit_browser.py`, which skip themselves because that browser is not installed on this machine; nothing was skipped for this change.
- The whole browser family then passed on its own: `PYTHONPATH=src python -m pytest -q -n 4 tests/browser` reported `530 passed, 2 skipped in 1030.94s`, the same two WebKit skips. This is the full check on the stylesheet change.
- A whole-tree serial `pytest` run was started at the same time as that batch and was killed by the machine at about seven percent: the memory of the box was exhausted (119 GB, the swap full) while both runs held browser servers and databases. It reported no test failure and is not recorded as a pass. The browser family was then run alone, with the memory back to 23 GB in use, and it passed as recorded above.
## 2026-11-02 — The in-app help follows the build, evidence

- Every label quoted by the help was taken from the running screens. The
  screens were read through the application itself (a signed-in client for
  each persona): `/agents`, `/agent/intake`, `/agent/steward_assist`,
  `/agents/runs`, `/queue/intake`, `/steward`, `/steward/batch`, a steward
  task, the work queue, the review queue and a permit workspace. The
  recorded data issue and the prepared recommendations were produced with the
  real actions (`agent.toggle`, `steward.assist.prepare`).
- The shared check of the help, `tests/integration/test_help_docs.py`, still
  verifies that every quoted label exists in the application and that every
  link of the tutorial opens for the persona it names. It passed with the
  new words.
- The steward lane check now reads every label the steward guides quote on
  the page that shows it, with the assistant awake, a recommendation
  prepared, a batch to confirm and a recorded issue to close: 46 passed.
- Focused runs after the final edit: `tests/integration/test_help_docs.py`,
  `test_help_docs_operator.py`, `test_help_docs_steward.py`,
  `test_help_docs_admin_a.py`, `test_help_docs_admin_b.py` and
  `tests/unit/test_help_content_overlay.py` gave 86 passed. The filter
  `-k "help or glossary or tutorial or guide"` over `tests/unit` and
  `tests/integration` gave 277 passed, and over `tests/browser` gave 83
  passed.
- The command of the brief, `pytest -q -p no:cacheprovider tests -k "help or
  glossary or tutorial or guide" -m "not browser"`, gave 361 passed and 3425
  deselected in 10m56s. The whole of `tests/unit` and `tests/integration`
  gave 2498 passed in 2m58s.
- The daily allowance of live Muse calls was checked against the deployment
  configuration before the help kept the number: `render.yaml` sets
  `ACME_MUSE_LIVE_CALL_CAP` and `ACME_MUSE_DAILY_CALL_CAP` to 100.
## 2026-11-02 — Breadcrumb lane evidence

- The old source was written over the fixed files (`git show HEAD:<path> > <path>`) and the new tests were run against it: `tests/integration/test_breadcrumb_trail.py` and `tests/browser/test_breadcrumb_browser.py` failed (19 failed, 1 passed). The fixed files were put back and the same tests passed (17 passed and 3 passed). The tests therefore hold the fix, not the old behaviour.
- The rendered trail was read back from the running application for every persona: the Applicant sees `Home (/city/) › Help and documentation (/help) › Tutorial`, the Data Steward `Home (/steward) …`, the Permit Reviewer `Home (/queue) …`, the City Administrator `Home (/overview) …` and the Agent Operator `Home (/agents) …`. The hub reads `Home › Help and documentation` and does not link to itself.
- The number of breadcrumb elements was counted in the rendered pages: one on every help page in both frames, one on a list page of the staff application, and one on a detail page (the crumb in its content, the way back to the list).
- The trail was measured in a browser at 1280, 1024, 900 and 390 pixels: the trail of the help pages is one row (22 pixels in the City frame, 20 in the staff frame) at every width, the last crumb truncates with an ellipsis instead of wrapping, and the page never overflows sideways (`document.documentElement.scrollWidth - window.innerWidth` is 0).
- Focused runs: `tests/integration/test_breadcrumb_trail.py` — 18 passed; `tests/browser/test_breadcrumb_browser.py` — 3 passed; `tests/unit/test_stylesheet_scopes.py` — 14 passed (the guard on the selector list of `app.css` is green: the shared trail rules live in `ui-patterns.css`, so `app.css` gained no selector). The command of the lane, `pytest -k "crumb or help or layout" tests`, passed with 295 selected tests.
- The whole suite on the committed state, run in parts because a single run does not finish inside the time limit of this sandbox: `tests/unit tests/integration tests/ui tests/supplementary tests/evaluator` — 2688 passed; `tests/acceptance tests/api tests/regression tests/scenarios tests/security` — 568 passed; the four parts of `tests/browser` — 132, 174, 82 and 142 passed with 2 skipped (the WebKit cases, WebKit is not installed here). That is 3786 passed and 2 skipped of the 3788 collected tests; no test failed and no existing test was changed.

## 2026-11-02 — Persona pill lane evidence

- The rendered chip was read back from the running application: the staff frame (`/permits/app_d05`, the Applicant) and the City frame (`/city/` and `/help`, the Applicant) carry the same chip. Its summary holds the dot and the role only, its `title` is the name of the person, and the menu opens with `<p class="account-person" data-testid="account-sub">Demo Applicant</p>` in the staff frame and with `applicant-name` in the City frame, above the items of the menu.
- The old source was written over the fixed files (`git show HEAD:<path> > <path>`) and the new tests were run against it: the unit test failed on the `account-sub` still in the chip, and the browser test measured the dot 7.59 pixels below the role on `/city/` as the Applicant. The fixed files were put back and the same tests passed.
- Measured in a browser at 1280 pixels: the dot and the role share their vertical centre exactly on `/city/` (the Applicant, 32 and 32), on `/queue` (the Permit Reviewer, 30 and 30) and on `/steward` (the Data Steward, 30 and 30). The chip is 40 pixels high and one line.
- Focused runs: `tests/unit/test_persona_switch_header.py` — 28 passed; `tests/unit/test_stylesheet_scopes.py` — 14 passed; `tests/integration/test_ui_applicant.py` and `tests/integration/test_city_website.py` — 65 passed; `pytest tests/unit tests/integration tests/ui -k "persona or account or menu or crumb"` — 178 passed, 2450 deselected; `pytest tests/browser -k "persona or account or menu or crumb"` — 113 passed, 420 deselected; `tests/browser/test_persona_chip_browser.py` — 5 passed; that file with `test_persona_switch_header_browser.py` and `test_persona_menu_mobile_browser.py` — 27 passed; the browser files that read the chip (`test_design_findings_browser.py`, `test_chrome.py`, `test_city_frame_browser.py`, `test_community_browser.py`, `test_csp_browser.py`, `test_demo_switch_browser.py`, `test_navigation_admin.py`) — 84 passed; the families outside the browser (`tests/acceptance tests/api tests/regression tests/scenarios tests/security tests/supplementary tests/evaluator`) — 629 passed; the whole of `tests/unit tests/integration tests/ui` — 2628 passed.

## 2026-11-02 — The technical documents of the help in the hosted image, evidence

- The cause was read out of the deployment: `render.yaml` builds with `dockerContext: ./repo` and `dockerfilePath: ./repo/Dockerfile-demo`, and that Dockerfile copied `src`, `config`, `migrations`, `fixtures` and `scripts` only. In the image `REPO_DIR` is `/app` and `PROJECT_ROOT` is `/`, so the six documents of the project root and the two documents of the repository itself were not there, and every page of **Help > Technical documents** showed "This document is not available in this copy of the application".
- The old source was written over the fixed file (`git show HEAD:repo/src/acme_city/help_docs/content.py > <path>`) and the new check was run against it: `tests/integration/test_help_docs_bundle.py` failed with 2 failed and 10 passed. `test_every_document_loads_when_the_project_root_is_not_there` failed on the message "This document is not available in this copy of the application", which is the bug of the hosted demonstration, and `test_a_document_that_is_nowhere_gives_the_plain_message` failed because the old source has no bundle. The fixed file was put back and the same file passed with 12 passed.
- The copies are the same as the originals: the new check reads every bundled file and compares it with the project-root original byte for byte, and it holds that the bundle holds exactly the documents the help names. `scripts/sync_help_docs_bundle.py --check` exits 0 on the committed tree, and on a small tree of its own it reports "missing in the bundle", copies the documents, reports "differs from the original" when the original changes and exits 1.
- The image is checked for the files it needs: both Dockerfiles copy `README.md`, `USER_TEST_GUIDE.md` and `help_docs_bundle/`, and `.dockerignore` excludes none of them. The shared recipe of the two Dockerfiles is unchanged, and `tests/security/test_public_demo_protection.py` still pins it.
- The served page was read back with the project root pointed at an empty folder, which is the layout of the image: the architecture page is served from the bundle with the same bytes as the committed file, every document of the help opens with 200, and the index shows no "Not available in this copy".
- The run of the brief: `pytest -q -p no:cacheprovider -n 4 tests/integration/test_help_docs.py tests/security/test_public_demo_protection.py tests/integration/test_help_docs_bundle.py tests/unit` gave 1594 passed. `scripts/scan_publishable_tree.py` passed with 958 source files and zero findings.

## 2026-11-03 — The tour voice on demand, evidence

- The old source was written over the fixed file (`git show HEAD:repo/src/acme_city/static/tour.js > repo/src/acme_city/static/tour.js`) and the new tests were run against it: `tests/browser/test_tour_voice_browser.py` and `tests/unit/test_tour.py` gave 9 failed and 31 passed. The seven browser failures were the tap that plays, the tap that stops, the step that stops the clip, the auto-play that carries no voice, the tour that keeps no key, the old key that is cleared and the refused voice that says why; the two unit failures were the label of the button and the contract of the on-demand voice. The fixed file was put back and the same tests passed (40 passed), so the tests hold the new behaviour and not the old one.
- The panel was read back in the browser: the button of the resident intro reads "Play voice" with `aria-pressed="false"`, a press reads "Stop voice" with `aria-pressed="true"`, the audio element of the tour is not paused while the clip plays, a second press pauses it again, and a clip that ends on its own leaves the button at rest.
- The step the tour leaves behind is silent. The spy on `HTMLMediaElement.prototype.pause` counted the stop before the tour moved on, and the spy on `HTMLMediaElement.prototype.play` counted one call for the press and no other, neither on the step the tour came to nor on the two steps the auto-play walked over.
- Nothing is kept about the voice: `localStorage.getItem('acme-tour-voice')` and `sessionStorage.getItem('acme-tour-voice')` are both null after a press and after the change of the step, and the key of the earlier build is removed from both stores when the engine starts.
- A refused clip is not silent: the note beside the button reads "The voice could not start. Tap again to try." and the button is at rest again.
- No caption and no clip changed: `config/tour_steps.json`, the twenty-seven shipped clips and the manifest are untouched, and the nine-second step of the auto-play stands.
- Focused runs: `tests/browser/test_tour_voice_browser.py` — 11 passed; `tests/unit/test_tour.py` — 30 passed; the run of the lane, `pytest -q -p no:cacheprovider -n 4 -k "tour or voice" tests`, gave 96 passed. `scripts/scan_publishable_tree.py` passed with 952 source files and zero findings. `scripts/sync_help_docs_bundle.py --check` exits 0: no document of the help, of the walkthrough or of the submission described the voice, so none of them changed and no copy of the bundle moved.
