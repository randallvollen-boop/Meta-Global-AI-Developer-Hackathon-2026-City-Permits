"""SQLAlchemy models for every persisted object group.

Importing this package registers every model on :data:`acme_city.persistence.base.Base.metadata`,
which is what the Alembic migration and the schema tests compare against.
"""

from acme_city.persistence.models import (
    agent,
    audit,
    change,
    finance,
    gis,
    governance,
    model_run,
    permit,
    registry,
    source,
)

__all__ = [
    "agent",
    "audit",
    "change",
    "finance",
    "gis",
    "governance",
    "model_run",
    "permit",
    "registry",
    "source",
]
