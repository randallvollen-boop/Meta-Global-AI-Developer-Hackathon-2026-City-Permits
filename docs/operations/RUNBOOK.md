# Runbook: outside intake, agent triage, and human decisions

ACME City Permits is a fictional demonstration. Every person, address, rule,
fee and permit is synthetic, the server binds to loopback only
(`127.0.0.1:8266`), and no agent or model approves, prices or issues a permit.

## Start, reset and simulate

From `repo/`:

```bash
uv run python scripts/prepare_user_test.py --mode fresh
uv run python scripts/start_demo.py --host 127.0.0.1 --port 8266
# open http://127.0.0.1:8266 and choose a persona
uv run python scripts/stop_demo.py
```

Simulate incoming permits (server running; signs in as Data Steward, which
holds the staging grant; override with `--actor`):

```bash
uv run python scripts/simulate_intake.py --scenario fence-conforming-rear
uv run python scripts/simulate_intake.py --scenario mixed --count 6 --base-url http://127.0.0.1:8266
```

Or, in the browser, sign in as **City Administrator**, open **Governance and
sources**, and use **Simulate incoming permits**. Scenarios:
`fence-conforming-rear`, `fence-front-too-tall`, `fence-missing-site-plan`,
`deck-high`, `mixed` (about six records).

## How data comes in

The city gathers permits outside this system through the fictional **ACME
ePermit Portal (simulated)**, with three channels: `portal` (web form),
`counter_scan` (paper handed in at the counter and scanned/transcribed) and
`email`. The portal is registered as the source system `intake_portal` with
the dataset `submitted_applications` (contract
`contract_intake_portal_submitted_applications`, domain `permits`, owner
Building Safety director, queue `queue_permits`, custodian Permitting) — see
it on **Governance and sources**.

Each intake record carries: channel, received_at, portal reference, applicant
(name, email, phone), site address and parcel text, permit type key,
submitted facts, and document text (typed documents such as `site_plan` and
`material_spec`).

Ingestion (`src/acme_city/intake/service.py`) never writes tables directly:

1. **Stage raw** — `IngestionService.ingest` validates the record against its
   registered contract and preserves the raw snapshot (idempotent on the
   portal reference: a repeat returns `duplicate` and creates nothing).
2. **Create the case** — `PermitService.submit`, as the seeded intake service
   identity, creates the Permitting application, its first immutable revision
   and its site (parcel/address resolved from the submitted text).
3. **Store documents** — `DocumentService.store_version` stores each
   document's bytes and records its hash.
4. **Triage** — the five agent steps below run synchronously.

APIs: `POST /api/intake/records`, `POST /api/intake/simulate`,
`GET /api/intake/scenarios`, plus the source endpoints
`GET /api/sources/systems`, `POST /api/sources/{system}/{dataset}/intake`.

## The triage pipeline (agents propose; people decide)

On intake, on an application revision and on **Re-run triage** (Permit
workspace action), these steps run server-side in order. Each runs as a named
**service identity** (never a selectable persona) and is recorded as an
auditable agent step (`agent_steps`: start, end, inputs, outcome, identity),
audited as `agent.<step>`, and shown in the workspace timeline and, where Muse
is involved, in the Muse run tab. Current seeded identities:
`service_delegate_steward` (intake/identity/extraction/rules/recommendation
steps; explicit grants in `config/actors.json`, including the `application.submit`
and `application.evaluate` grants the delegate needed to create and evaluate
cases — it has **no** `permit.decide`, `permit.issue` or finance grant).

| # | Step | What it does |
|---|------|--------------|
| 1 | Intake agent | Checks completeness against the permit type's `required_fields`/`required_documents` (`config/rules_and_fees.json`). Missing → application `needs_information` and the missing items are recorded for the applicant. Complete → routed to the type's `review_route` queue (e.g. "Building Safety counter review"). |
| 2 | Identity agent | Runs the deterministic matcher to **propose** links for applicant, parcel and contractor. The Data Steward approves them in **Steward review**; no agent approves a link. |
| 3 | Extraction agent (Muse Spark) | Runs the existing Muse extraction on the document text — **replay by default** (recorded, labelled, deterministic from the received text, no provider call); live only with `--live-muse`/the simulate flag, within `ACME_MUSE_LIVE_CALL_CAP`, Meta Standard `muse-spark-1.3` only. It proposes values; the steward accepts or corrects them ("Accept or correct extracted …" actions). |
| 4 | Rules agent | Runs the deterministic evaluator (`rules/evaluator.py`) via `PermitService.evaluate` and records the evaluation (rule versions, inputs, citations). |
| 5 | Recommendation agent | Creates an advisory `Recommendation`: outcome deterministically from the rule results (any `fail` → `deny`, or `request_information` when the failure is missing/blank input; any `condition` → `approve_with_conditions`; any judgment/`review` → `needs_reviewer_judgment`; else `approve`); rationale citing each rule id, observed value, limit and citation; optional Muse summary (strict JSON, replay by default) that may only explain — a summary naming a different outcome is rejected and the deterministic text is shown. |

