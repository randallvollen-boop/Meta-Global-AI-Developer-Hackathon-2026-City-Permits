# ACME City Permits

ACME City Permits is a fictional municipal permitting application. It follows one permit from the applicant's form to a recorded decision and an issued permit. Meta Muse proposes. People decide.

Live demo: https://acme-city-permits.onrender.com
Video: [link to be added]
Repository visibility: [REVIEW: Randall. The repository is private today. Make it public before submission, then delete this line.]

Every person, business, parcel, permit, fee, rule and document in this application is fictional. The application issues no real permit and sends nothing to a real municipality.

Prepared by Randy Vollen, host of www.VollenData.com, for the Muse Hackathon, using the fictional City of Acme.

## Track and starting point

Startup track: For teams and founders building a real product.
Judged on technical execution and whether it holds up in production.

Before the event, only the requirements package existed. It arrived on October 26, 2026. There was no application code.

The git history starts on October 27, 2026. Its first commit is a baseline of the overnight build of October 26. Everything the demo shows beyond that baseline was built during the event.

The build window is not settled. The participant guide says October 27 to November 4. The event page says October 26. [REVIEW: Randall. Confirm the window before submission.]

## Impact

The problem: a permit passes through many hands, and the facts about it sit in several systems that can disagree. The application keeps one governed record for each permit. It shows each person the step they own.

Who it helps:

* **Applicants** apply, save a draft, upload documents, answer a request for information, track the case and read the messages from the City.
* **Data stewards** clear the findings that block a case and keep the master records consistent.
* **Permit reviewers** check the facts against the City rules and record the decision.
* **City administrators** set the rules, fees and processing policy, and read the operations and audit screens.

The model never decides. Every permit decision, fee and issuance is made by a named person or a deterministic service.

## Meta tooling

Muse is the model inside the application. It is the only Meta model named here.

* It reads the text of received documents and proposes structured values.
* It proposes record matches for the data stewards.
* It writes a cited answer for the applicant help panel.
* It explains a policy scenario and writes a policy briefing.
* It explains a steward recommendation in plain words.
* Muse Image generates the fictional permit type icons through a governed administrator action.

Every proposal is checked against a strict schema, recorded with its source and its usage, and decided by a named person. The model never approves a permit, never sets a fee and never issues a permit.

Live Muse is on for the hosted demonstration, with a daily allowance of 100 live calls. When the allowance is used up, the app falls back to its recorded answers and says so on screen. [REVIEW: Randall]

## Demo

Open https://acme-city-permits.onrender.com and pick a persona with the demo switcher. All five are available. The personas run in the order one permit moves through them: Applicant, Agent Operator, Data Steward, Permit Reviewer and City Administrator.

The guided walkthrough is at https://acme-city-permits.onrender.com/walkthrough. It takes about ten minutes, and every step names the persona and the screen.

How to try it:

1. As Applicant, start a fence or deck application, save it, submit it and open the tracker.
2. As Agent Operator, open Agents, wake the agents, run the intake agent on a waiting case and then the adjudication agent, and wake the steward assistant.
3. As Data Steward, open Data issues, press **Prepare recommendations**, read the evidence behind each proposal, and accept one with **Accept recommendation**.
4. As Permit Reviewer, open a case in review, check the facts, and follow the separate decision and issuance steps.
5. As City Administrator, open the overview, the operations screens and the audit trail, and try a what-if policy scenario.

The data is fictional and is meant to be disposable. It resets nightly once the scheduled reset is configured, and every deploy rebuilds it. [REVIEW: Randall]

Optional automatic processing of waiting cases exists. It is off on the hosted demo. Automatic linking of records is built and paused on the hosted demo.

## Technical depth

Production behaviour:

* A production mode is separate from the demo mode.
* Each client address has rate limits. Limits apply to all requests, writes, sessions and uploads. Client addresses are read from the proxy header only as far as the trusted proxy allows.
* Security headers are added to every response, including a content security policy.
* Server-held actors, scoped permissions, record scope and version checks protect every sensitive read and write.
* Every governed change is recorded in the audit history.
* Waiting agent work sits in a durable queue. A run records each of its nodes.
* The Muse adapter allows only named models and strict schemas, bounds each request, never retries by itself, labels live and recorded results, and cannot approve, price or issue a permit.
* Live Muse calls and Muse Image generation have daily caps.

Architecture:

* A Python FastAPI service renders the public site, the applicant portal and the staff interface with Jinja templates and small vanilla JavaScript.
* SQLAlchemy and Alembic manage one SQLite database. It holds applications, master records, source links, decisions, rules, fees, audit records, model runs and workflow state.
* Four simulated source adapters represent permitting, geographic information, ERP finance and the ePermit intake portal. A database outbox records governed changes and acknowledgments.

Checks and tests:

* 17 permit types, listed in `repo/config/rules_and_fees.json`.
* 57 requirements, listed in `repo/docs/REQUIREMENTS_OUTLINE.md`.
* 39 checks: AT01 to AT20, VC01 to VC08 and D01 to D11, listed in `repo/config/check_inventory.json`.
* 6 simulated subscriber departments, listed in `repo/config/property_subscribers.json`.
* 10 local gates, run by `repo/scripts/run_all_checks.py`.
* The automated suite covers the acceptance checks, the security checks, the browser checks and the unit tests. [COUNT: re-measure before submission: the number of tests collected and the number that passed.]

## How to run it locally

The application is in `repo/`. It needs Python 3.12 and [uv](https://docs.astral.sh/uv/). Run these commands from the `repo/` directory.

```bash
uv run python scripts/prepare_user_test.py --mode demo-synthetic
uv run python scripts/start_demo.py --host 127.0.0.1 --port 8266
```

Open http://127.0.0.1:8266. The server binds only to the local computer. The prepare mode loads the synthetic year of permits that the walkthrough needs. `repo/USER_TEST_GUIDE.md` lists the other prepared states and the commands that stop the server.

## License

All rights reserved. Copyright 2026 Randall Vollen and VollenData. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

[Internal workspace map](docs/process/WORKSPACE.md)
