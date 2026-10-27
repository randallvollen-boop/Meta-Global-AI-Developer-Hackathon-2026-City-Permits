# ACME City End-to-End Requirements Outline

Date: October 26, 2026  
Authoritative specification: `../../intake/extracted/ACME_MDM_Build_Package/requirements/ACME_MDM_Demo_Requirements.txt`  
Specification SHA-256: `54881e679cf9744f61251f7cc314ffa5400ffd3f53f67e21581371cf9f27de4d`

This outline is an execution index. The authoritative specification controls every conflict.

## Product completion condition

`SYN-APP-001`, a fictional commercial tenant-improvement application, must move through immutable submission, a substantive live Muse extraction or identity proposal, schema validation, recorded steward decisions, deterministic validation, an actual seeded reviewer decision, a versioned fee assessment, Finance-confirmed allocation of a settled simulated payment, and a separate simulated permit issuance. The complete source-to-outcome trace must survive refresh and restart. An identical issuance retry must return the original permit and artifact.

## Governance and ownership — 7 requirements

| ID | Required behavior | Verification |
| --- | --- | --- |
| GOV-01 | Register domain, owner, steward queue, custodian, contract, authority and correction route before trusted publication; allow raw unowned staging only. | AT01 |
| GOV-02 | Resolve current responsibility through effective assignments and preserve historical attribution. | AT01 |
| GOV-03 | Give every queue an active primary, delegate, escalation owner and configurable response target. | AT01 |
| GOV-04 | Show owner, steward, source, correction destination, versions, source/receipt times and issues on governed records. | AT01 |
| GOV-05 | Declare one correction destination per decision-relevant field group; disputed authority creates a blocking issue. | AT01, AT07 |
| GOV-06 | Escalate outside-delegation, disputed and cross-domain decisions while preserving positions and outcomes. | AT01 |
| GOV-07 | Maintain effective-dated assignments; require active-work reassignment and preview authority-policy impacts. | AT01 |

## Explicit edits and history — 5 requirements

| ID | Required behavior | Verification |
| --- | --- | --- |
| EDIT-01 | Use explicit action names and working local source screens with permission, persistence and acknowledgement. | AT02 |
| EDIT-02 | Explain denied edits by source, steward, permitted route, role, state or unresolved issue. | AT02 |
| EDIT-03 | Preview old/proposed values, evidence, destination, affected cases/permits and rechecks before approval. | AT02 |
| EDIT-04 | Treat source facts as authoritative only after source acknowledgement; show pending, rejected and failed states truthfully. | AT08 |
| EDIT-05 | Change current profiles without rewriting submitted declarations, notices, decisions or issued permits. | AT04 |

## Source registration and intake — 5 requirements

| ID | Required behavior | Verification |
| --- | --- | --- |
| ING-01 | Define source keys, types, schema versions, required/allowed values, date meanings, field classes and correction routes. | AT01 |
| ING-02 | Preserve raw snapshots and quarantine invalid types, nonfinite values, ranges, conditions, references and enums with field errors. | AT12 |
| ING-03 | Make ingestion idempotent, preserve changed/late versions and prevent older arrivals from replacing newer accepted state. | AT05, AT08 |
| ING-04 | Normalize safely while retaining raw values, units and identifiers; normalization never establishes authority or identity. | VC01 |
| ING-05 | Report received/accepted/unchanged/quarantined/unresolved denominators and distinguish source, effective and receipt times. | VC02 |

## Registry MDM and identity — 5 requirements

| ID | Required behavior | Verification |
| --- | --- | --- |
| MDM-01 | Use immutable typed canonical IDs and versioned source crosswalks without schema changes for new datasets. | AT05 |
| MDM-02 | Produce evidence-based proposals with supporting/conflicting facts; every new P0 link requires steward approval. | AT06 |
| MDM-03 | Prevent false matches based only on names, addresses or scores; preserve unit, issuer and temporal distinctions and support no-match. | AT06 |
| MDM-04 | Build trusted views from field authority and provenance, preserving disagreement and never inventing missing facts. | AT07 |
| MDM-05 | Correct/remove links reversibly with expected versions, reasons, impact previews and revalidation tasks; never destructively merge sources. | AT20 |

