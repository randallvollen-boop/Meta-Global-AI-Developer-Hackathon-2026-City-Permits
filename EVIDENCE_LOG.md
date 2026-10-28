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

`gh auth status` showed only `elawclerkdemo` as the active authenticated account. Randall then fixed the publication owner for this hackathon to `RandallVollen-boop` only. No authentication change, remote creation, commit, push, or external write occurred.

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
