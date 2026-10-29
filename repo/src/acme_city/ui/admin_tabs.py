"""The tabs of the administration screen and the parts of its Users tab.

Each tab is a template under ``templates/admin/`` that ``admin.html``
includes in registry order.  A lane adds a tab with ``register_admin_tab``
and a part of the Users tab with ``register_users_extra``, both called from
the lane's own module; no lane edits this file to add one.  A tab with a
required grant is shown only to an actor who holds that grant.  The
``context_fn`` of a tab or a part returns the template variables it needs.
"""
# REQUIRES: UX-01

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext

#: A function that returns the template variables of a tab or a part.
ContextFn = Callable[[Session, ActorContext], dict[str, Any]]


@dataclass(frozen=True)
class AdminTab:
    """One tab of the administration screen."""

    key: str
    label: str
    template: str
    required_grant: str | None = None
    context_fn: ContextFn | None = None
    order: int = 100


@dataclass(frozen=True)
class UsersExtra:
    """One part appended to the Users tab."""

    template: str
    context_fn: ContextFn | None = None


#: The registered tabs, by key.
ADMIN_TABS: dict[str, AdminTab] = {}

#: The registered parts of the Users tab, in registration order.
ADMIN_USERS_EXTRAS_PROVIDERS: list[UsersExtra] = []


def register_admin_tab(
    key: str,
    label: str,
    template: str,
    required_grant: str | None = None,
    context_fn: ContextFn | None = None,
    order: int = 100,
) -> AdminTab:
    """Register one tab; a key that is already registered is refused."""
    if key in ADMIN_TABS:
        raise ValueError(f"the administration tab {key!r} is already registered")
    tab = AdminTab(key, label, template, required_grant, context_fn, order)
    ADMIN_TABS[key] = tab
    return tab


def unregister_admin_tab(key: str) -> None:
    """Remove one tab."""
    ADMIN_TABS.pop(key, None)


def register_users_extra(template: str, context_fn: ContextFn | None = None) -> UsersExtra:
    """Append one part to the Users tab."""
    extra = UsersExtra(template, context_fn)
    ADMIN_USERS_EXTRAS_PROVIDERS.append(extra)
    return extra


def unregister_users_extra(template: str) -> None:
    """Remove every part of the Users tab that renders ``template``."""
    ADMIN_USERS_EXTRAS_PROVIDERS[:] = [
        extra for extra in ADMIN_USERS_EXTRAS_PROVIDERS if extra.template != template
    ]


def _holds(session: Session, actor: ActorContext, permission: str) -> bool:
    from acme_city.auth.permissions import PermissionResolver

    return any(
        grant.action == permission
        for grant in PermissionResolver(session).grants_for(actor.actor_id)
    )


def visible_tabs(session: Session, actor: ActorContext) -> list[AdminTab]:
    """Return the tabs the actor may see, in order."""
    return [
        tab
        for tab in sorted(ADMIN_TABS.values(), key=lambda tab: tab.order)
        if tab.required_grant is None or _holds(session, actor, tab.required_grant)
    ]


#: The five tabs of the screen.  The labels are what ``|title`` made of the
#: keys before the registry existed.
for _order, (_key, _label) in enumerate(
    (
        ("permit-types", "Permit Types"),
        ("appearance", "Appearance"),
        ("users", "Users"),
        ("reason-codes", "Reason Codes"),
        ("log", "Log"),
    )
):
    register_admin_tab(_key, _label, f"admin/_{_key.replace('-', '_')}.html", order=_order * 10)


__all__ = [
    "ADMIN_TABS",
    "ADMIN_USERS_EXTRAS_PROVIDERS",
    "AdminTab",
    "UsersExtra",
    "register_admin_tab",
    "register_users_extra",
    "unregister_admin_tab",
    "unregister_users_extra",
    "visible_tabs",
]
