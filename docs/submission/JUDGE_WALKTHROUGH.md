# City of Acme permits: judge walkthrough

Four paths, each one independent, and each with its own guided tour. The café path offers a fresh copy of the café case, so every judge walks a case of their own. Every record in the app is fictional, and the app issues no real permit.

Start at https://acme-city-permits.onrender.com/walkthrough. The same steps are on that page, and the button on each step switches to the right persona and opens the screen. To run the app on a local computer instead, follow `repo/USER_TEST_GUIDE.md`. From `repo/`, run `uv run python scripts/prepare_user_test.py --mode demo-synthetic` and then `uv run python scripts/start_demo.py --host 127.0.0.1 --port 8266`, and open http://127.0.0.1:8266/walkthrough. The demo-synthetic mode loads the synthetic year of permits that the City view needs.

The permit life cycle behind these steps is at `/lifecycle`: every status, every move, and who makes each move.

## Apply as a resident

A resident applies for a fence, checks the application before it is sent and follows it through the City.

A resident at 400 Lantern Row wants a fence for the back yard. The case starts on Apply, before a form is filled, because the permit and the documents are not known yet.

4 steps, about 3 minutes.

### 1. Apply for a permit

As **Applicant**, open `/apply`.

- Why: We are here because the resident asks Muse which fence permit fits, then names the project.
- Do: Choose Residential deck or fence, type 400 Lantern Row, answer the questions for a 6 ft fence in the front yard, attach a file for each of the two required documents and tick the certification.
- Look for: The form asks only the questions that project needs, and the assistant names the published rule behind each answer.

### 2. Check the application before it is sent

As **Applicant**, open `/apply`.

- Why: We are here because Check my application asks Muse for feedback before the application is sent.
- Do: Press Check my application, then change the 6 ft front yard fence to 4 ft and press Submit application, or press Submit anyway and write why you send it now.
- Look for: The findings are grouped under Must fix, Should check and Looks good, and each one names the published rule behind it.

### 3. Let the agent route the application

As **Agent Operator**, open `/agent/intake`.

- Why: We are here because Muse reads the documents and the agent sends the application to the right queue.
- Do: Press Wake agent, then press Process the next 20 cases.
- Look for: The Router line sends an application that breaks a rule to Early resolution and says which rule.

### 4. Track the application

As **Applicant**, open `/apply/track`.

- Why: We are here because the resident needs to see what the City has recorded so far.
- Do: Press Track application on the City of Acme website and open the application.
- Look for: The tracker lists both documents as received and the status of the application.

## Get the café open

Cedarline Coffee cannot open until its permit is issued, and its owner is recorded three ways in three city systems.

Cedarline Coffee cannot open until its permit is issued. The case starts with the Data Steward, because the owner is recorded three ways.

6 steps, about 6 minutes.

### 1. Match the café to its owner

As **Data Steward**, open `/steward`.

- Why: We are here because the owner is three records until a steward decides, and Explain with Muse only rewrites the reason.
- Do: Press Start fresh, then open Data issues, press Prepare recommendations, press Accept recommendation on each task that carries a High pill and approve the link of the property.
- Look for: Every task of the café carries a High pill and a reason in one line, and the decision is recorded in your name.

### 2. Let the agent route the case

As **Agent Operator**, open `/agent/intake`.

- Why: We are here because Muse has read the documents and a person has to send the case on.
- Do: Press Wake agent, then press Process one beside the case of the café.
- Look for: The run shows Completed and the Router line says Ready for review in the Building area.

### 3. Run the checks and approve the case

As **Permit Reviewer**, open `/queue/review`.

- Why: We are here because the identity is clear, so a person can decide the case.
- Do: Open the case of the café from the Review queue, press Start under Confirm parcel on the People and organizations tab and submit it, press Start under Run application checks and submit it, then press Start under Record review decision, choose Approve and write your reason.
- Look for: The rule results show Passed and the decision is recorded in the case history with your reason.

### 4. Apply the café's payment

As **City Administrator**, open `/reconciliation`.

- Why: We are here because the café paid its 150.00 fee when it applied, but the payment came in under its old finance account, so nobody could match it to the case.
- Do: Open Reconciliation, press Start under Assess application, type the reference of the café's case and press Assess application, then press Start under Confirm allocation and press Confirm allocation, then press Start under Reconcile assessment and press Reconcile assessment.
- Look for: The fee from the approved schedule is assessed, the café's payment is applied, and the balance shows 0.00, so the permit can be issued.

### 5. Issue the permit

As **Permit Reviewer**, open `/queue/review`.

- Why: We are here because deciding and issuing are separate.
- Do: Open the case of the café again and press Start under Issue permit.
- Look for: The permit number appears on the case and the issued artifact opens.

### 6. Find it as a resident

Open `/city/community`.

- Why: We are here because a resident should find the permit without a homeowner's name.
- Do: Search for the permit number on the City of Acme website.
- Look for: The public record shows the permit, the parcel and the outcome, and never a homeowner's name, documents or fees.

## Run the city

The record of the café decision, the City at a glance and a what if on a fee change.

The café permit is on the public record. The City starts with the audit log, because it has to see who decided.

3 steps, about 3 minutes.

### 1. Check the record of the decision

As **City Administrator**, open `/ops/audit`.

- Why: We are here because the decision has to stay tied to the person who made it.
- Do: Choose Recorded permit decision in the Action filter, press Apply filters, then press View details on the top row.
- Look for: The actor, the time, the decision and the case it belongs to are recorded together.

### 2. See the city at a glance

As **City Administrator**, open `/insight/city`.

- Why: We are here because the City needs the counts and the map with a definition beside each figure.
- Do: Filter the City view by permit type and outcome.
- Look for: The map, the counts and the definition printed beside each figure.

### 3. Try a what if on a fee change

As **City Administrator**, open `/policy/scenarios`.

- Why: We are here because Muse writes the briefing for a fee change, and the run decides nothing.
- Do: Open What-if, save a new what-if, change a fee and run it over the cases.
- Look for: The run writes down what the change would do and it decides nothing.

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
