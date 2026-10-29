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
    roles = ("agent_operator", "permit_reviewer", "intake_clerk")
    return {
        "agent_role_permissions": [
            {
                "role_id": role_id,
                "label": labels.get(role_id, role_id),
                "enabled": bool(rows.get(role_id) and rows[role_id].can_run_agents),
            }
            for role_id in roles
        ]
    }


def register() -> None:
    """Register the role-permissions partial in the Users tab."""
    admin_tabs.register_users_extra("admin_role_permissions.html", role_permissions_context)


__all__ = ["register"]
