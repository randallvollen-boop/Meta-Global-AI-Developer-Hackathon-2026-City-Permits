# Governed Foundation Implementation Plan

> **For agentic workers:** Execute F1–F4 in order. Do not modify intake files.

**Goal:** Establish the reproducible Python project, complete SQLite schema, deterministic fictional configuration, server-held actor sessions, authorization, governance and audit foundation used by every later subsystem.

**Architecture:** SQLAlchemy declarative models and Alembic migrations own persistence. Pydantic command/view models cross service boundaries. Seed configuration is committed JSON validated before insertion; mutable demo state lives only in the ignored SQLite database.

**Tech Stack:** Python 3.12, uv, FastAPI, SQLAlchemy 2, Alembic, Pydantic 2, Jinja2, pytest, HTTPX, SQLite.

**Spec:** `../REQUIREMENTS_OUTLINE.md`

**Parent plan:** `2026-10-26-acme-city-end-to-end.md`

## Global Constraints

- Preserve ignored intake unchanged.
- All seeded records are fictional and deterministic.
- Database timestamps are timezone-aware UTC; unknown source/effective times remain null.
- IDs are stable prefixed UUID-compatible strings; display numbers never serve as primary keys.
- Server permissions derive from persisted grants and session cookies, never client-supplied role fields.
- Administrator configuration access grants no business approval action.

### Task F1: Project, configuration and requirement contract

**Requirement:** Freeze the executable project shape and prove all 57 requirements and 28 AT/VC checks are represented before feature coding.

**Files:**
- Create: `pyproject.toml`
- Create: `uv.lock`
- Create: `.gitignore`
- Create: `src/acme_city/__init__.py`
- Create: `src/acme_city/app.py`
- Create: `src/acme_city/core/config.py`
- Create: `src/acme_city/core/ids.py`
- Create: `src/acme_city/core/clock.py`
- Create: `src/acme_city/core/errors.py`
- Create: `src/acme_city/core/results.py`
- Create: `config/requirements.json`
- Create: `scripts/check_requirement_coverage.py`
- Create: `tests/unit/test_requirement_contract.py`
- Create: `tests/unit/test_config.py`

**Interfaces:**
- Produces `Settings.load() -> Settings`, `new_id(prefix: str) -> str`, `utc_now() -> datetime`, `VersionedResult[T]`, `ConflictResult` and `create_app(settings: Settings | None = None) -> FastAPI`.
- `Settings` exposes `database_url`, `secret_key`, `demo_timezone`, `muse_model_allowlist`, `muse_live_call_cap`, `evidence_root`, and safe local-key-file loading without logging values.

**Acceptance checks:**
- `uv sync --all-groups` → dependencies resolve and lockfile exists.
- `uv run pytest tests/unit/test_requirement_contract.py tests/unit/test_config.py -q` → 57 distinct requirement IDs, 20 AT IDs, 8 VC IDs, and no secret value in settings representations.
- `uv run python scripts/check_requirement_coverage.py --planning-only` → zero duplicate or missing IDs.

- [ ] Create `pyproject.toml` with runtime and test dependency groups, Python `>=3.12,<3.13`, package discovery under `src`, and pytest configuration that treats warnings as errors except explicitly documented third-party deprecations.
- [ ] Copy only requirement identifiers, titles and planned check IDs into committed `config/requirements.json`; do not copy ignored source paths or executable claims.
- [ ] Implement settings loading from environment plus safely parsed `~/.config/ai-keys.env`, with environment taking precedence and `META_API_KEY` excluded from `repr`/serialization.
- [ ] Implement ID, clock, error and result primitives with unit tests for stable prefixes, UTC awareness and conflict serialization.
- [ ] Create the FastAPI factory with health endpoint `GET /healthz` returning `{"status":"ok","database":"uninitialized"}` until F2 initializes persistence.
- [ ] Run F1 checks and record command/count/result in `../../EVIDENCE_LOG.md` without copying secrets.

### Task F2: Complete persistence model and migration

**Requirement:** Provide executable schemas and relationships for all P0 logical objects, immutable/versioned history, idempotency, dependency records, outbox, audit and model traces.

