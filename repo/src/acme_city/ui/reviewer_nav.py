"""The navigation of the Permit Reviewer lane.

``nav_plugins.load_plugins`` imports this module and calls ``register``.
The lane adds its entries to ``view_models.NAV_PROFILES`` or
``view_models.HOME_OVERRIDES`` here.

The Permit Reviewer works in three places: the work queue that lists the
cases waiting on someone, the permit workspace of one case, and the review
queue that holds the cases with the reviewer.  Those three are the whole bar.
The people and organizations and the intake queue stay open to the reviewer,
but no reviewer task uses them, so they are not listed.
"""

from __future__ import annotations

from typing import Any

from acme_city.ui import view_models

#: The actor id of the Permit Reviewer.
REVIEWER_ACTOR_ID = "persona_permit_reviewer"

#: The screens of the side navigation, in the order they are listed.
REVIEWER_SCREENS: tuple[str, ...] = (
    "queue",
    "permit",
    "review_queue",
)


def reviewer_profile(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the navigation of the Permit Reviewer.

    The three screens the reviewer works in are listed, in the canonical order
    of the screens.  A screen the reviewer may open but does not work in is
    not listed.
    """
    by_key = {item["key"]: item for item in items}
    return [by_key[key] for key in REVIEWER_SCREENS if key in by_key]


def register() -> None:
    """Register the navigation of the lane.

    Registering twice changes nothing: the profile of the reviewer is always
    the same function.
    """
    view_models.NAV_PROFILES[REVIEWER_ACTOR_ID] = reviewer_profile


__all__ = [
    "REVIEWER_ACTOR_ID",
    "REVIEWER_SCREENS",
    "register",
    "reviewer_profile",
]
