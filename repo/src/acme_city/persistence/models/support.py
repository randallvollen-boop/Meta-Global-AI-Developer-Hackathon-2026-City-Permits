"""Support cases of the City Administrator.

A support case is the City's own record of help it gave outside the
application: a call, a visit to the counter, an email.  It names the
application only when the person who recorded it knew one, and it carries the
channel and a short summary.  A support case never changes an application.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from acme_city.persistence.base import Base, CorrelationMixin, CreatedAtMixin, IdMixin, VersionMixin

#: The channels a support case may have, in the order the form offers them.
SUPPORT_CHANNELS: Final[tuple[str, ...]] = ("phone", "email", "counter", "mail", "other")


class SupportCase(IdMixin, VersionMixin, CorrelationMixin, CreatedAtMixin, Base):
    """One support case recorded by a member of the City."""

    __tablename__ = "support_cases"

    #: The application the case is about, when the person knew one.
    application_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("applications.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: The reference exactly as it was recorded (the application number).
    reference: Mapped[str | None] = mapped_column(String(96), nullable=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_by_actor_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    __table_args__ = (
        CheckConstraint(
            "channel IN ('phone', 'email', 'counter', 'mail', 'other')",
            name="channel_allowed",
        ),
    )


__all__ = ["SUPPORT_CHANNELS", "SupportCase"]