**Files:**
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/script.py.mako`
- Create: `migrations/versions/0001_initial.py`
- Create: `src/acme_city/persistence/base.py`
- Create: `src/acme_city/persistence/session.py`
- Create: `src/acme_city/persistence/types.py`
- Create: `src/acme_city/persistence/models/governance.py`
- Create: `src/acme_city/persistence/models/source.py`
- Create: `src/acme_city/persistence/models/registry.py`
- Create: `src/acme_city/persistence/models/change.py`
- Create: `src/acme_city/persistence/models/permit.py`
- Create: `src/acme_city/persistence/models/finance.py`
- Create: `src/acme_city/persistence/models/model_run.py`
- Create: `src/acme_city/persistence/models/audit.py`
- Create: `src/acme_city/persistence/models/__init__.py`
- Create: `tests/unit/test_schema.py`
- Create: `tests/unit/test_migrations.py`

**Interfaces:**
- Produces `SessionFactory`, `transaction() -> Iterator[Session]`, `Base.metadata`, `initialize_database(settings)`, and `database_health(settings) -> DatabaseHealth`.
- Every mutable aggregate has integer `version >= 1`; immutable events/snapshots have stable IDs, correlation IDs and creation timestamps.
- Money columns store integer cents and ISO currency; source/effective/receipt timestamps are separate nullable columns.

**Acceptance checks:**
- `rm -f var/schema-test.db && ACME_DATABASE_URL=sqlite:///var/schema-test.db uv run alembic upgrade head` → exit 0.
- `uv run pytest tests/unit/test_schema.py tests/unit/test_migrations.py -q` → foreign keys on, invalid references rejected, migration upgrade works from empty database, and model metadata covers all required object groups.
- `uv run alembic check` → no ungenerated model changes.

- [ ] Define governance, actor, role, permission, assignment, queue, source-contract and authority-policy tables with effective dates and historical attribution.
- [ ] Define raw snapshots, quarantine errors, ingestion runs and source observations with payload hashes and separate source/effective/ingested times.
- [ ] Define Party, contact/alias, parcel/address/unit, credentials, application-party/site and versioned crosswalk/proposal/provenance tables.
- [ ] Define change cases, source commands/acknowledgements, dependencies, outbox deliveries and consumer acknowledgements with unique idempotency constraints.
- [ ] Define applications/revisions, documents/versions, extraction observations, evaluations/results, recommendations, decisions, permits, permit snapshots and impact reviews.
- [ ] Define rule/fee versions, assessments/lines, finance accounts/links, payments/events, allocations and reconciliation results using integer cents.
- [ ] Define model runs, model inputs/outputs/validation errors, audit events and evidence references; store no credentials.
- [ ] Write the initial Alembic migration by inspection, not autogeneration alone, and test downgrade/upgrade on a disposable database.

### Task F3: Validated configuration and deterministic fixtures

**Requirement:** Seed coherent fictional relationships, source variations, actual actors/queues, source contracts, authority, rules and D01–D11 starting conditions without exposing evaluator truth to runtime services.

**Files:**
- Create: `config/actors.json`
- Create: `config/permissions.json`
- Create: `config/domains.json`
- Create: `config/source_contracts.json`
- Create: `config/authority_policies.json`
- Create: `config/rules_and_fees.json`
- Create: `config/demo.json`
- Create: `fixtures/base_population.json`
- Create: `fixtures/source_variations.json`
- Create: `fixtures/evaluator_truth.json`
- Create: `src/acme_city/fixtures/schemas.py`
- Create: `src/acme_city/fixtures/loader.py`
- Create: `src/acme_city/fixtures/reset.py`
- Create: `scripts/reset_demo.py`
- Create: `tests/unit/test_fixture_validation.py`
- Create: `tests/unit/test_reset.py`

**Interfaces:**
- Produces `FixtureBundle.load(path) -> FixtureBundle`, `reset_demo(session, bundle, *, confirmation: str) -> ResetResult`, and `fixture_version` persisted with every run.
- Runtime package code cannot import `fixtures/evaluator_truth.json`; only `tests/evaluator/` receives its path explicitly.

