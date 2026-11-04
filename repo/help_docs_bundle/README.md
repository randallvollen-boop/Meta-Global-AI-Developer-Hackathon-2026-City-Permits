# ACME City Permits

ACME City Permits is a fictional municipal permitting application. It follows one permit from the applicant's form to a recorded decision and an issued permit. Muse proposes. People decide.

Live demo: https://acme-city-permits.onrender.com
Video: the three-minute tour video is on YouTube at https://www.youtube.com/watch?v=NelkRrahaXw and on the landing page of the live demo, under the persona cards.

Every person, business, parcel, permit, fee, rule, and document in this application is fictional. The application issues no real permit and sends nothing to a real municipality.

Prepared by Randy Vollen, host of www.VollenData.com, for the Muse Hackathon, using the fictional City of Acme.

## Submission overview

* Track: Indie Developer · Build for Your World.
* Built during the event: before any code was written for `repo/`, Randall used an AI chat in the browser to write a requirements package and a click-through prototype of the screens. No code from either runs here. Every line of code under `repo/` was written between the overnight baseline of October 26 and November 3. See "Track and starting point".
* Meta AI at runtime: Muse on the Meta Model API, through `muse-spark-1.3` for document reading, record matching, the help chat, the policy briefing and explanations, and `muse-image-1.0` for the permit type icons. At build time, `muse-wonder-1.0` reviewed the prototype and built the user interface redesign, the permit-type icon feature, the ePermit intake channels and the agent triage. See "Muse" for where each model runs and what it does.
* Bonus prize targeted: Best Agentic Use-Case. The intake and adjudication agents run multi-step over the waiting cases, each run keeps its step graph and can be replayed, and a named person makes every decision.
* Video: https://www.youtube.com/watch?v=NelkRrahaXw
* Try it: https://acme-city-permits.onrender.com, with no API key needed. When live Muse is off, the demo shows recorded answers and labels them.

## Track and starting point

Indie Developer track.

What existed before any code was written for `repo/`:

* The requirements package: 57 requirements, the synthetic ACME City data and documents, and the acceptance arithmetic, dated October 26, 2026. Randall wrote it with an AI chat in the browser, before the build started. The package also contains a small folder of generated Python scripts and static pages, `reference/acme-city/` (a synthetic data generator, deterministic fence rules, a findings dashboard, a self-test), which served as reference material only. That folder is not bundled here, no file of it was copied into `repo/`, and nothing in it implements the registry, the stewardship, the agents, the Muse integration or the server-enforced permissions that this application has.
* A click-through prototype of the screens, written the same way: one JSX file of about 3,100 lines with fourteen screens and no back end. It was a design reference only. Muse Wonder reviewed it against the built application, and its application form and its idea of agents that a person wakes and runs were rebuilt in this codebase. None of its code is in this repository.

Everything under `repo/` was written during the event: the whole application. The git history starts on October 27, 2026, and its first commit is a baseline of the overnight build of October 26, the first night of the event. The work recorded in `BUILD_LOG.md` runs from October 26 to November 3, 2026.

Pre-existing code that the application depends on, all as named open-source packages and none of it written for this project: FastAPI, Starlette and uvicorn (the web service), SQLAlchemy and Alembic (the database and migrations), Jinja2 (templates), Pydantic (schemas), httpx (the Meta Model API client) and python-multipart (uploads). The tests use pytest and Playwright. The version constraints are declared in `repo/pyproject.toml` and the resolved versions are locked in `repo/uv.lock`.

The participant guide says the build window runs October 27 to November 4. The event page says October 26.

## Impact

A permit passes through many hands, and the facts about it sit in several systems that can disagree. The application keeps one governed record for each permit, and it shows each person the step they own.

Who it helps:

