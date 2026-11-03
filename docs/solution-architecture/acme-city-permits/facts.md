# ACME City Permits architecture facts — as built (local candidate)

Date: 2026-10-26, updated 2026-11-02. Audience: internal AVA Library. No client. Architecture status is AS BUILT: the integrated verification gate passed. Canonical status: `STATUS.json` in this workspace.

## Handling and never-on-page list

Never on the page: credentials, tokens or private email; people's names or contact details; local usernames, machine paths, hostnames, IP addresses or exact hardware; client names/data/logos/scans; City of Westerville logos, portal copies or implied endorsement; real applicant, contractor, parcel, payment or permit records; raw source archives; private account screenshots; deal terms, grant balances, prize claims or submission credentials; unmeasured accuracy, savings, performance or compliance claims; hidden chain-of-thought; Contributor model use; production-readiness or tamper-proof claims.

Use only fictional ACME City records and examples. VollenData text branding only; the page is prepared by Randy Vollen, host of www.VollenData.com, for the Muse Hackathon, using the fictional City of Acme; no logo of any kind. Every interface mockup says “Example with fictional data.” The internal-review banner is removed by the project owner's decision of 2026-11-02: the banner rule of the build skill does not apply to this page, and the builder must not restore it. The same decision keeps every open-gate and review-status line off the page: no release-gate row, no brand or delivery-owner gate status, no draft or review marker. Those statuses stay in this fact sheet and in `PROJECT_NOTE.md`, which are internal. The only model name the page may carry is Muse: no Muse product variant, no model version and no other model is named, in the copy, in the diagram or in the alt text.

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

## Five selectable personas

The application dropdown shows exactly five human demo personas, in story order (`repo/config/actors.json`; `loader.py:140`; `ops/checks.py:192`). Underlying permissions remain explicit and action-specific; a persona label never grants authority by itself.

1. **Applicant** — manages its authorized profile, drafts, submissions and requested responses. It cannot view other applicants, match candidates or staff-only evidence.
2. **Agent Operator** — carries the `agent_operator` grants: `agent.toggle`, `agent.run.intake`, `agent.run.adjudication`, `permit.intake.process_selected` and `agent.ops.read`. It wakes, sleeps and runs the intake and adjudication agents, processes a bounded selection of waiting cases and reads run history. It cannot decide, issue or configure. Navigation: Agents (`/agents`, its home), Intake agent, Adjudication agent, Agent runs (`ui/agent_nav.py`). Only this persona holds the wake and run grants (`tests/regression/data/persona_grant_deltas.json`, OPR-3).
3. **Data Steward** — carries explicit Intake Clerk, Domain Steward and Domain MDM Steward grants for scoped queues. It reviews quality issues, proposes source corrections and decides permitted identity links. It cannot approve or issue permits or allocate money.
4. **Permit Reviewer** — carries explicit Permit Reviewer and Issuing Officer grants. Review approval and the separate Issue permit action remain different server-enforced actions. It cannot edit credentials, source facts or receipts.
5. **City Administrator** — carries separately declared Administrator, Governance Lead, Data Owner, Finance and Auditor grants needed for the demo. Configuration rights do not create business approval rights. The City Administrator sets the agent processing policy in Administration, Agent processing, and does not wake or run agents; Finance allocation and owner/governance approvals are authorized by their explicit grants and state rules.

System custodians, source adapters, outbox workers and Muse are service identities, not dropdown personas. Historical blueprint actors remain source references only and are not selectable or separately presented in the new UI.

## Planned application architecture

One Python 3.12 FastAPI service binds loopback for local use and runs as a paid Render web service for the hosted demonstration. SQLAlchemy and Alembic manage one SQLite database. Jinja pages and small vanilla JavaScript enhancements provide eight screens. Three persisted in-process source adapters simulate Permitting, GIS and ERP/Finance. A database outbox carries durable publication and acknowledgements. An append-only application audit trail records accepted and denied sensitive actions without claiming tamper-proof storage.

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

## Hosting and production

