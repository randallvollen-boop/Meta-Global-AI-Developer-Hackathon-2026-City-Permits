# Registry and Stewardship Implementation Plan

> **For agentic workers:** Begin after foundation F4. R1 precedes R2; R2 precedes R3; R4 integrates the slice.

**Goal:** Implement registered source ingestion, canonical identity, evidence-based matching, steward decisions, source correction acknowledgements, reliable publication and impact propagation.

**Architecture:** Three local source adapters persist their own source records and versions. Registry services own canonical IDs, crosswalks and provenance but never source facts. Change services own lifecycle, acknowledgements and a database outbox with idempotent dispatch.

**Tech Stack:** Foundation stack plus SQLAlchemy services and FastAPI routers.

**Spec:** `../REQUIREMENTS_OUTLINE.md`

**Parent plan:** `2026-10-26-acme-city-end-to-end.md`

## Global Constraints

- Source adapters are explicitly labeled simulated and cannot imply real municipal writes.
- Raw payloads are preserved before normalization.
- Arrival time never substitutes for source or effective time.
- Every P0 cross-source link requires an actual authorized steward decision.
- Similar names, shared addresses and model scores cannot independently establish identity.
- Approved is not synchronized; accepted source versions and registry commits are separate transitions.

### Task R1: Registered source intake and persisted adapters

**Requirement:** Implement ING-01–ING-05, EDIT-01 source destinations, D06, D08 and D10 intake behavior.

**Files:**
- Create: `src/acme_city/ingestion/schemas.py`
- Create: `src/acme_city/ingestion/normalization.py`
- Create: `src/acme_city/ingestion/validation.py`
- Create: `src/acme_city/ingestion/service.py`
- Create: `src/acme_city/ingestion/router.py`
- Create: `src/acme_city/adapters/sources/base.py`
- Create: `src/acme_city/adapters/sources/permitting.py`
- Create: `src/acme_city/adapters/sources/gis.py`
- Create: `src/acme_city/adapters/sources/erp_finance.py`
- Create: `tests/unit/test_ingestion.py`
- Create: `tests/unit/test_normalization.py`
- Create: `tests/api/test_source_adapters.py`
- Create: `tests/regression/test_invalid_inputs.py`

**Interfaces:**
- Produces `IngestCommand`, `IngestResult`, `IngestionService.ingest`, and `SourceAdapter.apply(command: SourceCommand, actor: ActorContext) -> SourceAcknowledgement`.
- `IngestResult` reports `received`, `accepted`, `unchanged`, `quarantined`, `unresolved`, snapshot IDs and field errors.

**Acceptance checks:**
- `uv run pytest tests/unit/test_ingestion.py tests/unit/test_normalization.py tests/api/test_source_adapters.py tests/regression/test_invalid_inputs.py -q` → pass.
- Identical source version/payload → unchanged with same snapshot; changed payload/version → new immutable snapshot; older late version → history only plus issue.
- Unowned feed → staged/quarantined from trusted publication until governance registration.

- [ ] Implement contract-driven type, finite-number, range, enum, conditional, reference and source-version validation while preserving raw payload/hash first.
- [ ] Implement name/address comparison normalization that preserves raw values and unit boundaries and creates no identity link.
- [ ] Implement idempotent ingestion keys from source, dataset, record, source version and payload hash with explicit ambiguity handling.
- [ ] Implement source observations with separate source/effective/ingested timestamps and accurate denominators.
- [ ] Implement working local source endpoints for Permitting, GIS and ERP/Finance that authorize writes, require expected versions, persist source versions and return accepted/rejected/timeout/conflict acknowledgements.
- [ ] Add regression inputs for `setback='twenty'`, `setback='nan'`, blank fence location and unsupported sign type with area 1000; verify explicit errors and no crash/approval.

### Task R2: Canonical identity, proposals, trusted views and decisions

**Requirement:** Implement MDM-01–MDM-04, GOV-05, D01, D02, D03 and D04 identity behavior.

**Files:**
- Create: `src/acme_city/registry/schemas.py`
- Create: `src/acme_city/registry/candidates.py`
- Create: `src/acme_city/registry/provenance.py`
- Create: `src/acme_city/registry/service.py`
- Create: `src/acme_city/registry/router.py`
- Create: `tests/unit/test_candidate_generation.py`
- Create: `tests/unit/test_trusted_view.py`
- Create: `tests/api/test_registry_api.py`
- Create: `tests/scenarios/test_d01_identity.py`
- Create: `tests/scenarios/test_d02_false_friend.py`
- Create: `tests/scenarios/test_d03_credential.py`
- Create: `tests/scenarios/test_d04_unknown_parcel.py`

**Interfaces:**
- Produces `MatchProposalCommand`, `MatchProposalView`, `MatchDecisionCommand`, `CrosswalkView`, `RegistryService.propose`, `decide`, `current_crosswalk`, and `trusted_view(entity_id)`.
- Proposal evidence records `field`, `source_snapshot_id`, raw/normalized values, direction (`supporting` or `conflicting`) and method; proposal scores are labeled uncalibrated unless evidence proves calibration.

