# City of Acme local user test guide

The application uses fictional City of Acme records, rules, fees, payments and permits. It does not connect to a municipality or issue an official permit.

## Start the application

Run these commands from the `repo/` directory:

```bash
uv run python scripts/prepare_user_test.py --mode fresh
uv run python scripts/start_demo.py --host 127.0.0.1 --port 8266
```

Open <http://127.0.0.1:8266>. The server binds only to the local computer.

The fictional City of Acme website is at <http://127.0.0.1:8266/city/>. The Permits button selects the Applicant persona through the same persona selector and opens the applicant pages inside the city layout. The Demo controls menu in the top right, on both the website and the staff app, switches between the five personas.

The selector offers exactly five personas, in the order a permit moves through them:

1. Applicant: applies for a permit on the City website and tracks it.
2. Agent Operator: wakes the intake and adjudication agents and asks them to process waiting cases (Wake agent, then the batch button, which reads Process N cases, or Process the next 20 of N when more than 20 cases are waiting, or Process one). Under More tools the Intake queue holds the batch action "Process selected with agent". The Agent Operator records no permit decision. The Data Steward can also wake the Steward assistant from Data issues with Wake or Put to sleep.
3. Data Steward: approves identity and parcel links and works the Data issues queue.
4. Permit Reviewer: confirms the parcel, runs the application checks, records the review decision and issues the permit.
5. City Administrator: assesses fees, reconciles payments, configures the app and reads the audit log.

Service accounts and internal role templates never appear in the selector.

## Recommended browser walkthrough

A replay-labelled starting point exercises the Muse contract without sending a provider request:

```bash
uv run python scripts/stop_demo.py
uv run python scripts/prepare_user_test.py --mode ready-for-review
uv run python scripts/start_demo.py --host 127.0.0.1 --port 8266
```

1. Choose **Permit Reviewer**
2. Open **Permit workspace** and select `SYN-APP-001`
3. Run **Run application checks** and inspect the deterministic rule results
4. Use **Record review decision** to record the outcome **approved**
5. Switch to **City Administrator**
6. Open **Reconciliation**
7. Assess `app_synth_001` at `50000.00`
8. Allocate `150.00` from `payment_d01_settled` with a new idempotency key
9. Reconcile the assessment and confirm a `0.00` balance with exact status
10. Switch to **Permit Reviewer**
11. Return to the permit workspace and issue the simulated permit with a new command key
12. Without reloading the page, submit the same Issue permit form again and confirm that the permit number and artifact remain unchanged. A retry is the same command only while the form still carries the same command key and the same expected versions; a reloaded page carries the new versions.

Each governed detail screen shows Owner, Steward, Source, Change this in, Source last changed, Last received or checked, Version and Open recorded issues. Submitted, proposed, current and issued values use separate visual treatments.

## Full stewardship path from fresh fixtures

Choose **Data Steward**, open **Data issues** and, under "Work from a source record", propose then confirm these four synthetic D01 links (ERP means enterprise resource planning):

| Source system | Dataset | Record |
| --- | --- | --- |
| `erp_finance` | `business_licensing_register` | `ERP-BL-00412` |
| `permitting` | `applicant_profiles` | `PER-AP-0003` |
| `erp_finance` | `finance_accounts` | `ERP-ACC-77120-LEG` |
| `permitting` | `contractor_register` | `PER-CR-00188` |

Type the source system value exactly as shown in the table. A display name such as "ERP Finance" is refused with a 403.

The Finance account decision creates the governed payer link used by assessment and allocation. Continue with the reviewer and City Administrator steps above.

The model extraction can also be exercised through the bounded walkthrough script. Replay is the default evidence path:

```bash
uv run python scripts/demo_walkthrough.py \
  --base-url http://127.0.0.1:8266 \
  --mode replay \
  --evidence-dir evidence/runs/manual-replay
```

Replay evidence is always labelled `replay` and does not satisfy a live-provider check.

## Failure and exception demonstrations

### D02 false friend

Open **Data issues** as Data Steward (every reset puts the Cedarline comparisons in the queue; see the steward demonstration below). Open the issue for `ERP-BL-00413` and compare it with the existing Cedarline records. The similarly named organization remains a separate canonical party. Reject or leave unsupported links unresolved.

### D06 source correction

Use **Master records** (People and organizations) or a Data issues case to request a correction. Inspect the destination, proposed value, evidence, affected applications and required rechecks before any transition. A correction request does not overwrite the submitted application snapshot.

### D11 financial exceptions

Open **Reconciliation** as City Administrator. Review the synthetic partial, overpaid, reversed, unsettled, other-currency and unmatched payments. Each exception retains its own status, balance and reason. None can issue a permit without exact settled allocation.

### Access control

Choose Applicant and try to open another applicant's case. The page `/permits/app_synth_001` returns 404 ("That application is not available to you"), and the API `/api/permits/applications/app_synth_001` returns 403. The Applicant's own case, `/permits/app_d05`, opens. Switch to City Administrator and try to approve a permit. Configuration access does not provide reviewer authority.

## Synthetic year demonstration

```bash
uv run python scripts/prepare_user_test.py --mode demo-synthetic
```

This resets the fictional fixtures and loads the synthetic year of permits (the same loader the hosted demo uses, with its default seed and count unless you pass `--synthetic-seed` and `--synthetic-count`). The Run the city path of the judge walkthrough (`docs/submission/JUDGE_WALKTHROUGH.md`), the City view at `/insight/city` and the resident search at `/city/community`, need it. The mode is a prepare mode; it does not start the server. Start the app afterwards with `uv run python scripts/start_demo.py --host 127.0.0.1 --port 8266`.

