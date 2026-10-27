# Manual use case: the fence permit

Follow these steps in the browser. Every step names the screen, what to
click, and what you should see — including the exact agent outcomes. The same
steps are proven automatically by
`tests/acceptance/test_use_case_fence.py`.

All records are fictional. Deterministic note: the simulated scenarios always
use portal references `PORTAL-2026-FENCE-FRONT-001` and
`PORTAL-2026-FENCE-REAR-001` (first run on a fresh database) and create the
next application numbers in sequence. Exact fee/payment amounts in step 6 are
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

1. Click **City Administrator**. The left navigation lists all eight screens.
2. Click **Governance and sources** in the left navigation.
3. Open **Simulate incoming permits**, set **Scenario** to
   `fence-front-too-tall`, and click **Simulate incoming permits**. You should
   see "Simulated 1 incoming permit(s); 1 new application(s)" in the Last
   action region.
4. Repeat with **Scenario** `fence-conforming-rear`.
5. (Equivalent terminal path: `uv run python scripts/simulate_intake.py
   --scenario fence-front-too-tall` and `--scenario fence-conforming-rear`.)

## 3. Watch the triage run

1. Click **Work queue**. Both new fence applications are listed
   (`deck_fence`, submitted through the portal).
2. Open one. In **Recommendation and decision** you should see the
   **Agent recommendation** card and the **Agent steps** table with five
   steps — intake, identity, extraction, rules, recommendation — each naming
   its service identity and outcome. The Muse run tab shows the replayed
   extraction run labelled **Replay** with "Proposes values" wording.

## 4. As Data Steward, approve identity links and extracted values

1. Switch persona to **Data Steward** (top-right persona control). The left
   navigation now lists only Queue, Applicants, Properties, Permit, Steward
   review and Rules — Reconciliation and Governance are gone and return 403
   if visited directly.
2. Click **Steward review**. For each proposed link from `intake_portal` /
   `submitted_applications`, use **Confirm link** with a reason.
3. Open each fence case from the **Work queue**. Where extracted values are
   proposed, use **Accept or correct extracted …** next to the Decision
   actions: accept the value, or correct it (corrected value + reason are
   required).

## 5. As Permit Reviewer, read the recommendation and decide

1. Switch to **Permit Reviewer**. Navigation lists Queue, Applicants and
   Permit workspace.
2. Open the **front-yard** fence case. The Agent recommendation card shows
   the outcome **deny** with the rationale citing **DF-1** ("Front yard fence
   is above the 4 ft maximum … ACME Code §14-305", observed 6, limit 4) and
   "Advisory. The Permit Reviewer decides."
3. Optionally record your stance with **Record stance on the agent
   recommendation** (disagreeing requires a reason).
4. Record the decision with **Record reviewer decision**: outcome **denied**,
   reason referring to DF-1. You should see "Recorded the reviewer decision
   'denied'."
5. Open the **rear-yard** fence case. The recommendation is **approve**
   (DF-2 passed: 6 ft side/rear fence at the 6 ft limit). Record the decision
   **approved** with your reason.

## 6. Fees, reconciliation and issuance (approved rear case only)

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
   panel shows the permit number.
5. The denied front-yard case has no assessment path to issuance: its
   decision is final for this walkthrough.
