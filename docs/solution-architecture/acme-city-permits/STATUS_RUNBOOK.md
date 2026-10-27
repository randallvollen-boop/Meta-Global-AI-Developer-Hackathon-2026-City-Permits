# Architecture Status Runbook

Canonical status file: `STATUS.json`  
AVA Library article ID: `acme-city-permits-architecture`  
Architecture source: `facts.md` plus accepted build/test evidence

## Update rules

1. Update status only after the parent accepts concrete source and test evidence.
2. A worker report, generated file, screenshot or plan is not implementation or verification evidence by itself.
3. `requirements.implemented` counts requirements with an inspected implementation location.
4. `requirements.verified` counts requirements whose mapped executable checks passed against the integrated candidate.
5. `execution.tasks_verified` counts plan tasks whose acceptance checks passed and whose changes were accepted by the parent.
6. AT, VC and D counts come from the final machine-readable acceptance manifest, not test filenames or collection counts.
7. A failed/blocked live Muse run stays `failed` or `blocked`; replay never changes it to passed.
8. Keep `architecture_status` equal to `planned` through implementation. Change it to `as_built` only after AT01–AT20, VC01–VC08, D01–D11, live Muse, restart, idempotent issuance retry and browser gates pass.

## Phase transitions

- Planning → Foundation: requirements outline and plans accepted.
- Foundation → Registry/Permit slices: migrations, reset, four-persona sessions/RBAC, governance and audit checks accepted.
- Registry/Permit slices → Muse/UI: deterministic domain/API gates accepted and integrated.
- Muse/UI → Acceptance: strict model contract, replay/failure behavior, eight screens and browser slice checks accepted.
- Acceptance → As built: complete integrated manifest and local user-test handoff accepted.

## Rebuild and private AVA update

Run from this directory after editing `STATUS.json`:

```bash
python3 -I update_status.py --publish-ava
```

The updater must:

1. Validate status count bounds, phase values and exactly four selectable personas.
2. Replace only the marked status section in `page/body.src.html` and the `info.status` data object.
3. Inline Vollen assets, rebuild with the installed kit and run the Linux checker.
4. Refuse publication on a build/check/status mismatch.
5. Replace the existing private AVA Library article under the same ID with `library_add.py --replace`.
6. Never start or restart the AVA service; its Library files update offline.
7. Write the page hash, checker result and AVA index receipt to `BUILD_REPORT.md` and the project evidence log.

Without `--publish-ava`, the updater rebuilds/checks locally only.
