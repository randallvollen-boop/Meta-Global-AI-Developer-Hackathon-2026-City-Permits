# City permit application alignment

Date: October 26, 2026  
State: built and merged on main (Phases 1 to 3 verified by the 10 checks in `repo/scripts/run_all_checks.py`); see `HANDOFF.md`

## 1. Authoritative target

The city-permit option is the ACME City permitting demonstration, built on registry master data management (MDM), defined by:

`intake/extracted/ACME_MDM_Build_Package/requirements/ACME_MDM_Demo_Requirements.txt`

The full specification controls. Companion JSON (JavaScript Object Notation) and text files are indexes, plans, and seed blueprints. They are not executable schemas, tests, or proof.

The prior city-permit application is preserved at:

`intake/extracted/ACME_MDM_Build_Package/reference/acme-city/`

It contributes a fictional permit domain, five permit-type configurations, synthetic data, deterministic rules, reports, and static pages. It does not implement the required live MDM registry, steward actions, source acknowledgments, server-enforced roles, payment allocation, reviewer decisions, or permit issuance chain. It stays unchanged as a reference baseline.

The source run guide also names an external click-through prototype, `PROTO-PERMIT-01` at `Prototypes/permit-processing`, but explicitly says it is not bundled. A scoped local search found no such directory. The alignment therefore treats that prototype as unavailable input and does not reuse it as code or implementation evidence.

The package preserves duplicate baseline code trees at `reference/acme-city/uc01/` and `reference/acme-city/files/uc01-code/`. If implementation is released, use `uc01/` as the single read-only reference and do not let the copies diverge. Its rules as written in the narrative documents and its executable rules also contain citation conflicts that must be reconciled into one approved catalog before publication. Four named evaluator defects (nonnumeric setback, nonfinite setback, blank fence location, and unsupported sign type) remain explicit regression gates.

## 2. Product story

The primary case is `SYN-APP-001`, a fictional commercial tenant-improvement application with:

- an organization alias;
- an ambiguous unit address;
- a contractor credential;
- a legacy enterprise resource planning (ERP) account identifier;
- a settled but initially unallocated simulated payment;
- a synthetic declared valuation of 50,000.00 USD.

The working chain must persist and expose:

`submission → live Muse proposal → steward decision → deterministic validation → reviewer decision → fee assessment → finance allocation → simulated issuance → restart/retry verification`

Muse proposes extractions or identity links with their evidence. Deterministic logic and authorized fictional actors control publication, rules, money, decisions, and issuance.

## 3. Westerville process model

Use the City of Westerville, Ohio's current public permitting process as the workflow reference, with the application visibly fictional ACME City software and no claim to be an official portal or clone.

The Westerville reference suggests this P0 shape:

1. **Route the submission.** Smaller projects and eligible trade permits use a permit portal; new commercial buildings, major renovations, site development, and digitally reviewed work use a plan-review portal. Model these as submission channels inside the simulated Permitting source, not as real integrations.
2. **Verify the contractor.** Commercial-trade access depends on an appropriately licensed contractor and verified registration. Model the fictional contractor credential as a distinct authoritative Permitting record with status, issuer, validity dates, and access effect.
3. **Submit a commercial interior alteration.** D01 remains a tenant-improvement case with an application, plans, site/unit evidence, contractor evidence, valuation, and supporting documents. Preserve immutable submission and resubmission versions.
4. **Completeness and plan review.** Intake checks required fields/documents, then routes current plans through building and applicable zoning/engineering/fire review. Muse may extract proposed facts; deterministic checks and human reviewers control outcomes.
5. **Corrections and resubmittals.** Review comments lead to explicit information requests and versioned resubmissions. Source corrections, application revisions, and identity-link corrections remain separate actions.
6. **Fees, approval, and issuance.** Show review fees, payment state, approval, and issuance as distinct stages. Keep the package's synthetic fee formula for AT17 rather than importing Westerville's current fee schedule into the fictional demo.
7. **Status and records.** Applicants and staff can inspect status, open issues, versions, responsibility, and next action. Refresh/restart preserves the chain.
8. **Inspection handoff.** Westerville requires onsite inspections after issuance. Record a P1 inspection handoff in the issued snapshot; full scheduling remains outside P0, consistent with the specification.

Westerville publishes an approximately ten-workday review estimate for commercial interior alterations and area-based fees, but those remain dated source context. They are not ACME service promises or authoritative demo calculations.

