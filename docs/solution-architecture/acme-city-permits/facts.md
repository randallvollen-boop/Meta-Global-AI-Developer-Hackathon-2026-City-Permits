# ACME City Permits architecture facts — as built (local candidate)

Date: 2026-10-26. Audience: internal AVA Library. No client. Architecture status is PLANNED while implementation is active; it becomes AS BUILT only after the integrated verification gate passes. Canonical status: `STATUS.json` in this workspace.

## Handling and never-on-page list

Never on the page: credentials, tokens or private email; people's names or contact details; local usernames, machine paths, hostnames, IP addresses or exact hardware; client names/data/logos/scans; City of Westerville logos, portal copies or implied endorsement; real applicant, contractor, parcel, payment or permit records; raw source archives; private account screenshots; deal terms, grant balances, prize claims or submission credentials; unmeasured accuracy, savings, performance or compliance claims; hidden chain-of-thought; Contributor model use; production-readiness or tamper-proof claims.

Use only fictional ACME City records and examples. Vollen Data Services text branding only; no VDS, Globex, Initech or municipal logo. Every interface mockup says “Example with fictional data.” Retain “Internal draft. [REVIEW REQUIRED] before external use.”

## Evidence sources

- `requirements/ACME_MDM_Demo_Requirements.txt` in the ignored build package, version 1 dated 2026-10-26, SHA-256 `54881e679cf9744f61251f7cc314ffa5400ffd3f53f67e21581371cf9f27de4d`.
- `repo/docs/REQUIREMENTS_OUTLINE.md`, written and coverage-checked 2026-10-26: 57 of 57 requirement IDs represented.
- `repo/docs/plans/2026-10-26-acme-city-end-to-end.md` plus five child plans, written and self-reviewed 2026-10-26: 22 implementation tasks, no missing child-plan links or placeholder markers.
- `CITY_PERMIT_ALIGNMENT.md`, current 2026-10-26, records the Westerville-inspired fictional workflow, source authority, Muse boundary and milestones.
- `GO_NO_GO.md`, `RISK_LIST.md`, `BUILD_LOG.md` and `EVIDENCE_LOG.md`, current 2026-10-26.
- Official public City of Westerville Building, Forms and Online Portals, Submit a Permit and Schedule an Inspection pages, checked 2026-10-26. They inform workflow shape only, not ACME law, fees, service levels, branding or integration claims.
- Meta Model API catalog and documentation checked 2026-10-26. The account catalog accepted credentials and listed `muse-spark-1.3` Standard. No City Permits model run has completed at the time of this fact sheet.

## Current status and progress source

<!-- FACT_STATUS_BEGIN -->
`STATUS.json` is the one architecture-status record. Current state at 2026-10-27 10:49 Eastern:

- Overall: VERIFIED.
- Architecture: AS BUILT.
- Requirements: 57 total, 57 outlined, 57 implemented, 57 verified through integrated mapped checks.
- Execution tasks: 22 total, 22 verified; Complete: redesigned interface, local user test.
- Verification inventory: 20 acceptance tests with 20 passed, 8 supplementary checks with 8 passed, and 11 scenarios with 11 recorded.
- Live Muse primary-chain evidence: SUCCEEDED.
<!-- FACT_STATUS_END -->

Status updates occur only from actual task/test evidence. A plan, screenshot, generated file or worker claim alone does not increment implemented or verified counts. The page is rebuilt and replaced in AVA under the same article ID at each accepted phase transition. Final status changes to AS BUILT only after AT01–AT20, VC01–VC08, D01–D11, live Muse evidence, restart persistence, issuance retry and browser checks pass.

## Product outcome

Build one local, persisted, fictional municipal permitting application. The primary SYN-APP-001 commercial tenant-improvement case moves through immutable submission, actual synthetic evidence, a bounded live Muse extraction or identity proposal, schema validation, recorded steward decisions, deterministic validation, an actual seeded reviewer decision, versioned fee assessment, Finance-confirmed allocation of a settled simulated payment and a separate simulated permit issuance. Refresh, restart and an identical issuance retry preserve and return the same trace and artifact.

