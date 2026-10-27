# Muse Integration and User Interface Implementation Plan

> **For agentic workers:** M1 can begin after foundation fixtures. M2 consumes source/registry services. M3 consumes all domain APIs. M4 gates the browser experience.

**Goal:** Add bounded live/replay Muse proposals, traceable model runs, actual synthetic documents and the complete eight-screen user experience with responsibility, evidence, history and scoped actions.

**Architecture:** Meta Responses API is isolated behind `MuseClient`. `MuseService` records a run before network dispatch, validates strict JSON-schema output against visible records/documents, and writes proposals only after validation. Server-rendered pages consume domain view services; vanilla JavaScript submits explicit actions and renders typed operational feedback.

**Tech Stack:** HTTPX, Pydantic JSON Schema, Meta Responses API, FastAPI/Jinja2, vanilla JavaScript, Playwright.

**Spec:** `../REQUIREMENTS_OUTLINE.md`

**Parent plan:** `2026-10-26-acme-city-end-to-end.md`

## Global Constraints

- Model allowlist contains only `muse-spark-1.3` Standard.
- Live-call cap for the build run is two successful requests, no web search/tool calls, concurrency one and no automatic retry.
- Each call reserves at most 4,000 input and 1,200 output tokens; provider errors stop further live calls.
- Runtime payloads contain only actor-authorized records and document versions; evaluator truth is excluded by construction and payload inspection.
- `text.format.type` is `json_schema` with `strict: true`; `response_format` is never sent.
- Live, replay, cached and failed runs remain separate immutable records.
- UI uses fictional ACME branding and does not clone or impersonate the Westerville portal.

### Task M1: Synthetic documents, replay records and truth isolation

**Requirement:** Implement AI-05 and the document/replay preconditions for D01/D09/AT14/AT15.

**Files:**
- Create: `fixtures/documents/SYN-APP-001-application-v1.txt`
- Create: `fixtures/documents/SYN-APP-001-application-v2.txt`
- Create: `fixtures/documents/SYN-APP-001-adversarial.txt`
- Create: `fixtures/replay/extraction-success.json`
- Create: `fixtures/replay/match-proposal-success.json`
- Create: `fixtures/replay/malformed-output.json`
- Create: `src/acme_city/muse/payloads.py`
- Create: `tests/unit/test_document_fixtures.py`
- Create: `tests/security/test_truth_isolation.py`
- Create: `tests/security/test_prompt_injection_boundary.py`

**Interfaces:**
- Produces `VisibleEvidenceBundle.for_actor(application_id, actor)`, immutable `DocumentRef(document_id, version, content_hash, line_count)`, and replay records tied to source model-run/fixture/prompt/schema versions.

**Acceptance checks:**
- `uv run pytest tests/unit/test_document_fixtures.py tests/security/test_truth_isolation.py tests/security/test_prompt_injection_boundary.py -q` → pass.
- Actual outbound payload capture contains no `truth_`, intended-link or expected-decision values and no out-of-scope records.
- Adversarial document instruction appears only as evidence text and cannot alter requested schema, tools, permissions or workflow state.

- [ ] Create coherent fictional application documents with line-stable evidence for alias, unit address, contractor reference, valuation, occupancy and project description; label every file fictional.
- [ ] Store document v1/v2 hashes and application-revision relationships; v2 never overwrites v1.
- [ ] Create an adversarial evidence variant requesting unauthorized approval and fixtures for unknown IDs, invented locations/citations and malformed numeric output.
- [ ] Implement actor-scoped payload assembly from application/document/source services and a static plus runtime assertion excluding evaluator truth.
- [ ] Create replay fixtures from the same strict output schemas and require explicit replay selection plus source-run linkage.

### Task M2: Meta client, strict schemas and traceable model runs

**Requirement:** Implement AI-01–AI-04, live/replay/cached operation and model-boundary validation.

**Files:**
- Create: `src/acme_city/muse/schemas.py`
- Create: `src/acme_city/muse/client.py`
- Create: `src/acme_city/muse/validation.py`
- Create: `src/acme_city/muse/service.py`
- Create: `src/acme_city/muse/router.py`
- Create: `tests/unit/test_muse_schemas.py`
- Create: `tests/unit/test_muse_validation.py`
- Create: `tests/integration/test_muse_replay.py`
- Create: `tests/integration/test_muse_http_contract.py`
- Create: `tests/acceptance/test_at14.py`
- Create: `tests/acceptance/test_at15.py`

**Interfaces:**
- Produces `MuseRunCommand(task, mode, application_id, document_ids, candidate_ids, prompt_version, schema_version)`, `ModelRunView`, `MuseClient.create_response(payload)`, and `MuseService.run`.
- Extraction schema returns `application_id`, `document_id`, `document_version`, and `observations[{field, proposed_value, evidence{line_start,line_end,excerpt}}]`.
- Matching schema returns `source_snapshot_id`, `candidates[{entity_id,supporting[],conflicting[],proposal_score?}]`, `recommended_disposition` and `explanation`; disposition is a proposal only.

**Acceptance checks:**
- `uv run pytest tests/unit/test_muse_schemas.py tests/unit/test_muse_validation.py tests/integration/test_muse_replay.py tests/integration/test_muse_http_contract.py tests/acceptance/test_at14.py tests/acceptance/test_at15.py -q` → pass without live spend.
- HTTP contract test asserts `POST https://api.meta.ai/v1/responses`, bearer auth redacted from logs, model allowlist, `text.format.json_schema`, `max_output_tokens`, no tools and no retry.
- Unknown IDs, excerpt mismatch, out-of-range line evidence, unsupported citations and malformed JSON yield failed validation with no proposal/business write.

