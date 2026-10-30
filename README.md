# City Permits Hackathon Option

Sibling workspace for the ACME City permitting option, built on registry master data management (MDM), for the 2026 Meta Global AI Developer Hackathon.

## Status

- Package copied and extracted: complete.
- Requirements aligned to the city-permit target: complete at planning and scaffold level.
- Application implementation: built under `repo/`. Phases 1, 2 and 3 are merged on main and verified by the 10 checks in `repo/scripts/run_all_checks.py`.
- Full requirement outline: `repo/docs/REQUIREMENTS_OUTLINE.md`.
- Executable parent plan: `repo/docs/plans/2026-10-26-acme-city-end-to-end.md`.
- Vollen architecture: a checked internal draft is published in the team's internal knowledge library as `acme-city-permits-architecture`. Progress is recorded in `docs/solution-architecture/acme-city-permits/STATUS.json`.
- Deployment: the public demo is hosted on Render at https://acme-city-permits.onrender.com with live Muse off; the deployment runbook is `docs/operations/DEPLOY_RENDER.md`. The submission is Randall's own action and has not been made.
- Later lanes on top of phases 1 to 3: the Muse Wonder redesign, the policy what-if, the applicant help assistant, the City of Acme website and town map, ePermit intake, the intake and adjudication agents with the Agent Operator persona and a durable work queue, the steward Data issues workspace and automatic linking (paused on the hosted demo), and a production mode separate from demo mode.

## Workspace map

| Path | Purpose |
| --- | --- |
| `intake/archive/` | Preserved downloaded ZIP archive |
| `intake/extracted/ACME_MDM_Build_Package/` | Preserved extracted package and original ACME reference application |
| `CITY_PERMIT_ALIGNMENT.md` | Product, architecture, screen, workflow, and acceptance alignment |
| `CONTEXT.md` | Current facts, decisions, and unresolved gates |
| `GO_NO_GO.md` | Implementation and external-action gates |
| `RISK_LIST.md` | Known source, implementation, evidence, and publication risks |
| `BUILD_LOG.md` | Work history |
| `EVIDENCE_LOG.md` | Intake and verification receipts |
| `docs/solution-architecture/acme-city-permits/` | Vollen standard STD-29 fact sheet, progress status, page build and checks |
| `repo/` | New application implementation and executable plans |
| `work/` | Local analysis and temporary project evidence |

## Start here

1. Read `AGENTS.md` and `CONTEXT.md`.
2. Read the authoritative specification:
   `intake/extracted/ACME_MDM_Build_Package/requirements/ACME_MDM_Demo_Requirements.txt`.
3. Read `CITY_PERMIT_ALIGNMENT.md` and `GO_NO_GO.md`.
4. Use `repo/` only after implementation is explicitly released.

The original RailFlow workspace remains separate at `../Meta-Global-AI-Developer-Hackathon-2026/`.

## License

Copyright © 2026 Randall Vollen and VollenData. All rights reserved. Public for transparency, hackathon evaluation and demonstration only; no permission to reproduce, modify, redistribute, sublicense, host commercially or sell without written authorization from Randall Vollen. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