The workflow is inspired by Westerville’s public pattern: route work by project type, validate contractor registration, submit commercial plans, perform completeness and plan review, preserve corrections/resubmittals, separate fees/approval/issuance, track status and hand issued work to inspection. ACME rules, actors, fees and artifacts remain fictional.

## Four selectable personas

The application dropdown shows exactly four human demo personas. Underlying permissions remain explicit and action-specific; a persona label never grants authority by itself.

1. **Applicant** — manages its authorized profile, drafts, submissions and requested responses. It cannot view other applicants, match candidates or staff-only evidence.
2. **Data Steward** — carries explicit Intake Clerk, Domain Steward and Domain MDM Steward grants for scoped queues. It reviews quality issues, proposes source corrections and decides permitted identity links. It cannot approve or issue permits or allocate money.
3. **Permit Reviewer** — carries explicit Permit Reviewer and Issuing Officer grants. Review approval and the separate Issue permit action remain different server-enforced actions. It cannot edit credentials, source facts or receipts.
4. **City Administrator** — carries separately declared Administrator, Governance Lead, Data Owner, Finance and Auditor grants needed for the demo. Configuration rights do not create business approval rights; Finance allocation and owner/governance approvals are authorized by their explicit grants and state rules.

System custodians, source adapters, outbox workers and Muse are service identities, not dropdown personas. Historical blueprint actors remain source references only and are not selectable or separately presented in the new UI.

## Planned application architecture

One Python 3.12 FastAPI service binds loopback only. SQLAlchemy and Alembic manage one SQLite database. Jinja pages and small vanilla JavaScript enhancements provide eight screens. Three persisted in-process source adapters simulate Permitting, GIS and ERP/Finance. A database outbox carries durable publication and acknowledgements. An append-only application audit trail records accepted and denied sensitive actions without claiming tamper-proof storage.

Modules:

- Governance and authority: domains, datasets, contracts, assignments, queues, grants and field correction routes.
- Source intake: immutable snapshots, raw payload hashes, validation, quarantine, source ordering, freshness and denominators.
- Registry and stewardship: stable canonical identities, proposals, crosswalk decisions, provenance, trusted views and reversible links.
- Changes and publication: state machine, source commands, acknowledgements, expected versions, dependencies, outbox and impact tasks.
- Permit operations: profiles, immutable submissions, documents, evaluations, recommendations, actual decisions, issuance and impact review.
- Rules and finance: one approved versioned catalog, exact assessments, payment events, allocations, reconciliation and exceptions.
- Muse: strict live/replay/cached proposal runs, output validation, trace records and no authoritative write permissions.
- Evidence: requirement mappings, AT/VC/D outcomes, manifests, artifact hashes, browser checks and user-test handoff.

## Required screens

1. Work queue.
2. Applicants.
3. Properties, Businesses and Contractors.
4. Permit workspace.
5. Steward review.
6. Rules and fees.
7. Reconciliation.
8. Governance and sources.

Every governed detail view shows Owner, Steward, Source, Change this in, Version, Last source update, Last received and Open issues. Current master, submitted, proposed and issued values remain visually distinct.

## Source authority and write paths

- Permitting owns applicant profiles, applications, contractor registration, decisions and issuance.
- GIS owns parcels, official addresses/units and zoning facts.
- ERP/Finance owns business licensing, finance accounts and payment events.
- The registry owns canonical identities, source links, match decisions, provenance and publication history, not source-owned facts.
- Approved does not mean synchronized. A factual correction becomes authoritative only after its source adapter accepts a version. A registry identity correction commits a new crosswalk version without claiming to edit a source fact.

## Muse contribution

Knowledge and grounding: actual versioned fictional documents, source snapshots, candidate IDs, allowed visible records, source/effective/receipt times, rule versions and exact evidence lines. Evaluator truth, expected decisions and all `truth_*` data remain outside runtime payloads and retrieval.

