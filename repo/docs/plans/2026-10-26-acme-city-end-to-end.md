# ACME City End-to-End Application Implementation Plan

> **For agentic workers:** Implement this plan task-by-task. One task per fresh
> delegate or inline with a review checkpoint between tasks. Steps use checkbox
> (`- [ ]`) syntax for tracking. Child plans are authoritative for their subsystem.

**Goal:** Deliver a locally runnable, persisted, fictional ACME City permit application that satisfies all 57 P0 requirements, exposes the eight required screens, integrates Muse Standard for bounded proposals, and produces AT01–AT20, VC01–VC08 and D01–D11 evidence for a user walkthrough.

**Architecture:** One FastAPI service, one SQLite database, server-rendered Jinja pages with small vanilla-JavaScript enhancements, three persisted simulated source adapters, a registry-MDM domain, a database outbox and append-only application audit trail. Domain services own business transitions; HTTP handlers only validate requests, resolve server-held actor context and render results. Muse is an adapter that creates validated proposals and trace records without authoritative write permissions.

**Tech Stack:** Python 3.12, `uv`, FastAPI, SQLAlchemy 2, Alembic, Pydantic 2, Jinja2, python-multipart, HTTPX, pytest, pytest-asyncio, Playwright for Python, SQLite, HTML/CSS/vanilla JavaScript.

**Spec:** `../REQUIREMENTS_OUTLINE.md` and `../../../intake/extracted/ACME_MDM_Build_Package/requirements/ACME_MDM_Demo_Requirements.txt`

**Parent plan:** none

**Child plans:**

- `2026-10-26-governed-foundation.md`
- `2026-10-26-registry-stewardship.md`
- `2026-10-26-permit-finance.md`
- `2026-10-26-muse-and-ui.md`
- `2026-10-26-integrated-acceptance.md`

## Global Constraints

- Build only under `repo/`; preserve ignored `intake/` unchanged and never execute bundled code in place.
- Use fictional ACME City people, organizations, sources, rules, payments and permit artifacts only.
- Use Westerville public workflow concepts without logos, copied portal design, official-system claims, endorsement, real fees/codes/service levels or real data.
- Use Meta `muse-spark-1.3` Standard through server-side configuration; reject `-contributor` and every unallowlisted model.
- Keep `META_API_KEY` server-side, loaded from environment or the local ignored key file without printing or persisting it.
- Muse creates proposals only. Deterministic services and explicitly authorized seeded actors control publication, money, decisions and issuance.
- Keep intended links, expected outcomes and every `truth_*` field outside runtime payloads and retrieval.
- Use expected versions for corrections, crosswalks, rule publication, decisions, allocations and issuance.
- Expose exactly four selectable human personas: Applicant, Data Steward, Permit Reviewer and City Administrator. Keep granular grants explicit; service identities are not personas and Administrator membership alone grants no business approval.
- Use exact `Decimal` arithmetic serialized as integer cents in storage.
- Preserve current profile, submitted revision, recommendation, decision, assessment, allocation and issued snapshot as distinct records/versions.
- Treat JSON registers as planning inputs, never executable tests or proof.
- Do not commit, push, create a GitHub remote, deploy, publicly publish, accept event terms or submit to the hackathon during this implementation run. The sole authorized publication is the private checked architecture page in the local AVA Library under its stable article ID.
- Keep raw run evidence local under ignored `evidence/runs/`; write a synthetic-only sanitized summary separately when publication is later authorized.

## What is missing before execution

No product requirement is missing for a local P0 build. The following are operational gaps with explicit handling:

1. The external `PROTO-PERMIT-01` source is absent. Build the new application independently from the authoritative specification and preserved deterministic reference definitions.
2. The concrete stack was unspecified. This plan selects FastAPI, SQLAlchemy, SQLite and server-rendered HTML to minimize moving parts and support the required API, sessions, transactions and browser experience.
3. The provider balance/expiry/no-cash controls were not independently inspected. Cap the overnight live Muse work to two successful Spark Standard calls, no web search, at most 4,000 input and 1,200 output tokens per call, one in-flight call and no automatic retry. Stop live calls on any authentication, credit, billing or coverage error.
4. GitHub CLI is not authenticated to `RandallVollen-boop`. This does not block a local build; no remote operation is part of this plan.
5. Final event rules and submission format remain separate gates. The plan produces a local testable application and evidence, not a competition submission.

## Dependency graph

```text
Foundation/schema/config/session/RBAC
        ├── Source intake and adapters ── Registry/stewardship/corrections
        ├── Permit/rules/decisions ────── Finance/reconciliation/issuance
        └── Shared audit/outbox ───────── Muse adapter and trace
                                              │
All services ─────────────────────────────── UI screens
                                              │
All services + UI + live/replay ───────────── Acceptance/evidence/restart/browser gate
```

## Execution order

### Phase 1 — Contract and governed foundation

Execute `2026-10-26-governed-foundation.md` Tasks F1–F4 in order.

Exit evidence:

- `uv sync --all-groups` succeeds.
- Alembic creates a fresh database.
- Deterministic reset seeds configured actors, sources, contracts, ownership, rules and coherent D01–D11 starting data.
- Unit tests for configuration, schema, sessions, RBAC, governance and audit pass.

### Phase 2 — Independent domain slices

After F4, execute these branches against separate worktrees or serialize inline:

- `2026-10-26-registry-stewardship.md` Tasks R1–R4.
- `2026-10-26-permit-finance.md` Tasks P1–P3 while registry R1–R2 proceeds.

Integrate registry before permit Task P4 because issuance depends on approved links and source authority. Integrate permit decisions before finance Tasks P4–P5 because assessments and issuance reference immutable decisions.

Exit evidence:

