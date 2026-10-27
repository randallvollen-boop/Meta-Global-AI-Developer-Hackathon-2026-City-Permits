# Integrated Acceptance and Local Handoff Implementation Plan

> **For agentic workers:** Execute after all domain and UI child plans. A failed or blocked gate remains failed/blocked; never weaken checks or relabel replay as live.

**Goal:** Produce executable AT01–AT20, VC01–VC08 and D01–D11 results, verify a full persisted D01 chain with bounded live Muse evidence, and leave one locally launchable environment plus a manual user-test guide.

**Architecture:** Acceptance tests exercise the real FastAPI application, SQLite transactions, server-held sessions and browser. A run coordinator resets an isolated fictional database, records expected/observed evidence, runs checks, restarts the app and hashes artifacts into a manifest.

**Tech Stack:** pytest, HTTPX, Playwright, Python subprocess management, JSON evidence manifests, SHA-256.

**Spec:** `../REQUIREMENTS_OUTLINE.md`

**Parent plan:** `2026-10-26-acme-city-end-to-end.md`

## Global Constraints

- Test wrappers preserve child exit codes and reject empty/fully skipped collections.
- Live provider failures are recorded and block AI-01/full AT19; they never silently select replay.
- Reuse deterministic test evidence only while code, fixture, database schema and environment inputs remain unchanged.
- Final user database is freshly reset and then advanced only through the documented demo preparation path.
- Start/stop scripts operate only on the PID and database under this repository.

### Task A1: Requirement-linked acceptance test inventory

**Requirement:** Provide executable checks for every requirement/check/scenario and prove nonvacuous collection.

**Files:**
- Create: `config/check_inventory.json`
- Create: `tests/acceptance/test_at02.py`
- Create: `tests/acceptance/test_at03.py`
- Create: `tests/supplementary/test_vc06.py`
- Create: `tests/supplementary/test_vc07.py`
- Create: `tests/supplementary/test_vc08.py`
- Create: `tests/evaluator/test_d01_d11.py`
- Create: `scripts/check_requirement_coverage.py`
- Create: `scripts/check_test_collection.py`

**Interfaces:**
- `check_inventory.json` maps each requirement to implementation symbols and executable check node IDs; each AT/VC/D item maps to at least one node ID.
- `check_requirement_coverage.py` exits nonzero on absent symbol/file, duplicate/missing ID or non-collected test node.

**Acceptance checks:**
- `uv run python scripts/check_requirement_coverage.py` → 57/57 requirements, 20/20 AT, 8/8 VC, 11/11 D mapped; zero missing symbols/nodes.
- Persona/session collection asserts exactly four selectable humans—Applicant, Data Steward, Permit Reviewer and City Administrator—and confirms no service identity appears in the selector.
- `uv run pytest --collect-only -q > var/collection.txt && uv run python scripts/check_test_collection.py var/collection.txt` → nonzero tests in unit, API, security, acceptance, supplementary, scenario and browser families.

- [ ] Enumerate exact pytest node IDs for all AT/VC/D checks and requirement-to-symbol references.
- [ ] Implement remaining AT02/AT03 and VC06–VC08 tests through real session/API boundaries.
- [ ] Implement evaluator-only D01–D11 expected-versus-observed checks that read truth only after runtime outputs are complete.
- [ ] Detect skips, xfails and empty families; allow a live-provider skip only when recorded as a blocking result, never as a passing AT19.

### Task A2: Evidence recorder and acceptance runner

**Requirement:** Implement EVAL-01–EVAL-03 and a reproducible integrated run.

**Files:**
- Create: `src/acme_city/evidence/schemas.py`
- Create: `src/acme_city/evidence/manifest.py`
- Create: `scripts/run_acceptance.py`
- Create: `scripts/verify_evidence.py`
- Create: `tests/unit/test_evidence_manifest.py`
- Create: `tests/integration/test_acceptance_runner.py`

**Interfaces:**
- `CheckResult(check_id, status, requirement_ids, expected, observed, evidence_refs, failure)` where status is `passed`, `failed`, or `blocked`.
- `RunManifest` includes build hash, fixture version, database schema revision, source snapshots, model/replay mode, prompt/schema/rule versions, actor/timestamps, expected/actual outcomes, failures and artifact hashes.

**Acceptance checks:**
- `uv run pytest tests/unit/test_evidence_manifest.py tests/integration/test_acceptance_runner.py -q` → pass.
- `uv run python scripts/run_acceptance.py --deterministic --evidence-dir evidence/runs/deterministic` → exactly 20 AT, 8 VC and 11 D result entries; live-dependent checks blocked, not passed.
- `uv run python scripts/verify_evidence.py evidence/runs/deterministic` → valid schema/hashes/references.

- [ ] Implement append-safe evidence writing through temporary file plus atomic rename; include no secrets, cookies or raw authorization headers.
- [ ] Capture test commands, exit codes, collected/passed/failed/skipped counts, duration and exact revision/tree hash.
- [ ] Calculate identity/extraction/workflow denominators separately and label fixture-scale limitations.
- [ ] Keep baseline synthetic metrics, observed Muse/registry results and business outcomes in separate manifest sections.
- [ ] Verify every evidence reference resolves to an existing record ID/version or artifact hash.

### Task A3: Full D01 live, restart and issuance-retry gate

**Requirement:** Complete AI-01, AT15 and full AT19 using bounded live Muse work plus actual steward/reviewer/Finance/issuance actions.

**Files:**
- Create: `scripts/demo_walkthrough.py`
- Create: `tests/integration/test_restart_persistence.py`
- Create: `tests/integration/test_issuance_timeout_retry.py`
- Modify: `scripts/run_acceptance.py` — add explicit `--live-muse` mode and call budget.