- The live public demonstration is at `https://acme-city-permits.onrender.com` on a paid Render web service. It runs the demo image from `repo/Dockerfile-demo`, uses SQLite and contains fictional data only.
- Render automatic deploys are off. A person starts each release deploy. The blueprint defines one web service, built from `repo/Dockerfile-demo`, and no scheduled job, so every deploy rebuilds the demonstration data.
- The hosted demonstration is not production mode. `ACME_PUBLIC_DEMO=1` applies the public demonstration lock. The next deploy sets `ACME_MUSE_PROVIDER_ENABLED=1`, `ACME_MUSE_LIVE_CALLS_ALLOWED=1` and a daily cap of 100. A public demo without `ACME_MUSE_LIVE_CALLS_ALLOWED` still locks live calls.
- The production mode remains a hardened core rather than a finished product. Real sign-in, a server database, backups, monitoring and malware scanning remain open.

## Open decisions and release gates

- External click-through prototype source remains absent; the new app is built independently from the specification.
- Provider-reported credit balance, expiration, eligible products and no-cash enforcement remain unverified; live calls use a two-success cap and stop on provider/billing errors.
- The repository is on GitHub under the personal owner, private until submission.
- Final competition candidate, event terms, submission format and submission remain held. The public demonstration is deployed separately in demo mode.
- Brand and delivery-owner review are open. The security review has run, and its High and Medium findings are fixed. These statuses are internal. The project owner's decision of 2026-11-02 keeps them off the page: no release-gate row, no gate status and no internal-review or draft marker is written there, and the build skill must not restore one.
- Architecture status is AS BUILT; the integrated evidence gate passed.

## Kit provenance

Build with the installed Solution Architecture Kit and Vollen Linux brand layer. No shared kit edits are planned. The page uses the kit's `vds` brand, which renders no logo, and a private denylist file outside the repository keeps wrong-brand words off the page. Record kit hashes and Linux wrapper use in `BUILD_REPORT.md`. The app and page use system font stacks only, with no embedded fonts.

## How it was built (2026-10-27)

- Local and other frontier models assisted the Muse models: requirements, plans, implementation slices, integration, the live Muse extraction fix, the gates and review of each merge. The page names no non-Muse product or model (Randall, 2026-10-30). From 2026-11-02 the rule is tighter: Muse is the only model name the page carries, and no Muse product variant is named either.
- Meta Muse Spark 1.3 is the runtime extraction model. Muse Wonder 1.0 reviewed the prototype and built the redesign. Muse Image 1.0 made 14 of the 17 permit-type icons.
- Before and after screenshots use fictional data only. Source: `docs/build-story/ENGINES.md`.

## Parity build, as built (2026-10-27)

Source: `BUILD_LOG.md` sections "Parity phase 1" and "Parity phase 2"; merges `07755ae` and `e2528a4` on main.

- Phase 1, merged `07755ae`. Two agents that a person wakes and runs. Since OPR-3 only the Agent Operator wakes them (`agent.toggle`) and runs them (`agent.run.intake`, `agent.run.adjudication`).
- The intake agent is a dependency graph: classifier; field extractor and document QC in parallel; address locator and completeness check in parallel; duplicate finder; router. Seven nodes (`agents/graphs.py`). The adjudication agent has five nodes: rule loader; rule evaluator; condition builder and precedent check in parallel; disposition. Every run is recorded with a per-node trace.
- Confirm records the reviewer's decision through the decision service, and the reviewer is the decider of record. Revert needs a reason and returns the case to manual review. A held recommendation cannot be confirmed.
- The permit catalogue has 17 types. Discretionary types carry no rule and are always held for a person. A configuration change applies only to new intake; the requirements in force when a case arrived are recorded on the case.
- Administration (City Administrator only) holds permit-type configuration, users, service identities, reason codes, the configuration log and the permit-type icons.
- Intake channels include mail and fax, with per-document scan-quality flags.
- Phase 2, merged `e2528a4`. A simulated GIS service runs in the app: 69 parcels, 71 addresses, no outside calls. The address locator proposes a parcel link and never approves it. An open parcel or identity link is Data follow-up and does not block the decision or issuance. The payer link and the fee still block issuing. Rule inputs that come from the parcel are read from the confirmed parcel only; rules that cannot run are shown as Not checked, and the adjudication agent recommends from the checked rules.
- The property master at `/property/{parcel}` is shared with simulated subscriber departments: tax and assessor, fire and life safety, code enforcement and utilities from phase 2, with sanitation and police added in P3insight (six in all, `config/property_subscribers.json`). Each reads fields and writes nothing back. `/map` is a server-rendered SVG town map with no outside tiles.
- The applicant portal at `/apply` has a chooser for the 17 types, a form per type with a completeness banner, uploads, drafts, certification, confirmation and tracking.
- Verification at the phase 2 merge, lead review on merged main: 10 of 10 gates pass; pytest 762 passed; acceptance 37 passed, 0 failed, 2 blocked. AT15 and AT19 need a live provider.