* **Applicants** apply, save a draft, press "Check my application", upload documents, answer a request for information, track the case, and read the messages from the City.
* **Agent operators** wake the intake and adjudication agents and run them over the waiting cases.
* **Data stewards** settle identity and property records and keep the master records consistent. Their work is Data follow-up: it never holds a case and it never refuses a decision. Missing applicant information still goes back to the applicant, and the payer link and the fee still block issuing.
* **Permit reviewers** check the facts against the City rules and record the decision.
* **City administrators** set the rules, fees, and processing policy, and read the operations and audit screens.

The model never decides. Every permit decision, fee, and issuance is made by a named person or a deterministic service.

## Muse

Muse is the model inside the application.

Which Meta models the project uses, where each one runs, and what each one does:

| Model | Where it runs | When | What it does in the project |
|---|---|---|---|
| `muse-spark-1.3` | Meta Model API (`api.meta.ai`), Standard mode, called from the server | At runtime | Reads received documents and proposes structured values; proposes record matches; writes the cited answer in the applicant help chat; explains a steward recommendation; explains the "Check my application" result; explains a policy scenario and drafts the council briefing |
| `muse-image-1.0` | Meta Model API, called from the server | At runtime, and once at build time | Generates the fictional permit type icons through an Administrator action with a daily cap; without a key that action is unavailable. Three icons came with the redesign build. The 14 seed icons in `repo/src/acme_city/static/permit-type-icons/` were generated with the same model on October 28, 2026 in a separate batch outside the in-app flow (14 calls); their prompts and hash prefixes are in `docs/operations/permit-type-icons-manifest.json` and their full SHA-256 hashes in `repo/config/publishable_binaries.json` |
| `muse-wonder-1.0` | Meta Model API, Standard mode, driven through a coding harness on the developer's machine | At build time only | Reviewed the prototype against the built application, then built the user interface redesign, the permit-type icon feature, the ePermit intake channels and the agent triage. It is never called by the running application |

No Meta model runs on Baseten or on the project's own compute. The text client sends only models on the allowlist (`ACME_MUSE_MODEL_ALLOWLIST`, by default `muse-spark-1.3` alone), the image client is fixed to `muse-image-1.0`, and no configuration can select a `-contributor` model. Other parts of the application were built with local and other frontier models; `docs/build-story/ENGINES.md` records which engine produced which part.

* It reads the text of received documents and proposes structured values.
* It proposes record matches for the data stewards.
* It writes a cited answer for the applicant's help chat.
* It explains a policy scenario and writes a policy briefing.
* It explains a steward recommendation in plain words.
* It explains the "Check my application" result in plain words when live. That button carries a Muse badge and may ask Muse for feedback. "Submit application" makes no Muse call at all.
* It generates the fictional permit type icons through a governed administrator action.

Every proposal is checked against a strict schema, recorded with its source and its usage, and decided by a named person. The model never approves a permit, never sets a fee, and never issues a permit.

Live Muse is on for the hosted demonstration. The allowance is a setting of that deployment: `render.yaml` gives the service 100 live calls per deploy and 100 provider calls a day, and Randall can change either number in the Render dashboard. When the allowance is used up, the help chat answers with the published rule text and says so on screen.

## Demo

Open https://acme-city-permits.onrender.com. The landing page lists the five personas first, with the "Watch the 3-minute tour" button under them. The personas run in the order one permit moves through them: Applicant, Agent Operator, Data Steward, Permit Reviewer, and City Administrator.

On every page with a persona signed in, the persona chip in the top right opens the "Demo controls" menu. The menu holds the five personas and the "Take the tour" button. The landing page has its own "Take the tour" button in the line of guides.

The walkthrough is at https://acme-city-permits.onrender.com/walkthrough. It has four paths, and each path has a guided tour and "Auto-play". The paths are "Apply as a resident", "Get the café open", "Run the city", and "Before you start". "Get the café open" is the main journey: the Data Steward links the café owner's three records, the agent routes the case, the Permit Reviewer approves, the City Administrator matches the fee paid from the old account and reconciles, the reviewer issues, and the permit appears on the public record. "Start fresh" gives each judge a fresh copy of the café case, so other visitors’ changes don’t get in the way. The resident track makes its own application, so it needs no copy. The city track does not change any case, so it needs no copy.

