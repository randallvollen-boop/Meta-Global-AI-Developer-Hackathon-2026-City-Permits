"""Declarative base, naming convention and shared column mixins.

Naming conventions are declared explicitly so that Alembic can compare the
models with the database and so that constraint names are stable across
machines.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import Integer, MetaData, String, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from acme_city.core.clock import utc_now
from acme_city.persistence.types import UTCDateTime

NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base for every persisted object."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map: ClassVar[dict[str, Any]] = {dict[str, Any]: None}


class IdMixin:
    """A stable, prefixed, UUID-compatible primary key."""

    id: Mapped[str] = mapped_column(String(64), primary_key=True)


class VersionMixin:
    """A mutable aggregate carries an integer version that starts at one."""

    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )


class CreatedAtMixin:
    """The creation time of the record, in timezone-aware UTC."""

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )


class CorrelationMixin:
    """A correlation identifier that links related records and audit events."""

    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


__all__ = [
    "Base",
    "CorrelationMixin",
    "CreatedAtMixin",
    "IdMixin",
    "NAMING_CONVENTION",
    "VersionMixin",
]
