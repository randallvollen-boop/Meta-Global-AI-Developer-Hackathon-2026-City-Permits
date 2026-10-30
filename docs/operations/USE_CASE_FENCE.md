# Manual use case, the fence permit

Follow these steps in the browser. Every step names the persona, the screen,
the click and the expected result, including the exact agent outcomes.
`tests/acceptance/test_use_case_fence.py` runs the same steps automatically
through the same governed actions.

All records are fictional. The simulated scenarios create the next application
numbers in sequence (`SYN-APP-014` and `SYN-APP-015` on a freshly reset
database). The fee and payment amounts in step 10 come from the Reconciliation
screen of the current run. Read them off the page, because the total changes
between runs.

Two behaviors of the screens matter while you follow along. Most action
buttons sit under a **Start** control: press **Start**, fill the form, then
press the button inside it. And a page does not refresh itself after an
action, so reload it after each action to see the new state (the agent screens
have a **Refresh** link for the same purpose).

## 1. Reset and start the app

```bash
cd repo
uv run python scripts/prepare_user_test.py --mode fresh
uv run python scripts/start_demo.py --host 127.0.0.1 --port 8266
```

Open <http://127.0.0.1:8266>. The page shows **Choose a persona** with exactly
five personas: Applicant, Agent Operator, Data Steward, Permit Reviewer and
City Administrator.

## 2. As City Administrator, simulate the two fence cases

1. Click **City Administrator**. The left navigation lists Planning overview,
   Work queue, Master records, Permit workspace, Data issues, Source records,
   Activity, Rules and fees, Reconciliation, **Governance and sources**,
   **Administration** and Intake queue, and under More tools: City view,
   What-if, Operations, Audit log, Support and Checks. It has no **Intake
   agent** or **Adjudication agent** entry; the Administrator opens a 403 on
   those screens.
2. Click **Governance and sources** in the left navigation.
3. Under Next actions, press **Start** on **Simulate incoming permits**, set
   **Scenario** to `fence-front-too-tall`, and press **Simulate incoming
   permits**. The page reports "Simulated 1 incoming permit(s); 1 new
   application(s): SYN-APP-014."
4. Repeat with **Scenario** `fence-conforming-rear`. The page reports
   "Simulated 1 incoming permit(s); 1 new application(s): SYN-APP-015."
5. The terminal path gives the same result: `uv run python scripts/simulate_intake.py
   --scenario fence-front-too-tall` and `--scenario fence-conforming-rear`.

Both cases now wait. Nothing has been triaged.

## 3. As Agent Operator, wake the intake agent

1. Switch to **Agent Operator** (Demo controls at the bottom left, or the
   persona selector). The left navigation lists **Agents**, **Intake agent**,
   **Adjudication agent** and **Agent runs**. The **Agents** page shows both
   agents as **asleep** and 2 cases waiting.
2. Click **Intake agent**. The state reads **asleep**, **Process next 20** is
   disabled, and the page says "The agent is asleep, so the run buttons are
   off. Use Wake agent above to turn them on."
3. Press **Wake agent** and reload the page. The state reads **awake**, the
   button becomes **Put agent to sleep**, and "At a glance" shows **Waiting 2**,
   **Processed 0**, **Needs human 0**, **Errors 0**. Under "Cases waiting for
   the agent" the table lists `SYN-APP-014` and `SYN-APP-015`, each with a
   **Process one** button.
4. Press **Show the processing steps**. The diagram shows the seven steps:
   Classifier, Field extractor, Document QC (quality check), Address locator,
   Completeness, Duplicate finder and Router. The page says "Each group waits
   for the group before it. The steps of one group run one after the other."
5. The other personas do not see these screens in their navigation. Data
   Steward and City Administrator get a 403 on `/agent/intake`, and so does the
   Permit Reviewer.

## 4. As Agent Operator, run the intake agent

1. Press **Process next 20** (or **Process one** beside each case) and reload.
   "At a glance" now shows **Waiting 0**, **Processed 2**, **Needs human 0**,
   **Errors 0**, and "Recent results" lists one run for each case with the
   result **Completed** and "7 step(s)".
2. Press **All runs**, then **View run** on the row for `SYN-APP-014`. The
   run detail lists the seven steps, each **ok**: Classifier, Field extractor,
   Document QC, Address locator, Completeness, Duplicate finder and Router. The
   Router line reads "Ready for review in the Building area."
3. Both cases are now **ready_for_review** in the **Building** review area.
   The identity links and the parcel link are proposed for the Data Steward to
   approve.
4. Switch to **Data Steward**. The left navigation lists Data issues, Master
   records, Source records, Activity, Work queue, Permit workspace, Rules and
   fees, Intake queue, Early resolution and Steward automation. There is no
   Governance, Reconciliation or Administration entry, and `/governance` returns
   403.

## 5. As Data Steward, approve the links and the extracted values

1. Open the permit workspace of a fence case. The page shows the address the
   applicant typed, "400 Lantren Row", and the parcel the address locator
   proposed, `ACME-P-1001`. The locator corrected the typing to the official
   address "400 Lantern Row".
2. Click **Data issues**. Each proposed identity link is a row with **Review
   match**. Open it and press **Start** under **Confirm link to ...**, write a
   decision note, and submit it.
3. Each fence case also has a row **Check the property** with **Review
   property**. Open the one that names the case reference, press **Start** under
   **Approve parcel link for** that reference, write a decision note, and submit
   it. Approving a parcel link never approves the permit.
4. Open each fence case in the **Permit workspace**. On the Review tab, for
   each extracted value (`parcel_reference` and `unit_address`) press **Start**
   under **Accept or correct extracted ...**, choose **accept**, write a reason
   and submit. The page says "Recorded the steward decision on extracted
   parcel_reference: accepted." A corrected value needs a value and a reason.

