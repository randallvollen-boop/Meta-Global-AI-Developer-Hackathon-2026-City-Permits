# ACME City Permits operations

This folder explains how fictional permit data arrives from outside the electronic system, how the agent triage pipeline handles it, where people act, and how to run the demo.

The data, rules, fees, people and permits are synthetic. The application binds
to loopback only and is not a municipal system.

## Contents

- `RUNBOOK.md`: data flow, triage steps, human actions, failure handling,
  start, reset and simulate.
- `USER_STORIES.md`: persona and agent user stories with acceptance criteria.
- `USE_CASE_FENCE.md`: a manual browser walkthrough, automated by
  `tests/acceptance/test_use_case_fence.py`.
