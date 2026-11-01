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
- Admin-a groups the navigation (ADA-3): the daily work stays in the bar and
  every other screen moves under More tools, so the bar shows only the
  screens an administrator works in.  The two groups together keep the order
  of the screens, so the grouping never moves a destination.
"""

from __future__ import annotations

ACTOR_ID = "persona_city_administrator"

#: The screens of the side navigation, in the order they are listed.
PRIMARY: tuple[str, ...] = (
    "overview",
    "rules",
    "reconciliation",
    "governance",
    "admin",
)

#: The screens under More tools.
SECONDARY: tuple[str, ...] = (
    "queue",
    "masters",
    "permit",
    "steward",
    "source_records",
    "activity",
    "insight_city",
    "policy_scenarios",
    "ops_dashboard",
    "ops_audit",
    "ops_support",
    "ops_checks",
)
