# Manual use case: the fence permit

Follow these steps in the browser. Every step names the screen, what to
click, and what you should see — including the exact agent outcomes. The same
steps are proven automatically by
`tests/acceptance/test_use_case_fence.py`.

All records are fictional. Deterministic note: the simulated scenarios always
use portal references `PORTAL-2026-FENCE-FRONT-001` and
`PORTAL-2026-FENCE-REAR-001` (first run on a fresh database) and create the
next application numbers in sequence. Exact fee/payment amounts in step 8 are
taken from the Reconciliation screen of *your* run — read them off the page;
do not expect a fixed total.

## 1. Reset and start the app

```bash
cd repo
uv run python scripts/prepare_user_test.py --mode fresh
uv run python scripts/start_demo.py --host 127.0.0.1 --port 8266
```

Open <http://127.0.0.1:8266>. You should see **Choose a persona** with exactly
four personas: Applicant, Data Steward, Permit Reviewer, City Administrator.

## 2. As City Administrator, simulate the two fence cases

1. Click **City Administrator**. The left navigation lists all eleven
   screens: the eight original ones plus **Intake agent**, **Adjudication
   agent** and **Administration**.
2. Click **Governance and sources** in the left navigation.
3. Open **Simulate incoming permits**, set **Scenario** to
   `fence-front-too-tall`, and click **Simulate incoming permits**. You should
   see "Simulated 1 incoming permit(s); 1 new application(s)" in the Last
   action region.
4. Repeat with **Scenario** `fence-conforming-rear`.
5. (Equivalent terminal path: `uv run python scripts/simulate_intake.py
   --scenario fence-front-too-tall` and `--scenario fence-conforming-rear`.)

Both cases now wait. Nothing has been triaged.

## 3. As City Administrator, wake the intake agent

1. Click **Intake agent** in the left navigation.
2. The banner reads **asleep** and the run buttons are disabled with "The
   agent is asleep. Wake the agent first."
3. Click **Wake agent**. The banner now reads **awake** and the KPI cards
   show **Waiting 2**, **Processed 0**, **Needs human 0**, **Errors 0**.
4. The pipeline diagram shows the six nodes — Classifier, then Field
   extractor and Document QC side by side, then Duplicate finder and
   Completeness side by side, then Router — with the legend "Columns run in
   parallel; arrows are dependencies".

## 4. As Data Steward, run the intake agent

1. Switch persona to **Data Steward** (top-right persona control). The left
   navigation now lists Work queue, Applicants, Properties, Permit
   workspace, Steward review, Rules and fees plus **Intake agent**.
   Reconciliation, Governance, Adjudication agent and Administration are
   gone and return 403 if visited directly.
2. Click **Intake agent**. The waiting list holds both fence cases.
3. Click **Process all waiting**.
4. The run history now shows one run with the six-node trace: Classifier
   **ok**, Field extractor **ok**, Document QC **ok**, Duplicate finder
   **ok**, Completeness **ok**, Router **ok**.
5. Both cases are now **ready_for_review** in the **Building** review area,
   and the identity links are proposed for you to approve.

## 5. As Data Steward, approve the links and the extracted values

1. Click **Steward review**. For each proposed link from `intake_portal` /
   `submitted_applications`, use **Confirm link** with a reason.
2. Open each fence case from the **Work queue**. Where extracted values are
   proposed, use **Accept or correct extracted …**: accept the value, or
   correct it (corrected value + reason are required).

## 6. As City Administrator, wake the adjudication agent

1. Switch to **City Administrator** and open **Adjudication agent**.
2. Click **Wake agent**. The banner reads **awake**; the KPIs show **In
   review 2**, **Recommended 0**, **Awaiting confirmation 0**, **Held for a
   person 0**.
3. The pipeline diagram shows the five nodes — Rule loader, Rule evaluator,
   then Condition builder and Precedent check side by side, then Disposition.

## 7. As Permit Reviewer, run the adjudication agent

1. Switch to **Permit Reviewer**. The navigation lists Work queue,
   Applicants, Permit workspace plus **Adjudication agent**.
