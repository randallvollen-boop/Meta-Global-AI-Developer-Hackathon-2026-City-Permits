"""SQLAlchemy models for every persisted object group.

Importing this package registers every model on :data:`acme_city.persistence.base.Base.metadata`,
which is what the Alembic migration and the schema tests compare against.
"""

from acme_city.persistence.models import (
    agent,
    agent_ops,
    audit,
    change,
    finance,
    gis,
    governance,
    help,
    model_run,
    permit,
    policy,
    registry,
    registry_automation,
    source,
    support,
)

__all__ = [
    "agent",
    "agent_ops",
    "audit",
    "change",
    "finance",
    "gis",
    "governance",
    "help",
    "model_run",
    "permit",
    "policy",
    "registry",
    "registry_automation",
    "source",
    "support",
]
