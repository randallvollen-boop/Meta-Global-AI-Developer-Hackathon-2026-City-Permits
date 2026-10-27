# Permit, Rules, Finance and Issuance Implementation Plan

> **For agentic workers:** P1–P3 may begin after foundation F4. P4 consumes approved links from registry R2. P5 consumes P3 and P4.

**Goal:** Implement immutable application revisions, deterministic rules, actual reviewer decisions, exact fee assessment, payment event history, governed allocations, reconciliation and separate idempotent simulated issuance.

**Architecture:** Permit, rule and finance services are separate transactional boundaries sharing stable version references. Recommendations are advisory records; decisions require a permitted actor. Issuance snapshots immutable inputs and returns the same artifact for identical retries.

**Tech Stack:** Foundation stack, Python `Decimal`, SQLite integer cents, Jinja printable permit template.

**Spec:** `../REQUIREMENTS_OUTLINE.md`

**Parent plan:** `2026-10-26-acme-city-end-to-end.md`

## Global Constraints

- Preserve all five permit configurations; only `com_ti` receives the complete P0 operational chain.
- Use one approved fictional rule/fee catalog for execution, retrieval, explanations and citations.
- Use `initial_submitted_at` for the P0 zoning/fee selection basis and explicit review/issuance times for credentials.
- Recommendations never populate reviewer identity or perform decisions.
- Approval and issuance are separate authorized transitions.
- Store money as integer cents and calculate with `Decimal` plus `ROUND_HALF_UP` exactly once at the variable component.

### Task P1: Approved rule/fee catalog and deterministic evaluator

**Requirement:** Implement REF-01–REF-02, PER-02, PER-06 and the exact AT12/AT13 rule behavior.

**Files:**
- Create: `src/acme_city/rules/schemas.py`
- Create: `src/acme_city/rules/catalog.py`
- Create: `src/acme_city/rules/evaluator.py`
- Create: `src/acme_city/rules/service.py`
- Create: `src/acme_city/rules/router.py`
- Create: `tests/unit/test_rule_catalog.py`
- Create: `tests/unit/test_evaluator.py`
- Create: `tests/acceptance/test_at12.py`
- Create: `tests/acceptance/test_at13.py`

**Interfaces:**
- Produces `RuleCatalogService.resolve(kind, permit_type, basis_at) -> RuleSetVersion`, `evaluate(inputs, rule_set) -> tuple[RuleResult, ...]`, `publish(command, actor) -> VersionedResult[RuleSetView] | ConflictResult`.
- `RuleResult.status` is one of `pass`, `condition`, `fail`, `review`; missing/invalid/unknown applicability yields `review`, never implicit pass.

**Acceptance checks:**
- `uv run pytest tests/unit/test_rule_catalog.py tests/unit/test_evaluator.py tests/acceptance/test_at12.py tests/acceptance/test_at13.py -q` → pass.
- Exact malformed inputs produce field/review results without crash or approval.
- Author cannot approve own rule; overlapping published applicability without explicit precedence is rejected.

- [ ] Implement catalog mappings from preserved baseline rule IDs to one nonconflicting fictional citation/version register.
- [ ] Implement Draft → In review → Approved → Published → Retired with author/approver separation and expected versions.
- [ ] Implement finite numeric, enum and conditional applicability validation before comparisons.
- [ ] Implement deterministic evaluation for all five permit configurations while keeping complete workflow behavior scoped to `com_ti`.
- [ ] Persist selected rule versions, input values, basis date/reason and every rule result.

### Task P2: Applications, revisions, evidence and evaluations

**Requirement:** Implement PER-01–PER-03, EDIT-05, D01, D04, D05 and D09 application behavior.

**Files:**
- Create: `src/acme_city/permits/schemas.py`
- Create: `src/acme_city/permits/service.py`
- Create: `src/acme_city/permits/router.py`
- Create: `src/acme_city/documents/service.py`
- Create: `tests/unit/test_application_revisions.py`
- Create: `tests/unit/test_evaluations.py`
- Create: `tests/api/test_permit_api.py`
- Create: `tests/scenarios/test_d05_profile_history.py`
- Create: `tests/scenarios/test_d09_invalid_extraction.py`
- Create: `tests/acceptance/test_at04.py`
- Create: `tests/acceptance/test_at09.py`

**Interfaces:**
- Produces `SubmitApplicationCommand`, `ApplicationRevisionView`, `EvaluationView`, `PermitService.submit`, `revise`, `evaluate`, and `DocumentService.store_version`.
- Document versions store bytes outside templates under ignored `var/documents`, with hash/path metadata in the database and filename/media-type allowlists.

**Acceptance checks:**
- `uv run pytest tests/unit/test_application_revisions.py tests/unit/test_evaluations.py tests/api/test_permit_api.py tests/scenarios/test_d05_profile_history.py tests/scenarios/test_d09_invalid_extraction.py tests/acceptance/test_at04.py tests/acceptance/test_at09.py -q` → pass.
- Profile v2 changes current contact while submitted revision/notice remains v1.
- Decision-relevant dependency change marks evaluation and approved-unissued decision stale; re-evaluation does not restore approval.

- [ ] Implement draft, immutable submission/revision snapshots, role/site relationships, document versions and independent identity/financial/workflow state dimensions.
- [ ] Enforce applicant record scope and staff representation attribution on profile/application actions.
- [ ] Store actual fictional document bytes and versions with hashes; presence flags alone are rejected.
- [ ] Persist evaluations with application, source, crosswalk, credential, rule and basis versions.
- [ ] Register dependencies for every decision-relevant input so registry/rule/credential changes invalidate only affected cases.

### Task P3: Actual reviewer decisions and impact history

