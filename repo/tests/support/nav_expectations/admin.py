"""The navigation grouping of the City Administrator.  Owned by admin-a.

This module holds the grouping only; the agent screens the Administrator may
open are listed in ``agent_grants.py``.

- Changed deliberately (the City Administrator planning overview): the
  Administrator lands on the overview, behind the grant admin.overview.view
  that only the Administrator holds, so it is the first entry.
- Steward restyle: Master records holds People & organizations as a tab, so
  "applicants" is not listed; Source records and Activity follow Data issues.
- P3insight adds the City view (insight.city.view), policy 2 the What-if
  screen (policy.scenario.manage) and P3c the four operations screens, each
  behind its own grant that only the Administrator holds.
"""

from __future__ import annotations

ACTOR_ID = "persona_city_administrator"

#: The screens of the side navigation, in the order they are listed.
PRIMARY: tuple[str, ...] = (
    "overview",
    "queue",
    "masters",
    "permit",
    "steward",
    "source_records",
    "activity",
    "rules",
    "reconciliation",
    "governance",
    "admin",
    "insight_city",
    "policy_scenarios",
    "ops_dashboard",
    "ops_audit",
    "ops_support",
    "ops_checks",
)

#: The screens under More tools.
SECONDARY: tuple[str, ...] = ()
