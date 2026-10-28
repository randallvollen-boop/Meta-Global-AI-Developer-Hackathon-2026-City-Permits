# ACME City permit application

This directory holds the ACME City permit application, built on registry master data management (MDM).

## Current state

The application is built. Phases 1, 2 and 3 (3a, 3b, chat 1 and 2, insight, and policy 1 to 4) are merged on main and verified by the 10 checks in `scripts/run_all_checks.py`. `USER_TEST_GUIDE.md` and `../docs/operations/` explain how to run and test it.

## Source of truth

The authoritative requirements remain outside this repository in the ignored intake evidence:

`../intake/extracted/ACME_MDM_Build_Package/requirements/ACME_MDM_Demo_Requirements.txt`

`../CITY_PERMIT_ALIGNMENT.md` holds the reviewed application mapping. Do not copy the intake tree into Git, and do not modify the preserved reference application in place.

## Implementation areas

- governance and source registration;
- source snapshots and quarantine;
- registry identities, crosswalks, provenance, and stewardship;
- source corrections, acknowledgments, outbox, and impact tasks;
- versioned permit applications, evaluations, reviewer decisions, and issuance;
- governed rules, fees, payment events, allocations, and reconciliation;
- Meta Muse Standard adapter with validated proposals and labeled replay;
- server-held fictional actors, scoped permissions, and audit history;
- automated AT01 to AT20 and VC01 to VC08 checks with D01 to D11 evidence.

The stack is Python 3.12 with FastAPI, SQLAlchemy and Alembic, one SQLite database, server-rendered HTML with vanilla JavaScript, three in-process source adapters and a database-backed outbox.
