# ACME City Permits

ACME City Permits is a fictional municipal permitting application that follows one permit from the applicant's form to a recorded decision and an issued permit, with Meta Muse proposing and people deciding.

Live demo: https://acme-city-permits.onrender.com

Video: [link to be added]

Every person, business, parcel, permit, fee, rule and document in this application is fictional. The application issues no real permit and sends nothing to a real municipality.

## The five personas

The demo switcher offers five people, in the order one permit moves through them.

* **Applicant.** Applies for a permit on the City of Acme website, saves a draft, uploads documents, answers a request for information, tracks the case and reads the messages from the City.
* **Agent Operator.** Wakes the intake, adjudication and steward agents, runs a waiting case or a batch, reads the run history and retries a failed run. The operator records no permit decision.
* **Data Steward.** Clears the findings that block a case and keeps the master records trustworthy. The steward assistant prepares proposals with **Prepare recommendations**, and the steward accepts them with **Accept recommendation** or **Accept all high-confidence**, or presses **Explain with Muse** for a plain reading of the reason.
* **Permit Reviewer.** Checks the property and the application facts against the City rules, records the decision of record, adds conditions and issues the permit in a separate step.
* **City Administrator.** Sets the rules, fees and agent processing policy, manages the configuration, and reads the operations, reconciliation and audit screens. Configuration access never grants permit authority.

## How it uses Meta Muse

Muse is the model inside the application. It reads the text of received documents and proposes structured values, proposes record matches, writes a cited answer for the applicant help panel, explains a policy scenario, writes a policy briefing and explains a steward recommendation in plain words. Every proposal is checked against a strict schema, recorded with its source and its usage, and decided by a named person. The model never approves a permit, never sets a fee and never issues a permit.

Muse Image generates the fictional permit type icons through a governed administrator action.

The steward assistant uses the same rule. It prepares its proposals on the Data issues screen, where the steward presses **Prepare recommendations** and then **Accept recommendation** or **Accept all high-confidence**, and presses **Explain with Muse** for a plain reading of the reason.

Live Muse is on for the hosted demonstration, with a daily allowance of 100 live calls. When the allowance is used up, the app falls back to its recorded answers and says so on screen.

## What was built during the event

Only the requirements package existed before the event. It arrived on October 26, 2026, and there was no application code.

The git history starts on October 27, 2026, with a baseline commit of the overnight build of October 26. Everything below was built during the event.

* The registry, governance, rules, fees, finance and issuance foundations.
* The interface redesign, the persona navigation and the City frame.
* The intake and adjudication agents, the durable agent work queue and the Agent Operator persona.
* The ePermit intake portal with five channels and scan quality flags.
* The City of Acme public website, the town map and the community lookup.
* The applicant help assistant, and the policy what-if with its briefing and its proposal.
* The steward Data issues workspace, the steward assistant with its batch preview and its agreement figure, and automatic linking.
* The life cycle page, the walkthrough page and the persona video.
* A production mode that is separate from demo mode, with rate limits and security headers.

## How to try it

1. Open https://acme-city-permits.onrender.com.
2. Pick a persona with the demo switcher. All five are available.
3. As Applicant, start a fence or deck application, save it, submit it and open the tracker.
4. As Agent Operator, open Agents, wake the agents, run the intake agent on a waiting case and then the adjudication agent, and wake the steward assistant.
5. As Data Steward, open Data issues, press **Prepare recommendations**, read the evidence behind each proposal, and accept one with **Accept recommendation**.
6. As Permit Reviewer, open a case in review, check the facts, and follow the separate decision and issuance steps.
7. As City Administrator, open the overview, the operations screens and the audit trail, and try a what-if policy scenario.

The guided walkthrough is at https://acme-city-permits.onrender.com/walkthrough. It takes about ten minutes and every step names the persona and the screen.

The data is fictional and is meant to be disposable. It resets nightly once the scheduled reset is configured, and every deploy rebuilds it.

## How to run it locally

The application is in `repo/`. It needs Python 3.12 and [uv](https://docs.astral.sh/uv/). Run these commands from the `repo/` directory.

```bash
uv run python scripts/prepare_user_test.py --mode demo-synthetic
uv run python scripts/start_demo.py --host 127.0.0.1 --port 8266
```

Open http://127.0.0.1:8266. The server binds only to the local computer. The prepare mode loads the synthetic year of permits that the walkthrough needs. `repo/USER_TEST_GUIDE.md` lists the other prepared states and the commands that stop the server.

## Architecture

* A Python FastAPI service renders the public site, the applicant portal and the staff interface with Jinja templates and small vanilla JavaScript enhancements.
* SQLAlchemy and Alembic manage one SQLite database that holds applications, master records, source links, decisions, rules, fees, audit records, model runs and workflow state.
* Four simulated source adapters represent permitting, geographic information, ERP finance and the ePermit intake portal. A database outbox records governed changes and acknowledgments.
* Server held actors, scoped permissions, record scope, version checks and audit history protect every sensitive read and write.
* The Meta Muse adapter allows only named models and strict schemas, bounds each request, never retries by itself, labels live and recorded results, and cannot approve, price or issue a permit.

## Verification

* 17 permit types, listed in `repo/config/rules_and_fees.json`.
* 57 requirements, listed in `repo/docs/REQUIREMENTS_OUTLINE.md`.
* 39 checks, being AT01 to AT20, VC01 to VC08 and D01 to D11, listed in `repo/config/check_inventory.json`.
* 6 simulated subscriber departments, listed in `repo/config/property_subscribers.json`.
* 10 local gates, run by `repo/scripts/run_all_checks.py`.
* The automated suite covers the acceptance checks, the security checks, the browser checks and the unit tests, and the full run passes.

## License

All rights reserved. Copyright 2026 Randall Vollen and VollenData. The repository is public for transparency, hackathon evaluation and demonstration only. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

[Internal workspace map](docs/process/WORKSPACE.md)

Prepared by Randy Vollen, host of www.VollenData.com, for the Muse Hackathon, using the fictional City of Acme.