## Phase 3, built

Source: `../acme-permits-parity-notes/BRIEF-P3-OPERATIONS.md`, read 2026-10-28. The items here were built and merged to main by 2026-10-28, per `BUILD_LOG.md`. The page labels them built.

- Build order: P3a (lifecycle, comments, findings, archive), P3b (queue views, early resolution, review queue, service targets), P3chat in three runs, P3c (operations dashboard, audit log, support, checks), P3insight, P3policy in four runs. The applicant side moves onto a fictional City of Acme website at `/city/`.
- P3chat, applicant help chat. Muse Spark answers only from a server-built set of sources: published effective rules with ACME Code citations, permit-type settings, lifecycle passages, service targets and the applicant's own case. Code checks that every citation exists and every quote is verbatim, and that any fee, dimension or timing comes from a server-computed fact. It blocks outcome promises and legal-advice claims. If a check fails, the applicant sees the matching rule text labelled "not an AI answer". "Ask the City" sends the question to a person. Tests and the default demo use labelled replay.
- P3insight, community permit insight. The City Administrator gets permit activity on the town map by district, with filters for type, outcome, period and exceptions (variances, waivers, denials, conditions), business activity by category, and trends. Residents get "Permits in my community" on the City of Acme website: the same map and totals, plus public lookup by address, street or permit number. The public record shows the permit number, type, parcel and address, work description, status, dates, outcome, conditions, an exception marker and the contractor business name. It never shows homeowner names, documents, internal notes, comments, contact details or fees, and district totals under 3 show as "fewer than 3". Business categories (restaurant, bar, retail, office) are added. Sanitation and police join the simulated subscriber departments. Everything displayed comes from seeded synthetic data with a synthetic label.
- P3policy, what-if for administrators. A scenario applies proposed rule, document, process-category, service-target or fee changes in memory only. A deterministic engine reruns the rule evaluator, intake checks and fee calculation over current cases, decided cases or a seeded synthetic year. It reports cases whose outcome changes, cases no longer held for a reviewer, needs-information changes, service-target changes and hypothetical assessed fees. It makes no staff-time or revenue claim, and every case that moves from fail to pass is listed. Muse Spark explains a stored run in a council briefing, and every number in the briefing must equal a computed measure. "Propose as draft" creates draft rule versions that still need independent approval. Demo scenario: fence height limit raised from 6 ft to 7 ft.

## Explainer video, finished (Randall approved the script 2026-10-28, picture lock 2026-11-02)

Source: `../acme-permits-parity-notes/VIDEO-SCRIPT-r7.md`. Review record: `VIDEO-SCRIPT-REVIEW.md` (private; it never goes on the page).

- The demo video is finished. The final cut was recorded from the final build of the application and reached picture lock on 2026-11-02. The page states that plainly and carries no draft number and no draft badge.
- Length target: under the organisers' 3 minute limit, seven scenes: the problem; three groups, one app; residents; city staff; city leaders; one shared record; close. The final cut runs 179.7 s (about 3:00), so it stays under the limit.
- Presenter: the VollenData sunflower character, lip-synced with a video model to text-to-speech narration. Slides, app recordings, captions and assembly are done in a TypeScript video engine running on the local GPU. Hook and close stills come from Muse Image.
- Workflow: presenter clips; app recordings on a separate copy of the app, with the Muse moments taken from the live paths of the City (the help assistant, Check my application, Explain with Muse and the policy briefing); video engine assembly; review; final render; Randall's sign-off. The workflow completed and the cut was signed off on 2026-11-02. Nothing is published or submitted without Randall's go.
- Script text for the page: the narration paragraphs of the approved script, verbatim, under the "Explainer video" heading.
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
- City of Acme website, merged `ead8790`: a fictional city website at `/city/` with a Permits entry. The applicant portal pages render inside the city layout, and a "Demo: switch user" control uses the existing persona selector, which now offers exactly five personas.

## Merged-main verification (2026-10-28)

Source: `repo/var/check-run-main-p3a/` and `repo/var/check-run-main-city/` (`run-all-summary.json` status passed, no failed steps).

