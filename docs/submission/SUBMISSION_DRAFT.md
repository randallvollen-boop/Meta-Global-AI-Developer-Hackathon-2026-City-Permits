# ACME City Permits

## Draft status

This is submission text for Randall to review and submit himself. It has not been submitted. The hosted demo at https://acme-city-permits.onrender.com shows all five personas.

## Track

Startup track: For teams and founders building a real product.
Judged on technical execution and whether it holds up in production.

The entry is framed around production behaviour: rate limits, caps, audit history, nightly resets, tests, and checks. Only features built during the event are shown as judged work.

## Entry requirements

* Public repository: https://github.com/randallvollen-boop/Meta-Global-AI-Developer-Hackathon-2026-City-Permits [REVIEW: Randall. The repository is private today. Make it public before submission, and confirm this link.]
* Accessible three-minute demo video: [link to be added]
* Live product: https://acme-city-permits.onrender.com

## Summary

ACME City Permits is a fictional municipal permitting application. It follows a permit from intake through identity and property review, application checks, a human decision, fee reconciliation, and permit issuance. It combines registry master data, versioned rules, role based actions, audit history, and bounded Muse proposals. Every authoritative decision stays with a person or a deterministic service.

## What it does

### Applicant

An applicant can choose from seventeen fictional permit types, locate a property, save a draft, submit an application, replace documents, answer a request for information, track progress, read messages from the City, and download a submission or issued permit. "Check my application" runs the reviewer's rules on the draft before it is sent. Muse explains the result in plain words when live. "Must fix" holds "Submit application" unless the applicant presses "Submit anyway" with a reason, and the reviewer then sees "Submitted with known issues". The help chat on the page answers from the published ACME rules and the applicant's own case. It cites its sources and says when it cannot answer.

### Agent operator

The Agent Operator wakes and runs the intake and adjudication agents, and wakes the steward assistant. The operator opens the "Agents" home, wakes an agent with "Wake agent", puts it back to sleep with "Put agent to sleep", runs one case with "Process one" or a batch with "Process the next 20 cases", opens "Agent runs" to read a run, and retries a failed run with "Try again". The intake agent is a seven node graph and the adjudication agent is a five node graph, and each run records its nodes. The agents prepare a case and leave a recommendation. They never decide, price, or issue a permit. Waiting work sits in a durable queue, and the City Administrator sets the processing policy under "Administration", "Agent processing". Automatic processing of waiting cases is built and off on the hosted demo. The City Administrator can also grant the right to wake and run agents to permit reviewers and intake clerks from "Administration", "Users and roles".

### Data steward

A data steward works the "Data issues" workspace, which has a guide, and the "Early resolution" screen. The steward reviews possible duplicate records, approves identity and parcel links, and accepts or corrects values proposed from documents. The steward can also inspect "Master records", "Source records", and the change activity on the "Activity" screen. These actions do not approve a permit.

Once the Agent Operator wakes it, the steward assistant works the "Data issues" queue when the steward asks, up to 20 tasks per press of "Prepare recommendations". For each task it gathers the evidence and proposes a decision with a High, Review, or Held level and a one line reason. The steward reads the evidence and presses "Accept recommendation", which is refused if the record changed since, or decides the task another way. A held recommendation can never be accepted. "Accept all high-confidence" shows the exact list before anything is accepted, and skips and names any item that changed. An agreement figure shows how many recommendations the steward accepted unchanged in the last 7 days. "Explain with Muse" rewrites the reason in plain words without changing the decision.

### Permit reviewer

A permit reviewer works the "Review queue", checks the property and application facts, and reads the recommendation the adjudication agent leaves after it runs the City rule checks. The reviewer records the decision of record with "Record review decision", chooses "Approve", "Approve with conditions", or "Deny", writes the "Rationale (internal record)", and presses "Record the decision". When the applicant presses "Submit anyway", the reviewer sees "Submitted with known issues". The reviewer can add conditions, request revisions, and issue a permit only after the required links, decision, fee assessment, payment allocation, and reconciliation are complete.

### City administrator

A city administrator opens the "Planning overview", then "Rules and fees", "Reconciliation", "Governance and sources", and "Administration". The other screens sit under "More tools", among them the "Operations dashboard", the "Audit log", "Support", "Checks", the "City view", and the "What-if". The Administration screen carries the tabs "Permit types", "Appearance", "Users and roles", "Agent processing", "Reason codes", "Configuration log", and "Sample data". The administrator can simulate incoming applications, set the agent processing policy, manage fictional configuration, run the checks on the "Checks" screen, and create governed policy drafts. The administrator's configuration grants leave the permit decision with the Permit Reviewer.