## Steward assistant demonstration

```bash
uv run python scripts/prepare_user_test.py --mode steward-demo
```

Every reset now builds the steward demonstration, so `--mode fresh` holds the same tasks; this mode is kept as a named way to prepare them. **Data issues** holds five tasks the steward assistant can work on, none of them decided:

- four *proposed* links: Permitting `PER-AP-0003`, ERP `ERP-BL-00412` and `ERP-BL-00413` (the Cedarline comparison: Cedarline Coffee Roasters LLC, alias Cedar Line Coffee Roasters, against Cedarline Coffee Works LLC, a different license number and a different unit), and ERP `ERP-BL-00710`, the business license of Quarry Lane Imports LLC;
- one open issue where two versions of the Quarry Lane Imports LLC record disagree.

Choose **Agent Operator**, open **Agents**, click **Steward assistant** under **Agent status** and press **Wake agent**. Then choose **Data Steward**, open **Data issues** and press **Prepare recommendations** (up to 20 tasks per press). The rows show all three levels: **High** on the three links the source ties to one master record, **Review** on `ERP-BL-00413`, which fits two master records almost equally well, and **Held** on the conflicting issue, which only a person may settle. Each row has a one-line reason.

Open the `ERP-BL-00413` task. The assistant panel shows the evidence and **Accept recommendation**, **Clear recommendation** and **Explain with Muse** (on for the hosted demonstration, with a daily allowance of 100 calls; off while live Muse is off or that allowance is used up, with a note). Read the six questions in order, preview an action, then press **Reject match** or **Confirm link**. Back on **Data issues**, **Accept all high-confidence (3)** opens the list of the three High links; **Accept these 3 recommendations** accepts exactly that list, and an item that changed in between is skipped and named. **Agreement with the assistant** then reads "N accepted unchanged of M prepared in the last 7 days".

On the hosted demo (the `ready-for-review` seed) the two Cedarline links the walkthrough approves, `PER-AP-0003` and `ERP-BL-00412`, are already decided, so Quarry Lane Imports LLC (`ERP-BL-00710`) is the High task.

## Automatic linking demonstration

```bash
uv run python scripts/prepare_user_test.py --mode steward-automation
```

This prepares the Cedarline demonstration and one link the automatic linking applied. The policy of the Data Steward is activated for the applicant records, the worker of the City compares the accepted record with the master records and applies the link that passes every check. The link waits in **Data issues** until a person has looked at it.

Choose **Data Steward** and open **Data issues**. The applied link is a row of its own: open it and read the score, the evidence of the comparison and the two controls. Press **Keep this link** to record that the master record is right, or press **Undo this link**, give a reason, and the link is taken back while the event that applied it stays in the trail. Then open **Steward automation** to read the policy, preview the accepted records and pause the automation.

The settings screen says that this deployment runs the automation paused, because no new record is queued for the worker here. The link in the queue was applied while the mode was prepared, and it waits for your review. The mode is a prepare mode. The default reset, the Cedarline demonstration and every acceptance fixture hold no applied link, and the linking service never calls a model provider.

## Prepared states

```bash
# Reset only; all D01 work remains open and the steward demonstration tasks wait in Data issues
uv run python scripts/prepare_user_test.py --mode fresh

# Reset plus the synthetic year of permits (the Run the city path)
uv run python scripts/prepare_user_test.py --mode demo-synthetic

# Replay-labelled Muse evidence and approved identity links
uv run python scripts/prepare_user_test.py --mode ready-for-review

# Replay-labelled completed reference with one simulated issued permit
uv run python scripts/prepare_user_test.py --mode completed-reference
```

Preparation refuses to reset the database while the owned demo server is running. Stop the server first.

## Stop and reset

```bash
uv run python scripts/stop_demo.py
uv run python scripts/prepare_user_test.py --mode fresh
```

The stop command validates the recorded process identity before sending a signal. It never uses a broad process kill.

## Evidence and checks

Runtime evidence is under `evidence/runs/` and remains outside Git. Useful commands:

```bash
uv run python scripts/check_requirement_coverage.py
uv run python scripts/run_acceptance.py --deterministic --evidence-dir evidence/runs/deterministic
uv run python scripts/verify_evidence.py evidence/runs/deterministic
uv run python scripts/run_all_checks.py --evidence-dir evidence/runs/final
```

Deterministic acceptance leaves live-only AT15 and AT19 blocked. On October 27, 2026, one authorized Standard-mode `muse-spark-1.3` extraction returned an incomplete provider response with no output text. The failed run and provider response identifier are recorded under `evidence/runs/live/`. No retry was sent because the primary extraction did not succeed.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Port 8266 is occupied | Stop the recorded server with `uv run python scripts/stop_demo.py`. If no record exists, choose another loopback port. |
| Process record is stale | Run the stop command. It removes a stale record after confirming the process identifier (PID) is gone. |
| Database is not marked as the fictional demo | Use `prepare_user_test.py`; do not delete or repoint an unknown database. |
| Database schema is out of date | Run `uv run alembic upgrade head`, then prepare the fictional demo again. |
| Meta key is missing | Replay mode stays available. Live mode needs the server-side `META_API_KEY` in `~/.config/ai-keys.env`. Never place the key in a browser form or repository file. |
| Muse response is refused, incomplete or invalid | Keep the failed run as evidence. Replay does not replace live evidence. Do not retry automatically. |
| A form reports a token error | Reload the page after switching personas, then submit the action again. |

Post-issuance inspection scheduling is a later-phase concept and is not implemented in this local candidate.