Public process references, checked October 26, 2026:

- https://www.westerville.org/services/planning-development/building
- https://www.westerville.org/services/planning-development/forms-and-online-portals
- https://www.westerville.org/services/planning-development/quick-links/submit-a-permit
- https://www.westerville.org/services/planning-development/quick-links/schedule-an-inspection

## 4. Source and authority alignment

| Domain | Authoritative component | Registry responsibility |
| --- | --- | --- |
| Applicant profiles and applications | Simulated Permitting source | Canonical party links, provenance, publication history |
| Contractor registration | Simulated Permitting source | Holder link and trusted combined view |
| Parcels, official addresses/units, zoning | Simulated geographic information system (GIS) source | Parcel/address crosswalks and provenance |
| Businesses and business licenses | Simulated ERP/Finance source | Organization links and selected authoritative attributes |
| Finance accounts and payment events | Simulated ERP/Finance source | Account-party links and evidence for allocation |
| Permit decisions and issuance | Permitting workflow with authorized actors | Dependency trace and immutable linked versions |
| Canonical identities and source links | Registry | Stable IDs, proposals, accepted/rejected links, reversible decisions |
| Rules and fee schedules | Approved application catalogs | Version selection, provenance, effective history |

A registry correction changes a link. A factual correction changes the authoritative source through its local adapter and requires acknowledgment. The interface keeps these operations separate.

## 5. Application structure

Implementation belongs under `repo/` and isolates the following modules even if one service and one SQLite database are used:

1. **Governance and authority**: domains, datasets, contracts, owners, stewards, queues, delegates, escalation, field authority, correction routes.
2. **Source intake**: immutable snapshots, raw payload references, schema validation, quarantine, source ordering, freshness, and counts.
3. **Registry and stewardship**: canonical entities, crosswalks, match proposals, evidence, no-match, steward decisions, provenance, and impact preview.
4. **Corrections and publication**: change cases, source commands, acknowledgments, registry commits, durable outbox, consumer acknowledgments, retries, and dependency tasks.
5. **Permit operations**: profiles, application revisions, documents, evaluations, recommendations, actual reviewer decisions, issuance, and impact review.
6. **Rules and finance**: one approved rule/fee catalog, exact fee arithmetic, assessments, payment events, allocations, reconciliation, reversals, and exceptions.
7. **Muse adapter**: live/replay/cached modes, prompt/output schemas, allowed-record validation, traceable runs, and isolated evaluation truth.
8. **Access and audit**: server-held fictional sessions, domain/action/record scope, denied writes, and append-only application audit history.

The executable implementation plan selects one Python 3.12 FastAPI service, SQLAlchemy/Alembic, one SQLite database, server-rendered HTML with vanilla JavaScript, three in-process source adapters and a database-backed outbox.

### Selectable personas

The application actor dropdown is capped at four human personas:

1. **Applicant**: authorized profile, draft, submission and response actions.
2. **Data Steward**: explicit intake, domain stewardship and registry-link grants within scoped queues.
3. **Permit Reviewer**: explicit reviewer and separate issuing-officer grants; approval never issues automatically.
4. **City Administrator**: separately declared configuration, governance, owner, Finance and audit grants needed by the demo; each sensitive action still checks its specific grant and workflow state.

The original role definitions remain a permission vocabulary and add no personas. Source adapters, custodians, outbox workers and Muse are service identities and never appear in the dropdown.

## 6. Required user experience

| Screen | Required outcome |
| --- | --- |
| Work queue | Assigned applications/issues, blocker, age, target, and next action |
| Applicants | Shared Party identity, aliases, contacts, cases, evidence, sources, and history |
| Properties / Businesses / Contractors | Role-filtered authoritative facts, relationships, credentials, and correction routes |
| Permit workspace | Submission, documents, identity state, deterministic rules, review, finance, and history in one case view |
| Steward review | Evidence comparison, supported/rejected links, source corrections, impact preview, and acknowledgment state |
| Rules and fees | Current/historic versions, owners, effective dates, approvals, publication, and affected cases |
| Reconciliation | Assessments, receipts, account links, proposed allocations, balances, reversals, and exceptions |
| Governance and sources | Dataset registration, ownership/steward assignments, authority, unowned intake, and synchronization health |

