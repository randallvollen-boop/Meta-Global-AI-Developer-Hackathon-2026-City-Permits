"""The governed service of the applicant help assistant.

Every write of the assistant is a governed action:

* it checks the grant of the acting persona;
* it checks the CSRF token of the request (the route does that);
* it checks a **mandatory expected version** of the conversation it writes
  to, and refuses a version that is missing as well as one that is stale;
* it writes an audit record that carries the identifiers and the outcome of
  the turn but **never the text of the question**.

The assistant itself writes nothing else: a question creates a turn, a turn
quotes the source bundle, and "Ask the City" creates a help request.  It
never changes an application, and it never decides anything.
"""
# REQUIRES: PER-04, PER-05, SEC-02, SEC-03, SEC-04
# A question, a turn and a help request are the only writes of the assistant;
# each one checks the grant and a mandatory version, and each one is audited
# without the text of the question.

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from acme_city.applicant_help import matching
from acme_city.applicant_help.config import HelpConfig, load_config
from acme_city.applicant_help.sources import SourceBundle, build_bundle
from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.clock import utc_now
from acme_city.core.errors import NotFoundError, ValidationError
from acme_city.core.ids import new_id
from acme_city.muse.payloads import assert_no_truth_in_payload
from acme_city.persistence.models import help as help_models

#: The grant that lets an applicant ask a question.
PERMISSION_ASK = "applicant.help.ask"

#: The grant that lets an applicant ask a person at the City.
PERMISSION_ESCALATE = "applicant.help.escalate"

#: The domain the help grants belong to.
HELP_DOMAIN = "permits"

#: The action names the audit trail records.
ACTION_ASK = "applicant.help.ask"
ACTION_ESCALATE = "applicant.help.escalate"

#: The mode of an answer that was produced without a model.
FALLBACK_MODE = "fallback"


