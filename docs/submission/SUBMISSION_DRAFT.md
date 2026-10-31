# ACME City Permits

## Draft status

This is submission text for Randall to review and submit himself. It has not been submitted. The hosted demo at https://acme-city-permits.onrender.com shows all five personas.

## Summary

ACME City Permits is a fictional municipal permitting application that follows a permit from intake through identity and property review, application checks, a human decision, fee reconciliation, and permit issuance. It combines registry master data, versioned rules, role based actions, audit history, and bounded Meta Muse proposals while keeping every authoritative decision with a person or deterministic service.

## What it does

### Applicant

An applicant can choose from seventeen fictional permit types, locate a property, save a draft, submit an application, replace documents, answer a request for information, track progress, read messages from the City, and download a submission or issued permit. The help panel uses published ACME rules and the applicant's own case. It cites its sources and says when it cannot answer.

### Agent operator

The Agent Operator is the only persona that wakes and runs the intake and adjudication agents, and the only one that wakes the steward assistant. The operator opens the Agents home, wakes or puts an agent to sleep, runs one case or a batch of waiting cases, opens Agent runs to read a run and retries a failed run. The intake agent is a seven node graph and the adjudication agent is a five node graph, and each run records its nodes. The agents prepare a case and leave a recommendation. They never decide, price or issue a permit. Waiting work sits in a durable queue, and the City Administrator sets the processing policy under Administration, Agent processing. Optional automatic processing exists and is off on the hosted demo.

### Data steward

A data steward works the Data issues workspace, which has a guide, and the Early resolution screen. The steward reviews possible duplicate records, approves identity and parcel links, and accepts or corrects values proposed from documents. The steward can also inspect master records, source records, provenance, and change activity. These actions do not approve a permit.

Once the Agent Operator wakes it, the steward assistant works the Data issues queue when the steward asks, up to 20 tasks per press of Prepare recommendations. For each task it gathers the evidence and proposes a decision with a High, Review or Held level and a one line reason. The steward reads the evidence and presses Accept recommendation, which is refused if the record changed since, or decides the task another way. A held recommendation can never be accepted. Accept all high-confidence shows the exact list before anything is accepted, and skips and names any item that changed. An agreement figure shows how many recommendations the steward accepted unchanged in the last 7 days. Explain with Muse rewrites the reason in plain words without changing the decision.

### Permit reviewer

A permit reviewer works the Review queue, checks the property and application facts, and reads the rule-based recommendation the adjudication agent leaves. The reviewer can confirm or revert that recommendation, record the decision of record, add conditions, request revisions, and issue a permit only after the required links, decision, fee assessment, payment allocation, and reconciliation are complete.

### City administrator

A city administrator sees the "Planning overview", the "Operations dashboard", the "Audit log", "Support", "Governance and sources", "Rules and fees", "Reconciliation" and "Administration", the last with its tabs for the users and roles, the appearance and the configuration. The administrator can simulate incoming applications, set the agent processing policy, manage fictional configuration, run the checks on the Checks screen, and create governed policy drafts. Configuration authority does not grant permit decision authority.

## How it uses Meta Muse

Meta Muse Spark can propose structured values from received document text and can produce bounded record match proposals. The application validates the response against a strict schema and records its source, usage, latency, and validation result. A data steward decides whether a proposed value or link becomes part of the governed record.

The applicant help and City policy paths also have bounded Muse support. Muse can draft a cited answer, explain a policy simulation, write a briefing from typed facts, or propose a policy change. The server checks sources, claims, figures, rule citations, and allowed change types. A failed answer is refused. A policy proposal is not saved until an authorized person chooses to save it, and it still follows the normal draft and approval process.

The steward assistant follows the same rule. It prepares its proposals on the Data issues screen, where the steward presses Prepare recommendations and then Accept recommendation or Accept all high-confidence, and Explain with Muse rewrites a reason in plain words without changing the decision.

Muse Image support can generate fictional permit type icons through a governed administrator action with daily limits and recorded provenance.

Live Muse is on for the hosted demo, with a daily allowance of 100 live calls. When the allowance is used up, the app falls back to its recorded answers and says so on screen. [REVIEW: Randall]

## Models used