Every governed record must show a compact responsibility panel: **Owner, Steward, Source, Change this in, Version, Last source update, Last received, Open issues**. Field-level authority appears on demand.

## 7. Data and workflow invariants

- Stable internal IDs are distinct from names, addresses, display numbers, account IDs, and source IDs.
- Applicant, owner, contractor, payer, and permit holder are roles and never interchangeable identities.
- Current profile, submitted revision, recommendation, signed decision, assessment, allocation, and issued permit are separate records or versions.
- Unknown source/effective times remain unknown; ingestion time is not substituted.
- Similar names, shared addresses, or model scores cannot establish identity without a recorded steward decision.
- Approval and synchronization are separate states. Source-owned facts become authoritative only after source acknowledgment.
- Expected versions protect corrections, link decisions, rule publication, allocations, reviewer decisions, and issuance.
- Relevant changes invalidate affected evaluations and approved-but-unissued decisions; deterministic revalidation does not restore reviewer approval.
- Issued history remains immutable and receives a separate impact-review case.
- Money uses exact decimal or minor-unit arithmetic. Model text never establishes an authoritative amount.
- Identical command retries are idempotent; changed operations or expected versions require new linked commands.

## 8. Demonstration arithmetic

The fictional schedule is:

`100.00 USD + (0.001 × declared valuation)`, with the variable component rounded once to cents using `ROUND_HALF_UP`.

- 50,000.00 valuation → 50.00 variable + 100.00 fixed = **150.00 USD**.
- 70,000.00 reassessment → **170.00 USD**.
- Applying the existing 150.00 payment once leaves **20.00 USD due** and keeps issuance blocked.

These are synthetic demo inputs and state no municipal policy.

## 9. Muse alignment

Target the configured Standard model actually available at implementation. Current account catalog evidence includes `muse-spark-1.3`; Contributor variants are prohibited for this workspace.

The preferred demonstration uses Muse for both document extraction and identity-link proposals. P0 requires at least one substantive live task in the primary chain. The adapter must:

- use actual synthetic files or permitted source records;
- validate structured output against allowed IDs and evidence locations;
- reject invented IDs, unsupported citations, malformed numbers, and embedded instructions requesting unauthorized actions;
- persist provider/model, mode, prompt/schema versions, inputs, output, validation, latency, available usage, and errors;
- keep evaluation truth and `truth_*` fields outside runtime payloads and retrieval;
- label live, replay, and cached modes visibly.

## 10. Milestone alignment

| Milestone | Gate |
| --- | --- |
| 1. Governed data foundation | AT01 plus implemented endpoint scope checks; persistence after restart |
| 2. Stewardship and corrections | AT05 to AT08 with deterministic proposals and real steward actions |
| 3. Operational permit chain | AT02 to AT04, AT09 to AT13, AT16 to AT18, AT20; deterministic D01 only |
| 4. Live Muse evidence | AT14, AT15, full AT19; rerun AT06 with live proposals |
| 5. Integrated release | AT01 to AT20, VC01 to VC08, D01 to D11, reset and restart evidence, and accurate claims |

No milestone is verified from a screenshot, static report, generated role label, mocked final state, or companion JSON file.

## 11. Current decisions and pending gates

### Established

- New workspace is separate from any other project.
- Intake package and old city-permit reference remain preserved and unmodified.
- New code will live under `repo/`.
- Intake is excluded from Git.
- Synthetic data only; no real municipal systems, permits, payments, or client records.
- Meta Standard mode only; no Contributor variant.

### Pending

- Randall's final choice between hackathon build options.

- GitHub repository name and visibility; owner is fixed to `RandallVollen-boop` only.
- Full event/Rules acceptance and any submission-format requirements.
- Independent confirmation of credit balance, expiration, eligible products, and no-cash controls.
- Live Muse city-permit task and evidence.

### 2026-11-02 — Non-blocking steward data

- An open parcel or identity link is Data follow-up, not an adjudication hold.
  The adjudication agent recommends from checked deterministic rules and names
  every parcel-dependent rule that remains Not checked. A Permit Reviewer still
  records the decision and any required exception rationale.
- Authorized parcel and identity corrections remain available after review,
  decision, and issuance; neither changes source-owned facts. Payer linkage
  and the assessed, settled fee remain issuance gates.
- D01–D11, AT01–AT20, DF-1, and DF-2 expected data remain unchanged. Browser
  verification of this design change remains pending with the lead.