- [ ] Implement strict Pydantic schemas and generated JSON Schema with `additionalProperties: false` and explicit required fields.
- [ ] Implement safe Meta key loading and HTTPX request/timeout handling; record response ID, model, status, output, usage, cached/reasoning tokens, latency, refusal/error and validation state without headers.
- [ ] Implement live mode with call-budget reservation and stop-on-provider-error behavior.
- [ ] Implement replay mode from versioned fixtures and cached mode from an exact input/prompt/schema/model hash; never rewrite a failed live run.
- [ ] Validate document evidence against exact stored document version and candidate IDs against actor-visible records before creating extraction observations or match proposals.
- [ ] Mount `/api/muse/runs` and `/api/muse/run`; only permitted staff actors can request bounded model work.

### Task M3: Complete eight-screen application UI

**Requirement:** Implement UX-01–UX-04, EDIT-01–EDIT-03 visible behavior and the required Westerville-inspired fictional process.

**Files:**
- Create: `src/acme_city/ui/router.py`
- Create: `src/acme_city/ui/view_models.py`
- Create: `src/acme_city/templates/base.html`
- Create: `src/acme_city/templates/components/responsibility_panel.html`
- Create: `src/acme_city/templates/components/evidence_panel.html`
- Create: `src/acme_city/templates/components/history_panel.html`
- Create: `src/acme_city/templates/work_queue.html`
- Create: `src/acme_city/templates/applicants.html`
- Create: `src/acme_city/templates/masters.html`
- Create: `src/acme_city/templates/permit_workspace.html`
- Create: `src/acme_city/templates/steward_review.html`
- Create: `src/acme_city/templates/rules_fees.html`
- Create: `src/acme_city/templates/reconciliation.html`
- Create: `src/acme_city/templates/governance_sources.html`
- Create: `src/acme_city/static/app.css`
- Create: `src/acme_city/static/app.js`
- Create: `tests/ui/test_view_models.py`
- Create: `tests/api/test_pages.py`
- Create: `tests/supplementary/test_vc03.py`
- Create: `tests/supplementary/test_vc04.py`
- Create: `tests/supplementary/test_vc05.py`

**Interfaces:**
- Produces page view models with `responsibility`, `current`, `submitted`, `proposed`, `issued`, `open_issues`, `allowed_actions`, `denied_action_explanations`, `evidence`, and `history` sections.
- Every action form posts stable IDs, expected version and CSRF token; role strings are absent.

**Acceptance checks:**
- `uv run pytest tests/ui/test_view_models.py tests/api/test_pages.py tests/supplementary/test_vc0{3,4,5}.py -q` → pass.
- All eight screen routes return 200 for permitted actors and scoped 403/404 for forbidden records.
- Every governed detail view includes Owner, Steward, Source, Change this in, Last source update, Last received, Version and Open issues.

- [ ] Implement stable navigation and a server-held actor selector with exactly Applicant, Data Steward, Permit Reviewer and City Administrator; keep service identities and underlying role templates out of the dropdown. Add the fictional-demo banner and explicit Live/Replay/Cached badges.
- [ ] Implement Work queue filters by My work, department, object and state with blocker, age, target and next action.
- [ ] Implement shared Party views for Applicants, Businesses and Contractors without duplicating canonical identities or permissions.
- [ ] Implement Permit workspace sections for submission/documents, identity, validation/rules, recommendation/decision, finance and history.
- [ ] Implement Steward review comparison, supporting/conflicting evidence, impact preview, explicit link/source actions and acknowledgement status.
- [ ] Implement Rules/fees, Reconciliation and Governance/sources actions with author/approver and domain permissions.
- [ ] Implement compact responsive CSS at 390px, keyboard focus, accessible labels/status, and no dependency on external scripts/fonts.
- [ ] Implement operational feedback from actual response destination/version/pending state; never render success for unacknowledged source/consumer work.

### Task M4: Browser behavior and user-path gate

**Requirement:** Verify the UI performs actual persisted transitions rather than displaying predetermined final states.

**Files:**
- Create: `tests/browser/conftest.py`
- Create: `tests/browser/test_navigation.py`
- Create: `tests/browser/test_actor_scope.py`
- Create: `tests/browser/test_primary_chain.py`
- Create: `tests/browser/test_failure_states.py`
- Create: `scripts/browser_acceptance.py`

**Interfaces:**
- `browser_acceptance.py --base-url URL --output PATH` produces JSON with route checks, viewport checks, page errors, action outcomes and screenshot hashes.

**Acceptance checks:**
- `uv run playwright install chromium` → browser available.
- `uv run pytest tests/browser -q` → pass against isolated seeded server.
- `uv run python scripts/browser_acceptance.py --base-url http://127.0.0.1:8266 --output evidence/runs/browser.json` → eight screens visited, no page errors, no 390px horizontal overflow, scoped denial verified and all exercised actions survive reload.

- [ ] Build a fixture that launches an isolated server/database and records its PID without touching another running service.
- [ ] Verify keyboard navigation, labels, focus states, status announcements and mobile/desktop layouts.
- [ ] Verify Applicant cannot open another applicant, Data Steward cannot decide or issue a permit, City Administrator's configuration grant alone cannot approve business actions, Permit Reviewer cannot edit receipts, and Applicant cannot inspect steward candidates.
- [ ] Execute steward approval/rejection, source timeout, reviewer decision, Finance allocation and issuance through real forms/API, reloading after each action.
- [ ] Capture only newly rendered fictional pages and redact session cookies/authorization headers from traces.
