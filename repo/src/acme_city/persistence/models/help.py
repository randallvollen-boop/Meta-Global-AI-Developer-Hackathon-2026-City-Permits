"""Applicant help conversations, turns and help requests.

Three record groups hold the applicant's help conversation:

* a **conversation** belongs to one applicant and one browser session.  It
  names the application or the permit type the applicant was looking at when
  the conversation was opened, so the answer may be about that case or that
  form;
* a **turn** is one question and the answer the server gave.  The turn keeps
  the sources the answer was drawn from — the identifier, the version, the
  text and the hash of each one — so a later reader can tell which published
  text answered the question;
* a **help request** is a question the applicant asked a person at the City to
  answer.  It is the only route by which a member of the City sees the
  conversation, and only the escalated part of it.

A conversation is private to its owner.  The rows carry no secret and no
credential: the session is stored as a hash because the rate limit is counted
per session.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from acme_city.persistence.base import (
    Base,
    CorrelationMixin,
    CreatedAtMixin,
    IdMixin,
    VersionMixin,
)
from acme_city.persistence.types import UTCDateTime

#: The outcomes one turn may have.
#:
#: ``matched`` means the deterministic matcher found published text that
#: answers the question; ``no_match`` means it found none, and the answer is
#: an explicit no-match result rather than a guess.  ``answered`` means the
#: assistant wrote the answer and the validation passed it; ``rejected``
#: means the validation refused the answer and the deterministic answer was
#: shown instead; ``unanswerable`` means the assistant refused to answer and
#: the deterministic answer was shown instead; ``failed`` means the run
#: itself failed.
TURN_OUTCOMES: Final = frozenset(
    {"matched", "answered", "no_match", "rejected", "unanswerable", "failed"}
)

#: The states a help request may have.
HELP_REQUEST_STATUSES: Final = frozenset({"open", "answered"})

#: The placements the help panel is opened from.
HELP_PLACEMENTS: Final = frozenset({"chooser", "form", "track"})


class HelpConversation(IdMixin, VersionMixin, CorrelationMixin, CreatedAtMixin, Base):
    """One applicant's help conversation."""

    __tablename__ = "help_conversations"

    #: The applicant who owns the conversation.  Nobody else may read it.
    owner_actor_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: The hash of the browser session that opened the conversation.  The
    #: rate limit is counted per session, and the cookie value itself is
    #: never stored.
    owner_session_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    #: The application the conversation is about, when it is about one.
    application_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("applications.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: The permit type the conversation is about, when the applicant is
    #: filling in a form and has no application yet.
    permit_type_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: The panel the conversation was opened from: ``chooser``, ``form`` or
    #: ``track``.
    placement: Mapped[str] = mapped_column(String(16), nullable=False, default="chooser")
    #: The number of questions the applicant asked in this conversation.
    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    __table_args__ = (
        CheckConstraint(
            "placement IN ('chooser', 'form', 'track')",
            name="placement_allowed",
        ),
    )


class HelpTurn(IdMixin, CreatedAtMixin, Base):
    """One question the applicant asked and the answer the server gave."""

    __tablename__ = "help_turns"

    conversation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("help_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: The question, exactly as the applicant typed it.  It is untrusted
    #: input: it is never rendered as markup and never becomes an
    #: instruction.
    question: Mapped[str] = mapped_column(Text, nullable=False)
    #: ``matched``, ``answered``, ``no_match``, ``rejected``, ``unanswerable``
    #: or ``failed``.
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="no_match")
    #: The paragraphs of the answer and the citations of each one.
    answer: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    #: The sources the answer used: the identifier, the version, the text and
    #: the hash of each one.
    sources: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    #: The hash of the whole source bundle the answer was drawn from, so a
    #: later reader can tell that the published text has not moved.
    bundle_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: The mode the answer was produced in: ``fallback`` when no model wrote
    #: it, ``replay`` when a replay fixture did and ``live`` when a live run
    #: did.
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="fallback")
    #: The number of this turn in its conversation, starting at one.
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('matched', 'answered', 'no_match', 'rejected', "
            "'unanswerable', 'failed')",
            name="outcome_allowed",
        ),
        CheckConstraint("mode IN ('fallback', 'replay', 'live')", name="mode_allowed"),
    )


class HelpRequest(IdMixin, VersionMixin, CorrelationMixin, CreatedAtMixin, Base):
    """A question the applicant asked a person at the City to answer.

    The request is the only route by which a member of the City sees the
    applicant's question.  The reply is the answer of the person; it is
    written by the support path of the phase 3 support screen, which is
    delivered with the chat part that follows this one.
    """

    __tablename__ = "help_requests"

    conversation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("help_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: The applicant who asked.
    applicant_actor_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: The application the question is about, when it is about one.
    application_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("applications.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: The question, exactly as the applicant typed it.
    question: Mapped[str] = mapped_column(Text, nullable=False)
    #: ``open`` or ``answered``.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    #: The reply of the person at the City.
    reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    answered_by_actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'answered')",
            name="status_allowed",
        ),
    )


__all__ = [
    "HELP_PLACEMENTS",
    "HELP_REQUEST_STATUSES",
    "TURN_OUTCOMES",
    "HelpConversation",
    "HelpRequest",
    "HelpTurn",
]