2. Click **Adjudication agent** and click **Run all**.
3. The **front-yard** fence is recommended **deny**, citing **DF-1** (6 ft
   above the 4 ft maximum, ACME Code §14-305).
4. The **rear-yard** fence is recommended **approve**, citing **DF-2**
   (6 ft at the 6 ft limit).

## 8. As Permit Reviewer, confirm the denial and revert the approval

1. Open the **front-yard** fence case. The **Agent recommendation** card
   shows the outcome pill **deny**, the rule rows with their citations, the
   pipeline trace and "The agent recommends; a person confirms or reverts.
   Nothing is final until confirmed."
2. Click **Confirm**. The decision of record is **denied**, by the Permit
   Reviewer. The case shows **denied**.
3. Open the **rear-yard** fence case and click **Revert** with a reason. The
   recommendation becomes **reverted** and the case returns to manual review.
   You may now either confirm the recommendation or decide the case yourself
   with **Record reviewer decision**.
4. Either way, the decision of record is yours: the agent never records it.

## 9. A reviewer comment and an approval with conditions

1. Still as **Permit Reviewer**, open the rear-fence case (the one whose
   recommendation you reverted).
2. In the **Case record** panel, open **Write a comment**, write "The rear
   fence complies with DF-2. The gate must open inward." and leave **Who
   may read it** on *Visible to the applicant*. The comment is written and
   audited; the case version does not move, because a comment changes no
   state.
3. Open **Record the reviewer decision**, choose **Approve with
   conditions**, write "The gate must open inward." in **Conditions of
   approval** (one per line) and the rationale "the rear fence complies
   with DF-2" in **Rationale**, and submit.
4. The decision panel now reads **Approved with conditions** and lists the
   condition. The condition travelled with the decision: the applicant
   reads it on the tracking page as "Conditions of your approval", and it
   is printed on the permit artifact.
5. A **Deny** needs a denial reason code and every outcome needs a
   rationale: an approval with conditions that names no condition is
   refused by the server, not only by the form.

## 10. Fees, reconciliation and issuance (approved rear case only)

1. Switch to **City Administrator**, open **Reconciliation**.
2. Use **Assess application** for the approved rear-fence application (the
   declared valuation comes from its submitted facts; read the assessed total
   off the resulting assessment).
3. Use **Import ERP payment** for that amount, **Confirm allocation** to
   allocate the settled receipt to the assessment, and **Reconcile
   assessment**. You should see a **0.00** balance with an **exact** position.
4. Switch to **Permit Reviewer**, open the rear-fence case, and use
   **Issue permit** with a command key (e.g. `issue-<application id>`). You
   should see "Issued the simulated permit ACME-…" and the **Issued permit**
   panel shows the permit number. The printed artifact carries the
   conditions of approval.
5. The denied front-yard case has no assessment path to issuance: its
   decision is final for this walkthrough.

## 11. The queues of the City

1. Switch to **Data Steward** and open **Intake queue** (the left
   navigation, below **Intake agent**). The saved views are **Active**,
   **Awaiting agent**, **Needs information**, **In review**, **Archived** and
   **Closed**, each with its count. The two fence cases are in **Active**
   and **In review**; the closed view holds the issued case of the fixed
   demonstration corpus.
2. Use **Search** to find `PORTAL` and the filters (**Channel**, **Permit
   type**, **Priority**, **Owner**) and the **Sort**; everything works
   through the address bar, so it works without JavaScript.
3. The age chip of a case shows its real age and is coloured against the
   service target of its permit type. The **Signals** column shows only what
   the server holds: the duplicate finding, the scan-quality flags of the
   received pages, the recorded parcel link and what the intake agent left
   on the case.
4. Open **Early resolution**: the cases that wait for a person are grouped
   by their primary finding, each group with its count and its top findings.
5. Switch to **Permit Reviewer** and open **Review queue**: the cases in
   review, the counts per review area, the adjudication recommendation of
   each case and the decisions that were recorded recently.