## How it uses Muse

Muse is the model inside the application. Muse proposes. People decide.

Muse can propose structured values from received document text and can produce bounded record match proposals. The application validates the response against a strict schema and records its source, usage, latency, and validation result. A data steward decides whether a proposed value or link becomes part of the governed record.

The applicant help and City policy paths also have bounded Muse support. Muse can draft a cited answer, explain a policy simulation, write a briefing from typed facts, or propose a policy change. When the applicant presses "Check my application", Muse explains the result in plain words when live. The server checks sources, claims, figures, rule citations, and allowed change types. A failed answer is refused. A policy proposal is not saved until an authorized person chooses to save it, and it still follows the normal draft and approval process. The administrator writes the briefing with "Write the briefing with Muse".

The steward assistant follows the same rule. It prepares its proposals on the "Data issues" screen, where the steward presses "Prepare recommendations" and then "Accept recommendation" or "Accept all high-confidence", and "Explain with Muse" rewrites a reason in plain words without changing the decision.

Muse also generates the fictional permit type icons through a governed administrator action with daily limits and recorded provenance.

Live Muse is on for the hosted demo, with an allowance of 100 live calls a day. When that allowance is used up, the help chat answers with the published rule text and says so on screen.

## Future feature: assistants through MCP

This is a plan. Nothing of it is built. The demonstration has no Model Context Protocol (MCP) server today.

The plan is that an assistant acts as one of the five personas, with that persona's permissions. It reads by default. A write needs the person's confirmation before it happens. Every call is audited as "Assistant via MCP". No tool decides, approves, issues, or publishes anything.

The plan is written up in [docs/operations/MCP_PLAN.md](../../docs/operations/MCP_PLAN.md).

## Production behaviour

* A production mode that is separate from demo mode.
* Per client address rate limits on all requests, writes, sessions, and uploads, with a bounded request size.
* Security headers on every response, including a content security policy.
* The server holds the actors, and scoped permissions, record scope, version checks, audit history, and explicit human actions protect every sensitive read and write.
* Waiting agent work sits in a durable queue. Automatic processing of waiting cases is off on the hosted demo.
* The Muse adapter allows only named models and strict schemas, bounds each request, never retries automatically, labels live and replay results, and cannot approve, price, or issue a permit.
* Live Muse calls have a daily cap, and icon generation has its own daily cap.
* Every governed change is recorded in the audit history.
* The hosted data is fictional. It resets nightly once the scheduled reset is configured, and every deploy rebuilds it. [REVIEW: Randall]
* Automatic linking of records is built and paused on the hosted demo.
* The walkthrough has four paths, and each path has a guided tour and "Auto-play". "Start fresh" gives each judge a fresh copy of the café case.
* "Check my application" runs the reviewer's rules on the draft before it is sent. "Must fix" holds "Submit application" unless the applicant presses "Submit anyway" with a reason, and the reviewer then sees "Submitted with known issues".

## Architecture

* A Python FastAPI service renders the public site, applicant portal, and staff interface with Jinja templates and small vanilla JavaScript enhancements.
* SQLAlchemy and Alembic manage one SQLite database that stores applications, master records, source links, decisions, rules, fees, audit records, model runs, and workflow state.
* Four simulated source adapters represent permitting, geographic information, enterprise resource planning (ERP) finance, and the ePermit intake portal, which takes five channels (portal, counter scan, email, mail, and fax) and records scan quality flags. A database outbox records governed changes and acknowledgments.
* The Muse adapter allows only named models and strict schemas, bounds each request, never retries automatically, labels live and replay results, and cannot approve, price, or issue a permit.

## What was built during the event

Before the event only the reference requirements package existed (received 2026-10-26). There was no application code.

The git history starts on October 27 with a baseline commit of the overnight build of October 26. Work after that baseline includes:

