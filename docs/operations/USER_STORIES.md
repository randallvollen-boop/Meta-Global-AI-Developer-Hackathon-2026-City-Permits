# User stories

"As a … I want … so that …", with acceptance criteria tied to real screens and
actions. Agents are system actors (service identities), never selectable
personas. All data is fictional ACME City data.

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

## Data Steward

- As a Data Steward, I want agent-proposed identity links with their evidence,
  so that I can approve only links the evidence supports.
  - Acceptance: **Steward review** shows proposals with supporting/conflicting
    evidence; **Confirm link** records my decision, my id and the reason.
- As a Data Steward, I want to accept or correct Muse's proposed values, so
  that proposed values never silently become submitted facts.
  - Acceptance: in the Permit workspace, **Accept or correct extracted …**
    records the decision; correcting requires a value and a reason.
- As a Data Steward, I want the navigation to hide screens outside my grants,
  so that the menu never promises access the server would refuse.
  - Acceptance: Steward navigation lists Queue, Applicants, Properties,
    Permit, Steward review and Rules; Reconciliation and Governance return 403.

## Permit Reviewer

- As a Permit Reviewer, I want the Agent recommendation card at the Decision
  step, so that I see the deterministic outcome, rationale and citations
  before I decide.
  - Acceptance: the card shows the outcome pill, "Advisory. The Permit
    Reviewer decides.", rule citations and (when run) the Muse summary.
- As a Permit Reviewer, I want to agree or disagree with the recommendation,
  so that my judgment is recorded beside the agent's advice.
  - Acceptance: **Record stance on the agent recommendation**; disagreeing
    without a reason is refused.
- As a Permit Reviewer, I want issuance to stay a separate action, so that an
  approval never issues by itself.
  - Acceptance: **Issue permit** requires a current approved decision, valid
    links/credentials and an exact reconciliation; the command key is
    idempotent.

## City Administrator

- As a City Administrator, I want to simulate incoming permits from the
  outside portal, so that I can watch data arrive and be triaged.
  - Acceptance: **Governance and sources** → **Simulate incoming permits**
    (e.g. `fence-front-too-tall`); each record becomes an application with
    five recorded agent steps.
- As a City Administrator, I want the registered sources visible, so that I
  can see owner, steward queue and custodian for every dataset, including
  `intake_portal` / `submitted_applications`.
  - Acceptance: the Registered source datasets table shows the portal
    contract as complete and publishable.
- As a City Administrator, I want to assess and reconcile fees, so that a
  permit is only issued against an exactly reconciled position.
  - Acceptance: **Reconciliation** → Assess application, Import ERP payment,
    Confirm allocation, Reconcile assessment; balance 0.00, status exact.
    My configuration access does **not** give me `permit.decide`: trying to
    record a reviewer decision as Administrator is refused.

## Service agents (system actors)

- As the Intake agent (service identity), I want to check completeness
  against the permit type's required fields/documents, so that incomplete
  cases ask the applicant for exactly what is missing.
- As the Identity agent, I want to propose applicant/parcel/contractor links
  from the deterministic matcher, so that a steward — never an agent —
  approves them.
- As the Extraction agent (Muse Spark), I want to propose values from the
  received document text (replay by default), so that a steward can accept or
  correct each one.
- As the Rules agent, I want to run the deterministic evaluator, so that the
  same facts and rule versions always give the same results.
- As the Recommendation agent, I want to state an advisory outcome with a
  rationale citing each rule, so that the human reviewer's decision is
  informed but never replaced. My optional Muse summary may only explain;
  if it names a different outcome it is rejected.