- Main at `b7ce8bd` (phase 3a merged): all 10 gates pass; 866 passed in 848.51 s; acceptance 37 passed, 0 failed, 2 blocked.
- Main at `ead8790` (phase 3a and the City of Acme website merged): all 10 gates pass; 879 passed in 882.39 s; acceptance 37 passed, 0 failed, 2 blocked (AT15 and AT19 need live evidence). The page reports this run.
- The demo restarted at schema revision 0006 with the city website at `/city/`.

## Phase 3 progress, Muse-first build credit and video plan (2026-10-28, afternoon)

- P3b built: merge `9a7b8ed` "Merge parity phase 3b: queues, bulk intake, review queue, conditions". Source: `git log main`.
- P3chat run 1 merged (`7d4c0fd`, main `604949d`): help panel, sources, conversation, Ask the City; the answer is deterministic with no model call; the Muse path arrives in run 2. Source: BUILD_LOG.md line 184.
- P3policy run 1 merged (`4f14a36`): evaluation kernels and impact engine, no screens. Source: BUILD_LOG.md line 231.
- P3insight: on branch `feature/p3-insight`, not merged. Source: `git branch --contains`.
- Also merged: guarded buttons (`d3bad15`), shared UI patterns (`1590701`), seed icons for the remaining 14 permit types (`6f976e0`; Muse Image `muse-image-1.0`, 14 calls). Source: BUILD_LOG.md line 206.
- Muse Spark 1.3 runtime uses: intake field extraction (`agents/extraction.py`, model `muse-spark-1.3`), reviewer case summary that explains only (`triage/summary.py`). Replay is the default; live extraction succeeded earlier (see Merged-main verification).
- Muse Wonder 1.0: cited prototype review; built the UI redesign, the permit-type icon feature, the simulated intake portal and the first automated triage with recommendation. Source: BUILD_LOG.md lines 64 to 100.
- Muse Image 1.0: 14 of the 17 permit-type icons (17 icon files exist; 14 calls are recorded); in-app icon generation for City Administrators (`permits/icons.py`, `muse/image_client.py`).
- Other models are listed as notes (Randall, 2026-10-28: "Lead with how muse was used, and keep the other models as notes"). None runs inside the application.
- Video plan: about 2:40 under the organisers' 3 minute limit; narration about 1:31 at the chosen pace (Randall chose 2.75 on the review page; measured 3.08 to 3.35 words per second); presenter bottom left over screens (Randall, 2026-10-28); scripted browser recording test `acme-permits-parity-notes/screen-test-01/screen-test-01b.mp4`; opening "built this week" line proposed, per the organisers' FAQ.

## Phase 3 merges, prose pass and draft video (2026-10-28, midday)

- Merged to main: P3insight `d5844ef` (city view, community permits, synthetic year, Sanitation and Police); P3policy run 2 `ee78093`; P3chat2 `36c2017` (Muse applicant assistant in replay, validation, decline, fallback); P3policy runs 3 and 4 `016d44c` (Muse briefing, explanation, proposals, draft conversion); restyles `fad956f`, `2b3272b`, `b28ce38`. Source: `git log main --merges`.
- App wording checked in templates: fallback shows "the rule text that matches your words"; draft action "Save as a draft rule change"; drafts need independent approval. "fewer than 3" present in source.
- Prose pass under vollencoms at Randall's request (relayed by HackathonMuse; Randall: "We need to run vollencoms across any prose").
- Draft cut 1: `acme-permits-parity-notes/draft-01/acme-permits-draft-01.mp4`, 2:14, narration r9 (`VIDEO-SCRIPT-r9.md`, approved by Randall 2026-10-28), wardrobe D, 13 clips, FFmpeg assembly.

## As-built diagram contents (2026-10-28, main at `4ea0497`)

The diagram on the page (`#arch`) shows every block below. Each line names the source that backs it. The status block, its dates and the verification gates are unchanged. The evidence for the added parts is the build log entries cited here. No new gate is claimed.

