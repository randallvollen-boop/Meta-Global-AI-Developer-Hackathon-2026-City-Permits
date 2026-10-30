# User stories

"As a … I want … so that …", with acceptance criteria tied to real screens and
actions. Agents are system actors (service identities), never selectable
personas. All data is fictional ACME City data.

## The persona mapping

The prototype had seven roles. They map onto the five personas of this
demonstration, listed here in the order a permit moves through them:

| Prototype role | Persona that does it here |
|---|---|
| Applicant | Applicant |
| Agent supervisor (wake and sleep the agents, ask them to run) | Agent Operator |
| Intake clerk (process intake, early resolution) | Data Steward |
| Reviewer and supervisor (confirm/revert, decide, issue) | Permit Reviewer |
| Administrator, auditor, support (configuration, users, audit, fees) | City Administrator |

The five personas are the only selectable actors. The two agents and every
other organizational identity are service identities. Only the Agent Operator
wakes the agents and asks them to run; the City Administrator sees the agent
policy and the roles that may wake and run agents, but does not wake, sleep
or run an agent.

## Applicant

The Applicant uses the City website, not the staff app. The navigation lists
My permits, Start an application, Help and Home.

- As an Applicant, I want to see only my own cases, so that I never see
  another applicant's records.
  - Acceptance: sign in as Applicant; **My permits** (`/apply/track`) lists
    only my applications. The page of another applicant's case returns 404
    ("That application is not available to you") and the API returns 403. The
    staff screens return 403.
- As an Applicant, I want the tracker and "What happens next" on my case, so
  that I know what the city is waiting for.
  - Acceptance: open **My permits** and select an application; the tracker
    and next-step text name the current server-recorded state and never
    promise an approval.
- As an Applicant, I want to answer a needs-information case, so that my case
  can proceed.
  - Acceptance: on the tracker, **Submit revised documents** sends the
    revised files, and **Send the answer to the City** (the move the life
    cycle calls "Answer and resubmit") sends the answer; either creates a new
    immutable revision and the earlier revision is unchanged.
- As an Applicant, I want to choose what I am trying to do and fill in the
  form for that project, so that I only give what that kind of project needs.
  - Acceptance: **Start an application** (`/apply`) opens the chooser that
    asks what the applicant is trying to do; the form shows the type's fields
    (required ones starred, optional ones marked), the locator's address
    suggestions, a document checklist with "Sent to the City separately", and
    the certification; **Submit application** is never disabled: an incomplete
    submit is refused by the server and the form returns "There is a problem"
    with a linked list and a message beside each missing item, keeping
    everything entered; the confirmation shows the reference number.
- As an Applicant, I want to save a draft and track an application, so that I
  can finish later and see what the City says.
  - Acceptance: **Save draft** keeps a draft and says so; **Track
    application** (`/apply/track`) shows the status, "Messages from the City"
    and, when the City asked, **Submit revised documents**.
- As an Applicant, I want to ask what the rules say and what the process is,
  so that I understand the permit before I file it.
  - Acceptance: the help panel on the chooser, on the application form and on
    the tracker answers from the City's published rules and from my own case
    only; the answer quotes the rule it used, shows its citation and labels itself
    "Matching ACME rule text (not an AI answer)"; a question that matches nothing says so
    instead of guessing; the panel shows the configured service target and
    the current review-area backlog as two separate figures and never a
    completion date.
- As an Applicant, I want to ask a person at the City when the assistant
  cannot help, so that my question is answered by the City.
  - Acceptance: **Ask the City** creates a help request that the City's
    support desk answers; my conversation stays private to me until then.
    After three questions the assistant could not answer, or when I ask for a
    person, the panel prompts me to use it; the City's answer appears on my
    case and in the panel.
- As an Applicant, I want the help panel never to lose what I have typed,
  so that asking a question does not cost me my application.
  - Acceptance: the help question is a form of its own; on the application
    form the answer opens in a separate window and the fields and files I
    typed stay exactly as they were, with JavaScript switched off as well.

## Agent Operator

- As an Agent Operator, I want to wake and sleep the two agents, so that the
  City decides when automation runs.
  - Acceptance: **Intake agent** and **Adjudication agent** show an
    awake/asleep state with **Wake agent** / **Put agent to sleep**; the change
    is audited as `agent.toggle`. A persona without `agent.toggle` sees a lock
    line instead. The navigation lists Agents, Intake agent, Adjudication agent
    and Agent runs.