What the demonstration has now:

* The help chat on the City pages. The "Ask" button opens it over the page, and each answer cites the published rule behind it.
* One contact page, "Contact the City", with the departments and a way to ask a person.
* The agents' "Incoming" list, the step graph of each run, and a "Replay run" button behind "More details" that walks a recorded run again.
* The "Sample data" tab in Administration, which creates the fictional cases the agents work on.
* The guided tour of "Apply as a resident" fills the resident's form, so "Check my application" runs against a finished application.
* A recovery page for a judge's copy of the café case that a deploy removed. It says the copy is gone and offers a fresh one.
* The real clock. No scenario clock is set on the hosted demo, so the current date on screen is today's date.
* Screens that stay slim. The secondary detail sits behind "More details".
* A light theme by default, and a dark mode in the "Demo controls" menu.

How to try it:

1. Open the walkthrough. On "Apply as a resident", press "Check my application". That runs the reviewer's rules on the draft before it is sent. The button carries a Muse badge, and Muse explains the result in plain words when it is live. "Must fix" holds "Submit application" unless the applicant presses "Submit anyway" with a reason, and the reviewer then sees "Submitted with known issues". "Submit application" itself makes no Muse call.
2. Press "Start fresh" on "Get the café open", then start that path or press "Auto-play" on its guided tour.
3. As Data Steward, open "Data issues", press "Prepare recommendations", and press "Accept recommendation" on each task that carries a "High" pill.
4. As Agent Operator, press "Wake agent", then press "Process one" beside the case of the café.
5. As Permit Reviewer, open the case from the "Review queue", press "Start" under "Confirm parcel" on the "People and organizations" tab, press "Start" under "Run application checks", then press "Start" under "Record review decision" and choose "Approve".
6. As City Administrator, open "Reconciliation", press "Start" under "Assess application", allocate the 150.00 receipt from the old finance account, and reconcile.
7. As Permit Reviewer, press "Start" under "Issue permit". Search for the permit number on the City of Acme website.

The data is fictional and is meant to be disposable. Every deploy rebuilds the demonstration data.

Automatic processing of waiting cases is built and off on the hosted demo. Automatic linking of records is built and paused on the hosted demo.

## Future feature: assistants through MCP

This is a plan. Nothing of it is built. The demonstration has no Model Context Protocol (MCP) server today.

The plan is that an assistant acts as one of the five personas, with that persona's permissions. It reads by default. A write needs the person's confirmation before it happens. Every call is audited as "Assistant via MCP". No tool decides, approves, issues, or publishes anything.

The plan is written up in [docs/operations/MCP_PLAN.md](docs/operations/MCP_PLAN.md).

## Future feature: applicant email

Real email delivery of applicant notices. The demonstration records each notice and shows it to the applicant, and sends no email.

## Technical depth

Production behaviour:

* A production mode is separate from the demo mode.
* Each client address has rate limits. Limits apply to all requests, writes, sessions, and uploads. Client addresses are read from the proxy header only as far as the trusted proxy allows.
* Security headers are added to every response, including a content security policy.
* The server holds the actors, and scoped permissions, record scope, and version checks protect every sensitive read and write.
* Every governed change is recorded in the audit history.
* Waiting agent work sits in a durable queue. A run records each of its nodes.
* The Muse adapter allows only named models and strict schemas, bounds each request, never retries by itself, labels live and recorded results, and cannot approve, price, or issue a permit.
* Live Muse calls are capped in total between deploys. The provider calls and the icon generation each have their own daily cap.
* The walkthrough has four paths, and each path has a guided tour and "Auto-play". "Start fresh" gives each judge a fresh copy of the café case, so other visitors’ changes don’t get in the way. The resident track makes its own application, so it needs no copy. The city track does not change any case, so it needs no copy.
* "Check my application" runs the reviewer's rules on the draft before it is sent. It carries a Muse badge and may ask Muse for feedback when live. "Must fix" holds "Submit application" unless the applicant presses "Submit anyway" with a reason, and the reviewer then sees "Submitted with known issues". "Submit application" makes no Muse call.