- Public visitor persona, no sign-in, reaches the City of Acme website and "Permits in my community" (`/city/`, `/city/community`). Source: `repo/BUILD_LOG.md`, 2026-10-28 "Parity phase 3 insight" (public allowlist model, 17 fields) and 2026-10-27 "Parity phase 3a and the City of Acme website merged"; routes in `repo/src/acme_city/city/router.py`.
- Applicant help assistant (`/apply/help`, `/apply/help/panel`, `/apply/help/escalate`): cited source bundle, Muse Spark `applicant_assist` in labelled replay by default, live only behind a server setting, "Ask the City" fallback. Source: BUILD_LOG.md 2026-10-28 "Parity phase 3 chat 1" and "chat 2"; `repo/src/acme_city/applicant_help/`, `ui/help_routes.py`.
- What-if policy agent (`/policy/scenarios`, `/policy/runs/*`, `/policy/propose`): immutable runs on a synthetic year, Muse Spark explanations and proposals (`policy_propose`), draft conversion needing independent approval. Source: BUILD_LOG.md 2026-10-28 "P3policy run 1" to "run 4"; `repo/src/acme_city/policy/`, `ui/policy_routes.py`.
- Council briefing (`/policy/runs/{id}/briefing`): typed facts first, Muse Spark `policy_brief` optional, whole-response rejection of an uncited figure. Source: BUILD_LOG.md "P3policy run 3"; `policy/briefing.py`, `muse/schemas.py` (`POLICY_BRIEF_TASK`).
- Permit insight map (`/insight/city`, City Administrator, grant `insight.city.view`). Source: BUILD_LOG.md "Parity phase 3 insight"; `repo/src/acme_city/insight/city_view.py`, `ui/router.py`.
- Operations screens (`/ops/dashboard`, `/ops/audit`, `/ops/support`, `/ops/checks`, City Administrator, one grant each). Source: BUILD_LOG.md "P3c: operations dashboard, audit log, support, checks"; merged as `c412079`; `repo/src/acme_city/ops/`, `ui/ops_routes.py`.
- Synthetic history generator (`generate_synthetic_year` in `portal_intake/scenarios.py`, `config/synthetic_distributions.json`), records flagged synthetic, adapted by `policy/synthetic_feed.py`. Source: BUILD_LOG.md "Parity phase 3 insight" and "P3policy run 2".
- Meta Muse Image (`muse-image-1.0`): 14 seed icons made on 2026-10-28 (14 calls), plus in-app icon generation for City Administrators at `/admin?tab=appearance` (`permits/icons.py`, `muse/image_client.py`). Source: BUILD_LOG.md "Permit type icons for all 17 types".
- Sanitation and Police as simulated subscribers, six departments in all (`config/property_subscribers.json` holds `tax_assessor`, `fire_safety`, `code_enforcement`, `utilities`, `sanitation`, `police`). Source: BUILD_LOG.md "Parity phase 3 insight".

Layout notes for the diagram: the persona tier gains the public visitor, the application tier gains two rows for the phase 3 blocks, and the external tier gains Muse Image beside Muse Spark. The status record block moved to the lower right so the application tier could grow. Two earlier details were corrected in the same pass: the `db_evidence` edge now starts at the database block, and the Muse request and proposal labels sit on their lines.

Left out because it could not be verified: nothing is drawn for a live Muse Spark call on the help or briefing paths, because both default to replay and the log records no live run for them.

## Permit life cycle (2026-10-29, branch `feature/permit-lifecycle` off main `6437418`)

Randall asked for a permit life cycle in the architecture, a route to test it and a judge walkthrough (2026-10-29). Status: BUILT and merged to main (`src/acme_city/permits/lifecycle_map.py`).