* Muse Spark is the runtime model. It extracts values from documents, proposes record matches, prepares steward recommendations, helps applicants, writes the policy briefing, explains a simulation and proposes policy changes. It makes proposals only, and people decide.

* Muse Image (muse-image-1.0) made 14 of the 17 permit type icons.

* Muse Wonder (muse-wonder-1.0) worked as a builder: the October 27 interface redesign, the permit type icon feature, and a second build with persona navigation, the ePermit intake portal and the agent triage.

* Local and other frontier models assisted with planning, coding and review.

## What was built during the event

Before the event only the reference requirements package existed (received 2026-10-26). There was no application code. The whole application was built during the event. The git history starts on October 27 with a baseline commit of the overnight build of October 26. Work after that baseline includes:

* Parity phases 1 to 3 and the Muse Wonder redesign.

* A policy what-if tool. Runs are immutable and hash verified, and a Muse briefing and proposal pass claim checks before anyone sees them.

* The applicant help assistant.

* The City of Acme public website with a community lookup that shows no homeowner names, documents or fees, a town map and a City view.

* ePermit intake with five channels and scan quality flags.

* The intake and adjudication agents, a durable agent work queue, and optional automatic processing (off on the hosted demo).

* The steward Data issues workspace and guide, the steward assistant with its batch preview and agreement figure, and automatic linking, which is built and paused on the hosted demo.

* The lifecycle and walkthrough pages, and a demo video on the persona page.

* A production mode that is separate from demo mode, rate limits and security headers.

## Verification

* The full automated suite passes. It covers the acceptance checks, the security checks, the browser checks and the unit tests. [COUNT: re-measure before submission: the number of tests collected and the number that passed.]

* 10 gates run in `scripts/run_all_checks.py`.

* 57 requirements map to 39 checks (AT01 to AT20, VC01 to VC08, D01 to D11). The requirements are listed in `repo/docs/REQUIREMENTS_OUTLINE.md` and the checks in `repo/config/check_inventory.json`.

* There are 17 permit types and six simulated subscriber departments. They are listed in `repo/config/rules_and_fees.json` and `repo/config/property_subscribers.json`.

## License

All rights reserved. Copyright 2026 Randall Vollen and VollenData. The repository is public for transparency, hackathon evaluation and demonstration only.

## Architecture

* A Python FastAPI service renders the public site, applicant portal, and staff interface with Jinja templates and small vanilla JavaScript enhancements.

* SQLAlchemy and Alembic manage one SQLite database that stores applications, master records, source links, decisions, rules, fees, audit records, model runs, and workflow state.

* Four simulated source adapters represent permitting, geographic information, ERP finance and the ePermit intake portal, which takes five channels (portal, counter scan, email, mail and fax) and records scan quality flags. A database outbox records governed changes and acknowledgments.

* Server held actors, scoped permissions, record scope, version checks, audit history, and explicit human actions protect every sensitive read and write.

* The Meta Muse adapter allows only named models and strict schemas, bounds each request, never retries automatically, labels live and replay results, and cannot approve, price, or issue a permit.

## How to try it

1. Open https://acme-city-permits.onrender.com. The data resets nightly once the scheduled reset is configured, and every deploy rebuilds it. [REVIEW: Randall]

2. Use Demo controls to choose a persona. All five are available.

3. As Applicant, start a fictional Residential deck or fence application, save it, submit it, and open its tracker.

4. As Agent Operator, wake the agents and run the intake agent on a waiting case, then the adjudication agent. Wake the steward assistant too.

5. As Data Steward, open Data issues, press Prepare recommendations, and inspect the evidence behind each recommendation and the proposed record and parcel links. Accept one with Accept recommendation, or open the list with Accept all high-confidence, and press Explain with Muse for a plain reading of the reason.

6. As Permit Reviewer, open a case in review, inspect the checks and recommendation, then follow the separate decision and issuance steps.

7. As City Administrator, open the "Planning overview", the "Operations dashboard", the "Audit log", "Support", "Governance and sources", "Rules and fees", "Reconciliation" and "Administration" screens, and try a policy what-if.

Prepared by Randy Vollen, host of www.VollenData.com, for the Muse Hackathon, using the fictional City of Acme.
