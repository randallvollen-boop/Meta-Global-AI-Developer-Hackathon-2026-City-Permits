# City of Acme permits: judge walkthrough

Four paths, each one independent, and each with its own guided tour. The café path offers a fresh copy of the café case, so every judge walks a case of their own. Every record in the app is fictional, and the app issues no real permit.

Start at https://acme-city-permits.onrender.com/walkthrough. The same steps are on that page, and the button on each step switches to the right persona and opens the screen. To run the app on a local computer instead, follow `repo/USER_TEST_GUIDE.md`. From `repo/`, run `uv run python scripts/prepare_user_test.py --mode demo-synthetic` and then `uv run python scripts/start_demo.py --host 127.0.0.1 --port 8266`, and open http://127.0.0.1:8266/walkthrough. The demo-synthetic mode loads the synthetic year of permits that the City view needs.

The permit life cycle behind these steps is at `/lifecycle`: every status, every move, and who makes each move.

## Apply as a resident

A resident applies for a fence, checks the application before it is sent and follows it through the City.

A resident at 400 Lantern Row wants a fence for the back yard. The case starts on Apply, before a form is filled, because the permit and the documents are not known yet.

5 steps, about 4 minutes.

### 1. Apply for a permit

As **Applicant**, open `/apply`.

- Why: We are here because the resident asks Muse which fence permit fits, then names the project.
- Do: Choose Residential deck or fence, press Use a sample address and pick 400 Lantern Row, answer the questions for a 4 ft fence in the side or rear yard, attach a file for each of the two required documents, and tick the certification.
- Look for: The form asks only the questions that project needs, and the assistant names the published rule behind each answer.

### 2. Check the application before it is sent

As **Applicant**, open `/apply`.

- Why: We are here because Check my application asks Muse for feedback before the application is sent.
- Do: With the story’s answers already filled in, press Check my application, then set the fence to 6 ft in the front yard and press Check my application again to see Must fix, or press Submit application.
- Look for: The findings are grouped under Must fix, Should check and Looks good, and each one names the published rule behind it.

### 3. Let the agent route the application

As **Agent Operator**, open `/agent/intake`.

- Why: We are here because document reading is a recorded Muse run (replay) and the agent sends the application to the right queue.
- Do: Press Wake agent, then press the batch button, which reads Process N cases, or Process the next 20 of N when more than 20 cases are waiting.
- Look for: The Router line sends an application that breaks a rule to Early resolution and says which rule.

### 4. Track the application

As **Applicant**, open `/apply/track`.

- Why: We are here because the resident needs to see what the City has recorded so far.
- Do: Press Track application on the City of Acme website and open the application.
- Look for: The tracker lists both documents as received and the status of the application.

### 5. Read the messages from the City

As **Applicant**, open `/apply/track`.

- Why: We are here because the applicant is told of each decision.
- Do: Open the application in the list and read Messages from the City.
- Look for: The tracker shows Messages from the City and says the City would also send this by email while the demonstration sends no email.

## Get the café open

Cedarline Coffee cannot open until its permit is issued, and its owner is recorded three ways in three city systems.

Cedarline Coffee cannot open until its permit is issued. The case starts with the Data Steward, because the owner is recorded three ways.

6 steps, about 6 minutes.

### 1. Match the café to its owner

As **Data Steward**, open `/steward`.

- Why: We are here because the owner is three records until a steward decides, and the Agent Operator or the Data Steward wakes the Steward assistant.
- Do: Press Start fresh, then on Data issues press Wake if the steward assistant is asleep, or open Steward assistant in the left menu as the Agent Operator and press Wake agent, then press Prepare recommendations, press Accept recommendation on each task that carries a High pill, and approve the link of the property.
- Look for: Every task of the café carries a High pill and a reason in one line, Put to sleep is beside Wake once the assistant is awake, and the decision is recorded in your name.

### 2. Let the agent route the case

As **Agent Operator**, open `/agent/intake`.

- Why: We are here because document reading is a recorded Muse run (replay) and a person has to send the case on.
- Do: Press Wake agent, then press Process one beside the case of the café.
- Look for: The run shows Completed and the Router line says Ready for review in the Building area.

### 3. Run the checks and approve the case

As **Permit Reviewer**, open `/permits/{case}`.