- 12 statuses. Source: the `status_allowed` check constraint in `repo/src/acme_city/persistence/models/permit.py`.
- 16 moves, each with its source statuses, target, acting grant and screen. Source: `repo/src/acme_city/permits/lifecycle_map.py`. The source status sets are imported from the services where they exist: `ADVANCEABLE_STATUSES`, `RETURNABLE_STATUSES`, `REVISION_STATUSES` and `ARCHIVABLE_STATUSES` (`permits/lifecycle.py`), `DECIDABLE_STATUSES` (`permits/decisions.py`) and `RESPONDABLE_STATUSES` (`applicant_portal/service.py`).
- Where each move happens in code: submit (`permits/service.py` `submit`, created as submitted), intake routing (`kernel/intake.py` `route`, applied in `agents/intake.py`), validate (`permits/service.py` `evaluate`), return, advance, request revisions, archive and restore (`permits/lifecycle.py`), revert recommendation (`agents/recommendation.py` `revert`), correct the application record (`permits/service.py` `revise`), approve, deny and request information (`permits/decisions.py`), issue (`permits/issuance.py`), resubmit (`applicant_portal/service.py` `resubmit`).
- Who: the selectable persona grants in `repo/config/actors.json`. Agent moves are labelled "Intake agent (automatic)".
- Checks: `repo/tests/unit/test_lifecycle_map.py` (6 tests) checks the table against the model and the imported status sets. `repo/tests/unit/test_lifecycle_map_probe.py` runs Run application checks, Correct the application record, Revert the agent recommendation and the issuance blockers from every stored status and compares the result with the table. FULL_SUITE_PLACEHOLDER
- In-app screens: `/lifecycle` and `/walkthrough`, mounted only with the persona selector (demonstration mode). Browser checks: `repo/tests/browser/test_guide_pages_browser.py`, 6 tests, passed 2026-10-29.
- Diagram and table: generated by `repo/scripts/build_lifecycle_diagram.py`. Standalone copy: `diagram/permit-lifecycle.svg`.
- Known gaps, stated on the page: no code path sets Withdrawn, so only seeded history holds it. Run application checks reopens an approved or denied case (`evaluate` sets ready for review unless the case is issued, returned or archived). Correct the application record reopens any case but a returned or archived one, including an issued one. Revert the agent recommendation reopens a returned case while a recommendation is pending.

Decided by Randall on 2026-10-29: no code change. A withdraw action, checks that leave decided cases decided, and issued permits that stay closed are listed as future features in `docs/submission/JUDGE_WALKTHROUGH.md`.

## Later lanes and corrections (2026-10-30, rebuild on branch docs/accuracy at 07f048b)

Sources are the code on that commit under `repo/`. Every item below was checked against code before the page changed.

- Five personas, Agent Operator included: `config/actors.json`, `ops/checks.py` `check_personas`. Operator grants and navigation as above. Only the Agent Operator holds `agent.toggle`, `agent.run.intake` and `agent.run.adjudication`.
- Administration tabs (`ui/admin_tabs.py`, `ui/agent_admin_views.py`): Permit types, Appearance, Users and roles (including which staff roles may run agents), Agent processing, Reason codes, Configuration log.
- Optional automatic processing: durable queue and one worker (`agents/worker.py`, `agents/policy.py`, `agents/runtime.py`). `ACME_AGENT_WORKER_ENABLED` defaults to false (`core/config_operator.py`) and `render.yaml` does not set it, so it is not enabled on Render. Automatic runs use built-in deterministic logic (`agents/extraction.py`, `agents/runtime.py`) and never call the provider.
- Daily Muse allowance: `muse/budget.py`, `ACME_MUSE_DAILY_CALL_CAP`, default 10 (`core/config_operator.py`). Live call cap default 2.
- Applicant help answer, council briefing and what-if proposals use the same adapter. On the hosted demonstration `ACME_APPLICANT_ASSIST_LIVE_ENABLED` and `ACME_POLICY_ASSIST_LIVE_ENABLED` are 1, with a daily cap of 100. When live Muse is off, or that allowance is used up, recorded answers are used.
- Town map: no outside tiles or network calls; parcels are textured with 17 bundled local WebP tiles (`static/map-tiles`, `gis/svg.py`); the City view uses them. The tiles were generated at build time with a local image model (commits `5eddb89`, `6e96c36`), a build-time asset only.
- Demo video: `static/video/demo-video.mp4` is bundled on the landing page of the live demonstration, under the persona cards, at 720p, 179.7 s (about 3:00), 7.83 MB, preload none, no autoplay. It is the final cut, and picture lock was reached on 2026-11-02.
- Tests: 3819 collected on merged main, counted on 2026-11-02 (`python -m pytest --collect-only -q`). The last recorded full run passed 3237 without the browser checks (`EVIDENCE_LOG.md`, 2026-11-02). Phase counts 762 and 879 are historical. 10 gates unchanged.
- Licence: all rights reserved, copyright Randy Vollen and VollenData; the repository is public for transparency, hackathon evaluation and demonstration only (`LICENSE`, `NOTICE`). The earlier Apache 2.0 statement is withdrawn.
- Approval policy: `config/approval_policy.json`, default `single` (one administrator may approve); `independent` requires a different administrator.
- Steward autolink: `registry/automation.py`, `agents/linking.py`, `scripts/run_linking_worker.py`. A steward-activated policy; a bounded worker applies only high-confidence party links through a narrow service identity (`linking_agent`); each applied link is reviewable and reversible; parcel and address families are suggest-only; no model call.
- Steward Data issues workspace (four work areas: Data issues, Master records, Source records, Activity) and deterministic steward guide (`ui/steward_guide.py`, "Saved guidance."). Community page redesign at `/city/community`. Netlify front door (`netlify/`): static page that waits for `/readyz` through a proxied path, then redirects.
- Screen names (`ui/view_models.py`): People and organizations, Master records (`/masters`, `/property`), Data issues (`/steward`), Source records, Activity, Intake queue, Early resolution, Review queue, City view, What-if, Operations, Agents, Agent runs, Agent cases, Steward automation, New master record.
- Six simulated subscriber departments (not four).
- Diagram: Agent Operator persona box added, persona boxes in story order, edge from the operator to the browser; the Administration to agents edge is now labelled processing policy. A separate worker and queue box was not drawn: the diagram grid has no free slot (the permit edge crosses the only empty cell), so the worker is described in the agents node text.

