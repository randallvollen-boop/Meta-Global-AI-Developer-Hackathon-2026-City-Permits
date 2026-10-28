# Runbook: outside intake, two people-driven agents, and human decisions

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
uv run python scripts/simulate_intake.py --scenario random --count 12
```

Or, in the browser, sign in as **City Administrator**, open **Governance and
sources**, and use **Simulate incoming permits**. Scenarios:
`fence-conforming-rear`, `fence-front-too-tall`, `fence-missing-site-plan`,
`deck-high`, `mixed` (about six records), `shed-large` (a 400 sq ft shed,
which carries a condition), `variance-request` (a discretionary type, which
is held), `hvac-no-contractor` (which fails), `fax-unreadable` (an unreadable
page, so the case goes to early resolution), `duplicate-fence` (the same
applicant, address and type as a fence already submitted) and `random`
(deterministic from a seed, across all seventeen permit types and all five
channels, with realistic omissions and quality problems).

## How data comes in

The city gathers permits outside this system through the fictional **ACME
ePermit Portal (simulated)**, with five channels: `portal` (web form),
`counter_scan` (paper handed in at the counter and scanned/transcribed),
`email`, `mail` (post) and `fax`. The portal is registered as the source
system `intake_portal` with the dataset `submitted_applications` (contract
`contract_intake_portal_submitted_applications`, domain `permits`, owner
Building Safety director, queue `queue_permits`, custodian Permitting) — see
it on **Governance and sources**.

Each intake record carries: channel, received_at, portal reference, applicant
(name, email, phone), site address and parcel text, permit type key,
submitted facts, and documents (typed documents such as `site_plan` and
`material_spec`), each with the scan-quality flags the record carried
(`rotated`, `low_res`, `handwritten`, `unreadable`, `duplicate_page`).

Ingestion (`src/acme_city/portal_intake/service.py`) never writes tables
directly:

1. **Stage raw** — `IngestionService.ingest` validates the record against its
   registered contract and preserves the raw snapshot (idempotent on the
   portal reference: a repeat returns `duplicate` and creates nothing).
2. **Create the case** — `PermitService.submit`, as the seeded intake service
   identity, creates the Permitting application, its first immutable revision
   and its site (parcel/address resolved from the submitted text). The
   permit-type requirements in force at that moment are recorded on the case,
   so a later configuration change never rewrites what this case was measured
   against.
3. **Store documents** — `DocumentService.store_version` stores each
   document's bytes, records its hash and records its scan-quality flags.
4. **Wait** — nothing else happens. The case sits in status `submitted` and
   is shown as **Awaiting intake agent**.

APIs: `POST /api/intake/records`, `POST /api/intake/simulate`,
`GET /api/intake/scenarios`, plus the source endpoints
`GET /api/sources/systems`, `POST /api/sources/{system}/{dataset}/intake`.

## The two agents (agents propose; people decide)

There are two agents and both are **service identities**, never selectable
personas:

| Agent | Identity | Who may run it | Who may wake it |
|---|---|---|---|
| Intake agent | `service_agent_intake` | Data Steward, City Administrator (`agent.run.intake`) | City Administrator only (`agent.toggle`) |
| Adjudication agent | `service_agent_adjudication` | Permit Reviewer, City Administrator (`agent.run.adjudication`) | City Administrator only (`agent.toggle`) |

**An agent is engaged only when it is awake, and only when a person runs
it.** After a reset both agents sleep. A City Administrator wakes one on its
screen (**Wake agent** / **Put agent to sleep**); until then every run is
refused. A person then runs it: **Process one** / **Process all waiting** on
the Intake agent screen, **Run** / **Run all** on the Adjudication agent
screen, or **Re-run intake agent** / **Re-run adjudication** on the permit
workspace. The same rules apply to a re-run.

Each run is recorded as an `agent_runs` row (agent, application, start and
finish, the acting service identity, the triggering person, the outcome) with
one `agent_run_nodes` row per node (node id, label, dependency level, status
`ok`/`warn`/`block` and a note).

### Intake agent — seven nodes

| Level | Node | What it does |
|---|---|---|
| 1 | Classifier | Confirms the permit type and the channel and sets the review area from the type. |
| 2 | Field extractor | Muse Spark extraction (replay by default) proposes values from the received documents. Where the validator scored the run, its real validation result is shown; no percentage is ever invented. |
| 2 | Document QC | Flags the scan-quality problems carried by the intake record. An unreadable page blocks. |
| 3 | Address locator | Asks the city locator (`findAddressCandidates`) for candidates for the typed address, then asks the parcel layer which parcel the best point falls in. It records the typed text, matched address, score, status (M/T/U), coordinates, candidate list, parcel id and method. One candidate scoring at least 90 (setting `ACME_GIS_AUTO_PROPOSE_SCORE`) is **proposed**, never auto-approved. A tie or a low score raises "Address needs a person to choose the property"; no candidate raises "Address not found in the city locator". Both go to early resolution. |
| 3 | Completeness | Checks the required fields and documents of the type. |
| 4 | Duplicate finder | Finds another live case that asks for the same project by the same applicant at the same address for the same permit type, and runs the identity matcher to propose applicant, parcel and contractor links for the steward. |
| 5 | Router | Any blocking finding → `needs_information` (**Route to early resolution**). A human-judgment finding (duplicate, conflict, low extraction quality) → `needs_information` (**Verify before review**). Otherwise → `ready_for_review` with its review area. |

Findings are written as application findings with a type (missing field,
missing document, unreadable, duplicate, conflict, low-confidence
extraction, judgment), a message, the rule, an **Applicant must** line and a
severity of `block` or `review`.

### Adjudication agent — five nodes

| Level | Node | What it does |
|---|---|---|
| 1 | Rule loader | Finds the type's published rules and flags a discretionary type (zoning variance, rezoning, certificate of appropriateness, site plan review). |
| 2 | Rule evaluator | Runs the existing deterministic evaluator. |
| 3 | Condition builder | Collects the conditions of approval from the `condition` results. |
| 3 | Precedent check | Finds an earlier decided case of the same type on the same parcel. |
| 4 | Disposition | `hold` when the type is discretionary, has no rules, or a rule needs judgment or a missing input; `deny` when a rule fails; `approve_with_conditions` when conditions apply; otherwise `approve`. |

The rationale cites each rule id, the observed value with its unit, the limit
and the citation — once.

### Confirm and revert

The recommendation card on the permit workspace shows the recommendation
pill, the rule rows with their citations, the conditions of approval, any
precedent warning, the pipeline trace and **"The agent recommends; a person
confirms or reverts. Nothing is final until confirmed."** The status is
`pending`, `confirmed` or `reverted`.

- **Confirm** needs `permit.decide` (Permit Reviewer only). It records the
  decision through the existing decision service with the confirming person
  as the decider of record: `approve` becomes approved, `approve_with_conditions`
  becomes approved with the conditions stored and shown as **Approved with
  conditions**, and `deny` becomes denied. A `hold` cannot be confirmed; the
  card says the reviewer decides with the normal decision form.
- **Revert** needs `permit.decide` and a reason. The case returns to manual
  review and the agent may run again.

The old agree/disagree stance is gone; the recommendation's history stays in
the audit trail.

## Where humans act

| Persona | Screen | Action | What happens next |
|---|---|---|---|
| City Administrator | Governance and sources | Simulate incoming permits | Records arrive via `intake_portal` and wait as **Awaiting intake agent** |
| City Administrator | Intake agent / Adjudication agent | Wake agent / Put agent to sleep | The agent may now be run by a person |
| Data Steward | Intake agent | Process one / Process all waiting | The six-node intake graph runs; the case is routed |
| Data Steward | Intake queue | Process selected with agent | The intake graph runs on a bounded selection of cases that wait for it; the batch is all-or-nothing |
| Data Steward | Steward review | Confirm/Reject link, Record no match | Identity links the reviewer will rely on become approved (or not); proposals stay evidence |
| Data Steward | Permit workspace | Accept or correct extracted … | Proposed Muse values become accepted/corrected; submitted revisions are never rewritten |
| Permit Reviewer | Adjudication agent | Run / Run all | The five-node adjudication graph runs and leaves a pending recommendation |
| Permit Reviewer | Permit workspace | Confirm / Revert the recommendation | The decision of record is the reviewer's, or the case returns to manual review |
| Permit Reviewer | Permit workspace | Record reviewer decision | The actual decision (`approved`/`denied`/`modified`/`information_requested`) with reason and versions; approval is refused while blockers (identity links, site, credentials, rule fails) stand |
| Permit Reviewer | Permit workspace | Approve with conditions | An `approved` decision that carries a non-empty list of conditions; the rationale is required and a denial needs a denial reason code |
| City Administrator | Administration | Permit types, users, reason codes | Every change is a governed, audited action and appears in the configuration log |
| City Administrator | Reconciliation | Assess application, Import ERP payment, Confirm allocation, Reconcile assessment | Fee assessed from the published schedule; reconciliation must be exact (balance 0.00) before issuance |
| Permit Reviewer | Permit workspace | Issue permit | Separate human action; idempotent on the command key; blocked until decision, links, assessment and exact reconciliation all hold |
| Applicant | Permit workspace / Work queue | Submit application correction | Creates a new immutable revision; the case returns for another intake run |

Navigation is persona-scoped: the left bar and the bottom tab bar list only
the screens the persona holds a grant for (`navigation()` uses the same
`SCREEN_PERMISSIONS`/`holds_grant` logic as the screen guard, so a hidden
screen is also a 403). Order and labels are canonical for everyone.

| Persona | Screens |
|---|---|
| Applicant | Work queue, Applicants, Permit workspace |
| Data Steward | the six above plus **Intake agent**, **Intake queue** and **Early resolution** |
| Permit Reviewer | Work queue, Applicants, Permit workspace plus **Adjudication agent** and **Review queue** |
| City Administrator | the eight original screens plus **Intake agent**, **Adjudication agent** and **Administration** |

## The life of a case

The status of a case is server state.  A person with the matching grant
moves it; the browser never decides.

| Status | What it means | Who moves it, and how |
|---|---|---|
| `submitted` | The City has the application and it waits for the intake agent | the intake agent, when a person runs it |
| `needs_information` | The City needs something from the applicant | **Data Steward**: return it, or advance it to review |
| `revisions_requested` | The reviewer has sent the case back for revisions | **Permit Reviewer**: request revisions with a reason code and a message |
| `ready_for_review` | The case is complete and waits for a reviewer | **Data Steward**: advance to review |
| `under_review` | A reviewer has the case | the adjudication agent and the reviewer |
| `approved` / `denied` | A decision is recorded | the reviewer |
| `issued` | The permit is issued | the reviewer with the issuance grant |
| `returned` | The City gave the case back; the applicant starts a new application | **Data Steward**: return |
| `archived` | The case is closed; its history stays | **City Administrator**: archive, then restore |

**Return** (Data Steward) needs an active reason code of the `return` type.
It is terminal: the applicant starts a new application rather than
answering on the returned one.

**Advance to review** (Data Steward) is refused while a **current, unwaived
blocking finding** stands in the way.  Waive the finding first, or clear it.

**Request revisions** (Permit Reviewer) needs an active reason code of the
`revision` type and a message.  The message is written as a comment the
applicant reads, so the applicant sees why the case came back.

**Answer and resubmit** (Applicant) is available from `needs_information`
and from `revisions_requested`.  The resubmission is atomic: the revised
documents, the new submitted revision and the state of the case move
together.  The case returns to `submitted` (awaiting the intake agent), the
first submission date is kept, and the work done against the earlier
revision — the evaluation, the recommendation and the decision — becomes
stale.  A stale decision is never revived by a resubmission; a reviewer
reconfirms it.

**Archive and restore** (City Administrator) are the only actions an
archived case accepts.  Archiving needs an active reason code of the
`archive` type and is refused for an issued permit.  The restore returns the
case to the status it held.  It never revives a stale approval or a stale
recommendation: whatever was marked stale stays stale.

Every one of these actions checks the grant, the archived guard and a
**mandatory expected version** (a missing version is refused as well as a
stale one), and writes an audit record and an action record.

### The archive guard

An archived case is closed.  Every service path that could change it asks
the guard first and refuses it:

| Path | Where |
|---|---|
| API revision | `permits/service.py` → `PermitService.revise` |
| Document store | `documents/service.py` → `DocumentService.store_version` |
| Evaluation | `permits/service.py` → `PermitService.evaluate` |
| Intake agent | `agents/intake.py` → `IntakeAgent.run` |
| Adjudication agent | `agents/adjudication.py` → `AdjudicationAgent.run` |
| Recommendation confirm and revert | `agents/recommendation.py` → `confirm`, `revert` |
| Parcel operations | `gis/matching.py` → `locate`, `decide_link`, `choose_candidate`, `find_by_number`, `confirm` |
| Finance | `finance/service.py` → `assess`, `reassess`, `allocate` |
| Portal upload and resubmission | `applicant_portal/service.py` → `revise_documents`, `resubmit` |
| Decision and reconfirmation | `permits/decisions.py` → `decide`, `reconfirm` |
| Issuance | `permits/issuance.py` → `issue` |
| Bulk intake processing | `permits/bulk.py` → `process_selected` |

## Reason codes

A reason code names why a case was returned, denied, waived, sent back for
revisions or archived.  Its **type** says which of those uses it may
serve, so a denial code can never return a case.

| Type | Used by |
|---|---|
| `return` | the Data Steward returning a case |
| `denial` | a reviewer denying a case, by hand or by confirming a denial recommendation |
| `waiver` | the Data Steward waiving a finding |
| `revision` | the reviewer asking for revisions |
| `archive` | the City Administrator archiving a case |

The codes are configuration.  **Administration → Reason codes** lists them
with their type and their state; an administrator adds a code with its type
and retires a code.  A retired code keeps its label, its version and its
history, and its code cannot be taken again.  The five codes the
demonstration shipped with were backfilled explicitly when migration `0006`
was applied: `INCOMPLETE_APPLICATION`, `WITHDRAWN_BY_APPLICANT` and
`DUPLICATE_SUBMISSION` are `return` codes; `DOES_NOT_MEET_CODE` and
`OUTSIDE_JURISDICTION` are `denial` codes.

The code is checked **in the service that acts on the case**, not only in
the form: an unknown code, a retired code and a code of the wrong type are
all refused.  Each action record snapshots the code, its label and its
version as they were at that moment, so the history of a case still reads
correctly after a code is retired.  A denial needs a denial code on every
path: a manual decision, a confirmation of a denial recommendation and a
reconfirmation.

## Findings and waivers

A finding is evidence for a person.  It names what is wrong, the rule that
applies, what the applicant must do and whether it blocks the case or only
asks a person to look.  Nine types are recorded: `missing_field`,
`missing_document`, `unreadable`, `wrong_type`, `duplicate`, `conflict`,
`fee`, `low_confidence_extraction` and `judgment`.  The classifier records
`wrong_type` when the intake record asked for another permit type, and
`fee` when the City cannot price the case (the permit type names no fee
schedule, or no published schedule is in force on the recorded basis date).

Findings accumulate, so each one carries a state:

* **current** — the live statement about the case;
* **resolved** — a later run showed that the condition is gone;
* **superseded** — a later run or a resubmission replaced it.

The history is kept: a finding is never deleted.  A rerun supersedes the
findings it recorded again and resolves the ones it did not; a resubmission
supersedes the findings of the earlier revisions.

**Waive** (Data Steward) applies to a **current finding of a waivable
type** — `wrong_type`, `duplicate`, `conflict`, `low_confidence_extraction`
and `judgment`.  A missing field, a missing document, an unreadable page
and a fee question are not waivable: the applicant must supply them, and
money is never waived.  A waiver records the reason code, the free-text
reason, who waived it and when; the finding is then shown struck through
with that detail.

A waiver never clears a deterministic rule failure and never clears an
identity, credential, finance or parcel-clearance check: those keep
blocking a decision exactly as they did before.  Only the intake findings
stop blocking the **advance to review** step.  Every decision snapshots the
waivers that applied to the case when it was recorded.

The primary finding of a case — the one it is grouped by — is the blocking
one, or else the first in this stable order: `missing_field`,
`missing_document`, `unreadable`, `wrong_type`, `duplicate`, `conflict`,
`fee`, `low_confidence_extraction`, `judgment`, and then the finding
identifier.

## Comments

A comment is either **visible to the applicant** or an **internal note**.
The visibility is enforced by the server on every surface that shows a
comment: the applicant portal ("Messages from the City"), the permit
workspace, the history panel, the support lookup and the API.

* A member of the City reads every comment.  An applicant reads only the
  comments the City wrote for the applicant.
* The identifier of an internal note is not a way to read it: an applicant
  who asks for one by its identifier is told the comment does not exist.
* A comment of another applicant's case is out of reach of the record
  scope.
* The audit record of a comment carries the comment identifier and its
  visibility.  It never carries the text, so an internal note cannot
  travel to an applicant through the audit trail.

Writing a comment needs the `permit.case.comment` grant and the expected
version of the case.  A comment does not change the state of the case, so
it does not advance the case version.

## The three queues

Phase 3b adds three screens.  Each one is opened by a grant only its
persona holds, never by a persona label: the intake queue and the
early-resolution board belong to the **Data Steward**, the review queue to
the **Permit Reviewer**.  The shared `/queue` keeps the behaviour it had and
links the queues the acting persona may open.

| Persona | Screen | What it answers |
|---|---|---|
| Data Steward | `/queue/intake` | which cases has the City in front of it, and in which saved view |
| Data Steward | `/queue/early-resolution` | which cases wait for a person, and what is in the way |
| Permit Reviewer | `/queue/review` | which cases are in front of the reviewer, and what was decided recently |

### The intake queue

The saved views are exact; the count of a tab is the number of cases that
tab holds.

| View | The cases it holds |
|---|---|
| **Active** | `submitted`, `needs_information`, `ready_for_review`, `under_review`, `revisions_requested` |
| **Awaiting agent** | `submitted` cases that arrived from outside the City and have no intake run for their current revision |
| **Needs information** | `needs_information` |
| **In review** | `ready_for_review`, `under_review` |
| **Archived** | `archived` |
| **Closed** | `issued`, `denied`, `returned` |

The seeded demonstration cases (D01–D11) carry a scenario id: they are the
fixed corpus of the demonstration, not arrivals, so they never wait for the
intake agent.  The rule is the same one the **Waiting** figure of the
intake agent screen uses, so the two numbers always agree.

Search (reference, applicant name, address), the filters (channel, permit
type, priority, owner) and the sort (age, priority, type, reference) are
query-string values.  The screen works without JavaScript.

**Signals.**  A signal is shown only where the server holds the fact:

* **duplicate** — the recorded duplicate finding of the intake run, with the
  reference of the other case when the finding names one;
* **document** — the scan-quality flags the received pages carry
  (`rotated`, `low_res`, `handwritten`, `unreadable`, `duplicate_page`);
* **parcel** — the recorded parcel link: `no match`, `proposed`, `approved`
  or `confirmed`;
* **agent** — what the intake run of the current revision left: `not run`,
  `needs a person`, `failed` or `agent was satisfied`.

There is no invented confidence number: the agent signal is the recorded
outcome of the run, not a score the City never computed.

**Age and the service target.**  The age chip shows the real age of the
case in whole days since its first submission.  It is coloured against the
service target of the case's permit type — the fictional number of days the
City aims to review that type in, held in `config/rules_and_fees.json` as
`service_target_days` and seeded into `permit_types.service_target_days`.
It is a demonstration figure and never a promise.

### Process selected with agent

The bulk action is a **distinct** action (`permit.intake.process_selected`),
not the "process every waiting case" button of the agent screen.

* The selection is a list of application id and version pairs, at most
  **50** cases.
* An **empty selection is refused**.  The action never falls through to
  "process all".
* A repeated case is processed once; a case named at two different
  versions is refused as ambiguous.
* Every case is checked before any case runs: the grant, the record scope
  of the person, the version, the state of the case and the awake state of
  the agent.  A sleeping agent refuses the whole batch.
* The batch is **all-or-nothing**.  It runs inside one savepoint: a
  failure anywhere in it leaves every case exactly as it was, with no run
  and no audit record of a run.

### The early-resolution board

The cases in `needs_information`, grouped by their **primary finding**: the
blocking finding first, otherwise the first in the stable order
`missing_field`, `missing_document`, `unreadable`, `wrong_type`,
`duplicate`, `conflict`, `fee`, `low_confidence_extraction`, `judgment`,
and then the finding identifier.  Each group shows its count and the top
current findings.  A case appears under one group only.

Resolve means taking one of the record actions on the case itself: **ask
the applicant for information** (an applicant-visible comment), **return**
the case (a return reason code), **advance to review** (refused while a
current, unwaived blocking finding stands in the way) or **waive** a
finding of a waivable type.

### The review queue

The cases in `ready_for_review` and `under_review`, with the counts per
review area and the adjudication recommendation of each case when the agent
has made one.  Below it are the **recent decisions**: the last decisions of
record, newest first, with their outcome and the conditions that were
recorded with them.

### Approve with conditions

**An approval with conditions is an `approved` decision that carries a
non-empty list of conditions.**  The decision outcome vocabulary does not
change, and `modified` keeps its existing meaning and stays non-issuable.

* The form offers **Approve**, **Approve with conditions** and **Deny**.
* A **rationale is required on every outcome**.  A denial also needs an
  active denial reason code.
* The conditions are carried through the decision, the **reconfirmation**,
  the **applicant tracker** (as "Conditions of your approval") and the
  **immutable permit snapshot and artifact**.
* An approval with conditions that names no condition is refused by the
  service, not only by the form.

## The applicant help assistant

The help panel is offered to the **Applicant** on the chooser (`/apply`), on
the application form (`/apply/<type>`) and on the tracker
(`/apply/track?ref=…`).  No other persona may open it: the portal itself
answers 403 to a staff persona.

The assistant **explains**; it never decides.  It answers only from a source
bundle the server builds, and it quotes that bundle.

### What it answers from

| Source | What it holds |
|---|---|
| Published rule versions | the rules in force at the basis date, each rendered with its **applicability**, its **operator**, its **threshold** and its **conditions**; a draft rule never reaches an applicant |
| Permit-type configuration | the review area, the process category, the discretionary flag, the required fields and the required documents |
| Service target | the configured target of the type, with its definition, as a target and never as a promise |
| Lifecycle and process passages | the fixed applicant-facing passages of `config/applicant_help.json`, each with an identifier |
| The applicant's own case | its status, the current findings with their "you must" line, the comments written for the applicant and the next step open to them |

The **basis date** is the application's first submission time for the rules of
that case, and the server's own time for general guidance.

The bundle is checked against the same truth guard the model payloads use: it
may not carry an expected outcome or a decision.  It never carries another
applicant's record and never carries an internal note.

### How it answers

The answer of this part is **deterministic**: a stable ranking over the
bundle.  A word of the question that is a keyword of a passage counts double,
a word that appears in the text of the passage counts once, a passage whose
threshold is the number the question names counts again, and the passages
are ordered by the score and then by their identifier.  The answer quotes the
matching passages and shows them as citations.

* A question that matches nothing gets an explicit **no-match**, never a
  guess.
* The answer is labelled **"Matching ACME rule text (not an AI answer)"**.
* A limit is never an exemption: the answer quotes the rule with its
  applicability, so a 6 ft limit is shown as a limit that applies in the
  side and rear yard, and the front-yard limit is shown beside it.
* The **next steps** are derived by the server from the grants the applicant
  holds, never from the text of an answer.

### The two timing figures

The panel shows the configured **service target** and the current
**backlog of the review area** as two separate figures, each with its own
definition and the time it was read.  They are never added together, no
completion date is computed and no queue position is claimed.

### The conversation

A conversation belongs to the applicant who opened it.  It stores the turns,
the mode, the citations and the source snapshot of each turn — the source
identifier, its version, its text and its hash.  A member of the City does
not read an un-escalated conversation; the only route by which the City sees
the applicant's question is the **help request** the applicant raises with
**Ask the City**.

* Asking needs the `applicant.help.ask` grant, the CSRF token and a
  **mandatory expected version** of the conversation.  A missing version is
  refused as firmly as a stale one.
* Asking the City needs the `applicant.help.escalate` grant and the same
  mandatory version.  It creates the help request, which the support screen
  of phase 3c answers.
* The rate limit is 10 questions per session per 10 minutes
  (`config/applicant_help.json`).  The session is stored as a hash.
* A question is at most 1,000 characters and is untrusted input: it is
  never rendered as markup and never becomes an instruction.
* The audit record of a question carries the identifiers and the outcome of
  the turn.  It **never carries the text of the question**.

### Without JavaScript

The help question is a **form of its own**, never part of the application
form, so the fields and the files the applicant typed stay intact.  On the
application form the answer opens in a **separate browsing context**
(`/apply/help/panel`), which is what keeps that form untouched.  With
JavaScript the answer is rendered in place instead.

### The live switch

`applicant_assist_live_enabled` is a server-only setting and it is **off by
default**.  A credential alone never enables a live answer for an applicant.
This part of the work answers without a model; the live path arrives with
the part that adds it.
## The operations screens (City Administrator)

Four read-only screens and three governed writes, all opened by their own grants
(`ops.dashboard.view`, `ops.audit_log.view`, `support.lookup.view`,
`support.help_request.answer`, `support.case.record`, `ops.checks.run`).  The City
Administrator gains no decide, issue, return, waive or comment power from them.

### Operations dashboard: `/ops/dashboard`

Six figures, each with its definition printed beside it: active cases (the Active saved
view of the intake queue), average age of active cases (now minus the original submission
time), early-incomplete share (first intake run routed to needs information, over distinct
applications with a run), agent-processed (distinct applications with a completed intake
run), decisions recorded (decision rows, split by outcome) and needs a person (needs
information plus held recommendations).  Three charts (volume by status, channel
distribution, backlog by review area) are server-rendered SVG with a table beside each.
The seeded synthetic history is **left out** of every figure by default; **Include the
synthetic history (labelled)** counts it and says so on the page.

### Audit log: `/ops/audit`

A paged, newest-first view over the existing append-only audit records; it is not a
second trail.  Filters: actor type, action, search.  The actor type comes from the identity
records the server holds (a service identity with an agent role is an agent; a selectable
persona or a staff user added in Administration is a person; everything else, including a
row with no actor, is the system), never from the text of a row.  A row links to its record
for the target types that have a page and shows plain text for the rest; **Details** opens
the event in the side flyout.

### Support: `/ops/support`

* **Look up an application** by reference: status, timeline and the comments written for
  the applicant.  Internal notes are never shown.
* **Help requests**: the questions applicants sent with Ask the City, each with the part of
  the conversation up to the request (and nothing before the applicant raised it, or after).
  **Answer** (`support.help_request.answer`) records the reply and the answered status
  together, with a mandatory expected version.  On a case that can still change the reply is
  also written as a comment the applicant reads; on an archived case it stays on the help
  request only and the application is not touched.  The audit record carries identifiers,
  never the text.
* **Record assistance** (`support.case.record`): an optional reference, the channel and a
  summary; listed as **Recent support cases**.  The summary is not audited.
* A short FAQ and a fictional ACME contact and emergency notice.

### Checks: `/ops/checks`

**Run checks** (`ops.checks.run`) runs eight read-only invariant checks inside the
application and records one canonical `checks.run` audit event (separate from the
dispatcher's own feedback event).  Each check ends as pass, fail or **not applicable**.
The historical seed is a fixed baseline: the decision and permit the fixture inserts for D07
(SYN-APP-007) have no decision or issuance audit event, and phase 2 exempts a case with no
parcel match from parcel confirmation.  Those are reported as **not applicable (historical
seed)** or counted as exceptions; they are never counted as passes and no event is made up
for them.  A record that is not in the fixture and has no audit record fails the check.
The checks: exactly four selectable personas; no agent identity decided or issued anything;
every post-seed decision and issuance has an accepted audit record; the City Administrator
holds none of decide, issue, return, waive; every post-seed issuance rests on an approved,
parcel-confirmed decision; fee totals recompute to the stored amounts; no archived case sits
in an active queue; no internal comment is applicant-visible.

### The simulator

Random intake may state a high priority and may omit a field or a document, so a case needs
a return or a revision.  The simulator never assigns `returned` or `revisions_requested`:
only the Data Steward's return and the Permit Reviewer's request for revisions do.

## Permit type icons

Each of the 17 permit types has one bundled seed icon (a 192 by 192 WebP in `repo/src/acme_city/static/permit-type-icons/`, named in `PERMIT_TYPE_SEED_ICONS`). The reset loads them with source `seed`; `ensure_seeded` only fills a type that has no icon rows, so no migration is involved and an administrator's saved icon is never overwritten. To change a bundled icon, replace the file and reset the demonstration data.

The original three (commercial alteration, new building, sign) predate this note. The other 14 were generated with Muse Image (`muse-image-1.0`) on 2026-10-28 outside the in-app generate-and-save flow, 14 calls at $0.01, $0.14 in total, then downscaled from 1600 by 1600 to 192 by 192. Their file names, sha256 prefixes and prompts are in `docs/operations/permit-type-icons-manifest.json`; the 1600 by 1600 originals are not kept in the repository. Because they bypassed the in-app flow they have no generation audit record and do not count toward the daily generation caps.

## Failure handling

- **Missing documents/fields** — the completeness node records a blocking
  finding and the router sends the case to `needs_information`, naming
  exactly what is missing. The applicant supplies it (a new revision), then
  the intake agent runs again.
- **Unreadable page** — the document QC node records a blocking finding, so
  the case goes to early resolution even though the rest is complete.
- **Duplicate submission** — the duplicate finder records a review finding
  linked to the other case, and the router asks a person to verify before
  review.
- **Rule failures** — e.g. DF-1 (front fence 6 ft > 4 ft maximum) produces a
  `deny` recommendation. The reviewer may still decide (denials are not
  blocked); approvals are blocked by unresolved fail/review blockers.
- **Held cases** — a discretionary type, a type with no published rule and a
  rule that needs judgment all produce `hold`. The card says the reviewer
  decides with the normal decision form.
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

## Property master

The city identifies property by **parcel number**, not by address. A permit
comes in with address text; the locator corrects it to the closest official
address and the parcel layer says which parcel that point falls in. The
steward approves that identity link, and the reviewer confirms the parcel
before deciding.

**Simulated enterprise GIS.** The app serves ArcGIS REST shaped services
in-app under `/sim/arcgis/rest/services/ACME/` (labelled simulated on every
page and response): `AddressLocator/GeocodeServer` (`findAddressCandidates`,
`suggest`, `reverseGeocode`), `Parcels/FeatureServer/0/query` (LGIM-style
`PARCELID`, `SITEADDRESS`, `OWNERNME1`, `USECD`, `ZONING`, `CNVYNAME`,
`STATEAREA`, `LNDVALUE`, `IMPVALUE`, `CNTASSDVAL`, `TAXDIST`, `SCHLDSCRP`,
`FLOODZONE`) and `AddressPoints/FeatureServer/0/query`. They read the one
parcel and address truth of the registry tables, so nothing disagrees. The
town (69 parcels, 71 address points, 6 streets) is synthetic and
deterministic (`fixtures/gis_town.json`, rebuilt by `scripts/build_gis_town.py`).

The app's own code reaches them only through the `GisLocator` adapter over
HTTP. `ACME_GIS_BASE_URL` (default: the in-app simulator) plus
`config/gis_field_map.json` is all it takes to point at a real ArcGIS server.

**Who does what.**

| Step | Who | Action id |
|---|---|---|
| Propose the parcel link from the typed address | Intake agent | (Address locator node) |
| Approve or reject the parcel link, with the locator evidence | Data Steward | `parcel.link.decide` |
| Choose another candidate / find a parcel by number | Permit Reviewer (or Steward) | `parcel.candidate.choose`, `parcel.find` |
| Confirm the parcel ("Is this the right property?") | Permit Reviewer | `parcel.confirm` |
| Flag a wrong address to GIS | anyone with `correction.request.submit` | `change.request` |

No approval is possible until the parcel link is approved **and** confirmed
(blockers `parcel_link_unapproved`, `parcel_unconfirmed`). Rule inputs that
come from the parcel (zoning, flood zone) are read from the confirmed parcel
only. A seeded case without a locator match is unchanged.

**Screens.** The permit workspace has a **Property** card (typed address,
standardized address, parcel number, score and status, other candidates, and
a small SVG inset). Steward review lists the open parcel-link proposals with
the submitted point against the candidate parcels. `/property/{parcel}` is the
property record (parcel attributes, addresses and units, applications and
permits, a "Shared with" panel, a map, source and history). `/property?q=`
is "Find a property". `/map` is the town map (SVG, no outside tiles; pan, zoom
and click with JavaScript, plain links without it; every parcel and marker
has a text label and a parcel table sits beside it). Staff personas only; the
Applicant sees only the case's own parcel.

**Shared with.** The published dataset "Property master (parcel, address,
owner, zoning)" has four simulated subscriber departments (Tax / Assessor,
Fire and life safety, Code enforcement, Utilities), each with a contract
listing the fields it consumes (Governance and sources). No such system is
built; the signals are synthetic and labelled so.

**Scenarios.** `address-typo` ("412 Mapel Rdg Dr" corrects to 412 Maple Ridge
Drive, score 96), `address-ambiguous` ("400 Lantern Row Unit 3": the building
and two units, a person must choose) and `address-unknown` (no match). The
fence scenarios use "400 Lantren Row".

**Applicant portal.** `/apply` (Applicant persona only): the guided chooser
of 17 types, the per-type form with a live completeness banner (computed by
the server on every preview, save and submit), the locator's "Did you mean",
a document checklist with drag and drop, the certification, **Submit
application** (refused server-side unless complete and certified), **Save and
exit** (a draft) and **Track an application**. Arrivals land as "Awaiting
intake agent".

## Community permit insight (synthetic year, City view, community view)

Everything newly displayed here is **seeded synthetic data**, flagged `synthetic` on every row it writes and labelled "synthetic data" on screen. The default reset loads none of it, and no acceptance or D-fixture test reads it.

### The demo-synthetic prepare mode

```bash
uv run python scripts/prepare_user_test.py --mode demo-synthetic
# optional: --synthetic-seed 20261028 --synthetic-count 600
```

The mode resets the database to the fixtures and then loads the synthetic year with `scripts/load_synthetic_year.py` (it refuses a database that is not the marked fictional demo). Defaults: seed `20261028`, count `600`; both are bounded (seed 0 to 2147483647, count 1 to 2000) by `config/synthetic_distributions.json`, whose `distribution_version` is part of the seed. The same seed, count and version always give the same year.

- One generator, `portal_intake/scenarios.py: generate_synthetic_year(seed=, count=)`, builds the cases; `fixtures/synthetic.py: load_synthetic_year` writes them. P3policy reuses the generator.
- Twelve months of dated arrivals (window ends 2026-10-27), all 17 types across the three districts. Fences cluster in residential districts; restaurants, bars, patios, signs, fit-outs and changes of occupancy sit in the commercial corridor; variance requests concentrate in R-2 on a few parcels so the map shows a pattern.
- Fence heights (front yard around 4 ft and 6 ft, side and rear yard around 6 ft and 7 ft) and shed areas (around 200 and 600 sq ft) fall on both sides of each threshold.
- A case is a **historical record**: application, revision, site, parties, and a decision and permit where its lifecycle has one. No agent runs, no decision service runs, and **no audit event is written**. A decision names the actor `synthetic_history`, which is neither a persona nor an agent. The workspace of a synthetic case shows a "Synthetic history" panel instead of an audit history.
- Synthetic cases carry scenario id `SYNTH`, so they never wait for the intake agent, and they are left out of every staff queue and work list. They appear in the City view, the community view and the property record.
- **Reset to fixtures only:** run the default reset (`scripts/reset_demo.py --confirm-fictional-demo`, or `prepare_user_test.py --mode fresh`). It deletes every synthetic row with the rest of the data.

### Business categories

`credentials.business_category` (restaurant, bar, retail, office, other) is set on every business licence. Migration 0008 backfills the businesses that already exist from the words in their name, and the reset runs the same reported backfill (`business_categories_backfilled` in its output). Contractor registrations keep a blank category. Commercial permits link to the business, so they carry its category.

### City view (City Administrator): `/insight/city`

Opened by the grant `insight.city.view`, which only the City Administrator holds; it is the last entry of the navigation. Filters are query-string values and the screen works without JavaScript:

| Parameter | Values |
|---|---|
| `type` | a permit type key, for example `deck_fence` |
| `outcome` | `approved`, `conditions`, `denied`, `undecided` |
| `period` | `all` (default), `30d`, `90d`, `6m`, `12m` |
| `category` | one or more of `restaurant,bar,retail,office,other` (comma separated) |
| `exceptions` | `1` for variances, waivers, denials and approvals with conditions only |
| `synthetic` | `include` (default) or `exclude` |

Quick views: `/insight/city?category=restaurant,bar` (restaurants and bars) and `/insight/city?type=zoning_variance&exceptions=1` (variances). The page has the district-shaded map (darker is more permits; orange dots mark parcels with exceptions, larger is more) with the district table, exceptions by kind and parcel, business activity by category, the monthly trend (SVG and table), and the permits in the view. Every figure is a count over the stored applications and its definition is printed beside it. A permit with no matched parcel is counted in the total and reported as "no matched parcel" instead of being drawn. The "Start a what-if from this view" control is absent until P3policy exists.

### Permits in my community (public): `/city/community`

On the City of Acme website, linked from `/city/permits` and the home page services. No persona or sign-in; read-only (other methods answer 405); rate limited per client address (60 requests a minute, `429` with `Retry-After`).

- `/city/community` shows the district-shaded map and district totals, with an optional type filter.
- `/city/community?q=<address, street or permit number>` looks permits up.
- `/city/community/permit/<number>` is one public record. Add `?format=json` (or send `Accept: application/json`) for the JSON of any of these.
- The public read model (`insight/public.py`) is an allowlist of 17 fields: reference, permit number, type, parcel, address, district, work description, public status, submitted / decided / issued dates, outcome, conditions, exception marker, **contractor business name** and the synthetic flag. It never holds an applicant or homeowner name, a document, a note or comment, a contact detail, a fee, a finding, a draft, or an internal id.
- Drafts, withdrawn, returned and archived cases and anything before submission are not public. A case that is not public answers exactly like a number that does not exist.
- Any district or filter total under 3 shows as "fewer than 3" (the district is hatched on the map).

### Simulated departments

`config/property_subscribers.json` now holds six simulated subscribers of the property master. Sanitation (next collection day) and Police (licensed late-night premises, from the bar-category businesses sited on the parcel) join the four from phase 2, under a visible "Simulated departments" heading in the property record's Shared with panel and in Governance and sources. All signals are synthetic.

### Model source label

Every model run shown on the evidence panel and the workspace carries a source label such as "Muse Spark (live)" or "Muse Spark (replay)" with tokens and latency. The macro `templates/components/muse_source.html` is the one to reuse on the chat, briefing and what-if screens when they are built.

## Fence flow

```mermaid
sequenceDiagram
    participant P as ACME ePermit Portal (simulated)
    participant A as City Administrator
    participant I as Intake agent (service identity)
    participant S as Data Steward
    participant J as Adjudication agent (service identity)
    participant R as Permit Reviewer
    P->>P: submit fence record (portal/counter_scan/email/mail/fax); the address is typed slightly wrong
    P->>I: stage raw, create application + revision + documents
    I->>I: wait as "Awaiting intake agent"
    A->>I: wake the intake agent
    S->>I: Process all waiting (seven-node graph; the locator corrects the address and proposes the parcel)
    I->>I: route to ready_for_review with the review area
    S->>I: approve identity links, the parcel link and extracted values
    A->>J: wake the adjudication agent
    R->>R: confirm the parcel (Is this the right property?)
    R->>J: Run all (five-node graph)
    J->>J: recommendation pending (e.g. deny, DF-1) — advisory
    R->>J: Confirm (decision of record) or Revert (reason required)
    A->>I: assess fee, import payment, allocate, reconcile (exact)
    R->>I: issue permit (separate human action)
```