Architecture:

* A Python FastAPI service renders the public site, the applicant portal, and the staff interface with Jinja templates and small vanilla JavaScript.
* SQLAlchemy and Alembic manage one SQLite database. It holds applications, master records, source links, decisions, rules, fees, audit records, model runs, and workflow state.
* Four simulated source adapters represent permitting, geographic information, enterprise resource planning (ERP) finance, and the ePermit intake portal. A database outbox records governed changes and acknowledgments.

Checks and tests:

* 17 permit types, listed in `repo/config/rules_and_fees.json`.
* 57 requirements, listed in `repo/docs/REQUIREMENTS_OUTLINE.md`.
* 39 checks: AT01 to AT20, VC01 to VC08, and D01 to D11, listed in `repo/config/check_inventory.json`.
* 6 simulated subscriber departments, listed in `repo/config/property_subscribers.json`.
* 85 permissions, listed in `repo/config/permissions.json`.
* 10 local gates, run by `repo/scripts/run_all_checks.py`.
* The automated suite collects 3,842 tests. The full run of November 3, 2026 passed 3,840 of them and skipped 2, the two WebKit browser tests, because that browser is not installed on the machine. It covers the acceptance checks, the security checks, the browser checks, and the unit tests.

## How to run it locally

The application is in `repo/`. It needs Linux (or Windows Subsystem for Linux; the launcher tracks the server through `/proc`), Python 3.12 and [uv](https://docs.astral.sh/uv/). Run these commands from the `repo/` directory.

```bash
uv run python scripts/prepare_user_test.py --mode demo-synthetic
uv run python scripts/start_demo.py --host 127.0.0.1 --port 8266
```

Open http://127.0.0.1:8266. The server binds only to the local computer. The prepare mode loads the synthetic year of permits that the walkthrough needs. `repo/USER_TEST_GUIDE.md` lists the other prepared states and the commands that stop the server.

No account is needed for this. Without a Meta API key the application runs with live Muse off: the intake agent reads documents with its built-in deterministic extraction, record matching and the policy briefing answer from the demonstration fixtures in `repo/fixtures/replay/`, the help chat answers from its fixtures and labels each answer "Recorded demo answer", and each such model run is stored with the mode "replay"; "Check my application" falls back to the deterministic rules with no Muse explanation; icon generation is unavailable.

### Using a Meta API key (optional)

Live Muse needs a key for the Meta Model API. The application reads `META_API_KEY` from the environment, or from a key file outside the repository (`~/.config/ai-keys.env` by default, or the file named by `ACME_KEY_FILE`). It reads only `META_API_KEY` and `ACME_SECRET_KEY` from that file; every other setting comes from the environment.

1. Copy `repo/.env.example` to a file outside the repository and fill in `META_API_KEY`. Never commit the key: `.env` is ignored by Git at the root and under `repo/`, and `repo/scripts/scan_publishable_tree.py` fails on secret-shaped values anywhere under `repo/`.
2. Stop the server from the quick start, turn the live features on and start it again:

```bash
uv run python scripts/stop_demo.py
export ACME_KEY_FILE=~/.config/ai-keys.env
export ACME_APPLICANT_ASSIST_LIVE_ENABLED=1 ACME_POLICY_ASSIST_LIVE_ENABLED=1 ACME_PRESUBMIT_REVIEW_LIVE_ENABLED=1
uv run python scripts/start_demo.py --host 127.0.0.1 --port 8266
```

Locally, in demo mode, the provider is enabled as soon as a key is present (`ACME_MUSE_PROVIDER_ENABLED=0` turns it off; in production mode it is off unless set to 1). `ACME_MUSE_LIVE_CALLS_ALLOWED` is the extra lock of the hosted public demo and has no effect locally. The three per-feature switches above are off by default. Each live result then carries the "live" label and its model run record keeps the model name and the validated output. `ACME_MUSE_LIVE_CALL_CAP` (default 2, counted over the live runs stored in the database, not per process), `ACME_MUSE_DAILY_CALL_CAP` (default 10) and `ACME_MUSE_IMAGE_DAILY_CAP` (default 10) bound the spend; `repo/.env.example` lists the settings with their defaults. The hosted demonstration holds its key as a Render secret (`render.yaml`, `sync: false`).

## Third-party and non-Meta components

Everything that is not Muse, labelled:

* Server and tests: the open-source Python packages named under "Track and starting point", plus pytest and Playwright with its Chromium, Firefox and WebKit builds for the browser tests. No front-end framework; the pages are Jinja templates with vanilla JavaScript and CSS written for this project, no external scripts, no web fonts (system font stacks only) and no outside map tiles.
* Database and hosting: SQLite, and the public demo runs on Render.
* Text to speech: the 26 voice clips of the guided tour in `repo/src/acme_city/static/tour-audio/` and the narration of the demo video were made with Kokoro, an open-source text-to-speech model run locally. No Meta model produced speech.
* Images that are not Muse Image: the 17 town map tiles in `repo/src/acme_city/static/map-tiles/` and the 5 persona icons in `repo/src/acme_city/static/persona-icons/` were rendered at build time with a locally hosted image model that is not a Meta model. Every permit-type icon is Muse Image.
* Demo video: the screen recordings are the real application. The animated presenter was made with a video model that is not a Meta model; its narration is Kokoro.
* Data: every person, business, parcel, permit, fee, rule and document is fictional and was written for this project. No public dataset is used. The workflow was modelled on dated public municipal permitting pages, cited in `CITY_PERMIT_ALIGNMENT.md`, without their branding, fees or codes.

`repo/config/publishable_binaries.json` is the allowlist of the application's binary assets (icons, tiles, audio, video) with the source of each set and the hash of each image; the build-story screenshots under `docs/` are outside it.

## Recorded runs and evidence

For the steps a judge cannot rerun without a key, the record is in the repository:

* `repo/fixtures/replay/`: 19 fixtures, used whenever live Muse is off. None is a recording of a Muse call. Two, a document extraction and a record match proposal, are written in the shape of a live Muse Spark run so that the replay path exercises the same schema checks; their `source_run_id` and `source_response_id` are fictional placeholders and say so. One is a malformed output that the schema check rejects. The other 16, the 11 applicant help answers and the 5 policy scenarios (one briefing fails validation on purpose), are deterministic demonstration fixtures written for the demo against the published rule text they quote; each one says so in its `note`. Every model run is stored with its mode, "live" or "replay", and a replay never counts as live evidence. The real Muse response ids are in `EVIDENCE_LOG.md`.
* Model runs: every Muse Spark call, live or replay, is stored as a model run with its mode, its model, its status and its validated output; the "Check my application" runs store the hashes of their inputs; icon generations are audit records with the model and the estimated cost. The agents' "Replay run" button walks a recorded run again, step by step.
* `docs/operations/permit-type-icons-manifest.json`: the prompts and hash prefixes of the 14 seed icons generated with Muse Image; the icons themselves are the output.
* `EVIDENCE_LOG.md`: the dated record of live calls, test runs and gate results, including the Meta response ids of the live extraction runs. The run directories it names under `repo/evidence/runs/` are local and are not published. `BUILD_LOG.md` is the dated record of what was built when, and `docs/build-story/` holds the screenshots of the application at each stage.
* Acceptance checks: `repo/scripts/run_all_checks.py` runs the 10 gates and writes an evidence manifest with artifact hashes; `repo/scripts/verify_evidence.py` checks the manifest's required fields and the hashes of the artifacts it names.

## License

MIT License. Copyright (c) 2026 Randall Vollen and VollenData. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
