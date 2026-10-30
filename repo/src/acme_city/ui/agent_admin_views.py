"""The administration tabs and Users-tab parts of the Agent Operator lane.

``nav_plugins.load_plugins`` imports this module and calls ``register``.
The lane adds its tabs with ``admin_tabs.register_admin_tab`` and its parts
of the Users tab with ``admin_tabs.register_users_extra`` here, and never by
editing ``admin_tabs.py``.
"""

from __future__ import annotations

from sqlalchemy import select

from acme_city.persistence.models import agent_ops, governance
from acme_city.ui import admin_tabs

#: The roles the City worker option covers.
CITY_WORKER_ROLE_IDS: tuple[str, ...] = ("permit_reviewer", "intake_clerk")

#: The roles the table lists, in the order it lists them.
MANAGED_ROLE_IDS: tuple[str, ...] = ("agent_operator",) + CITY_WORKER_ROLE_IDS


def role_permissions_context(session, actor) -> dict:
    """Return the managed staff-role entitlement rows for the Users tab."""
    rows = {
        row.role_id: row
        for row in session.execute(select(agent_ops.AgentRoleEntitlement)).scalars().all()
    }
    labels = {
        row.role_id: row.label
        for row in session.execute(select(governance.Role)).scalars().all()
    }
    return {
        "agent_role_permissions": [
            {
                "role_id": role_id,
                "label": labels.get(role_id, role_id),
                "enabled": bool(rows.get(role_id) and rows[role_id].can_run_agents),
            }
            for role_id in MANAGED_ROLE_IDS
        ],
        # The City worker option is on when every City worker role may run
        # the agents.  The flag is computed by role id, never by the position
        # of a row in the table.
        "city_worker_enabled": all(
            bool(rows.get(role_id) and rows[role_id].can_run_agents)
            for role_id in CITY_WORKER_ROLE_IDS
        ),
    }


def register() -> None:
    """Register the role-permissions partial in the Users tab."""
    admin_tabs.register_users_extra("admin_role_permissions.html", role_permissions_context)


__all__ = ["register"]
