# Changes to the judge-facing documents

Date: 2026-11-02
Branch: `docs/final-pass`

This file records the last pass over the documents a judge reads: the README,
the submission text, the judge walkthrough, the operations runbook, the
deployment runbook and the in-app help. It covers three things: the stale
document audit of 2026-11-02, the internal-review and draft status markers
Randall removed on the same day, and the numbers the documents state.
`CHANGES-help.md` holds the help update committed before this pass; nothing
was appended to it.

Every number below was read from the code on 2026-11-02. The test count comes
from the collection and the full run of that day.

## Part 1. The stale-document findings

### `README.md`

| Line | What changed | Before | After |
| --- | --- | --- | --- |
| 32 | What the data steward does | "**Data stewards** clear the findings that block a case and keep the master records consistent." | "**Data stewards** settle identity and property records and keep the master records consistent. Their work is Data follow-up: it never holds a case and it never refuses a decision. Missing applicant information still goes back to the applicant, and the payer link and the fee still block issuing." |
| 47 | The Muse bullet on the pre-submit check | "It explains the "Check my application" result in plain words when live." | "It explains the "Check my application" result in plain words when live. That button carries a Muse badge and may ask Muse for feedback. "Submit application" makes no Muse call at all." |
| 52 | The allowance of the hosted demo | "Live Muse is on for the hosted demonstration, with an allowance of 100 live calls a day." | "Live Muse is on for the hosted demonstration. The allowance is a setting of that deployment: `render.yaml` gives the service 100 live calls and 100 provider calls a day, and Randall can change either number in the Render dashboard." |
| 68 to 70 | Three facts the demonstration has today | The list held no line about the tour, a lost copy or the clock | The guided tour of "Apply as a resident" fills the resident's form; a judge's copy of the café case that the nightly reset removed opens on a recovery page that offers a fresh one; no scenario clock is set, so the current date on screen is today's date |
| 76 | The first step of "How to try it" | "Muse explains the result in plain words when live." | "The button carries a Muse badge, and Muse explains the result in plain words when it is live. ... "Submit application" itself makes no Muse call." |
| 113 | The pre-submit bullet of "Production behaviour" | ""Check my application" runs the reviewer's rules on the draft before it is sent. "Must fix" holds "Submit application" unless the applicant presses "Submit anyway" with a reason, and the reviewer then sees "Submitted with known issues"." | The same, plus: "It carries a Muse badge and may ask Muse for feedback when live." and ""Submit application" makes no Muse call." |

### `docs/submission/SUBMISSION_DRAFT.md`

| Line | What changed | Before | After |
| --- | --- | --- | --- |
| 24 | The applicant paragraph | ""Check my application" runs the reviewer's rules on the draft before it is sent. Muse explains the result in plain words when live." | "The button carries a Muse badge, and Muse explains the result in plain words when it is live. ... "Submit application" makes no Muse call." |
| 32 | The data steward paragraph | "These actions do not approve a permit." | "These actions do not approve a permit. The steward's work is Data follow-up: it never holds a case and it never refuses a decision." |
| 50 | The Muse paragraph | "When the applicant presses "Check my application", Muse explains the result in plain words when live." | "When the applicant presses "Check my application", the button carries a Muse badge and Muse explains the result in plain words when it is live; "Submit application" makes no Muse call." |
| 56 | The allowance of the hosted demo | "Live Muse is on for the hosted demo, with an allowance of 100 live calls a day." | "Live Muse is on for the hosted demo. The allowance is a setting of that deployment: `render.yaml` gives the service 100 live calls and 100 provider calls a day, and Randall can change either number in the Render dashboard." |
| 79 | The pre-submit bullet of "Production behaviour" | ""Check my application" runs the reviewer's rules on the draft before it is sent." | The same, plus the Muse badge and the sentence ""Submit application" makes no Muse call." |
| 132 | The pre-submit bullet of "What the demonstration shows now" | "Muse explains the result in plain words when live." | "The button carries a Muse badge, and Muse explains the result in plain words when it is live. ... "Submit application" makes no Muse call." |
| 140 | The third step of "How to try it" | "Muse explains the result in plain words when live." | "The button carries a Muse badge, and Muse explains the result in plain words when it is live. ... "Submit application" makes no Muse call." |