Routing and topics: `muse-spark-1.3` Standard handles at least one substantive live task in the primary chain. Preferred tasks are structured application-field extraction and evidence-based identity proposals. Requests use strict JSON Schema, allowlisted IDs, bounded inputs/outputs, no web search, no tool calls and concurrency one. The application validates IDs, evidence locations, excerpts, categories and citations before creating proposals.

Authority: Muse cannot publish links, edit source facts, calculate authoritative money, make reviewer decisions, allocate payments or issue permits. Deterministic services and authorized personas control those actions.

Evidence: each run records mode, actual model/response ID, prompt/schema versions, input references, output, validation, available usage, latency and errors. Live, replay, cached and failed runs remain visibly distinct. Replay is an explicit recovery path and never counts as successful live evidence.

## Deterministic controls and finance

Stable internal IDs remain distinct from source IDs and display numbers. Expected versions protect corrections, links, rules, decisions, allocations and issuance. Submitted revisions, evaluations, decisions, assessments, allocations and issued snapshots are immutable/versioned.

Example with fictional data: fixed review fee 100.00 USD plus 0.001 times declared valuation, with the variable component rounded once using ROUND_HALF_UP. A 50,000.00 valuation produces 150.00 USD. A 70,000.00 reassessment produces 170.00 USD. Carrying forward the existing 150.00 allocation once leaves 20.00 due and blocks issuance.

## Verification architecture

- 57 P0 requirements map to implementation symbols and executable checks.
- AT01–AT20 cover governance, edits, access, identity, source acknowledgements, impact, reviewer actions, invalid inputs, rules, model boundaries, concurrency, finance, complete persistence and link correction.
- VC01–VC08 cover safe normalization, source observations, value distinctions, controls, feedback, records protection, meaningful denominators and separated measurements.
- D01–D11 cover the primary case, false match, credential, unknown parcel, profile history, source failure, issued history, replay/idempotency, malformed extraction, unowned feed and financial exceptions.
- Final local gate performs a fresh reset, complete checks, bounded live Muse run, restart, idempotent issuance retry and browser walkthrough on loopback.

No implementation or verification figure is shown as complete until the corresponding stored evidence exists.

## Open decisions and release gates

- External click-through prototype source remains absent; the new app is built independently from the specification.
- Provider-reported credit balance, expiration, eligible products and no-cash enforcement remain unverified; live calls use a two-success cap and stop on provider/billing errors.
- GitHub authentication to the required personal owner remains pending; remote creation, commits and pushes are not part of this build.
- Final competition candidate, event terms, submission format, deployment and submission remain held.
- Brand, delivery-owner and security review are open. Keep the internal-review banner.
- Architecture status remains PLANNED until the integrated evidence gate passes.

## Kit provenance

Build with the installed Solution Architecture Kit and Vollen Linux brand layer. No shared kit edits are planned. The kit-required `brand: Globex` value remains internal builder configuration while all visible and source output excludes wrong-brand words through the denylist. Record kit hashes, Linux wrapper use and the known unused Aptos embedding-rights limitation in `BUILD_REPORT.md`.

## How it was built (2026-10-27)

- OpenAI GPT-5.6 Sol with GPT-6 Astra led the first build: requirements, plans, integration and acceptance.
- MiniMax M3 executors built the implementation slices; the orchestrator reviewed each.
- Claude Opus 5.5 fixed the live Muse extraction, ran the gates, designed the redesign mockup and reviewed the Muse build.
- Meta Muse Spark 1.3 is the runtime extraction model. Muse Wonder 1.0 reviewed the prototype and built the redesign. Muse Image 1.0 made the permit-type icons.
- Before and after screenshots use fictional data only. Source: `docs/build-story/ENGINES.md`.

## Parity build, as built (2026-10-27)

Source: `BUILD_LOG.md` sections "Parity phase 1" and "Parity phase 2"; merges `07755ae` and `e2528a4` on main.

