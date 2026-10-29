"""Reset seed data of the agent operator lane."""

from __future__ import annotations

from acme_city.fixtures.reset import register_seed
from acme_city.persistence.models import agent_ops


@register_seed
def seed_operator_defaults(session, bundle):
    """Seed the managed entitlement and manual-processing defaults."""
    now = bundle.demo.assignment_epoch
    entitlements = {
        "agent_operator": True,
        "permit_reviewer": False,
        "intake_clerk": False,
        "domain_steward": False,
        "domain_mdm_steward": False,
    }
    for role_id, enabled in entitlements.items():
        session.add(
            agent_ops.AgentRoleEntitlement(
                id=f"agentrole_{role_id}", correlation_id=f"corr_agentrole_{role_id}", role_id=role_id,
                can_run_agents=enabled, version=1, changed_by=None, changed_at=now,
            )
        )
    policy = bundle.demo.agent_processing
    session.add(
        agent_ops.AgentProcessingPolicy(
            id="agentpolicy_default", correlation_id="corr_agentpolicy_default",
            mode=str(policy.get("mode", "manual")),
            runs_per_hour=int(policy.get("runs_per_hour", 60)),
            max_batch_size=int(policy.get("max_batch_size", 20)),
            version=1, changed_by=None, changed_at=now,
        )
    )
    return {
        "agent_role_entitlements": len(entitlements),
        "agent_processing_policies": 1,
    }