### `docs/submission/JUDGE_WALKTHROUGH.md` and its source

The document is generated from the application, and
`repo/tests/unit/test_judge_walkthrough_doc.py` holds it to the words of the
page. The wording was therefore changed at its source and the document was
regenerated with `walkthrough_markdown()`.

| File and line | What changed | Before | After |
| --- | --- | --- | --- |
| `repo/src/acme_city/ui/guide_views.py:107` | What the applicant does in the second step | "then set the fence to 6 ft in the front yard and press Check my application again to see Must fix, or press Submit application." | "then set the fence to 6 ft in the front yard and press Check my application again to see Must fix, which holds Submit application until the applicant presses Submit anyway with a reason." |
| `repo/src/acme_city/ui/guide_views.py:110` | What the applicant notices | "The findings are grouped under Must fix, Should check and Looks good, and each one names the published rule behind it." | "The button carries a Muse badge, and the findings are grouped under Must fix, Should check and Looks good, each naming the published rule behind it." |
| `repo/src/acme_city/ui/guide_views.py:113` | Why the step is on the walkthrough | "We are here because Check my application asks Muse for feedback before the application is sent." | "We are here because Check my application asks Muse for feedback before the application is sent, and Submit application makes no Muse call." |
| `docs/submission/JUDGE_WALKTHROUGH.md:29` to `:31` | The three lines of the step | The words above | The words above, regenerated |

Only the words changed. No label, no screen and no behaviour changed, and the
walkthrough page shows the same three sentences as the document.

### `docs/operations/RUNBOOK.md`

| Line | What changed | Before | After |
| --- | --- | --- | --- |
| 197 | Who sends a case back to the applicant | "**Data Steward**: return it, or advance it to review" | "**Permit Reviewer**: record the decision "Needs information", which sends the case back to the applicant, who answers it on the tracker. **Data Steward**: return it, or advance it to review" |

The rest of the runbook already matches the build: Data follow-up, the
recorded exception for an approval against a failed rule, the payer link and
the fee blocking issuance, the real clock, and the data identity and parcel
work of the steward, which is Data follow-up and does not hold a case.

### `docs/operations/DEPLOY_RENDER.md`

| Line | What changed | Before | After |
| --- | --- | --- | --- |
| 82 | The Live Muse step of the setup | "**Live Muse.** On for judging, at most 100 live calls a day." | "**Live Muse.** On for judging. The blueprint sets 100 live calls and 100 provider calls a day." |
| 121 | The head of the Live Muse section | "Live Muse is on for judging, at Randall's request (2026-10-31), with at most 100 live calls a day." | "Live Muse is on for judging, at Randall's request (2026-10-31). The blueprint sets the caps below, and Randall can change any of them in the Render dashboard." |
| 142 to 150 | The table of the paths that reach the provider | The first row read "Muse runs on a case (extraction, match proposal) | yes | yes | no" | Four live paths (the applicant help assistant, Check my application, Explain with Muse, and the what-if briefing, explanation and proposal) and one row that reads "Document reading by the intake agent | no, the run is recorded and sent no provider call | no | no". The line under the table says that on the applicant form "Check my application" is the button that may reach Muse, and that "Submit application" makes no Muse call |
| 162 | The step that turns live Muse on again | "set ACME_PRESUBMIT_REVIEW_LIVE_ENABLED to 1 so Check my application gives live Muse feedback." | The same, plus ""Submit application" makes no Muse call in either case." |

The number 100 is the one the blueprint sets (`render.yaml`), and the head of
the section now says that the dashboard can change it. The line at 137 about
the live call cap is right and was left alone.

The old first row was wrong: the intake agent reads the documents through the
built in path of the City (`repo/src/acme_city/agents/extraction.py`, mode
`builtin`, since the commit `bff7c0e` of 2026-10-29) and never calls the
provider. The line under the table already said so.

