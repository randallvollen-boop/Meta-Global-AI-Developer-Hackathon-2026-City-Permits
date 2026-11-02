# Impact — steward data is non-blocking

Date: 2026-11-02
Branch: `feature/steward-nonblocking`

## Changed outcomes

- An adjudication run with an open Data Steward parcel link no longer records
  `hold` with “Cannot recommend yet: the parcel is not confirmed. Waiting on
  Data Steward.” It records the merits-based `approve`, `deny`, or
  `approve_with_conditions` outcome from checked rules.
- Parcel-dependent rows whose evaluator reason is `parcel_not_confirmed` stay
  `Not checked`. The recommendation names their published rule title(s); it
  never reports that those checks passed.
- An open parcel or identity link remains Data follow-up. It does not replace
  the review queue’s next action. The payer-account link and assessed,
  reconciled fee remain issuance blockers.
- Parcel-link and registry-link services already accepted their authorized
  corrections after decision and issuance (only archived cases are refused by
  the parcel service; the registry service has no permit-status guard). No
  state-guard relaxation was needed or made.

## Tests changed

| Test | Old assertion | New assertion |
| --- | --- | --- |
| `repo/tests/unit/test_adjudication_disposition.py` | An unconfirmed parcel always held the recommendation. | Checked rules can recommend approval or approval with conditions; a real judgment rule still holds. |
| `repo/tests/unit/test_plain_reason.py` | The old hold sentence plus a generic zoning/flood message. | A merits recommendation plus named Not checked rule(s). |
| `repo/tests/integration/test_intake_triage.py` | A proposed parcel link created a Hold recommendation and a waiting message. | It creates an Approve recommendation and the Data follow-up tag. |
| `repo/tests/integration/test_queue_tags.py` | The tag read “Cannot recommend: parcel not confirmed.” | The tag reads “Data follow-up: parcel not confirmed.” |
| `repo/tests/unit/test_queue_stage.py` | Open steward data made review-queue next action “Waiting on Data Steward.” | Before evaluation the next action is “Needs checks”; after a current evaluation it is “Ready to decide.” |
| `repo/tests/unit/test_walkthrough_paths.py` | The guide’s expected next-action list included “Waiting on Data Steward.” | The list no longer treats Data follow-up as a next action. |

No tests were weakened, skipped, or marked xfail.

## D / AT / DF expectations

- D01–D11 evaluator expected outcomes: **none changed**. The focused D01–D11
  evaluator check passes without editing its expected data. D01–D06, D08,
  D09 and D11 have a review-queue presentation-only expectation in
  `test_queue_stage.py`: “Waiting on Data Steward” → “Needs checks.” D07 is
  issued and D10 has no application row, so neither presentation changes.
- AT01–AT20 expected outcomes: **none changed**.
- DF-1 and DF-2 expected outcomes: **none changed**. A checked DF failure
  still recommends denial; a checked DF pass still supports approval.

## Protected fixtures and hashes

- `repo/tests/regression/data/protected_fixture_hashes.json`: not touched.
- `repo/tests/regression/data/fixture_outcomes.json`: not touched.
- No protected fixture, rule fixture, replay fixture, migration, or acceptance
  expectation was changed; therefore no separate “Acceptance expectations for
  non-blocking steward data (needs Randall)” commit is required.

## Visible text changed

| Where | Old | New |
| --- | --- | --- |
| Adjudication rationale | “Cannot recommend yet: the parcel is not confirmed. Waiting on Data Steward.” | A merits recommendation from checked rules, followed by named Not checked rule(s) when applicable. |
| Recommendation reason | “Not checked: zoning and flood zone, because the parcel is not confirmed.” | “Not checked: <published parcel-rule title(s)>, because the parcel is not confirmed.” |
| Queue tag | “Cannot recommend: parcel not confirmed” | “Data follow-up: parcel not confirmed” |
| Review queue next action | “Waiting on Data Steward” | “Needs checks” before evaluation; “Ready to decide” after a current evaluation; post-approval fee/issue actions remain unchanged. |
| Work-queue fallback | “Waiting for the Data Steward” | “Waiting for the applicant’s answer” |
| Review help, glossary, guided tour, and judge walkthrough | Next-action lists named “Waiting on Data Steward.” | They explain that open parcel/identity links are a Data follow-up tag, not a next-action blocker. |
| Operations runbook and architecture facts | Unconfirmed parcel caused an agent hold. | The agent recommends from checked rules, names Not checked rules, and leaves Data follow-up open. |

No model name was added or changed; Muse remains the only model named in the
changed user-facing copy.

## Verification record

- Final post-change run: `uv run pytest -q` over the six changed-test modules,
  data-follow-up/workspace guides, policy parity, the protected fixture and
  outcome snapshot checks, and D01–D11 — **112 passed in 16.53s**.
- Browser tests were not run; the lead owns that check.
