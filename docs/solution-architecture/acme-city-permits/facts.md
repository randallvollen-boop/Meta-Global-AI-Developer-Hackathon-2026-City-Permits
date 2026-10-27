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
`STATUS.json` is the one architecture-status record. Current state at 2026-10-27 06:19 Eastern:

- Overall: VERIFIED.
- Architecture: AS BUILT.
- Requirements: 57 total, 57 outlined, 57 implemented, 57 verified through integrated mapped checks.
- Execution tasks: 22 total, 22 verified; Complete: local user test.
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