### `repo/config/help_content.json` and the overlays

| File and line | What changed | Before | After |
| --- | --- | --- | --- |
| `repo/config/help_content.json:266` | The allowance in the tutorial of the City Administrator | "The hosted demonstration allows 100 live Muse calls a day." | "The hosted demonstration is set for 100 live Muse calls and 100 provider calls a day, and whoever runs it can change that setting." |
| `repo/config/help_content.json:82` | A new step in the tutorial of the Applicant | The tutorial took the applicant from the empty form to the receipt without the pre-submit check | "Click "Check my application"." and the three groups, the Muse badge and the hold on "Submit application" |
| `repo/config/help_content.json:304` | A new step in the guide "Apply for a fence or deck permit" | The guide had no step for the pre-submit check | "Press "Check my application". The button carries a Muse badge, and Muse explains the result in plain words when it is live. The findings are grouped under "Must fix", "Should check" and "Looks good". A "Must fix" holds "Submit application" until you press "Submit anyway" and write why you are submitting now." |
| `repo/config/help_content.json:421` | The result of the guide "Run a what-if and write the briefing" | "When live Muse is off, or the daily allowance of 100 calls is used up, the briefing is a recorded answer and the label says so." | "When live Muse is off, or the allowance of the deployment is used up, the briefing is a recorded answer and the label says so." |
| `repo/config/help_content.json:492` | The note on the architecture page | "It is shown inside a sandbox that blocks every script, so it reads as a static page." | "It is shown inside a sandbox that blocks every script and every network request, so it reads as a static page." |
| `repo/config/help_content.d/admin_b.json:15` and `:31` | The allowance in the what-if texts | "The hosted demonstration allows 100 live Muse calls a day." | "The hosted demonstration is set for 100 live Muse calls and 100 provider calls a day, and whoever runs it can change that setting." |
| `repo/config/help_content.d/operator.json:21` | The allowance in the guide "Run the agents" | "On the hosted demonstration live Muse is on, with a daily allowance of 100 calls." | "On the hosted demonstration live Muse is on, with an allowance of 100 live calls and 100 provider calls a day that whoever runs it can change." |
| `repo/config/help_content.d/steward.json:43` | The allowance in the guide "Resolve a data issue" | "On the hosted demonstration live Muse is on, with a daily allowance of 100 calls." | "On the hosted demonstration live Muse is on, with an allowance of 100 live calls and 100 provider calls a day that whoever runs it can change." |

## Part 2. The internal-review and draft status markers

Every marker below was read out of the text a judge can see. The markers are
gone; the facts they stood next to stay where they were true.