## Changes, publication and concurrency — 6 requirements

| ID | Required behavior | Verification |
| --- | --- | --- |
| CHG-01 | Enforce server-side state transitions and permissions; retain actors, evidence, expected versions, destinations, responses and publication versions; prohibit self-approval. | AT08, AT13 |
| CHG-02 | Persist simulated source changes and acknowledgements; rejection/timeout preserves accepted state and blocks only dependent actions. | AT08 |
| CHG-03 | Register dependencies, preview impact, invalidate affected pending work and create one assigned review task per dependency/event. | AT09, AT20 |
| CHG-04 | Preserve submitted, evaluated, signed, financial and issued history; use impact review rather than silent mutation. | AT10, AT20 |
| CHG-05 | Use a durable outbox with correlation, version, idempotency, retries and acknowledgements that survives restart and rejects late rollback. | AT08, AT19 |
| CHG-06 | Require expected versions and return useful conflicts without overwriting accepted changes. | AT16 |

## Permit workflow — 6 requirements

| ID | Required behavior | Verification |
| --- | --- | --- |
| PER-01 | Scope applicant/staff contributions and keep application facts separate from shared Party and GIS facts. | AT04 |
| PER-02 | Return explicit validation/review results for missing, malformed, nonfinite and unsupported inputs; repair all four named evaluator defects. | AT12 |
| PER-03 | Persist evaluation inputs and versions; dependency changes stale evaluations and approved-unissued decisions; reviewer reconfirmation is mandatory. | AT09 |
| PER-04 | Persist an authenticated, authorized reviewer confirmation/modification/denial/information request with actor, time, reason and versions. | AT11 |
| PER-05 | Issue separately only after current prerequisites; use idempotent commands and immutable fictional permit snapshots/artifacts. | AT10, AT19 |
| PER-06 | Preserve initial and revision submission dates; record the configured date basis used for rules, fees and credentials. | AT13 |

## Rule and reference catalogs — 2 requirements

| ID | Required behavior | Verification |
| --- | --- | --- |
| REF-01 | Reconcile narrative and executable rules into one approved versioned catalog with stable IDs, types, citations, parameters and ownership. | AT13 |
| REF-02 | Govern Draft → In review → Approved → Published → Retired versions, preventing unresolved overlaps and using one selected version everywhere. | AT13 |

## Fees and finance — 5 requirements

| ID | Required behavior | Verification |
| --- | --- | --- |
| FIN-01 | Calculate authoritative fees deterministically with exact arithmetic and store lines, inputs, currency, rules and versions. | AT17 |
| FIN-02 | Reassess explicitly, atomically release/reallocate funds once, preserve prior assessments/allocations and prevent later schedules from rewriting history. | AT17 |
| FIN-03 | Keep stable receipt identity and append settlement/reversal events idempotently; conflicting key reuse fails. | AT18 |
| FIN-04 | Require approved payer/account links and Finance-confirmed version-scoped allocations; prevent duplicates, over-allocation, invalid settlement/currency and silent reversal handling. | AT17, AT18 |
| FIN-05 | Show assessed, settled-allocated and balance values with evidence; only exact current reconciliation permits issuance. | AT18 |

## Muse and model evidence — 5 requirements

| ID | Required behavior | Verification |
| --- | --- | --- |
| AI-01 | Perform at least one substantive live extraction or match-proposal task; Muse never publishes, prices, decides or issues. | AT14 |
| AI-02 | Use strict structured output and reject unknown IDs, invented evidence/citations, malformed values and unauthorized document instructions. | AT14 |
| AI-03 | Persist mode, provider/model, prompt/schema versions, input references, output, validation, usage, latency and errors; label proposal scores. | AT15 |
| AI-04 | Distinguish live, replay and cached runs; preserve live failures and require explicit replay selection. | AT15 |
| AI-05 | Keep expected outcomes and all evaluation truth outside runtime payloads/retrieval; use actual versioned synthetic documents. | AT14 |

## User experience — 4 requirements