**Requirement:** Implement PER-04, CHG-03–CHG-04 and D03/D07 human decision and historical behavior.

**Files:**
- Create: `src/acme_city/permits/decisions.py`
- Create: `src/acme_city/permits/impact.py`
- Create: `tests/unit/test_decisions.py`
- Create: `tests/scenarios/test_d03_credential_dates.py`
- Create: `tests/scenarios/test_d07_issued_history.py`
- Create: `tests/acceptance/test_at10.py`
- Create: `tests/acceptance/test_at11.py`

**Interfaces:**
- Produces `PermitDecisionCommand(application_id, outcome, reason, expected_application_version, expected_evaluation_version)`, `DecisionView`, `PermitService.decide`, `reconfirm`, and `ImpactService.apply_change`.

**Acceptance checks:**
- `uv run pytest tests/unit/test_decisions.py tests/scenarios/test_d03_credential_dates.py tests/scenarios/test_d07_issued_history.py tests/acceptance/test_at10.py tests/acceptance/test_at11.py -q` → pass.
- Client-supplied `final_ruling` without permitted transition → rejected with zero decisions.
- Current credential/rule/master change affects pending/approved-unissued/issued cases through revalidation, reconfirmation or impact review respectively.

- [ ] Implement reviewer confirm, modify, deny and request-information transitions with actual actor/time/reason/version references.
- [ ] Reject decisions with unresolved required identity/site/credential/rule blockers or stale expected versions.
- [ ] Implement reviewer reconfirmation as a new decision version referencing current evaluation rather than mutating the old decision.
- [ ] Preserve issued snapshots and create assigned impact-review records without silent amendment/revocation/reissue.

### Task P4: Exact finance, payment events and reconciliation

**Requirement:** Implement FIN-01–FIN-05, D01/D08/D11 and AT17/AT18.

**Files:**
- Create: `src/acme_city/finance/schemas.py`
- Create: `src/acme_city/finance/calculator.py`
- Create: `src/acme_city/finance/service.py`
- Create: `src/acme_city/finance/router.py`
- Create: `tests/unit/test_fee_calculator.py`
- Create: `tests/unit/test_payment_events.py`
- Create: `tests/unit/test_allocations.py`
- Create: `tests/api/test_finance_api.py`
- Create: `tests/scenarios/test_d11_financial_exceptions.py`
- Create: `tests/acceptance/test_at17.py`
- Create: `tests/acceptance/test_at18.py`

**Interfaces:**
- Produces `AssessmentCommand`, `AssessmentView`, `PaymentEventCommand`, `PaymentView`, `AllocationCommand`, `ReconciliationView`, and `FinanceService.assess`, `reassess`, `import_payment`, `allocate`, `reconcile`.
- Amount API fields are decimal strings; service converts to `Decimal`, validates currency and stores cents.

**Acceptance checks:**
- `uv run pytest tests/unit/test_fee_calculator.py tests/unit/test_payment_events.py tests/unit/test_allocations.py tests/api/test_finance_api.py tests/scenarios/test_d11_financial_exceptions.py tests/acceptance/test_at17.py tests/acceptance/test_at18.py -q` → pass.
- 50,000.00 → 150.00; 70,000.00 → 170.00; atomic carry-forward of 150.00 once → 20.00 due with v1 history preserved.
- Duplicate, over-allocation, unsettled, reversed, unmatched and incompatible currency paths remain explicit exceptions and never satisfy issuance.

- [ ] Implement exact fictional fee schedule selection from initial submission date and itemized immutable assessment lines.
- [ ] Implement reassessment as a transaction that creates v2, supersedes v1 as payable, releases/reallocates active funds exactly once and preserves v1 history.
- [ ] Implement stable receipt plus append-only source payment events with idempotent event keys and conflict on changed facts under the same key.
- [ ] Implement Finance-authorized version-scoped allocations across all active allocations and approved payer/account links.
- [ ] Implement reconciliation statuses for unpaid, partial, exact, overpaid, unmatched, unsettled, reversed, currency conflict and allocation conflict.

### Task P5: Separate idempotent issuance and artifact

**Requirement:** Implement PER-05, CHG-05 issuance behavior and deterministic portion of AT19.

**Files:**
- Create: `src/acme_city/permits/issuance.py`
- Create: `src/acme_city/templates/permit_artifact.html`
- Create: `src/acme_city/static/permit-print.css`
- Create: `tests/unit/test_issuance.py`
- Create: `tests/api/test_issuance_api.py`
- Create: `tests/acceptance/test_at19_deterministic.py`

**Interfaces:**
- Produces `IssuePermitCommand(application_id, decision_id, expected_application_version, expected_decision_version, command_key)`, `PermitView`, `PermitService.issue`, and `render_permit_artifact(permit_id) -> bytes`.
- Artifact hash is stored in immutable permit snapshot; identical retry returns same permit/artifact.

**Acceptance checks:**
- `uv run pytest tests/unit/test_issuance.py tests/api/test_issuance_api.py tests/acceptance/test_at19_deterministic.py -q` → pass.
- Any unresolved required link, invalid credential, stale decision/evaluation, nonexact reconciliation or pending decision-relevant correction blocks issuance.
- Simulated timeout after transaction commit followed by identical retry → same permit ID, number and artifact hash.

- [ ] Implement a separate issuance permission and endpoint; reviewer approval never issues automatically.
- [ ] Check current application/evaluation/decision/link/credential/assessment/reconciliation versions inside one transaction.
- [ ] Generate one clearly fictional permit number and immutable snapshot of facts, rules, decision, assessment and active allocations.
- [ ] Render a printable fictional artifact with no City of Westerville branding or official-system claim.
- [ ] Store idempotency fingerprint from operation, expected versions and payload; reject changed payload under reused key.