@dataclass(frozen=True)
class Answer:
    """What the assistant answered."""

    mode: str
    label: str
    matched: bool
    paragraphs: tuple[dict[str, Any], ...]
    cannot_answer: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        """Return the answer as a plain mapping."""
        return {
            "mode": self.mode,
            "label": self.label,
            "matched": self.matched,
            "paragraphs": [dict(paragraph) for paragraph in self.paragraphs],
            "cannot_answer": self.cannot_answer,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class AskResult:
    """The outcome of one question."""

    conversation: help_models.HelpConversation
    turn: help_models.HelpTurn
    answer: Answer
    bundle: SourceBundle


def session_hash(actor: ActorContext) -> str:
    """Return the hash of the browser session of an actor.

    The rate limit is counted per session, and the cookie value itself never
    reaches the database.
    """
    if not actor.session_id:
        return ""
    return hashlib.sha256(f"help:{actor.session_id}".encode("utf-8")).hexdigest()[:32]


class ApplicantHelpService:
    """Reads the help configuration and writes the conversation."""

    def __init__(
        self,
        session: Session,
        *,
        settings: Any = None,
        now: datetime | None = None,
        config: HelpConfig | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._now = now or utc_now()
        self._config = config if config is not None else load_config()
        self._audit = AuditService(session, now=self._now)
        self._permissions = PermissionResolver(session, now=self._now)

    # ------------------------------------------------------------------ reading

    @property
    def config(self) -> HelpConfig:
        """Return the applicant-help configuration."""
        return self._config

    def conversation_for(
        self, actor: ActorContext, conversation_id: str
    ) -> help_models.HelpConversation | None:
        """Return a conversation of the acting applicant.

        A conversation of another applicant is not found: the applicant does
        not learn that it exists.
        """
        if not conversation_id:
            return None
        row = self._session.get(help_models.HelpConversation, conversation_id)
        if row is None or row.owner_actor_id != actor.actor_id:
            return None
        return row

    def turns(self, conversation: help_models.HelpConversation) -> list[help_models.HelpTurn]:
        """Return the turns of a conversation, oldest first."""
        return list(
            self._session.execute(
                select(help_models.HelpTurn)
                .where(help_models.HelpTurn.conversation_id == conversation.id)
                .order_by(help_models.HelpTurn.turn_number, help_models.HelpTurn.id)
            ).scalars()
        )

    def help_requests(
        self, conversation: help_models.HelpConversation
    ) -> list[help_models.HelpRequest]:
        """Return the help requests of a conversation, oldest first."""
        return list(
            self._session.execute(
                select(help_models.HelpRequest)
                .where(help_models.HelpRequest.conversation_id == conversation.id)
                .order_by(help_models.HelpRequest.created_at, help_models.HelpRequest.id)
            ).scalars()
        )

    def unsuccessful_turn_count(
        self, conversation: help_models.HelpConversation
    ) -> int:
        """Return the number of turns of a conversation that did not answer.

        A turn that found no published text and a turn whose answer was
        refused are both counted once, and only once: one per submitted turn.
        """
        rows = self._session.execute(
            select(help_models.HelpTurn.outcome)
            .where(help_models.HelpTurn.conversation_id == conversation.id)
        ).scalars()
        return sum(1 for outcome in rows if outcome != "matched")

    # ------------------------------------------------------------------ writing

    def _authorize(self, actor: ActorContext, action: str) -> None:
        """Check the grant of the acting applicant."""
        from acme_city.applicant_portal.service import applicant_party

        party = applicant_party(actor)
        self._permissions.authorize(
            actor,
            action,
            ResourceContext(domain_id=HELP_DOMAIN, record_ids=(party,) if party else ()),
        )

    def _turns_in_window(self, owner_hash: str, since: datetime) -> int:
        """Return the number of questions this session asked in the window."""
        count = self._session.execute(
            select(func.count())
            .select_from(help_models.HelpTurn)
            .join(
                help_models.HelpConversation,
                help_models.HelpConversation.id == help_models.HelpTurn.conversation_id,
            )
            .where(
                help_models.HelpConversation.owner_session_hash == owner_hash,
                help_models.HelpTurn.created_at >= since,
            )
        ).scalar_one()
        return int(count or 0)

    def ask(
        self,
        actor: ActorContext,
        *,
        question: str,
        expected_version: int,
        conversation_id: str = "",
        placement: str = "chooser",
        permit_type_key: str = "",
        application_id: str = "",
    ) -> AskResult:
        """Answer one question and record the turn.

        Args:
            actor: The acting applicant.
            question: The question, exactly as the applicant typed it.
            expected_version: The version of the conversation the applicant
                read.  A new conversation starts at zero.
            conversation_id: The conversation to continue, when there is one.
            placement: The panel the question was asked from.
            permit_type_key: The permit type the applicant is looking at.
            application_id: The application the applicant is asking about.

        Returns:
            The conversation, the turn and the answer.

        Raises:
            PermissionDeniedError: when the applicant may not ask.
            ValidationError: when the question is empty, too long, beyond the
                rate limit, or carries a version that is missing or stale.
            NotFoundError: when the conversation is not the applicant's.
        """
        self._authorize(actor, PERMISSION_ASK)
        config = self._config
        clean = str(question or "").strip()
        if not clean:
            raise ValidationError("type a question for the assistant")
        if len(clean) > config.max_message_length:
            raise ValidationError(
                f"the question is longer than {config.max_message_length} characters"
            )
        if expected_version is None:
            raise ValidationError(
                "an expected version is required to ask a question"
            )

        owner_hash = session_hash(actor)
        since = self._now - timedelta(minutes=config.rate_limit_window_minutes)
        if self._turns_in_window(owner_hash, since) >= config.rate_limit_questions:
            raise ValidationError(
                "you have asked enough questions for now; ask again in a few minutes"
            )

        conversation: help_models.HelpConversation | None = None
        if conversation_id:
            conversation = self.conversation_for(actor, conversation_id)
            if conversation is None:
                raise NotFoundError("that conversation is not available to you")
            if conversation.version != expected_version:
                raise ValidationError(
                    "the conversation changed since it was read; read it again and retry"
                )
        elif expected_version != 0:
            raise ValidationError(
                "a new conversation starts at version 0; read the panel again and retry"
            )

        bundle = build_bundle(
            self._session,
            actor,
            config=config,
            permit_type_key=permit_type_key,
            application_id=application_id,
            now=self._now,
        )
        answer = self._answer(bundle, clean)

        if conversation is None:
            conversation = help_models.HelpConversation(
                id=new_id("helpconv"),
                correlation_id=new_id("corr"),
                created_at=self._now,
                owner_actor_id=actor.actor_id,
                owner_session_hash=owner_hash,
                application_id=application_id or None,
                permit_type_key=permit_type_key or None,
                placement=placement if placement in help_models.HELP_PLACEMENTS else "chooser",
                turn_count=0,
                version=0,
            )
            self._session.add(conversation)
            self._session.flush()

        turn = help_models.HelpTurn(
            id=new_id("helpturn"),
            created_at=self._now,
            conversation_id=conversation.id,
            question=clean,
            outcome="matched" if answer.matched else "no_match",
            answer=answer.to_dict(),
            sources=self._source_snapshot(bundle, answer),
            bundle_hash=bundle.bundle_hash,
            mode=answer.mode,
            turn_number=conversation.turn_count + 1,
        )
        self._session.add(turn)
        conversation.turn_count += 1
        conversation.version += 1
        self._session.flush()

        # The audit record carries the identifiers and the outcome of the
        # turn.  It never carries the text of the question.
        self._audit.append(
            action=ACTION_ASK,
            actor=actor,
            target_type="help_conversation",
            target_id=conversation.id,
            after_version=conversation.version,
            reason="the applicant asked the help assistant a question",
            references=[turn.id],
            metadata={
                "turn_id": turn.id,
                "outcome": turn.outcome,
                "mode": turn.mode,
                "placement": conversation.placement,
                "matched_sources": len(turn.sources or []),
                "bundle_hash": turn.bundle_hash or "",
            },
        )
        self._session.flush()
        return AskResult(
            conversation=conversation, turn=turn, answer=answer, bundle=bundle
        )

    def escalate(
        self,
        actor: ActorContext,
        *,
        conversation_id: str,
        expected_version: int,
        question: str = "",
    ) -> help_models.HelpRequest:
        """Ask a person at the City to answer the applicant.

        The help request is the only route by which a member of the City
        sees the applicant's question.  The question text is stored on the
        request itself and never in an audit reason.

        Raises:
            PermissionDeniedError: when the applicant may not ask the City.
            ValidationError: when the version is missing or stale, or when
                there is no question to ask.
            NotFoundError: when the conversation is not the applicant's.
        """
        self._authorize(actor, PERMISSION_ESCALATE)
        config = self._config
        if expected_version is None:
            raise ValidationError(
                "an expected version is required to ask the City"
            )
        conversation: help_models.HelpConversation | None = None
        if conversation_id:
            conversation = self.conversation_for(actor, conversation_id)
            if conversation is None:
                raise NotFoundError("that conversation is not available to you")
            if conversation.version != expected_version:
                raise ValidationError(
                    "the conversation changed since it was read; read it again and retry"
                )
        elif expected_version != 0:
            raise ValidationError(
                "a new conversation starts at version 0; read the panel again and retry"
            )
        clean = str(question or "").strip()
        if not clean and conversation is not None:
            turns = self.turns(conversation)
            clean = turns[-1].question if turns else ""
        if not clean:
            raise ValidationError("type the question you want the City to answer")
        if len(clean) > config.max_message_length:
            raise ValidationError(
                f"the question is longer than {config.max_message_length} characters"
            )
        if conversation is None:
            conversation = help_models.HelpConversation(
                id=new_id("helpconv"),
                correlation_id=new_id("corr"),
                created_at=self._now,
                owner_actor_id=actor.actor_id,
                owner_session_hash=session_hash(actor),
                application_id=None,
                permit_type_key=None,
                placement="chooser",
                turn_count=0,
                version=0,
            )
            self._session.add(conversation)
            self._session.flush()
        request = help_models.HelpRequest(
            id=new_id("helpreq"),
            correlation_id=conversation.correlation_id,
            created_at=self._now,
            conversation_id=conversation.id,
            applicant_actor_id=actor.actor_id,
            application_id=conversation.application_id,
            question=clean,
            status="open",
            version=1,
        )
        self._session.add(request)
        conversation.version += 1
        self._session.flush()
        # The audit record names the help request and the conversation.  It
        # never carries the question.
        self._audit.append(
            action=ACTION_ESCALATE,
            actor=actor,
            target_type="help_request",
            target_id=request.id,
            after_version=conversation.version,
            reason="the applicant asked a person at the City to answer",
            references=[conversation.id],
            metadata={
                "help_request_id": request.id,
                "conversation_id": conversation.id,
                "status": request.status,
            },
        )
        self._session.flush()
        return request

    # ----------------------------------------------------------------- helpers

    def _answer(self, bundle: SourceBundle, question: str) -> Answer:
        """Return the deterministic answer of a question."""
        matches = matching.rank_passages(
            [source.to_dict() for source in bundle.passages],
            question,
            limit=self._config.max_matches,
        )
        if not matches:
            return Answer(
                mode=FALLBACK_MODE,
                label=self._config.no_match_text,
                matched=False,
                paragraphs=(),
                cannot_answer=True,
                reason="no_match",
            )
        paragraphs = tuple(
            {
                "text": match.text,
                "quote": match.text,
                "source_id": match.source_id,
                "title": match.title,
                "version": match.version,
                "citation": match.citation,
            }
            for match in matches
        )
        answer = Answer(
            mode=FALLBACK_MODE,
            label=self._config.fallback_label,
            matched=True,
            paragraphs=paragraphs,
            cannot_answer=False,
            reason="",
        )
        # The answer carries no truth: it quotes the published text and
        # nothing else.
        assert_no_truth_in_payload(answer.to_dict())
        return answer

    def _source_snapshot(
        self, bundle: SourceBundle, answer: Answer
    ) -> list[dict[str, Any]]:
        """Return the snapshot of the sources a turn used."""
        snapshot: list[dict[str, Any]] = []
        for paragraph in answer.paragraphs:
            source = bundle.source(str(paragraph.get("source_id", "")))
            if source is None:
                continue
            snapshot.append(
                {
                    "source_id": source.source_id,
                    "version": source.version,
                    "text": source.text,
                    "sha256": source.sha256,
                }
            )
        return snapshot


__all__ = [
    "ACTION_ASK",
    "ACTION_ESCALATE",
    "FALLBACK_MODE",
    "HELP_DOMAIN",
    "PERMISSION_ASK",
    "PERMISSION_ESCALATE",
    "Answer",
    "AskResult",
    "ApplicantHelpService",
    "session_hash",
]