## 6. As Agent Operator, wake the adjudication agent

1. Switch to **Agent Operator** and open **Adjudication agent**.
2. Press **Wake agent** and reload. The state reads **awake**. "At a glance"
   shows **In review 2**, **Recommended 0**, **Awaiting confirmation 0**,
   **Held for a person 0**.
3. Press **Show the processing steps**. The diagram shows the five steps: Rule
   loader, Rule evaluator, Condition builder, Precedent check and Disposition.

## 7. As Agent Operator, run the adjudication agent

1. Press **Process next 20** and reload. "At a glance" shows **In review 2**,
   **Recommended 2**, **Awaiting confirmation 2**, **Held for a person 0**.
   "Waiting for a person" lists `SYN-APP-015` with **approve** and
   `SYN-APP-014` with **deny**.
2. Switch to **Permit Reviewer**. The navigation lists Work queue, People &
   organizations, Permit workspace, Intake queue and Review queue. The Review
   queue shows **deny pending** for the front-yard case and **approve pending**
   for the rear-yard case. The Permit Reviewer cannot open the agent screens;
   `/agent/intake` returns 403.
3. Open the **front-yard** fence case (`SYN-APP-014`). The **Agent
   recommendation** card shows **deny pending**, "The agent recommends; a person
   confirms or reverts. Nothing is final until confirmed.", and the reason: "DF-1:
   Front yard fence is above the 4 ft maximum. Observed 6 ft is above the 4 ft
   maximum, ACME Code §14-305."
4. Open the **rear-yard** fence case (`SYN-APP-015`). The card shows **approve**,
   citing **DF-2** (6 ft at the 6 ft limit, ACME Code §14-306).

## 8. As Permit Reviewer, confirm the denial and revert the approval

1. On the front-yard case, press **Start** under **Confirm the recommendation**.
   A denial needs a denial reason code: choose **Does not meet code**. Press
   **Confirm**. The decision of record is **denied**, by the Permit Reviewer, and
   the case shows **denied**.
2. On the rear-yard case, press **Start** under **Revert the recommendation**,
   write a reason, and press **Revert**. The page says "Reverted the agent
   recommendation; the case is back in manual review." The recommendation
   becomes **reverted**.
3. The reviewer can now decide the rear case with **Record review decision**.
   In both paths the decision of record is the reviewer's. The agent never
   records it.

## 9. A reviewer comment and an approval with conditions

1. Still as **Permit Reviewer**, open the rear-fence case. On the **People &
   property** tab, press **Start** under **Confirm parcel** and submit it. The
   approval is blocked until the reviewer confirms the parcel. Reload the case.
2. Press **Start** under **Write a comment (applicant-visible or internal)**,
   write "The rear fence complies with DF-2. The gate must open inward." and
   leave **Who may read it** on *Visible to the applicant*. Press **Write the
   comment**. The page says "Added an applicant-visible comment." The case
   version stays the same because a comment changes no state.
3. Press **Start** under **Record review decision**, choose **Approve with
   conditions** in **Outcome**, write "The gate must open inward." in
   **Conditions of approval (one per line)** and "the rear fence complies with
   DF-2" in **Rationale (internal record)**, and press **Record the decision**.
4. The decision panel now reads **Approved with conditions** and lists the
   condition. The condition stays with the decision: the applicant reads it in
   the conditions of approval section of the tracking page, and it is printed
   on the permit artifact.
5. A **Deny** needs a **Denial reason code**, and every outcome needs a
   rationale. The server refuses an approval with conditions that names no
   condition, and the form refuses it as well.

## 10. Fees, reconciliation and issuance (approved rear case only)

1. Switch to **City Administrator**, open **Reconciliation**.
2. Use **Assess application** for the approved rear-fence application (the
   declared valuation comes from its submitted facts; read the assessed total
   off the resulting assessment).
3. Use **Import ERP payment** (ERP is enterprise resource planning) for that
   amount, **Confirm allocation** to allocate the settled receipt to the
   assessment, and **Reconcile assessment**. The screen shows a **0.00** balance
   with an **exact** position.
4. Until this is done, **Issue permit** on the approved case is refused ("the
   permit may not be issued yet", with "Permit issuance: Waiting. Assess the
   fee.").
5. Switch to **Permit Reviewer**, open the rear-fence case, and use **Issue
   permit** with a command key (for example `issue-<application id>`). The page
   shows "Issued the simulated permit ACME-...", and the **Issued permit**
   panel shows the permit number. The printed artifact lists the conditions of
   approval.
6. The denied front-yard case has no assessment path to issuance: its decision
   is final for this walkthrough.

## 11. The City queues

1. Switch to **Data Steward** and open **Intake queue** (the left navigation).
   The saved views are **Active**, **Awaiting agent**, **Needs information**,
   **In review**, **Archived** and **Closed**, each with its count. The two
   fence cases are in **Active** and **In review** until they are decided; the
   closed view holds the issued case of the fixed demonstration corpus.
2. Use **Search** to find a case reference and the filters (**Channel**,
   **Permit type**, **Priority**, **Owner**) and the **Sort**; all of them work
   through the address bar, so they work without JavaScript.
3. The age chip of a case shows its age and is colored against the service
   target of its permit type. The **Signals** column shows only what the server
   holds: the duplicate finding, the scan-quality flags of the received pages,
   the recorded parcel link and what the intake agent left on the case.
4. Open **Early resolution**. The cases that wait for a person are grouped by
   their primary finding, each group with its count and its top findings. With
   the two complete fence cases the page says "No case waits for a person."
5. Switch to **Permit Reviewer** and open **Review queue**. It lists the cases
   in review, the counts per review area, the adjudication recommendation of
   each case, and the recent recorded decisions.