- Phase 1, merged `07755ae`. Two agents that a person wakes and runs. Only the City Administrator wakes them (`agent.toggle`), and a person with `agent.run.intake` or `agent.run.adjudication` runs them.
- The intake agent is a dependency graph: classifier; field extractor and document QC in parallel; duplicate finder and completeness in parallel; router. Phase 2 adds an address locator node ahead of the duplicate finder, making seven nodes. The adjudication agent has five nodes: rule loader; rule evaluator; condition builder and precedent check in parallel; disposition. Every run is recorded with a per-node trace.
- Confirm records the reviewer's decision through the decision service, and the reviewer is the decider of record. Revert needs a reason and returns the case to manual review. A held recommendation cannot be confirmed.
- The permit catalogue has 17 types. Discretionary types carry no rule and are always held for a person. A configuration change applies only to new intake; the requirements in force when a case arrived are recorded on the case.
- Administration (City Administrator only) holds permit-type configuration, users, service identities, reason codes, the configuration log and the permit-type icons.
- Intake channels include mail and fax, with per-document scan-quality flags.
- Phase 2, merged `e2528a4`. A simulated GIS service runs in the app: 69 parcels, 71 addresses, no outside calls. The address locator proposes a parcel link and never approves it, and a permit decision is blocked until the parcel link is approved and confirmed.
- The property master at `/property/{parcel}` is shared with four simulated subscriber departments: tax and assessor, fire and life safety, code enforcement, and utilities. Each reads fields and writes nothing back (`config/property_subscribers.json`). `/map` is a server-rendered SVG town map with no outside tiles.
- The applicant portal at `/apply` has a chooser for the 17 types, a form per type with a completeness banner, uploads, drafts, certification, confirmation and tracking.
- Verification at the phase 2 merge, lead review on merged main: 10 of 10 gates pass; pytest 762 passed; acceptance 37 passed, 0 failed, 2 blocked. AT15 and AT19 need a live provider.

## Phase 3, planned (not built)

Source: `../acme-permits-parity-notes/BRIEF-P3-OPERATIONS.md`, read 2026-10-28. Every item here is planned. The page labels them planned and claims no result for them.

- Build order: P3a (lifecycle, comments, findings, archive; in progress), P3b (queue views, early resolution, review queue, service targets), P3chat in three runs, P3c (operations dashboard, audit log, support, checks), P3insight, P3policy in four runs. The applicant side moves onto a fictional City of Acme website at `/city/`.
- P3chat, applicant help chat. Muse Spark answers only from a server-built set of sources: published effective rules with ACME Code citations, permit-type settings, lifecycle passages, service targets and the applicant's own case. Code checks that every citation exists and every quote is verbatim, and that any fee, dimension or timing comes from a server-computed fact. It blocks outcome promises and legal-advice claims. If a check fails, the applicant sees the matching rule text labelled "not an AI answer". "Ask the City" sends the question to a person. Tests and the default demo use labelled replay.
- P3insight, community permit insight. The City Administrator gets permit activity on the town map by district, with filters for type, outcome, period and exceptions (variances, waivers, denials, conditions), business activity by category, and trends. Residents get "Permits in my community" on the City of Acme website: the same map and totals, plus public lookup by address, street or permit number. The public record shows the permit number, type, parcel and address, work description, status, dates, outcome, conditions, an exception marker and the contractor business name. It never shows homeowner names, documents, internal notes, comments, contact details or fees, and district totals under 3 show as "fewer than 3". Business categories (restaurant, bar, retail, office) are added. Sanitation and police join the simulated subscriber departments. Everything displayed comes from seeded synthetic data with a synthetic label.
- P3policy, what-if for administrators. A scenario applies proposed rule, document, process-category, service-target or fee changes in memory only. A deterministic engine reruns the rule evaluator, intake checks and fee calculation over current cases, decided cases or a seeded synthetic year. It reports cases whose outcome changes, cases no longer held for a reviewer, needs-information changes, service-target changes and hypothetical assessed fees. It makes no staff-time or revenue claim, and every case that moves from fail to pass is listed. Muse Spark explains a stored run in a council briefing, and every number in the briefing must equal a computed measure. "Propose as draft" creates draft rule versions that still need independent approval. Demo scenario: fence height limit raised from 6 ft to 7 ft.