## Master data as the spine (2026-10-30)

Sources: `repo/src/acme_city/registry/` (`service.py` propose, decide, apply_automatic_link; `provenance.py` trusted view), `persistence/models/registry.py` (CanonicalEntity, Crosswalk with versions and decision actor, MatchProposal, Provenance), `config/property_subscribers.json` (six departments, read only).
- Callers that import the registry: `ingestion/service.py`, `agents/intake.py`, `agents/linking.py`, `muse/service.py` (proposals); `permits/service.py`, `permits/issuance.py`, `permits/queues.py`, `finance/service.py` (reads); `ui/property_views.py` (property master).
- The public community lookup does not read registry identities. It reads `insight/public.py` over an allowlist model and the GIS catalog, so the page says it is separate by design.
- Diagram: the registry node is at the centre of the System view with a heavier outline (class `core`). New edges: agents to registry "proposes link", Data Steward to registry "decides", registry to permits, finance and property master "reads". Evidence and tests moved to the cell the registry used to hold.

## Final pass, 2026-11-02 (the rebuild of the page)

Sources: the tree at `3a77390`, read on 2026-11-02: `BUILD_LOG.md`, `EVIDENCE_LOG.md`, `GO_NO_GO.md`, `render.yaml`, `repo/docker-compose.yml`, `repo/config/permissions.json` and the code under `repo/src/acme_city/`.

- The internal-review banner and every other internal-review or draft status marker are removed from the page. The project owner's decision of 2026-11-02 overrides the banner rule of the build skill for this page. The byline and the "Example with fictional data" labels stay.
- Steward data no longer holds a case (merge `50638bb`, `BUILD_LOG.md` "Non-blocking steward data"). An open parcel or identity link is Data follow-up, and the agent recommends from the rules it could check. A rule that depends on the parcel shows as Not checked. Missing applicant information still returns to the applicant, and the payer link and the fee still block issuing.
- Approving against a failed rule is allowed and is recorded as an exception with its reason (commit `0bae0db`, `docs/operations/RUNBOOK.md`).
- The pre-submit check (`repo/src/acme_city/applicant_portal/presubmit.py`): Check my application runs the rules layer and asks Muse for feedback. The findings are grouped as Must fix, Should check and Looks good. Submit anyway needs a written reason, and submitting itself makes no model call (`repo/src/acme_city/ui/portal_routes.py`, `muse=False` on submit).
- The demonstration uses the real clock. Render no longer sets `ACME_SCENARIO_CLOCK=auto`, and the Compose file leaves the setting empty (commits `4782b46` and `3a77390`).
- Permissions: 85, in `repo/config/permissions.json`.
- Tests: 3819 collected on merged main, counted on 2026-11-02. The last recorded full run passed 3237 without the browser checks (`EVIDENCE_LOG.md`, 2026-11-02).
- The live paths of Muse: the applicant help answer, Check my application, Explain with Muse, the council briefing and the what-if proposals (`repo/src/acme_city/ui/guide_routes.py`, `_surface_live`). The document extraction is a recorded Muse run and is replayed (`repo/src/acme_city/agents/extraction.py`).
- The hosted demonstration enables live Muse in `render.yaml` with a daily allowance of 100 and a live-call cap of 100. The credential is entered in the Render dashboard and never sits in the repository.
- The demo video is finished. The final cut was recorded from the final build of the application and reached picture lock on 2026-11-02.
- The diagram keeps its Play and step-through engine. `repo/src/acme_city/templates/help.html` and `repo/src/acme_city/ui/help_docs_routes.py` are untouched by this pass.

