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
#:
#: The bar holds the screens an administrator task uses: the planning
#: overview, the rules and fees, the reconciliation, the governance and
#: sources, and the administration.
PRIMARY_SCREENS: tuple[str, ...] = (
    "overview",
    "rules",
    "reconciliation",
    "governance",
    "admin",
)

#: The screens that read across the whole program, and the screens no
#: administrator task uses.  They sit under More tools.
#:
#: They are the last screens of the Administrator's navigation, so the bar and
#: the More group together keep the order of the screens and the grouping
#: never reorders a destination.
SECONDARY_SCREENS: tuple[str, ...] = (
    "queue",
    "masters",
    "permit",
    "steward",
    "source_records",
    "activity",
    "intake_queue",
    "insight_city",
    "policy_scenarios",
    "ops_dashboard",
    "ops_audit",
    "ops_support",
    "ops_checks",
)


def profile(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the navigation of the City Administrator.

    The daily work comes first and keeps its own labels.  Every other screen
    the Administrator may open becomes a secondary item, so the bar shows only
    the screens an administrator works in and every screen stays reachable.
    The order of the screens is not changed.
    """
    order = {screen["key"]: index for index, screen in enumerate(view_models.SCREENS)}
    by_key = {item["key"]: item for item in items}
    ordered: list[dict[str, Any]] = []
    for key in PRIMARY_SCREENS:
        item = by_key.pop(key, None)
        if item is not None:
            ordered.append(dict(item))
    rest = sorted(by_key.values(), key=lambda item: order.get(item["key"], len(order)))
    for item in rest:
        entry = dict(item)
        entry["group"] = "secondary"
        ordered.append(entry)
    return ordered


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