- Why: We are here because a person decides the case, an open parcel or identity link is Data follow-up that does not block the decision, and the applicant is told by email at this point while the demonstration sends no email.
- Do: On the café’s case workspace, press Start under Confirm parcel, press Start under Run application checks or Run checks again, and record the decision.
- Look for: The checks summary reads Checks finished or These checks already ran on this revision, Next: record the decision appears when a decision is open, the Recommendation section reads Recommend deny: with the reason when the rules fail or Passed when they do not, Needs information is prefilled, plain blockers link to the fix, Data follow-up does not block the decision, and an approval against a failed rule reads Approved as an exception to the failed rule once Exception reason is written.

### 4. Apply the café’s payment

As **City Administrator**, open `/reconciliation`.

- Why: We are here because the café paid its 150.00 fee when it applied, but the payment came in under its old finance account, so nobody could match it to the case.
- Do: Open Reconciliation, press Start under Assess application, type the reference of the café’s case and press Assess application, then press Start under Confirm allocation and press Confirm allocation, then press Start under Reconcile assessment and press Reconcile assessment.
- Look for: The fee from the approved schedule is assessed, the café’s payment is applied, and the balance shows 0.00, so the permit can be issued.

### 5. Issue the permit

As **Permit Reviewer**, open `/permits/{case}`.

- Why: We are here because deciding and issuing are separate, and the payer link and the fee still block issuing.
- Do: On the café’s case workspace, when the fee is settled, press Start under Issue permit.
- Look for: After issuance, Stage reads Issued (6 of 6) and Next action reads Issued, and the applicant is told by email at this point while the demonstration sends no email.

### 6. Find it as a resident

Open `/city/community`.

- Why: We are here because a resident should find the permit without a homeowner’s name.
- Do: Search for the permit number or the address, or press Search for my permit.
- Look for: The public record shows the permit, the parcel and the outcome, and never a homeowner’s name, documents or fees.

## Run the city

Cafés like Cedarline waited weeks, and the City asks whether to change the commercial fee or the process.

Cafés like Cedarline waited weeks for a permit. Should the City change the commercial fee, or the process? The City starts with the counts, because that is where the wait shows up.

5 steps, about 5 minutes.

### 1. See where the weeks went

As **City Administrator**, open `/insight/city`.

- Why: We are here because the weeks cafés waited should show up in the counts.
- Do: Open the City view and read the counts, the map and the definition beside each figure for commercial cases.
- Look for: Each figure has its definition printed beside it.

### 2. Follow where the café’s time went

As **City Administrator**, open `/ops/audit`.

- Why: We are here because the counts raise where the café’s weeks went.
- Do: Choose Recorded permit decision in the Action filter, press Apply filters, then press View details on the top row.
- Look for: The actor, the time, the decision and the case it belongs to are recorded together.

### 3. Ask Muse what the pattern is

As **City Administrator**, open `/policy/scenarios`.

- Why: We are here because the record shows a pattern and a person should read it before any rule changes.
- Do: Open What-if, open More details and press Ask Muse to propose so Muse summarises the pattern.
- Look for: Muse summarises the pattern in the policy briefing and the run decides nothing.

### 4. Try the fee change

As **City Administrator**, open `/policy/scenarios`.

- Why: We are here because the City should see the effect of a fee change before it changes a rule.
- Do: Open What-if, press Create a what-if, change a fee and run it over the cases.
- Look for: The run writes down what the fee change would do and it decides nothing.

### 5. Leave the change for a person

As **City Administrator**, open `/policy/scenarios`.

- Why: We are here because the fee question is answered only when a person approves the change.
- Do: Draft the change and submit it for approval on Rules and fees, because a person must approve and publish it.
- Look for: A person must approve and publish it.

## Before you start

The video, the permit life cycle and the plans for assistants through MCP and for staff screens on a phone.

3 steps, about 2 minutes.

### 1. Watch the video

Open `/select`.

- Why: We are here because the video shows the same journey before you walk it.
- Do: Open the video below the persona cards and play it.
- Look for: It runs under three minutes and every record it shows is fictional.

### 2. Read the permit life cycle

Open `/lifecycle`.

- Why: We are here because each move names who makes it.
- Do: Read the main path across the top, then the statuses a case can move to instead.
- Look for: Each move names who makes it, an agent only routes cases and a person decides and issues.

### 3. See what the City plans next

Open `/help`.

- Why: We are here because the help hub holds the plan for what is not built yet.
- Do: Open Help and documentation and read the plan for assistants through MCP.
- Look for: The plan says plainly that none of it is built yet.
