# City of Acme permits: judge walkthrough

Four paths, each one independent. Every record in the app is fictional, and the app issues no real permit.

Start at https://acme-city-permits.onrender.com/walkthrough. The same steps are on that page, and the button on each step switches to the right persona and opens the screen. To run the app on a local computer instead, follow `repo/USER_TEST_GUIDE.md`. From `repo/`, run `uv run python scripts/prepare_user_test.py --mode demo-synthetic` and then `uv run python scripts/start_demo.py --host 127.0.0.1 --port 8266`, and open http://127.0.0.1:8266/walkthrough. The demo-synthetic mode loads the synthetic year of permits that the City view needs.

The permit life cycle behind these steps is at `/lifecycle`: every status, every move, and who makes each move.

## Get the café open

Cedarline Coffee cannot open until its permit is issued, and its owner is recorded three ways in three city systems.

6 steps, about 6 minutes.

### 1. Match the café to its owner

As **Data Steward**, open `/steward`.

- Do: Open Data issues, press Prepare recommendations, then open each task of the café and press Accept recommendation.
- Look for: The task carries a High pill and a reason in one line, and the decision is recorded in your name.

### 2. Let the agent route the case

As **Agent Operator**, open `/agent/intake`.

- Do: Press Wake agent, then press Process the next 20 cases.
- Look for: The run shows Completed and the Router line says Ready for review in the Building area.

### 3. Run the checks and approve the case

As **Permit Reviewer**, open `/queue/review`.

- Do: Open the case of the café from the Review queue, press Start under Run application checks, then press Start under Record review decision, choose Approve and write your reason.
- Look for: The rule results show Passed and the decision is recorded in the case history with your reason.

### 4. Pay the fee

As **City Administrator**, open `/reconciliation`.

- Do: Open Reconciliation, press Start under Assess application and assess the case of the café, then allocate the 150.00 receipt from the old finance account and reconcile the assessment.
- Look for: The receipt from the old account is matched and the balance shows 0.00.

### 5. Issue the permit

As **Permit Reviewer**, open `/queue/review`.

- Do: Open the case of the café again and press Start under Issue permit.
- Look for: The permit number appears on the case and the issued artifact opens.

### 6. Find it as a resident

Open `/city/community`.

- Do: Search for the permit number on the City of Acme website.
- Look for: The public record shows the permit, the parcel and the outcome, and never a homeowner's name, documents or fees.

## Apply as a resident

A resident applies for a fence, checks the application before it is sent and follows it through the City.

4 steps, about 3 minutes.

### 1. Apply for a permit

As **Applicant**, open `/apply`.

- Do: Choose Residential deck or fence, type 400 Lantern Row, answer the questions for a 6 ft fence in the front yard, attach a file for each of the two required documents, tick the certification and press Submit application.
- Look for: A reference number appears and the tracker lists both documents as received.

### 2. Check the application before it is sent

As **Applicant**, open `/apply`.

- Do: Press Check my application, then change the 6 ft front yard fence to 4 ft and press Check my application again, or press Submit anyway and write Why submit now.
- Look for: The findings are grouped under Must fix, Should check and Looks good, and each one names the published rule behind it.

### 3. Let the agent route the application

As **Agent Operator**, open `/agent/intake`.

- Do: Press Wake agent, then press Process the next 20 cases.
- Look for: The Router line sends an application that breaks a rule to Early resolution and says which rule.

### 4. Track the application

As **Applicant**, open `/apply/track`.

- Do: Press Track application on the City of Acme website and open the application.
- Look for: The tracker lists both documents as received and the status of the application.

## Run the city

The record of the café decision, the City at a glance and a what if on a fee change.

3 steps, about 3 minutes.

### 1. Check the record of the decision

As **City Administrator**, open `/ops/audit`.

- Do: Choose Recorded permit decision in the Action filter, press Apply filters, then press View details on the top row.
- Look for: The actor, the time, the decision and the case it belongs to are recorded together.

### 2. See the city at a glance

As **City Administrator**, open `/insight/city`.

- Do: Filter the City view by permit type and outcome.
- Look for: The map, the counts and the definition printed beside each figure.

### 3. Try a what if on a fee change

As **City Administrator**, open `/policy/scenarios`.

- Do: Open What-if, save a new what-if, change a fee and run it over the cases.
- Look for: The run writes down what the change would do and it decides nothing.

## Before you start

The video, the permit life cycle and the plans for assistants through MCP and for staff screens on a phone.

3 steps, about 2 minutes.

### 1. Watch the video

Open `/select`.

- Do: Open the video below the persona cards and play it.
- Look for: It runs under three minutes and every record it shows is fictional.

### 2. Read the permit life cycle

Open `/lifecycle`.

- Do: Read the main path across the top, then the statuses a case can move to instead.
- Look for: Each move names who makes it, an agent only routes cases and a person decides and issues.

### 3. See what the City plans next

Open `/help`.

- Do: Open Help and documentation and read the plan for assistants through MCP.
- Look for: The plan says plainly that none of it is built yet.
