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
| Data Steward | Steward review | Confirm/Reject link, Record no match | Identity links the reviewer will rely on become approved (or not); proposals stay evidence |
| Data Steward | Permit workspace | Accept or correct extracted … | Proposed Muse values become accepted/corrected; submitted revisions are never rewritten |
| Permit Reviewer | Adjudication agent | Run / Run all | The five-node adjudication graph runs and leaves a pending recommendation |
| Permit Reviewer | Permit workspace | Confirm / Revert the recommendation | The decision of record is the reviewer's, or the case returns to manual review |
| Permit Reviewer | Permit workspace | Record reviewer decision | The actual decision (`approved`/`denied`/`modified`/`information_requested`) with reason and versions; approval is refused while blockers (identity links, site, credentials, rule fails) stand |
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
| Data Steward | the six above plus **Intake agent** |
| Permit Reviewer | Work queue, Applicants, Permit workspace plus **Adjudication agent** |
| City Administrator | the eight original screens plus **Intake agent**, **Adjudication agent** and **Administration** |

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