- As an Agent Operator, I want to run the intake agent when it is awake, so
  that incoming cases are processed the way the City decided they should be.
  - Acceptance: **Intake agent** shows whether the agent is awake; **Process
    next 20** and **Process one** are disabled while it sleeps ("The agent is
    asleep, so the run buttons are off. Use Wake agent above to turn them on.");
    the seven-step run is recorded and **All runs**, then **View run**, shows
    each step. The page updates in place after each action.
- As an Agent Operator, I want to run the adjudication agent on the cases in
  review, so that each has a deterministic recommendation before a reviewer
  looks at it.
  - Acceptance: **Adjudication agent** runs **Process next 20** or **Process
    one** and the five-step run is recorded; the recommendation waits for a
    person. I record no permit decision.

## Data Steward

- As a Data Steward, I want the intake agent's findings to name what the
  applicant must do, so that a needs-information case asks for exactly what
  is missing.
  - Acceptance: each finding has a type, a message, the rule, an
    "Applicant must" line and a severity of block or review; a blocking
    finding routes the case to early resolution.
- As a Data Steward, I want agent-proposed identity links with their evidence,
  so that I can approve only links the evidence supports.
  - Acceptance: **Data issues** lists each proposal with **Review match**; the
    issue shows the supporting and conflicting evidence, and **Confirm link to ...**
    records my decision, my id and the reason.
- As a Data Steward, I want to approve the parcel a permit was matched to, so
  that the case is tied to the right property by parcel number.
  - Acceptance: **Data issues** lists a **Check the property** issue for each
    case, with **Review property**; it shows the typed address, the
    standardized address, the score and status, the candidates and a small map
    of the submitted point against the candidate parcels; **Approve parcel link
    for ...** records my decision and reason; it never approves the permit.
    Until the parcel link and the identity link are approved, a reviewer's
    approval is refused with the blockers `parcel_link_unapproved` and
    `identity_link_unapproved`.
- As a Data Steward, I want to accept or correct Muse's proposed values, so
  that proposed values never silently become submitted facts.
  - Acceptance: in the Permit workspace, **Accept or correct extracted …**
    records the decision; correcting requires a value and a reason.
- As a Data Steward, I want the navigation to hide screens outside my grants,
  so that the menu lists only screens the server allows.
  - Acceptance: Steward navigation lists Data issues, Master records, Source
    records, Activity, Work queue, Permit workspace, Rules and fees, Intake
    queue, Early resolution and Steward automation; Reconciliation, Governance,
    Administration and the agent screens return 403.

## Permit Reviewer

- As a Permit Reviewer, I want the cases in review to carry a deterministic
  recommendation before I look at them, so that I start from the rule results.
  - Acceptance: the Agent Operator runs the adjudication agent; the **Review
    queue** shows each case's recommendation (for example "deny pending"). The
    reviewer cannot wake or run an agent: the agent screens return 403.
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
    and **Flag address correction to GIS** (geographic information system); approval stays blocked until the
    parcel link is approved and confirmed.

## City Administrator

- As a City Administrator, I want to set the agent policy and see which roles
  may wake and run the agents, so that the City decides who controls
  automation without the Administrator running it.
  - Acceptance: **Administration** → **Agent processing** shows the policy
    (keep agents awake, maximum runs per hour, the processing mode) and "The
    policy says when the agents work. People still review the recommendations
    and make the permit decisions." **Administration** → **Users and roles**
    has the table "Roles that can wake and run agents" with **Save role
    permissions**. The Administrator has no **Wake agent** or **Process next 20**
    button: the agent screens return 403 for this persona.
- As a City Administrator, I want to simulate incoming permits from the
  outside portal, so that I can watch data arrive and wait for the agent.
  - Acceptance: **Governance and sources** → **Simulate incoming permits**
    (for example `fence-front-too-tall`); each record becomes an application in
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
  - Acceptance: **Administration** → Users and roles lists the five personas
    (Agent Operator, Applicant, City Administrator, Data Steward and Permit
    Reviewer) and the added users, and a separate table lists the service identities
    including the two agents; **Add user** creates a user with the grant
    template of one persona role, and the user does not appear in the persona
    switcher.
- As a City Administrator, I want to see every configuration change, so that
  the configuration log explains the current state.
  - Acceptance: **Administration** → Configuration log lists the entries
    newest first with when, change, target, before → after and actor.
- As a City Administrator, I want to assess and reconcile fees, so that a
  permit is only issued against an exactly reconciled position.
  - Acceptance: **Reconciliation** → Assess application, Import ERP payment (ERP is enterprise resource planning),
    Confirm allocation, Reconcile assessment; balance 0.00, status exact.
    My configuration access leaves me without `permit.decide`: trying to
    confirm a recommendation as Administrator is refused.

- As a City Administrator, I want an operations dashboard, so that I can see how
  permit work is going without trusting a number I cannot check.
  - Acceptance: **Operations** shows active cases, average age, early-incomplete share,
    agent-processed cases, decisions recorded and cases that need a person, each with its
    definition, three charts with a table beside each, and the synthetic history left out
    or labelled.
- As a City Administrator, I want a read-only audit log, so that I can see who or what did
  what.
  - Acceptance: **Audit log** lists the audit records newest first, filtered by actor type
    (person, agent, system), action and search, and links a row to its record where a page
    exists.
- As a City Administrator, I want a support screen, so that I can help applicants.
  - Acceptance: **Support** looks up a case by reference (status, timeline, comments the
    applicant can read), answers the help requests from Ask the City (a reply on a case
    also appears to the applicant on the case) and records assistance as a support case.
    I still cannot decide, issue, return or waive.
- As a City Administrator, I want to run invariant checks, so that I know the rules of the
  application still hold.
  - Acceptance: **Checks** runs eight read-only checks and lists pass, fail or not
    applicable with a one-line reason each; the D07 historical seed is not applicable and
    never a pass.

## Service agents (system actors)

- As the Intake agent (service identity), I want to run a seven-node graph on
  one case, so that the case is classified, read, checked for duplicates,
  checked for completeness and routed the same way every time.
- As the Field extractor, I want to propose values from the received document
  text (replay by default), so that a steward can accept or correct each one.
- As the Document QC (quality check) node, I want to flag the scan-quality problems the record
  carried, so that an unreadable page blocks the case.
- As the Duplicate finder, I want to find the case that asks for the same
  project, so that a person decides whether it is a resubmission and an
  agent never does.
- As the Adjudication agent (service identity), I want to run a five-node
  graph, so that the same facts and rule versions always give the same
  recommendation.
- As the Adjudication agent, I want a discretionary type always held, so
  that a person or the board decides it.
- As either agent, I want to state an advisory outcome with a rationale
  citing each rule once, so that the human reviewer decides with the advice in hand and
  keeps the decision.