## Presentation pass, 2026-11-02 (the brand line and the theme toggle)

Sources: the project owner's two corrections of 2026-11-02, read against the built page in a browser.

- The footer brand line, "VollenData" over "A Brighter Future, Rooted in Data.", is right aligned against the page edge. The two are separated by a visible 6px gap, and the markup carries a space between the two spans so a text copy reads "VollenData A Brighter Future, Rooted in Data." The wordmark stays the single word "VollenData". The rule lives in the page local block of `page/extra.css`, not in the brand layer copy, because the shared brand layer is recopied on every rebuild.
- The theme toggle sets `data-theme` on the root element and does not depend on `localStorage`. A frame that allows scripts without the same origin has an opaque origin, and `localStorage` raises a `SecurityError` there; the toggle still flips the theme. Persistence is best effort and is not needed for the page to work.
- The shared brand layer in the build skill, `assets/vds-brand/extra.css` and `assets/vds-brand/snippets.html`, was not changed. The sandbox refused both files. The skill still carries the older footer rule and the older theme script, and every other page copies that script into its own `body.src.html`, so the skill template should take the same script in a later pass.
- No figure, status value or claim changed in this pass.

## Judge-facing pass, 2026-11-02 (no review status, and Muse as the only model name)

Sources: the project owner's instruction of 2026-11-02, read against the built page.

- The page carries no open-gate or review-status sentence. The "Release gates" row of "What exists now" and the "Review gates" row of "Open decisions and limitations" are gone, and the open-decisions rows are renumbered. The security review section stays: it reports a completed review and its fixed findings, not a gate that is still open.
- The banner rule of the build skill does not apply to this page, and the same decision covers the gate and review status lines. Neither the banner nor any gate status is restored by a rebuild or by a status refresh. `update_status.py` no longer writes a release-gates row.
- The only model name on the page is Muse. The Muse product variants, the model versions and the model identifiers are removed from the copy, the diagram, the diagram alt text and the info panels. The diagram's external model services keep one node titled "Muse" and one titled "Icon generation", and the runtime node's subtitle reads "Standard mode, bounded call".
- The facts in this sheet keep the model names, the gate statuses and the review findings. The sheet is the gate for the build, and it is internal.

## Picture lock and no scheduled reset, 2026-11-02 (the rebuild of the page)

Sources: the project owner's instruction of 2026-11-02, read against `render.yaml` at the repository root, `repo/src/acme_city/static/video/demo-video.mp4`, `repo/src/acme_city/templates/components/demo_video.html` and `repo/src/acme_city/templates/base.html`, and a collection run on the merged main tree.

- The scheduled demonstration reset is gone. `render.yaml` holds one web service and no scheduled job. The page says so: the blueprint defines one web service, built from `repo/Dockerfile-demo`, and every deploy rebuilds the demonstration data. The reset schedule and its clock time appear nowhere on the page.
- The demo video is finished. Picture lock was reached on 2026-11-02. The bundled file is `repo/src/acme_city/static/video/demo-video.mp4`: 720p, 179.7 s (about 3:00), 7829407 bytes (7.83 MB), `preload="none"`, no autoplay. The component is included from `base.html` on the landing page, under the persona cards, so the video plays there.
- The page states the video as finished. The "In progress" chip, the "being recorded" sentence, the "Final pass" row about the drifting face and the "replaced at picture lock" sentence are gone. The video rows now carry the cut, the presenter, the voice, the screens, the file and where it plays.
- Tests: 3819 collected on merged main, counted on 2026-11-02 with `python -m pytest --collect-only -q`. The figure on the page and the two figures in this sheet are that count. The earlier note about checks that landed later the same day is dropped.
- The build is the same one the kit owns: `inline_assets.py` writes `page/body.html` from `page/body.src.html`, the kit builder writes the self-contained HTML, the Linux checker runs the kit checker in headless Chrome, and `check/verify_page.py` runs the independent checks.
- The allowed figure list in `check/verify_page.py` follows the page: the collected count, the video length and size, and the date fragment of 2026-11-02.