- AT01–AT13, AT16–AT18 and AT20 pass deterministically where their live-Muse clauses do not apply.
- D01 can reach deterministic issuance using recorded human actions and exact financial arithmetic, explicitly labeled as not yet full AT19.

### Phase 3 — Muse and complete user interface

Execute `2026-10-26-muse-and-ui.md` Tasks M1–M4.

Exit evidence:

- Strict Meta Responses API schema is implemented through `text.format.type=json_schema`.
- Live, replay, cached and failure traces are distinguishable.
- Every required screen renders with a responsibility panel and scoped actions.
- Browser checks cover actor switching, stewardship, reviewer, Finance and issuance paths.

### Phase 4 — Integrated acceptance and handoff

Execute `2026-10-26-integrated-acceptance.md` Tasks A1–A5.

Exit evidence:

- AT01–AT20 and VC01–VC08 have machine-readable results.
- D01–D11 have expected-versus-observed records.
- Full D01 includes a substantive live Muse task unless the provider returns a recorded blocking error.
- Restart preserves the chain; issuance retry returns the same permit and artifact.
- A fresh reset and one documented launch command produce the user-test environment.

## Stable application interfaces

Later tasks depend on these signatures; child plans define their implementations.

```python
# acme_city.auth.context
@dataclass(frozen=True)
class ActorContext:
    actor_id: str
    role_ids: frozenset[str]
    domain_scope: frozenset[str]
    record_scope: frozenset[str]

# acme_city.core.results
@dataclass(frozen=True)
class VersionedResult[T]:
    value: T
    version: int
    audit_event_id: str

@dataclass(frozen=True)
class ConflictResult:
    code: str
    expected_version: int
    current_version: int
    differences: tuple[dict[str, object], ...]

# acme_city.ingestion.service
class IngestionService:
    def ingest(self, command: IngestCommand, actor: ActorContext) -> IngestResult: ...

# acme_city.registry.service
class RegistryService:
    def propose(self, command: MatchProposalCommand, actor: ActorContext) -> MatchProposal: ...
    def decide(self, command: MatchDecisionCommand, actor: ActorContext) -> VersionedResult[CrosswalkView] | ConflictResult: ...

# acme_city.changes.service
class ChangeService:
    def request(self, command: ChangeRequestCommand, actor: ActorContext) -> ChangeCaseView: ...
    def transition(self, command: ChangeTransitionCommand, actor: ActorContext) -> VersionedResult[ChangeCaseView] | ConflictResult: ...
    def dispatch_pending(self, *, limit: int = 25) -> DispatchSummary: ...

# acme_city.permits.service
class PermitService:
    def submit(self, command: SubmitApplicationCommand, actor: ActorContext) -> ApplicationRevisionView: ...
    def evaluate(self, application_id: str, actor: ActorContext) -> EvaluationView: ...
    def decide(self, command: PermitDecisionCommand, actor: ActorContext) -> VersionedResult[DecisionView] | ConflictResult: ...
    def issue(self, command: IssuePermitCommand, actor: ActorContext) -> VersionedResult[PermitView] | ConflictResult: ...

# acme_city.finance.service
class FinanceService:
    def assess(self, command: AssessmentCommand, actor: ActorContext) -> AssessmentView: ...
    def import_payment(self, command: PaymentEventCommand, actor: ActorContext) -> PaymentView | ConflictResult: ...
    def allocate(self, command: AllocationCommand, actor: ActorContext) -> ReconciliationView | ConflictResult: ...

# acme_city.muse.service
class MuseService:
    def run(self, command: MuseRunCommand, actor: ActorContext) -> ModelRunView: ...

# acme_city.evidence.manifest
class EvidenceRecorder:
    def record_check(self, result: CheckResult) -> None: ...
    def finalize(self) -> pathlib.Path: ...
```

## Final local commands

```bash
cd repo
uv sync --all-groups
uv run alembic upgrade head
uv run python scripts/reset_demo.py --confirm-fictional-demo
uv run pytest -q
uv run python scripts/run_acceptance.py --all --evidence-dir evidence/runs/final
uv run python scripts/start_demo.py --host 127.0.0.1 --port 8266
```

Expected final state:

- Browser URL: `http://127.0.0.1:8266`
- Starting screen: Work queue with `SYN-APP-001` and D02–D11 variants.
- Actor selector establishes a server-held demo session.
- `scripts/demo_walkthrough.py --base-url http://127.0.0.1:8266` executes the primary chain through a separate issue action.
- `scripts/stop_demo.py` stops only the process recorded in `var/demo.pid`.
- `USER_TEST_GUIDE.md` gives the manual click path, known limitations and evidence location.

## Parent-plan acceptance

- `uv run python scripts/check_requirement_coverage.py` → exactly 57 requirement IDs, zero unmapped, and each ID linked to implementation symbols plus AT/VC checks.
- `uv run pytest -q` → zero failures, zero unexpected skips, nonzero test count reported.
- `uv run python scripts/run_acceptance.py --all --evidence-dir evidence/runs/final` → 20 AT results, 8 VC results and 11 D results; any blocked live provider gate is explicit rather than converted to a pass.
- `uv run python scripts/verify_evidence.py evidence/runs/final` → valid manifest, hashes and required identifiers/versions/actors/timestamps.
- `uv run python scripts/browser_acceptance.py --base-url http://127.0.0.1:8266` → eight screens, no page errors, no horizontal overflow at 390px, actor-scoped paths enforced and primary actions persistent.
- Architecture STATUS.json, checked STD-29 page and private AVA Library article use the same accepted counts/status under stable article ID `acme-city-permits-architecture`.
- Restart and rerun issuance command → same permit ID, number and artifact hash.
- Tracked-file scan → no API keys, private email, machine paths, network addresses, real applicant data or ignored intake files.