| File and line | What changed | Before | After |
| --- | --- | --- | --- |
| `README.md:7` | The visibility of the repository | "Repository visibility: [REVIEW: Randall. The repository is private today. Make it public before submission, then delete this line.]" | "Repository visibility: private. It must be public at submission." |
| `README.md:22` | The build window | "The build window is not settled. The participant guide says October 27 to November 4. The event page says October 26. [REVIEW: Randall. Confirm the window before submission.]" | "The participant guide says the build window runs October 27 to November 4. The event page says October 26." |
| `README.md:84` | The nightly reset | "The data is fictional and is meant to be disposable. It resets nightly once the scheduled reset is configured, and every deploy rebuilds it. [REVIEW: Randall]" | "The data is fictional and is meant to be disposable. The nightly reset rebuilds it, and every deploy rebuilds it." |
| `docs/submission/SUBMISSION_DRAFT.md` (lines 3 to 5 before the pass) | The whole "Draft status" section | "## Draft status / This is submission text for Randall to review and submit himself. It has not been submitted. The hosted demo at https://acme-city-permits.onrender.com shows all five personas." | The section is gone. The live address stays in "Entry requirements" and the personas stay listed where they were already described |
| `docs/submission/SUBMISSION_DRAFT.md:12` | The repository link of the entry | "* Public repository: https://github.com/... [REVIEW: Randall. The repository is private today. Make it public before submission, and confirm this link.]" | "* Public repository: https://github.com/... The repository is private today and is made public at submission." |
| `docs/submission/SUBMISSION_DRAFT.md:13` | The video of the entry | "* Accessible three-minute demo video: [link to be added]" | "* Accessible three-minute demo video: it plays on the landing page of the live demo, under the persona cards." The file is `repo/src/acme_city/static/video/demo-video.mp4` |
| `docs/submission/SUBMISSION_DRAFT.md:76` | The nightly reset | "... It resets nightly once the scheduled reset is configured, and every deploy rebuilds it. [REVIEW: Randall]" | "... The nightly reset rebuilds it, and every deploy rebuilds it." |
| `docs/submission/SUBMISSION_DRAFT.md:105` | The build window | "The build window is not settled. ... [REVIEW: Randall. Confirm the window before submission.]" | "The participant guide says the build window runs October 27 to November 4. The event page says October 26." |
| `docs/submission/SUBMISSION_DRAFT.md:121` | The licence wording | "... [REVIEW: Randall. Confirm the repository licence wording before submission.] See [LICENSE]..." | The sentence stays, the marker goes |
| `docs/submission/SUBMISSION_DRAFT.md:136` | The first step of "How to try it" | "... The data resets nightly once the scheduled reset is configured, and every deploy rebuilds it. [REVIEW: Randall]" | "... The data is fictional, the nightly reset rebuilds it, and every deploy rebuilds it." |
| `docs/operations/MCP_PLAN.md:8` | The note on what the plan could check | "Planned 2026-11-01 by a Claude planning subagent from the code at main fd41e14. Unverified: whether any write path already carries an idempotency key (only finance has one), and the exact permission names per persona." | "Planned 2026-11-01 by a Claude planning subagent from the code at main fd41e14. It reads the code as it stood then, and the two things it could not settle are in the open questions at the end." The two points became questions 8 and 9 of section 7 |

The words the application itself uses are untouched: "Save draft", "Save as a
draft rule change", "Draft: ready for your approval", the drafts of an
application, "Submit for review" on a rule version, "Ready for review" on a
case and "Recommended for review" on a record. "Example with fictional data"
and the byline "Prepared by Randy Vollen, host of www.VollenData.com, for the
Muse Hackathon, using the fictional City of Acme" are unchanged.

## Part 3. The numbers

| File and line | What changed | Before | After |
| --- | --- | --- | --- |
| `README.md:129` | The size of the automated suite | "The automated suite collects 3,414 tests, and all of them pass. ... The count comes from a full run on November 1, 2026." | "The automated suite collects 3,786 tests. The full run of November 2, 2026 passed 3,784 of them and skipped 2, the two WebKit browser tests, because that browser is not installed on the machine." |
| `README.md:127` | A new line in "Checks and tests" | The list held no count for the permissions | "* 85 permissions, listed in `repo/config/permissions.json`." |
| `docs/submission/SUBMISSION_DRAFT.md:109` | The size of the automated suite | "The full automated suite collects 3,414 tests, and all of them pass. ... The count comes from a full run on November 1, 2026." | "The full automated suite collects 3,786 tests. The full run of November 2, 2026 passed 3,784 of them and skipped 2, the two WebKit browser tests, because that browser is not installed on the machine." |
| `docs/submission/SUBMISSION_DRAFT.md:117` | A new line under "Verification" | The list held no count for the permissions | "* 85 permissions are listed in `repo/config/permissions.json`. Every grant is explicit, and a role label never authorizes an action." |
| `docs/operations/PRODUCTION_READINESS.md:61` | The inline style attributes | "About 80 inline `style="..."` attributes in 14 templates need it." | "47 inline `style="..."` attributes in 18 templates need it." |
| `docs/operations/RUNBOOK.md:32` | The list of the simulator scenarios | Eleven of the fourteen names | The three address scenarios of the property master, `address-typo`, `address-ambiguous` and `address-unknown`, were named as well |

### How each number was checked

