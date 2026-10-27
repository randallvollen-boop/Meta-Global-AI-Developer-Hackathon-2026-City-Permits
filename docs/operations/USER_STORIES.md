# User stories

"As a … I want … so that …", with acceptance criteria tied to real screens and
actions. Agents are system actors (service identities), never selectable
personas. All data is fictional ACME City data.

## The persona mapping

The prototype had seven roles. They map onto the four personas of this
demonstration:

| Prototype role | Persona that does it here |
|---|---|
| Applicant | Applicant |
| Intake clerk (process intake, early resolution) | Data Steward |
| Reviewer and supervisor (adjudicate, confirm/revert, decide) | Permit Reviewer |
| Administrator, auditor, support (wake/sleep agents, configuration, users) | City Administrator |

The four personas are the only selectable actors. The two agents and every
other organisational identity are service identities.

## Applicant

- As an Applicant, I want to see only my own cases in the Work queue, so that
  I never see another applicant's records.
  - Acceptance: sign in as Applicant; the left navigation lists only Work
    queue, Applicants and Permit workspace; hidden screens return 403.
- As an Applicant, I want the tracker and "What happens next" on my case, so
  that I know what the city is waiting for.
  - Acceptance: open the Permit workspace; the tracker and next-step text
    name the current server-recorded state and never promise an approval.
- As an Applicant, I want to answer a needs-information case, so that my case
  can proceed.
  - Acceptance: use **Submit application correction** with the missing facts;
    a new immutable revision is created and the earlier revision is unchanged.

- As an Applicant, I want to choose what I am trying to do and fill in the
  form for that project, so that I only give what that kind of project needs.
  - Acceptance: **Start a new application** (Work queue) opens "What are you
    trying to do?"; the form shows the type's fields, a completeness banner
    ("Ready to submit..." or "Still needed: ..."), the locator's "Did you
    mean", a document checklist and the certification; **Submit application**
    stays disabled until complete and certified, and the server refuses an
    incomplete submit too; the confirmation shows the reference number.
- As an Applicant, I want to save a draft and track an application, so that I
  can finish later and see what the City says.
  - Acceptance: **Save and exit** keeps a draft; **Track an application**
    shows the status, "Messages from the City" and, when the City asked,
    **Submit revised documents**.

## Data Steward

- As a Data Steward, I want to run the intake agent when it is awake, so
  that incoming cases are processed the way the City decided they should be.
  - Acceptance: **Intake agent** shows whether the agent is awake; the run
    buttons are disabled with "Wake the agent first" while it sleeps; a person
    with `agent.run.intake` runs **Process one** or **Process all waiting**
    and the six-node trace is recorded.
- As a Data Steward, I want the intake agent's findings to name what the
  applicant must do, so that a needs-information case asks for exactly what
  is missing.
  - Acceptance: each finding carries a type, a message, the rule, an
    "Applicant must" line and a severity of block or review; a blocking
    finding routes the case to early resolution.
- As a Data Steward, I want agent-proposed identity links with their evidence,
  so that I can approve only links the evidence supports.
  - Acceptance: **Steward review** shows proposals with supporting/conflicting
    evidence; **Confirm link** records my decision, my id and the reason.
- As a Data Steward, I want to approve the parcel a permit was matched to, so
  that the case is tied to the right property by parcel number.
  - Acceptance: **Steward review** → "Parcel links awaiting a decision" shows
    the typed address, the standardized address, the score and status, the
    candidates and a small map of the submitted point against the candidate
    parcels; **Approve parcel link** records my decision and reason; it
    never approves the permit.
- As a Data Steward, I want to accept or correct Muse's proposed values, so
  that proposed values never silently become submitted facts.
  - Acceptance: in the Permit workspace, **Accept or correct extracted …**
    records the decision; correcting requires a value and a reason.
- As a Data Steward, I want the navigation to hide screens outside my grants,
  so that the menu never promises access the server would refuse.
  - Acceptance: Steward navigation lists Work queue, Applicants, Properties,
    Permit workspace, Steward review, Rules and fees plus Intake agent;
    Reconciliation, Governance, Adjudication agent and Administration return
    403.

## Permit Reviewer

- As a Permit Reviewer, I want to run the adjudication agent when it is
  awake, so that the cases in review carry a deterministic recommendation
  before I look at them.
  - Acceptance: **Adjudication agent** shows whether the agent is awake; a
    person with `agent.run.adjudication` runs **Run** or **Run all** and the
    five-node trace is recorded.