* Parity phases 1 to 3 and the interface redesign.
* A policy what-if tool. Runs are immutable and hash verified, and a Muse briefing and proposal pass claim checks before anyone sees them.
* The applicant help chat.
* The City of Acme public website, with a community lookup that shows no homeowner names, documents, or fees, a town map, and the "City view".
* ePermit intake with five channels and scan quality flags.
* The intake and adjudication agents, a durable agent work queue, and automatic processing of waiting cases, which is off on the hosted demo.
* The steward "Data issues" workspace and guide, the steward assistant with its batch preview and agreement figure, and automatic linking, which is built and paused on the hosted demo.
* The lifecycle page, the walkthrough with four paths (each with a guided tour and "Auto-play"), and the demo video under the persona cards on the landing page.
* "Check my application" on the applicant form, with the "Must fix" hold and "Submit anyway".
* A production mode that is separate from demo mode, rate limits, and security headers.

The build window is not settled. The participant guide says October 27 to November 4. The event page says October 26. [REVIEW: Randall. Confirm the window before submission.]

## Verification

* The full automated suite collects 3,414 tests, and all of them pass. It covers the acceptance checks, the security checks, the browser checks, and the unit tests. The count comes from a full run on November 1, 2026.

* 10 gates run in `scripts/run_all_checks.py`.

* 57 requirements map to 39 checks (AT01 to AT20, VC01 to VC08, and D01 to D11). The requirements are listed in `repo/docs/REQUIREMENTS_OUTLINE.md` and the checks in `repo/config/check_inventory.json`.

* There are 17 permit types and six simulated subscriber departments. They are listed in `repo/config/rules_and_fees.json` and `repo/config/property_subscribers.json`.

## License

All rights reserved. Copyright 2026 Randall Vollen and VollenData. The repository will be public at submission, for evaluation and demonstration only. [REVIEW: Randall. Confirm the repository licence wording before submission.] See [LICENSE](../../LICENSE) and [NOTICE](../../NOTICE).

## What the demonstration shows now

* The landing page lists the five personas first, with the "Watch the 3-minute tour" button under them.
* The persona chip in the top right opens the "Demo controls" menu, which holds the five personas and the "Take the tour" button.
* The help chat on the City pages, opened by the "Ask" button, and one contact page, "Contact the City".
* The agents' "Incoming" list, the step graph of each run, and a "Replay run" button behind "More details".
* The "Sample data" tab in Administration, which creates the fictional cases the agents work on.
* Screens that stay slim, with the secondary detail behind "More details", and a light theme by default.
* The walkthrough has four paths, each with a guided tour and "Auto-play": "Apply as a resident", "Get the café open", "Run the city", and "Before you start". "Start fresh" gives each judge a fresh copy of the café case.
* "Check my application" on the applicant form. Muse explains the result in plain words when live. "Must fix" holds "Submit application" unless the applicant presses "Submit anyway" with a reason, and the reviewer then sees "Submitted with known issues".

## How to try it

1. Open https://acme-city-permits.onrender.com. The landing page lists the five personas first, with the "Watch the 3-minute tour" button under them. The data resets nightly once the scheduled reset is configured, and every deploy rebuilds it. [REVIEW: Randall]

2. On every page with a persona signed in, the persona chip in the top right opens the "Demo controls" menu. The menu holds the five personas and the "Take the tour" button. All five are available.

3. Open the walkthrough. On "Apply as a resident", press "Check my application". Muse explains the result in plain words when live. "Must fix" holds "Submit application" unless the applicant presses "Submit anyway" with a reason, and the reviewer then sees "Submitted with known issues".

4. Press "Start fresh" on "Get the café open", then start that path or press "Auto-play" on its guided tour. The Data Steward links the café owner's three records, the agent routes the case, the Permit Reviewer approves, the City Administrator matches the fee paid from the old account and reconciles, the reviewer issues, and the permit appears on the public record.

5. As Data Steward, open "Data issues", press "Prepare recommendations", and press "Accept recommendation" on each task that carries a "High" pill.

6. As Agent Operator, press "Wake agent", then press "Process one" beside the case of the café.

7. As Permit Reviewer, open the case from the "Review queue", press "Start" under "Confirm parcel" on the "People and organizations" tab, press "Start" under "Run application checks", then press "Start" under "Record review decision" and choose "Approve".

8. As City Administrator, open "Reconciliation", press "Start" under "Assess application", allocate the 150.00 receipt from the old finance account, and reconcile.

9. As Permit Reviewer, press "Start" under "Issue permit". Search for the permit number on the City of Acme website.

Prepared by Randy Vollen, host of www.VollenData.com, for the Muse Hackathon, using the fictional City of Acme.
