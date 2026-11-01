# ACME City Permits

ACME City Permits is a fictional municipal permitting application. It follows one permit from the applicant's form to a recorded decision and an issued permit. Muse proposes. People decide.

Live demo: https://acme-city-permits.onrender.com
Video: [link to be added]
Repository visibility: [REVIEW: Randall. The repository is private today. Make it public before submission, then delete this line.]

Every person, business, parcel, permit, fee, rule, and document in this application is fictional. The application issues no real permit and sends nothing to a real municipality.

Prepared by Randy Vollen, host of www.VollenData.com, for the Muse Hackathon, using the fictional City of Acme.

## Track and starting point

Startup track: For teams and founders building a real product.
Judged on technical execution and whether it holds up in production.

Before the event, only the requirements package existed. It arrived on October 26, 2026. There was no application code.

The git history starts on October 27, 2026. Its first commit is a baseline of the overnight build of October 26. Everything the demo shows beyond that baseline was built during the event.

The build window is not settled. The participant guide says October 27 to November 4. The event page says October 26. [REVIEW: Randall. Confirm the window before submission.]

## Impact

A permit passes through many hands, and the facts about it sit in several systems that can disagree. The application keeps one governed record for each permit, and it shows each person the step they own.

Who it helps:

* **Applicants** apply, save a draft, upload documents, answer a request for information, track the case, and read the messages from the City.
* **Agent operators** wake the intake and adjudication agents and run them over the waiting cases.
* **Data stewards** clear the findings that block a case and keep the master records consistent.
* **Permit reviewers** check the facts against the City rules and record the decision.
* **City administrators** set the rules, fees, and processing policy, and read the operations and audit screens.

The model never decides. Every permit decision, fee, and issuance is made by a named person or a deterministic service.

## Muse

Muse is the model inside the application.

* It reads the text of received documents and proposes structured values.
* It proposes record matches for the data stewards.
* It writes a cited answer for the applicant's help chat.
* It explains a policy scenario and writes a policy briefing.
* It explains a steward recommendation in plain words.
* It generates the fictional permit type icons through a governed administrator action.

Every proposal is checked against a strict schema, recorded with its source and its usage, and decided by a named person. The model never approves a permit, never sets a fee, and never issues a permit.

Live Muse is on for the hosted demonstration, with an allowance of 100 live calls a day. When that allowance is used up, the help chat answers with the published rule text and says so on screen.

## Demo

Open https://acme-city-permits.onrender.com. The landing page lists the five personas first, with the "Watch the 3-minute tour" button under them. The personas run in the order one permit moves through them: Applicant, Agent Operator, Data Steward, Permit Reviewer, and City Administrator.

On every page with a persona signed in, the persona chip in the top right opens the "Demo controls" menu. The menu holds the five personas and the "Take the tour" button. The landing page has its own "Take the tour" button in the line of guides.

The guided walkthrough is at https://acme-city-permits.onrender.com/walkthrough. It takes about ten minutes, and every step names the persona and the screen.

What the demonstration has now:

* The help chat on the City pages. The "Ask" button opens it over the page, and each answer cites the published rule behind it.
* One contact page, "Contact the City", with the departments and a way to ask a person.
* The agents' "Incoming" list, the step graph of each run, and a "Replay run" button behind "More details" that walks a recorded run again.
* The "Sample data" tab in Administration, which creates the fictional cases the agents work on.
* Screens that stay slim. The secondary detail sits behind "More details".
* A light theme by default, and a dark mode in the "Demo controls" menu.

How to try it:

1. As Applicant, start a "Residential deck or fence" application, save it, submit it, and open the tracker.
2. As Agent Operator, open "Agents", press "Wake agent" on the intake agent, the adjudication agent, and the steward assistant, then run the intake agent on a waiting case and the adjudication agent on that case.
3. As Data Steward, open "Data issues", press "Prepare recommendations", read the evidence behind each proposal, and accept one with "Accept recommendation".
4. As Permit Reviewer, open the "Review queue", open the case, press "Run application checks", and record the decision with "Record review decision".
5. As City Administrator, open "Planning overview", "Operations dashboard", and "Audit log", and try a what-if policy scenario.

The data is fictional and is meant to be disposable. It resets nightly once the scheduled reset is configured, and every deploy rebuilds it. [REVIEW: Randall]

Automatic processing of waiting cases is built and off on the hosted demo. Automatic linking of records is built and paused on the hosted demo.

## Future feature: assistants through MCP

This is a plan. Nothing of it is built. The demonstration has no Model Context Protocol (MCP) server today.

The plan is that an assistant acts as one of the five personas, with that persona's permissions. It reads by default. A write needs the person's confirmation before it happens. Every call is audited as "Assistant via MCP". No tool decides, approves, issues, or publishes anything.

The plan is written up in [docs/operations/MCP_PLAN.md](docs/operations/MCP_PLAN.md).

## Technical depth

Production behaviour:

* A production mode is separate from the demo mode.
* Each client address has rate limits. Limits apply to all requests, writes, sessions, and uploads. Client addresses are read from the proxy header only as far as the trusted proxy allows.
* Security headers are added to every response, including a content security policy.
* The server holds the actors, and scoped permissions, record scope, and version checks protect every sensitive read and write.
* Every governed change is recorded in the audit history.
* Waiting agent work sits in a durable queue. A run records each of its nodes.
* The Muse adapter allows only named models and strict schemas, bounds each request, never retries by itself, labels live and recorded results, and cannot approve, price, or issue a permit.
* Live Muse calls have a daily cap, and icon generation has its own daily cap.

Architecture:

* A Python FastAPI service renders the public site, the applicant portal, and the staff interface with Jinja templates and small vanilla JavaScript.
* SQLAlchemy and Alembic manage one SQLite database. It holds applications, master records, source links, decisions, rules, fees, audit records, model runs, and workflow state.
* Four simulated source adapters represent permitting, geographic information, enterprise resource planning (ERP) finance, and the ePermit intake portal. A database outbox records governed changes and acknowledgments.

Checks and tests:

* 17 permit types, listed in `repo/config/rules_and_fees.json`.
* 57 requirements, listed in `repo/docs/REQUIREMENTS_OUTLINE.md`.
* 39 checks: AT01 to AT20, VC01 to VC08, and D01 to D11, listed in `repo/config/check_inventory.json`.
* 6 simulated subscriber departments, listed in `repo/config/property_subscribers.json`.
* 10 local gates, run by `repo/scripts/run_all_checks.py`.
* The automated suite collects 3,414 tests, and all of them pass. It covers the acceptance checks, the security checks, the browser checks, and the unit tests. The count comes from a full run on November 1, 2026.

## How to run it locally

The application is in `repo/`. It needs Python 3.12 and [uv](https://docs.astral.sh/uv/). Run these commands from the `repo/` directory.

```bash
uv run python scripts/prepare_user_test.py --mode demo-synthetic
uv run python scripts/start_demo.py --host 127.0.0.1 --port 8266
```

Open http://127.0.0.1:8266. The server binds only to the local computer. The prepare mode loads the synthetic year of permits that the walkthrough needs. `repo/USER_TEST_GUIDE.md` lists the other prepared states and the commands that stop the server.

## License

All rights reserved. Copyright 2026 Randall Vollen and VollenData. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

The workspace map for the build team is in `docs/process/WORKSPACE.md`.