- As a Permit Reviewer, I want the recommendation card at the Decision step,
  so that I see the outcome, the rule rows with their citations, the
  conditions of approval and the pipeline trace before I decide.
  - Acceptance: the card shows the outcome pill, the status, the rationale,
    the rule citations, the conditions and "The agent recommends; a person
    confirms or reverts. Nothing is final until confirmed."
- As a Permit Reviewer, I want to confirm or revert the recommendation, so
  that my judgment is the decision of record.
  - Acceptance: **Confirm** records the decision through the normal decision
    service with me as the decider of record; **Revert** needs a reason and
    returns the case to manual review. A held recommendation cannot be
    confirmed.
- As a Permit Reviewer, I want issuance to stay a separate action, so that an
  approval never issues by itself.
  - Acceptance: **Issue permit** requires a current approved decision, valid
    links/credentials and an exact reconciliation; the command key is
    idempotent.

- As a Permit Reviewer, I want to confirm that the matched parcel is the right
  property, so that I never decide a case on the wrong parcel.
  - Acceptance: the **Property** card on the permit workspace shows the
    address the applicant typed, the standardized address, the parcel number
    (the key the city uses), the locator score and the other candidates, with
    **Confirm parcel**, **Choose another candidate**, **Find parcel by number**
    and **Flag address correction to GIS**; approval stays blocked until the
    parcel link is approved and confirmed.

## City Administrator

- As a City Administrator, I want to wake and sleep the two agents, so that
  the City decides when automation runs.
  - Acceptance: **Intake agent** and **Adjudication agent** show an
    awake/asleep banner with **Wake agent** / **Put agent to sleep**; the
    change is audited as `agent.toggle`. A persona without `agent.toggle` sees
    a lock line instead.
- As a City Administrator, I want to simulate incoming permits from the
  outside portal, so that I can watch data arrive and wait for the agent.
  - Acceptance: **Governance and sources** → **Simulate incoming permits**
    (e.g. `fence-front-too-tall`); each record becomes an application in
    status `submitted`, shown as **Awaiting intake agent**.
- As a City Administrator, I want the permit-type configuration in one place,
  so that required fields, required documents, review areas, process
  categories and fee schedules are managed together.
  - Acceptance: **Administration** → Permit types lists all seventeen types;
    **Require document** / **Stop requiring** changes one type and is
    audited; **Add permit type** creates a type with no rules, which the
    adjudication agent then holds for a person.
- As a City Administrator, I want to see the people and the service
  identities, so that I know who may act and which identities are machines.
  - Acceptance: **Administration** → Users and roles lists the four personas
    and the added users, and a separate table lists the service identities
    including the two agents; **Add user** creates a user with the grant
    template of one persona role, and the user does not appear in the persona
    switcher.
- As a City Administrator, I want to see every configuration change, so that
  the configuration log explains the current state.
  - Acceptance: **Administration** → Configuration log lists the entries
    newest first with when, change, target, before → after and actor.
- As a City Administrator, I want to assess and reconcile fees, so that a
  permit is only issued against an exactly reconciled position.
  - Acceptance: **Reconciliation** → Assess application, Import ERP payment,
    Confirm allocation, Reconcile assessment; balance 0.00, status exact.
    My configuration access does **not** give me `permit.decide`: trying to
    confirm a recommendation as Administrator is refused.

## Service agents (system actors)

- As the Intake agent (service identity), I want to run a six-node graph on
  one case, so that the case is classified, read, checked for duplicates,
  checked for completeness and routed the same way every time.
- As the Field extractor, I want to propose values from the received document
  text (replay by default), so that a steward can accept or correct each one.
- As the Document QC node, I want to flag the scan-quality problems the record
  carried, so that an unreadable page blocks the case.
- As the Duplicate finder, I want to find the case that asks for the same
  project, so that a person — never an agent — decides whether it is a
  resubmission.
- As the Adjudication agent (service identity), I want to run a five-node
  graph, so that the same facts and rule versions always give the same
  recommendation.
- As the Adjudication agent, I want a discretionary type always held, so
  that a person or the board decides it.
- As either agent, I want to state an advisory outcome with a rationale
  citing each rule once, so that the human reviewer's decision is informed
  but never replaced.