**Acceptance checks:**
- `uv run pytest tests/unit/test_candidate_generation.py tests/unit/test_trusted_view.py tests/api/test_registry_api.py tests/scenarios/test_d0{1,2,3,4}_*.py -q` → pass.
- D02 shared-building/similar-name candidate remains unresolved or rejected and never creates an accepted crosswalk automatically.
- Trusted views choose declared authoritative snapshots even when another source is newer or has a higher proposal score.

- [ ] Implement typed canonical identities and one-active-approved-crosswalk constraints with complete prior/rejected decision history.
- [ ] Generate deterministic candidate proposals from declared keys and comparison evidence, including explicit no-match and conflicting unit/credential evidence.
- [ ] Require `domain_mdm_steward` permission, domain scope and expected crosswalk version for every decision.
- [ ] Build field-level provenance and trusted views from active authority policy; unknown/disputed authority creates an assigned issue and dependent blocker.
- [ ] Persist actual steward actor/time/reason/evidence for supported and rejected D01/D02 links; do not use evaluator truth.

### Task R3: Change lifecycle, source acknowledgements and outbox

**Requirement:** Implement CHG-01–CHG-06, EDIT-03–EDIT-04, MDM-05 and D06/D08/D10 publication behavior.

**Files:**
- Create: `src/acme_city/changes/schemas.py`
- Create: `src/acme_city/changes/state_machine.py`
- Create: `src/acme_city/changes/service.py`
- Create: `src/acme_city/changes/dispatcher.py`
- Create: `src/acme_city/changes/router.py`
- Create: `tests/unit/test_change_state_machine.py`
- Create: `tests/unit/test_outbox.py`
- Create: `tests/api/test_changes_api.py`
- Create: `tests/scenarios/test_d06_source_correction.py`
- Create: `tests/scenarios/test_d08_replays.py`
- Create: `tests/acceptance/test_at08.py`
- Create: `tests/acceptance/test_at16.py`
- Create: `tests/acceptance/test_at20.py`

**Interfaces:**
- Produces `ChangeRequestCommand`, `ChangeTransitionCommand`, `ChangeCaseView`, `DispatchSummary`, `ChangeService.request`, `transition`, `preview_impact`, `dispatch_pending`.
- Factual path: Requested → In review → Awaiting approval? → Approved → Sent to source → Source acknowledged → Published → Closed.
- Registry path: Requested → In review → Awaiting approval? → Approved → Registry committed → Published → Closed.

**Acceptance checks:**
- `uv run pytest tests/unit/test_change_state_machine.py tests/unit/test_outbox.py tests/api/test_changes_api.py tests/scenarios/test_d06_source_correction.py tests/scenarios/test_d08_replays.py tests/acceptance/test_at08.py tests/acceptance/test_at16.py tests/acceptance/test_at20.py -q` → pass.
- Timeout/rejection preserves accepted source value; late v2 after accepted v3 cannot roll state back.
- Identical delivery reuses key and creates at most one dependent task; changed payload under same key returns conflict.

- [ ] Implement state-specific permissions, evidence, assignee/approver, expected version, destination and before/after version references.
- [ ] Implement impact preview over applications, evaluations, assessments, decisions and permits before approval.
- [ ] Implement source command dispatch with accepted, rejected, timeout and late-response fixture controls; source acknowledgement alone does not imply consumer publication.
- [ ] Implement durable outbox and consumer acknowledgement processing that survives restart and de-duplicates dependent tasks.
- [ ] Implement reversible crosswalk correction that preserves old decision, creates a new version and registers revalidation/impact tasks.
- [ ] Return structured `ConflictResult` with current version and field differences on stale changes; verify zero mutation.

### Task R4: Registry and source API integration gate

**Requirement:** Make the entire governed source-to-registry correction slice observable through scoped APIs before UI implementation.

**Files:**
- Modify: `src/acme_city/app.py` — mount ingestion, registry and changes routers.
- Create: `tests/acceptance/test_at01.py`
- Create: `tests/acceptance/test_at05.py`
- Create: `tests/acceptance/test_at06.py`
- Create: `tests/acceptance/test_at07.py`
- Create: `tests/supplementary/test_vc01.py`
- Create: `tests/supplementary/test_vc02.py`
- Create: `scripts/dispatch_outbox.py`

**Interfaces:**
- API routes use `/api/sources`, `/api/registry`, `/api/changes` and return stable typed error envelopes `{code, message, current_version?, differences?}`.

**Acceptance checks:**
- `uv run pytest tests/acceptance/test_at0{1,5,6,7,8}.py tests/acceptance/test_at16.py tests/acceptance/test_at20.py tests/supplementary/test_vc0{1,2}.py -q` → pass.
- `uv run python scripts/dispatch_outbox.py --once` before and after service restart → pending work persists and acknowledgements are idempotent.

- [ ] Mount routers and add OpenAPI operation IDs matching explicit actions rather than generic edits.
- [ ] Add acceptance fixtures that establish actor sessions through the real session endpoint and call direct APIs without test-only authorization bypasses.
- [ ] Record exact source/registry versions, actors, correlation IDs, command keys and affected task IDs in test evidence payloads.
- [ ] Run the registry slice gate and update the root build/evidence logs with actual counts and limitations.