| Number | Where it comes from |
| --- | --- |
| 3,786 tests | `pytest --collect-only -q` in `repo/`, on 2026-11-02, and the full run of the same day: 3,784 passed and 2 skipped, the two WebKit browser tests, because that browser is not installed on the machine |
| 85 permissions | `repo/config/permissions.json` holds 85 entries with 85 distinct `permission_id` values. The five personas hold 80 of them; the other 5 (`admin.health.view`, `admin.role.permissions.manage`, `agent.policy.manage`, `agent.run.linking`, `registry.master.create`) are held by service identities, so every key of the catalog is reachable |
| 10 gates | The ten steps of `repo/scripts/run_all_checks.py`: compile, requirement-coverage, collect, collection-contract, alembic-upgrade, alembic, publishable-tree, pytest, deterministic-acceptance, evidence-verification |
| 100 live calls and 100 provider calls a day | `render.yaml` sets `ACME_MUSE_LIVE_CALL_CAP` and `ACME_MUSE_DAILY_CALL_CAP` to 100. The code defaults are 2 and 10 (`repo/src/acme_city/core/config.py` and `config_operator.py`) |
| 10 image calls a day | `ACME_MUSE_IMAGE_DAILY_CAP` is 10 in `render.yaml` and 10 is the code default |
| 17 permit types | `repo/config/rules_and_fees.json` |
| 57 requirements | `repo/docs/REQUIREMENTS_OUTLINE.md` |
| 39 checks | `repo/config/check_inventory.json` |
| 6 simulated subscriber departments | `repo/config/property_subscribers.json` |
| 47 inline style attributes in 18 templates | `grep -ro 'style=' repo/src/acme_city/templates/` |
| 20 cases in a batch, 50 in a selection | `DEFAULT_MAX_BATCH_SIZE` in `repo/src/acme_city/agents/runtime.py` and `MAX_SELECTION` in `repo/src/acme_city/permits/bulk.py` |
| 69 parcels, 71 address points, 6 streets | `repo/fixtures/gis_town.json` |
| 14 generated icons, 14 calls at $0.01 | `docs/operations/permit-type-icons-manifest.json` holds 14 icons, and `BUILD_LOG.md` records the 14 calls and the $0.14 |
| 14 simulator scenarios | `SCENARIO_NAMES` in `repo/src/acme_city/portal_intake/scenarios.py`, which is also what `GET /api/intake/scenarios` returns |

The numbers that were already right were left alone: 17 permit types, 57
requirements, 39 checks, 6 subscriber departments, 10 gates, the seven node
intake graph and the five node adjudication graph, the 20 case batch, the 50
case selection, the 69 parcels, the 71 address points, the 6 streets, the 14
icons and the code defaults of the Muse caps.

## Open questions for Randall

Each marker below hid a question that is still open. The marker is gone from
the document and the question is here, with the text it had.

| Where it was | The text of the marker |
| --- | --- |
| `README.md:7` | "Repository visibility: [REVIEW: Randall. The repository is private today. Make it public before submission, then delete this line.]" The line itself stays in the README, so it can be deleted when the repository is made public |
| `README.md:22` and `docs/submission/SUBMISSION_DRAFT.md:105` | "[REVIEW: Randall. Confirm the window before submission.]" The build window is October 27 to November 4 in the participant guide and October 26 on the event page. The documents now state both dates and say which source gives which |
| `README.md:84` and `docs/submission/SUBMISSION_DRAFT.md:76` | "[REVIEW: Randall]" beside the nightly reset. The reset needs `ACME_DEPLOY_HOOK_URL` set in the Render dashboard (`docs/operations/DEPLOY_RENDER.md`, step 6), and the documents now say that the nightly reset rebuilds the data |
| `docs/submission/SUBMISSION_DRAFT.md:12` | "[REVIEW: Randall. The repository is private today. Make it public before submission, and confirm this link.]" The link points at `randallvollen-boop/Meta-Global-AI-Developer-Hackathon-2026-City-Permits` |
| `docs/submission/SUBMISSION_DRAFT.md:121` | "[REVIEW: Randall. Confirm the repository licence wording before submission.]" The wording now stands on its own, next to `LICENSE` and `NOTICE` |
| `docs/submission/SUBMISSION_DRAFT.md:13` | "[link to be added]" beside the three-minute demo video. The video plays on the landing page of the live demo; a hosted link for the entry form is not in the repository |

