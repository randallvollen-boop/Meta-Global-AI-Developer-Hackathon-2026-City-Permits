# ACME City local user test guide

The application uses fictional ACME City records, rules, fees, payments and permits. It does not connect to a municipality or issue an official permit.

## Start the application

Run these commands from the `repo/` directory:

```bash
uv run python scripts/prepare_user_test.py --mode fresh
uv run python scripts/start_demo.py --host 127.0.0.1 --port 8266
```

Open <http://127.0.0.1:8266>. The server binds only to the local computer.

The fictional City of Acme website is at <http://127.0.0.1:8266/city/>. The Permits button selects the Applicant persona through the same persona selector and opens the applicant pages inside the city layout. The floating "Demo: switch user" control, on both the website and the staff app, switches between the four personas.

The selector offers exactly four personas:

1. Applicant
2. Data Steward
3. Permit Reviewer
4. City Administrator

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
3. Run **Validate application** and inspect the deterministic rule results
4. Record the reviewer decision as **approved**
5. Switch to **City Administrator**
6. Open **Reconciliation**
7. Assess `app_synth_001` at `50000.00`
8. Allocate `150.00` from `payment_d01_settled` with a new idempotency key
9. Reconcile the assessment and confirm a `0.00` balance with exact status
10. Switch to **Permit Reviewer**
11. Return to the permit workspace and issue the simulated permit with a new command key
12. Repeat the issuance action with the same command key and confirm that the permit number and artifact remain unchanged

Each governed detail screen shows Owner, Steward, Source, Change this in, Last source update, Last received, Version and Open issues. Submitted, proposed, current and issued values use separate visual treatments.

## Full stewardship path from fresh fixtures

Choose **Data Steward**, open **Data issues** and, under "Work from a source record", propose then confirm these four synthetic D01 links (ERP means enterprise resource planning):

| Source | Dataset | Record |
| --- | --- | --- |
| ERP Finance | `business_licensing_register` | `ERP-BL-00412` |
| Permitting | `applicant_profiles` | `PER-AP-0003` |
| ERP Finance | `finance_accounts` | `ERP-ACC-77120-LEG` |
| Permitting | `contractor_register` | `PER-CR-00188` |

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

Open **Data issues** as Data Steward (the steward-demo prepare mode below puts the Cedarline comparisons in the queue). Open the issue for `ERP-BL-00413` or `PER-AP-0004` and compare it with the existing Cedarline records. The similarly named organization remains a separate canonical party. Reject or leave unsupported links unresolved.

### D06 source correction

Use **Master records** (People & organizations) or a Data issues case to request a correction. Inspect the destination, proposed value, evidence, affected applications and required rechecks before any transition. A correction request does not overwrite the submitted application snapshot.

### D11 financial exceptions

Open **Reconciliation** as City Administrator. Review the synthetic partial, overpaid, reversed, unsettled, other-currency and unmatched payments. Each exception retains its own status, balance and reason. None can issue a permit without exact settled allocation.

### Access control

Choose Applicant and try to open another applicant's direct permit URL. The server returns a permission denial. Switch to City Administrator and try to approve a permit. Configuration access does not provide reviewer authority.

## Cedarline steward demonstration

```bash
uv run python scripts/prepare_user_test.py --mode steward-demo
```

This adds three *proposed* links to **Data issues** (Permitting `PER-AP-0003`, ERP `ERP-BL-00412` and `ERP-BL-00413`) so the queue holds the Cedarline comparison: Cedarline Coffee Roasters LLC (alias Cedar Line Coffee Roasters) against Cedarline Coffee Works LLC, a different license number and a different unit. Nothing is decided. Choose **Data Steward**, open **Data issues**, open the `ERP-BL-00413` issue and read the six questions in order, preview an action, then press **Reject match** or **Confirm link**. The mode is a prepare mode; the default reset and every acceptance fixture hold no steward issue.

## Automatic linking demonstration

```bash
uv run python scripts/prepare_user_test.py --mode steward-automation
```

This prepares the Cedarline demonstration and one link the automatic linking applied. The policy of the Data Steward is activated for the applicant records, the worker of the City compares the accepted record with the master records and applies the link that passes every check. The link waits in **Data issues** until a person has looked at it.

Choose **Data Steward** and open **Data issues**. The applied link is a row of its own: open it and read the score, the evidence of the comparison and the two controls. Press **Keep this link** to record that the master record is right, or press **Undo this link**, give a reason, and the link is taken back while the event that applied it stays in the trail. Then open **Automatic linking** to read the policy, preview the accepted records and pause the automation.

The settings screen says that this deployment runs the automation paused, because no new record is queued for the worker here. The link in the queue was applied while the mode was prepared, and it waits for your review. The mode is a prepare mode. The default reset, the Cedarline demonstration and every acceptance fixture hold no applied link, and the linking service never calls a model provider.

## Prepared states

```bash
# Reset only; all D01 work remains open
uv run python scripts/prepare_user_test.py --mode fresh

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