The workspace shows an **Agent recommendation** card at the Decision step:
outcome pill, rationale, rule citations and "Advisory. The Permit Reviewer
decides." The reviewer's decision form sits beside it; the reviewer can agree
or disagree, and disagreeing requires a reason (`recommendation.stance`).

## Where humans act

| Persona | Screen | Action | What happens next |
|---|---|---|---|
| City Administrator | Governance and sources | Simulate incoming permits | Records arrive via `intake_portal`, applications are created and triaged; watch the workspace timeline |
| Data Steward | Steward review | Confirm/Reject link, Record no match | Identity links the reviewer will rely on become approved (or not); proposals stay evidence |
| Data Steward | Permit workspace | Accept or correct extracted … | Proposed Muse values become accepted/corrected; submitted revisions are never rewritten |
| Permit Reviewer | Permit workspace | Record stance on the agent recommendation | Agreement/disagreement (reason required to disagree) is recorded beside the decision |
| Permit Reviewer | Permit workspace | Record reviewer decision | The actual decision (`approved`/`denied`/`modified`/`information_requested`) with reason and versions; approval is refused while blockers (identity links, site, credentials, rule fails) stand |
| Permit Reviewer | Permit workspace | Re-run triage / Run validation | Agent steps or the deterministic evaluation run again for the current revision |
| City Administrator | Reconciliation | Assess application, Import ERP payment, Confirm allocation, Reconcile assessment | Fee assessed from the published schedule; reconciliation must be exact (balance 0.00) before issuance |
| Permit Reviewer | Permit workspace | Issue permit | Separate human action; idempotent on the command key; blocked until decision, links, assessment and exact reconciliation all hold |
| Applicant | Permit workspace / Work queue | Submit application correction | Creates a new immutable revision; the case returns for re-triage/re-evaluation |

Navigation is persona-scoped: the left bar and the bottom tab bar list only
the screens the persona holds a grant for (`navigation()` uses the same
`SCREEN_PERMISSIONS`/`holds_grant` logic as the screen guard, so a hidden
screen is also a 403). Order and labels are canonical for everyone.

## Failure handling

- **Missing documents/fields** — the intake step sets `needs_information` and
  the recommendation is `request_information`, naming exactly what is missing.
  The applicant supplies it (a new revision), then Re-run triage.
- **Rule failures** — e.g. DF-1 (front fence 6 ft > 4 ft maximum) produces a
  `deny` recommendation. The reviewer may still decide (denials are not
  blocked); approvals are blocked by unresolved fail/review blockers.
- **Muse failure** — a live error, refusal, incomplete response or a summary
  that names another outcome is recorded on the run and the deterministic
  rationale is shown. Replay is labelled `replay` and never substitutes for
  live evidence. Fallback is manual: the steward types the value (correction)
  or the reviewer proceeds from the submitted facts.
- **Duplicate delivery** — the same portal reference returns `duplicate`; no
  second application, revision or document is created.
- **Permission failures** — every write goes through a governed action/API
  with permission checks, CSRF, expected version and an audit record; denials
  are audited and shown as "The action was refused".

## Fence flow

```mermaid
sequenceDiagram
    participant P as ACME ePermit Portal (simulated)
    participant I as Intake + triage (service identities)
    participant S as Data Steward
    participant R as Permit Reviewer
    participant A as City Administrator
    P->>I: submit fence record (portal/counter_scan/email)
    I->>I: stage raw, create application + revision + documents
    I->>I: 1 intake completeness, 2 identity proposals
    I->>I: 3 Muse extraction (replay), 4 deterministic rules
    I->>I: 5 recommendation (e.g. deny, DF-1) — advisory
    S->>I: approve identity links; accept/correct extracted values
    R->>I: read recommendation, record stance, record decision
    A->>I: assess fee, import payment, allocate, reconcile (exact)
    R->>I: issue permit (separate human action)
```