**Acceptance checks:**
- `uv run python scripts/reset_demo.py --database sqlite:///var/reset-test.db --confirm-fictional-demo` → deterministic counts and fixture version printed, no secrets.
- Run reset twice → byte-equivalent canonical starting state after excluding action timestamps generated by reset; no duplicate IDs.
- `uv run pytest tests/unit/test_fixture_validation.py tests/unit/test_reset.py -q` → D01–D11 preconditions exist, D01 links/payment start unresolved/unallocated, and evaluator truth is absent from runtime fixture objects.

- [ ] Translate the 12 source role definitions into explicit action grants, but seed exactly four selectable human personas—Applicant, Data Steward, Permit Reviewer and City Administrator—plus nonselectable service identities. Map intake/steward/MDM grants to Data Steward, reviewer/issuing grants to Permit Reviewer, and separately declared administration/governance/owner/Finance/audit grants to City Administrator without making Administrator membership imply approval.
- [ ] Reconcile the preserved five permit configurations and 16 baseline rules into one fictional versioned catalog; choose one citation per executable rule and record source mappings.
- [ ] Seed coherent parties, parcels, units, credentials, finance accounts and role relationships before deriving Permitting, GIS and ERP/Finance variations.
- [ ] Seed D01 main case plus D02–D11 variants with real calendar dates, expected versions, source/effective/receipt times and stable source identifiers.
- [ ] Keep `evaluator_truth.json` out of runtime package data and add a static import scan asserting no `src/acme_city` module references it.
- [ ] Implement destructive reset only for a database explicitly marked `fictional_demo=true`; reject every other target.

### Task F4: Sessions, authorization, governance and audit services

**Requirement:** Implement GOV-01–GOV-07 and SEC-01–SEC-04 foundations, including server-held sessions, explicit grants, record scope, governance maintenance and append-only application audit.

**Files:**
- Create: `src/acme_city/auth/context.py`
- Create: `src/acme_city/auth/permissions.py`
- Create: `src/acme_city/auth/service.py`
- Create: `src/acme_city/auth/router.py`
- Create: `src/acme_city/governance/schemas.py`
- Create: `src/acme_city/governance/service.py`
- Create: `src/acme_city/governance/router.py`
- Create: `src/acme_city/audit/service.py`
- Create: `tests/unit/test_authorization.py`
- Create: `tests/unit/test_governance.py`
- Create: `tests/api/test_sessions.py`
- Create: `tests/api/test_governance_api.py`

**Interfaces:**
- Produces `SessionService.select_actor(actor_id) -> signed HTTP-only cookie`, `resolve_actor(request) -> ActorContext`, `authorize(actor, action, resource) -> None`, `GovernanceService.register_dataset`, `reassign_steward`, `preview_authority_change`, `publish_authority_change`, and `AuditService.append`.
- `AuditService.append` accepts immutable before/after version references and rejects update/delete through application APIs.

**Acceptance checks:**
- `uv run pytest tests/unit/test_authorization.py tests/unit/test_governance.py tests/api/test_sessions.py tests/api/test_governance_api.py -q` → pass.
- Persona selector API returns exactly Applicant, Data Steward, Permit Reviewer and City Administrator; service identities and source role templates are absent.
- Client-supplied role fields, unsigned cookies and out-of-scope direct URLs → 401/403 with zero business-row mutations.
- Deactivating a steward with active work and no reassignment → conflict; reassignment updates current responsibility and preserves prior attribution.

- [ ] Implement signed random session IDs stored server-side with actor ID and expiry; use `HttpOnly`, `SameSite=Lax`, and configurable `Secure` behavior.
- [ ] Implement permission resolution from persisted grants plus domain/action/record scope; do not infer permissions from labels.
- [ ] Implement governance registration and publication gate: incomplete datasets may stage raw snapshots but cannot publish trusted facts.
- [ ] Implement effective assignment resolution, steward deactivation/reassignment, owner escalation and authority impact preview.
- [ ] Implement append-only audit writes inside the same transaction as each accepted business mutation and denied-sensitive-write metadata without private values.
- [ ] Mount auth/governance routers in `create_app`; update `/healthz` to report migration status without database paths or secrets.