| ID | Required behavior | Verification |
| --- | --- | --- |
| UX-01 | Keep the responsibility panel visible and expose field-level source/edit authority on demand. | AT02 |
| UX-02 | Clearly distinguish current master, submitted, proposed and issued values and identify what each action changes. | VC03 |
| UX-03 | Use compact, consistent, keyboard-accessible controls and plain action labels. | VC04 |
| UX-04 | Show actual destination, accepted version or pending state and affected cases after actions; preserve feedback across refresh/navigation. | VC05 |

## Security and records — 4 requirements

| ID | Required behavior | Verification |
| --- | --- | --- |
| SEC-01 | Expose exactly four server-held selectable personas—Applicant, Data Steward, Permit Reviewer and City Administrator—with explicit granular role/action/domain/record grants; client role fields never authorize and service identities are not personas. This is the user-approved four-persona implementation of the source requirement. | AT03 |
| SEC-02 | Apply record/domain scope to lists, direct URLs, APIs, downloads and Muse context. | AT03 |
| SEC-03 | Separate contact, GIS, credential, link, rule, decision, allocation and issuance permissions; admin configuration never implies business approval. | AT03 |
| SEC-04 | Use fictional records, keep credentials server-side and preserve an append-only application audit trail without unsupported compliance claims. | VC06 |

## Evaluation and evidence — 3 requirements

| ID | Required behavior | Verification |
| --- | --- | --- |
| EVAL-01 | Report identity, extraction, unresolved and workflow outcomes with explicit denominators and small-fixture caveats. | VC07 |
| EVAL-02 | Keep baseline synthetic statistics, observed Muse/registry results and business outcomes separately labeled. | VC08 |
| EVAL-03 | Produce reproducible manifests containing fixture, source, model/replay, prompt/schema, rule, expected/actual and failure evidence. | AT19 |

## Required screens

1. Work queue.
2. Applicants.
3. Properties / Businesses / Contractors.
4. Permit workspace.
5. Steward review.
6. Rules and fees.
7. Reconciliation.
8. Governance and sources.

## Selectable personas

The application dropdown contains exactly four human personas:

1. Applicant.
2. Data Steward.
3. Permit Reviewer.
4. City Administrator.

Underlying role/action grants remain separate and auditable. Service identities, source adapters, custodians, outbox workers and Muse never appear in the dropdown. City Administrator receives separately declared configuration, governance, owner, Finance and audit grants; Administrator membership by itself never implies business approval.

## Controlled scenarios

| ID | Required scenario |
| --- | --- |
| D01 | Main commercial case: alias, unit variation, legacy finance ID, approved links, exact payment allocation and issuance. |
| D02 | False friend remains a distinct party despite similar name/address. |
| D03 | Expired/inactive contractor credential blocks the dependent action. |
| D04 | Unknown parcel remains unresolved; no invented parcel. |
| D05 | Profile update preserves submitted and issued history. |
| D06 | GIS correction rejection/delay retains accepted value and truthful pending/failed state. |
| D07 | Post-issuance rule/fee/master change preserves issued snapshot and opens impact review. |
| D08 | Replayed imports, payment, allocation, publication and issuance do not duplicate records/tasks/artifacts. |
| D09 | Malformed extraction, unknown category, invented citation and missing conditions produce explicit review results. |
| D10 | Unowned feed stages but cannot publish until governance registration. |
| D11 | Partial, excess, reversed, unsettled, unmatched or incompatible-currency payment never becomes false completion. |

## Westerville-inspired process constraints

Use public City of Westerville workflow concepts for channel routing, contractor registration, commercial plan review, versioned corrections, status tracking and post-issuance inspection handoff. Keep ACME City branding, synthetic rules, synthetic fee arithmetic and fictional data. Do not imply official integration, endorsement, legal authority or service levels.

## Acceptance inventory

- AT01–AT20: application/API behavior, including persistence, authorization, concurrency, idempotency, model boundaries, exact finance and end-to-end issuance.
- VC01–VC08: safe normalization, source observations, value distinctions, controls, feedback, records protection, denominators and separated measurements.
- D01–D11: controlled fixture outcomes recorded as expected versus observed.
- Final local gate: a fresh database reset, complete checks, one substantive live Muse run, application restart, browser walkthrough and exact issuance retry.
