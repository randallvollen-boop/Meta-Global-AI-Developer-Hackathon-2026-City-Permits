"""The navigation of the City Administrator lanes.

``nav_plugins.load_plugins`` imports this module and calls ``register``.
The lane adds its entries to ``view_models.NAV_PROFILES``,
``view_models.HOME_OVERRIDES`` or ``view_models.register_screen`` here.
"""
# REQUIRES: UX-01

from __future__ import annotations

from typing import Any

from acme_city.ui import view_models

#: The actor id of the City Administrator.
ADMIN_ACTOR_ID = "persona_city_administrator"

#: The screens the Administrator opens every day.  They stay in the bar.
PRIMARY_SCREENS: tuple[str, ...] = (
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
)

#: The screens that read across the whole program.  They sit under More tools.
#:
#: They are the last screens of the Administrator's navigation, so the bar and
#: the More group together keep the order of the screens and the grouping
#: never reorders a destination.
SECONDARY_SCREENS: tuple[str, ...] = (
    "insight_city",
    "policy_scenarios",
    "ops_dashboard",
    "ops_audit",
    "ops_support",
    "ops_checks",
)


def profile(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the navigation of the City Administrator.

    The daily work stays in the bar and the screens that read across the whole
    program move under More tools.  The order of the screens is not changed.
    """
    grouped = [dict(item) for item in items]
    for item in grouped:
        if item.get("key") in SECONDARY_SCREENS:
            item["group"] = "secondary"
    return grouped


def register() -> None:
    """Register the navigation of the lane.

    Registering twice changes nothing: the profile of the Administrator is
    always the same function.
    """
    view_models.NAV_PROFILES[ADMIN_ACTOR_ID] = profile


__all__ = [
    "ADMIN_ACTOR_ID",
    "PRIMARY_SCREENS",
    "SECONDARY_SCREENS",
    "profile",
    "register",
]