## Explainer video, planned (Randall approved the script 2026-10-28)

Source: `../acme-permits-parity-notes/VIDEO-SCRIPT-r7.md`. Review record: `VIDEO-SCRIPT-REVIEW.md` (private; it never goes on the page).

- Length 2:00, seven scenes: the problem; three groups, one app; residents; city staff; city leaders; one shared record; close.
- Presenter: an AI version of Randall rendered with MiniMax H3 from Randall's own face reference and voice sample. Slides, app recordings, captions and assembly are done in Kinetograph 0.2.0, a TypeScript video engine running on the local GPU. Hook and close stills come from Muse Image.
- Workflow: H3 pilot clip of scene 1 (on hold until the GPU is free); seven presenter clips; app recordings on a separate copy of the app with live Muse Spark for the Muse moments; Kinetograph assembly; review; final render; Randall's sign-off. Recording waits until P3chat, P3insight and P3policy merge. Nothing is published or submitted without Randall's go.
- Script text for the page: the seven narration paragraphs of `VIDEO-SCRIPT-r7.md`, verbatim, under a "Planned explainer video" heading.
- Never on the page: the private review record, voice or face reference file paths, or the identity name.

## Phase 3a and the City of Acme website, as built (2026-10-28)

Sources: `EVIDENCE_LOG.md` "Parity phase 3a evidence"; merges `b7ce8bd` (phase 3a) and `ead8790` (City of Acme website) on main.

- Lifecycle: new statuses `revisions_requested`, `returned` (terminal) and `archived`. A steward returns a case or advances it to review, and the advance is refused while a current, unwaived blocking finding stands. A reviewer requests revisions. The applicant resubmits, which versions the case, marks dependent work stale, keeps the first submission date and returns the case to intake. The City Administrator archives and restores, and every change is version-checked.
- An archive guard sits at the service level and is tested path by path on every application-changing path (revisions, documents, evaluation, both agents, confirm and revert, parcel operations, finance, portal upload and resubmission, restore).
- Typed reason codes cover return, denial, waiver, revision and archive. A denial needs a denial reason code on every decision path, and the code, label and version are recorded on the decision.
- Findings add `wrong_type` and `fee`. Findings are current, resolved or superseded. A waiver applies only to a current finding of a waivable type and never clears a deterministic decision blocker.
- Comments are either applicant-visible or internal, enforced on the server on every surface. The audit record carries the comment identifier and its visibility, never the text.
- Each case has a priority (normal or high) and an owner, and the owner is routing metadata only.
- Verification for phase 3a, run in its worktree: all 10 local gates pass; 866 tests passed with 0 failed and 0 skipped; acceptance 37 passed, 0 failed, 2 blocked (AT15 and AT19 need live evidence). No live provider call was made.
- City of Acme website, merged `ead8790`: a fictional city website at `/city/` with a Permits entry. The applicant portal pages render inside the city layout, and a "Demo: switch user" control uses the existing persona selector, which still offers exactly four personas.

## Merged-main verification (2026-10-28)

Source: `repo/var/check-run-main-p3a/` and `repo/var/check-run-main-city/` (`run-all-summary.json` status passed, no failed steps).

- Main at `b7ce8bd` (phase 3a merged): all 10 gates pass; 866 passed in 848.51 s; acceptance 37 passed, 0 failed, 2 blocked.
- Main at `ead8790` (phase 3a and the City of Acme website merged): all 10 gates pass; 879 passed in 882.39 s; acceptance 37 passed, 0 failed, 2 blocked (AT15 and AT19 need live evidence). The page reports this run.
- The demo restarted at schema revision 0006 with the city website at `/city/`.
