"""The display metadata of the navigation: icons, short labels and persona dots.

The shared frame reads these tables as Jinja globals.  ``SCREEN_ICONS`` names
the symbol of each screen in the side navigation, ``SCREEN_SHORT`` is the
short label of the mobile navigation and ``PERSONA_DOTS`` is the colour of the
dot beside the acting persona.  The keys of the reserved screens are listed
now so that a lane that builds one of them does not edit this file.
"""
# REQUIRES: UX-01

from __future__ import annotations

from typing import Any

#: The symbol of each screen in the navigation.  An unknown key shows ``file``.
SCREEN_ICONS: dict[str, str] = {
    "overview": "building",
    "queue": "inbox",
    "applicants": "users",
    "masters": "building",
    "permit": "file",
    "steward": "link",
    "rules": "scale",
    "reconciliation": "coins",
    "governance": "shield",
    "agent_intake": "spark",
    "agent_adjudication": "stamp",
    "admin": "db",
    "intake_queue": "inbox",
    "early_resolution": "alert",
    "review_queue": "stamp",
    "policy_scenarios": "scale",
    "source_records": "db",
    "activity": "clock",
    "ops_dashboard": "spark",
    "ops_audit": "shield",
    "ops_support": "users",
    "ops_checks": "stamp",
    # Reserved screens: no persona opens them until their slice builds the route.
    "agents_home": "spark",
    "agent_runs": "clock",
    "agent_case": "file",
    "steward_automation": "link",
    "steward_new_master": "building",
}

#: The short label of each screen in the mobile navigation.  An unknown key
#: shows the full label.
SCREEN_SHORT: dict[str, str] = {
    "queue": "Queue",
    "applicants": "People",
    "masters": "Masters",
    "permit": "Permit",
    "steward": "Issues",
    "rules": "Rules",
    "reconciliation": "Reconcile",
    "governance": "Governance",
    "agent_intake": "Intake",
    "agent_adjudication": "Adjudicate",
    "admin": "Admin",
    "intake_queue": "Intake queue",
    "early_resolution": "Early resolution",
    "review_queue": "Review queue",
    "policy_scenarios": "What-if",
    "source_records": "Sources",
    "activity": "Activity",
    "ops_dashboard": "Operations",
    "ops_audit": "Audit log",
    "ops_support": "Support",
    "ops_checks": "Checks",
    # Reserved screens.
    "agents_home": "Agents",
    "agent_runs": "Runs",
    "agent_case": "Cases",
    "steward_automation": "Automation",
    "steward_new_master": "New master",
}

#: The colour of the dot beside each persona label.  An unknown label shows
#: the accent colour.
PERSONA_DOTS: dict[str, str] = {
    "Applicant": "var(--warn)",
    "Data Steward": "var(--muse)",
    "Permit Reviewer": "var(--accent)",
    "City Administrator": "var(--ok)",
    "Agent Operator": "var(--info)",
}


def install(templates: Any) -> None:
    """Add the navigation tables and the home link to the template globals."""
    from acme_city.ui import view_models

    templates.env.globals.update(
        screen_icons=SCREEN_ICONS,
        screen_short=SCREEN_SHORT,
        persona_dots=PERSONA_DOTS,
        ui_home_href=view_models.home_href,
    )


__all__ = ["PERSONA_DOTS", "SCREEN_ICONS", "SCREEN_SHORT", "install"]