**Interfaces:**
- `demo_walkthrough.py --base-url URL --mode live|replay --evidence-dir PATH` uses public app endpoints and actor sessions, not direct database writes.
- Exit 0 only when the requested mode completes and evidence verifies; replay cannot satisfy `--mode live`.

**Acceptance checks:**
- `uv run python scripts/demo_walkthrough.py --base-url http://127.0.0.1:8266 --mode live --evidence-dir evidence/runs/live` → one successful strict-schema Muse task, actual steward/reviewer/Finance/issuance actions and exact reconciliation.
- Stop/restart service, reopen D01 → same application, crosswalk, source, evaluation, decision, assessment, payment, allocation and permit IDs/versions.
- Retry issuance after simulated response loss → same permit ID/number/artifact hash.
- `uv run python scripts/run_acceptance.py --all --live-muse --evidence-dir evidence/runs/final` → all required checks passed, or provider-dependent checks explicitly blocked with provider error and all independent checks still evaluated.

- [ ] Reserve the two-call live budget and execute extraction first; execute matching second only if extraction succeeds and the remaining reservation is covered.
- [ ] Validate and persist the live output before steward action; record any refusal/failure as its own immutable run.
- [ ] Execute the primary chain through session/API calls in this order: applicant submission, Muse proposal, steward rejection/approval, deterministic evaluation, reviewer approval, assessment, account-link approval, Finance allocation, separate issuance.
- [ ] Terminate only the owned server PID, restart on the same database and verify the complete chain.
- [ ] Simulate post-commit issuance response loss and prove identical retry returns the original artifact.

### Task A4: Reliable local launch and manual test handoff

**Requirement:** Leave a user-test environment that starts, stops and resets safely with one documented path.

**Files:**
- Create: `scripts/start_demo.py`
- Create: `scripts/stop_demo.py`
- Create: `scripts/prepare_user_test.py`
- Create: `USER_TEST_GUIDE.md`
- Create: `tests/integration/test_process_management.py`
- Create: `tests/integration/test_user_test_prep.py`

**Interfaces:**
- `start_demo.py --host 127.0.0.1 --port 8266` records PID, command, port, start time and database in `var/demo-process.json` and refuses an occupied port.
- `stop_demo.py` validates process identity before termination and never uses broad `pkill`.
- `prepare_user_test.py` resets, migrates, seeds and optionally prepares an unresolved D01 starting point; it never sends a live model call without `--live-muse`.

**Acceptance checks:**
- `uv run pytest tests/integration/test_process_management.py tests/integration/test_user_test_prep.py -q` → pass.
- Start → health 200 → stop → owned PID gone, unrelated processes untouched.
- `USER_TEST_GUIDE.md` gives URL, roles, primary click path, failure variants, reset/stop commands, known limitations and evidence location.

- [ ] Implement occupied-port and stale-PID checks using process command line and repository process record.
- [ ] Implement preparation modes `fresh`, `ready-for-review`, and `completed-reference`, each clearly labeled; default is `fresh`.
- [ ] Write the manual walkthrough for all eight screens and D01 plus D02/D06/D11 failure demonstrations.
- [ ] Add troubleshooting for missing key, blocked live provider call, schema mismatch, occupied port and database migration mismatch.

### Task A5: Final verification and publication hygiene

**Requirement:** Verify the final local candidate without committing, pushing, deploying or leaking local-only material.

**Files:**
- Create: `scripts/run_all_checks.py`
- Create: `scripts/scan_publishable_tree.py`
- Create: `evidence/README.md`
- Parent create/maintain: `../../docs/solution-architecture/acme-city-permits/STATUS.json`
- Parent create/maintain: `../../docs/solution-architecture/acme-city-permits/update_status.py`
- Parent create/maintain: `../../docs/solution-architecture/acme-city-permits/STATUS_RUNBOOK.md`
- Modify: `../../BUILD_LOG.md` — final commands, counts, environment and limitations.
- Modify: `../../EVIDENCE_LOG.md` — final evidence index and live/replay truth.
- Modify: `../../GO_NO_GO.md` — implementation and local-test gates only.

**Interfaces:**
- `run_all_checks.py` runs formatting/static checks, collection validation, unit/API/security/acceptance/supplementary/scenario/browser checks, preserving every child exit code.
- `scan_publishable_tree.py` excludes ignored paths and fails on key patterns, private email, machine paths, network addresses, real applicant data, unexpected binaries or intake files.

**Acceptance checks:**
- `uv run python scripts/run_all_checks.py --evidence-dir evidence/runs/final` → exit 0, nonzero test count, zero failures/unexpected skips.
- `uv run python scripts/scan_publishable_tree.py` → zero findings.
- `git status --short --ignored` → `intake/`, database, documents, PID files, raw model runs and browser artifacts ignored; source/plans/tests visible.
- Architecture STATUS.json matches accepted evidence counts; the rebuilt STD-29 page carries the same status and AVA Library article `acme-city-permits-architecture` is replaced under the same ID without starting the AVA service.
- No remote, commit, push, deployment, public publication or submission exists.

- [ ] Run the full final checks against the exact local candidate and read complete outputs/exit codes.
- [ ] Run a fresh process/browser check on port 8266 and leave the server running only if health and user-test preparation pass.
- [ ] Record check counts, live/replay status, request/response IDs without secrets, evidence paths and remaining limitations once in root logs.
- [ ] Update architecture STATUS.json only from accepted evidence, rebuild/check the STD-29 page, and replace the private AVA Library article under the same ID. Keep PLANNED / IN IMPLEMENTATION until the complete integrated gate passes; then and only then change to AS BUILT.
- [ ] Leave `USER_TEST_GUIDE.md` and the exact test URL in the final handoff.
