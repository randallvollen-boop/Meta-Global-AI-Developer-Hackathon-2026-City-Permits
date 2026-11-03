# Internal workspace map

This is the internal map of the ACME City Permits workspace. It is a working note for the people who build this project. The judge facing front page is the top level `README.md`.

## Where things are

| Path | Purpose |
| --- | --- |
| `AGENTS.md` | The workspace rules and the current authority |
| `CONTEXT.md` | Current facts, decisions and unresolved gates |
| `GO_NO_GO.md` | Implementation and external action gates |
| `RISK_LIST.md` | Known source, implementation, evidence and publication risks |
| `HANDOFF.md` | The handover note for the next session |
| `BUILD_LOG.md` | Work history |
| `EVIDENCE_LOG.md` | Intake and verification receipts |
| `CITY_PERMIT_ALIGNMENT.md` | Product, architecture, screen, workflow and acceptance alignment |
| `docs/process/` | Process notes, including this map |
| `docs/submission/` | The submission and the judge walkthrough |
| `docs/operations/` | The deploy runbook, the production readiness note, the runbook, the user stories, the fence use case and the plan for assistants through the Model Context Protocol (MCP) |
| `docs/solution-architecture/acme-city-permits/` | The standard architecture fact sheet, the progress status, the page build and its checks |
| `docs/build-story/` | The engine ledger and the screens captured along the way |
| `repo/` | The application implementation, the fixtures, the migrations, the tests and the plans |
| `repo/docs/REQUIREMENTS_OUTLINE.md` | The execution index of the 57 requirements |
| `repo/USER_TEST_GUIDE.md` | The local run commands and the prepared demo states |
| `LICENSE` and `NOTICE` | The all rights reserved license and the notice |
| `render.yaml` | The Render blueprint for the hosted demonstration |
| `.github/workflows/checks.yml` | The ten local gates on every push |

## Where the source evidence is

The preserved source evidence is local and is not tracked in Git.

* `intake/archive/` holds the downloaded package archive.
* `intake/extracted/ACME_MDM_Build_Package/` holds the extracted package and the original ACME reference application. The authoritative specification is `requirements/ACME_MDM_Demo_Requirements.txt` inside it.
* `work/` holds local analysis and temporary project evidence.

Do not modify or run the bundled reference code in place. Build new work under `repo/`.

## Where to start

1. Read `AGENTS.md` and `CONTEXT.md`.
2. Read the authoritative specification in the preserved package.
3. Read `CITY_PERMIT_ALIGNMENT.md` and `GO_NO_GO.md`.
4. Use `repo/` only after implementation is explicitly released.
