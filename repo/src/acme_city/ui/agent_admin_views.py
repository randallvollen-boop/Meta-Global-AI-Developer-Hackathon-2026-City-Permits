"""The administration tabs and Users-tab parts of the Agent Operator lane.

``nav_plugins.load_plugins`` imports this module and calls ``register``.
The lane adds its tabs with ``admin_tabs.register_admin_tab`` and its parts
of the Users tab with ``admin_tabs.register_users_extra`` here, and never by
editing ``admin_tabs.py``.

The Agent processing tab shows the processing policy of the City and the
control that saves it.  The policy says when the agents work, not what they
decide: people still review the recommendations and make the permit
decisions.  The tab is the administrator's, so it needs the configuration
grant; the operator reads the saved state on the agent screens.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from acme_city.persistence.models import agent_ops, audit, governance
from acme_city.ui import admin_tabs

#: The roles the City worker option covers.
CITY_WORKER_ROLE_IDS: tuple[str, ...] = ("permit_reviewer", "intake_clerk")

#: The roles the table lists, in the order it lists them.
MANAGED_ROLE_IDS: tuple[str, ...] = ("agent_operator",) + CITY_WORKER_ROLE_IDS

#: The key of the Agent processing tab of the administration screen.
PROCESSING_TAB_KEY = "agent_processing"

#: The label of the Agent processing tab.
PROCESSING_TAB_LABEL = "Agent processing"

#: The grant that opens the Agent processing tab and allows a save.
PERMISSION_MANAGE = "config.manage"

#: The label the tab shows for the mode of a policy that waits for a person.
MODE_MANUAL = "manual"

#: The label the tab shows for the engine that reads the received documents.
ENGINE_BUILTIN = "Built in logic"


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


def _settings() -> Any:
    """Return the settings of the running process, or ``None``.

    A tab context is built without the request, so the settings are read
    from the environment of the process.  Settings that cannot be read are
    treated as no provider call at all: the tab then says so instead of
    offering a setting the server would refuse.
    """
    from acme_city.core.config import Settings

    try:
        return Settings.load()
    except Exception:  # pragma: no cover - a broken environment
        return None


def muse_capability(settings: Any) -> tuple[int, str]:
    """Return the daily allowance of provider calls and why it is what it is.

    The allowance is a setting of the deployment, not a setting of the
    City: the tab shows what the process may do today and never offers to
    raise it.  A hosted demonstration, a deployment without a credential and
    a deployment with the provider switched off all allow no call at all.
    """
    if settings is None:
        return 0, "The settings of this deployment could not be read."
    from acme_city.muse.client import live_call_block_reason

    blocked = live_call_block_reason(settings)
    if blocked is not None:
        return 0, "Locked for this hosted demo."
    if settings.meta_api_key is None:
        return 0, "No provider credential is configured."
    if not settings.provider_enabled:
        return 0, "The provider is switched off in this deployment."
    return max(0, int(settings.muse_daily_call_cap)), ""


def _last_change(session, policy_id: str) -> str:
    """Return the sentence that names who changed the policy and when."""
    from acme_city.ui.view_models import actor_label

    row = session.execute(
        select(audit.AuditEvent)
        .where(
            audit.AuditEvent.target_type == "agent_processing_policy",
            audit.AuditEvent.target_id == policy_id,
        )
        .order_by(audit.AuditEvent.occurred_at.desc(), audit.AuditEvent.id.desc())
    ).scalars().first()
    if row is None:
        return "The demonstration reset seeded these settings."
    who = actor_label(session, row.actor_id) if row.actor_id else "the City"
    return f"Last changed by {who} at {row.occurred_at.isoformat()}."


def processing_context(session, actor) -> dict:
    """Return the processing policy of the City for the Agent processing tab."""
    from acme_city.agents.eligibility import eligible_applications
    from acme_city.agents.policy import current_policy
    from acme_city.agents.runtime import DEFAULT_RUNS_PER_HOUR
    from acme_city.muse.budget import MuseBudget

    policy = current_policy(session)
    settings = _settings()
    cap, cap_note = muse_capability(settings)
    automatic = policy is not None and policy.mode != MODE_MANUAL
    used = 0
    if cap and settings is not None:
        try:
            used = MuseBudget(session, settings=settings).used()
        except Exception:  # pragma: no cover - a broken budget table
            used = 0
    engine = (
        f"Muse, {used} of {cap} calls used today"
        if cap
        else ENGINE_BUILTIN
    )
    worker_on = bool(settings is not None and settings.agent_worker_enabled)
    return {
        "agent_processing": {
            "automatic": automatic,
            "mode_label": "Automatic processing" if automatic else "Manual processing",
            "runs_per_hour": (
                policy.runs_per_hour if policy is not None else DEFAULT_RUNS_PER_HOUR
            ),
            "version": policy.version if policy is not None else 0,
            "engine_label": engine,
            "muse_cap": cap,
            "muse_note": cap_note
            or "Provider calls are allowed in this deployment.",
            "eligible_count": len(eligible_applications(session)),
            "worker_note": (
                "The background worker runs while the service is up."
                if worker_on
                else "The background worker is off in this deployment, so automatic "
                "processing waits for it."
            ),
            "change_note": _last_change(
                session, policy.id if policy is not None else ""
            ),
        }
    }


def register() -> None:
    """Register the Agent processing tab and the role-permissions part."""
    admin_tabs.register_users_extra("admin_role_permissions.html", role_permissions_context)
    admin_tabs.register_admin_tab(
        PROCESSING_TAB_KEY,
        PROCESSING_TAB_LABEL,
        "admin_agent_processing.html",
        required_grant=PERMISSION_MANAGE,
        context_fn=processing_context,
        # The tab sits next to the Users tab of the administration screen.
        order=25,
    )


__all__ = [
    "ENGINE_BUILTIN",
    "PERMISSION_MANAGE",
    "PROCESSING_TAB_KEY",
    "PROCESSING_TAB_LABEL",
    "muse_capability",
    "processing_context",
    "register",
    "role_permissions_context",
]