## Left alone on purpose

- **The persona findings of the audit were not applied.** The audit asked for
  four selectable personas and asked that the Agent Operator be taken out of
  the documents. The Agent Operator is a selectable persona in this build:
  `repo/config/actors.json` lists five selectable personas, the selector, the
  tour and `repo/tests/integration/test_help_docs.py` use all five, and
  `repo/tests/api/test_sessions.py` expects five actors. The persona
  descriptions were not touched.
- **The count of the audit does not hold.** The audit says `actors.json`
  yields 82 distinct `permission_id` values. It yields 80 for the five
  personas, and the catalog holds 85 distinct keys. The number written into
  the README and the submission text is 85, the size of the catalog, with the
  definition spelled out above.
- **The architecture page and its sources.** `docs/solution-architecture/**`
  and the served page belong to another branch. The banner "Internal draft.
  [REVIEW REQUIRED] before external use." is still on the page and in
  `page/page.json`, and that page is served to judges under Help, Technical
  documentation. That branch should take the banner off.
- **The note on the architecture page.** The audit asked the help to say the
  sandboxed page allows scripts. The application does the opposite and the
  shared test says so:
  `repo/tests/integration/test_help_docs.py::test_the_architecture_page_is_served_as_committed_inside_a_script_free_sandbox`
  asserts that the iframe carries `sandbox=""` with no allow token and that
  the response policy sets `default-src 'none'` with no `script-src`. The
  note therefore still says the page reads as a static page. It now also
  says that the sandbox blocks every network request.
- **The claim that no model is called.** The audit asked for the help to stop
  saying that no model is called while the tutorial runs. The help update
  committed before this pass (`a75aa1e`, recorded in `CHANGES-help.md`) had
  already replaced that sentence with "A step that may call Muse for a live
  answer says so on the screen, and the label of that answer says so too",
  and the steps name the live surfaces.
- **The file name `docs/submission/SUBMISSION_DRAFT.md`.** The document itself
  carries no draft marker any more. The name was left because the path may be
  named in the hackathon governance, which this session may not read. Say the
  word and it becomes `docs/submission/SUBMISSION.md`.
- **The internal working notes.** `BUILD_LOG.md`, `EVIDENCE_LOG.md`,
  `CITY_PERMIT_ALIGNMENT.md`, `GO_NO_GO.md`, `HANDOFF.md`, `CONTEXT.md`,
  `RISK_LIST.md`, `IMPACT-steward6.md` and `docs/process/WORKSPACE.md` are
  the record of the build for Randall and the team, not documents shipped to
  judges. They keep the words "internal draft" and "[REVIEW REQUIRED]" where
  they record what was published and when.
- **The label of the document reading.** The walkthrough says that document
  reading is a recorded Muse run (replay), and that is the label the
  application itself uses for that surface
  (`repo/src/acme_city/ui/guide_routes.py`, the `intake` surface, whose
  replay label is "Recorded replay"). The run sends no provider call: the
  intake agent reads the documents through the built in path of the City
  since the commit `bff7c0e` of 2026-10-29, and the run panel says "Built in
  logic". The deployment runbook now says the same in its table of the paths
  that reach the provider.

## Checks

```
cd repo && PYTHONPATH=src <venv python> -m pytest -q -p no:cacheprovider \
    tests/unit tests/integration -k "doc or help or walkthrough or readme or copy or tour"
```

353 passed, 2145 deselected, on 2026-11-02.

The whole suite was run on the same day with
`PYTHONPATH=src <venv python> -m pytest -q -p no:cacheprovider -n 8`:
**3,784 passed, 2 skipped in 963.36s**. The two skipped are the WebKit
browser tests, which cannot run because that browser is not installed on the
machine. That is the number in Part 3.

No assertion was weakened or removed.
