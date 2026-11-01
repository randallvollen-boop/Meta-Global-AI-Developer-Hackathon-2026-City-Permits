"""The support service (S13) of the City Administrator.

Four things, each behind its own grant:

* ``support.lookup.view``: look up an application by reference.  The view is
  read only and shows the status, the timeline and the comments written for
  the applicant.  An internal note is never read here, whoever asks.
* ``support.help_request.answer``: list the open help requests the applicants
  sent through Ask the City, read the escalated part of the conversation, and
  answer.  The reply and the answered status are recorded together, with a
  mandatory expected version.  On a case that can still change the reply is
  also written as a comment the applicant reads; on an archived case it
  replies on the help request only and never touches the application.
* ``support.case.record``: record assistance given outside the application.
* The service gives no power to decide, issue, return or waive.

The audit records carry identifiers and the outcome.  They never carry the
text of a question, a reply or a summary.
"""
# REQUIRES: PER-04, SEC-03, UX-02
# A help request is answered atomically under its own grant and version, an
# applicant-visible comment is written only on a case that can still change,
# and no audit record carries the text of a question, a reply or a summary.

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.clock import utc_now
from acme_city.core.errors import NotFoundError, ValidationError
from acme_city.core.ids import new_id
from acme_city.permits.guard import is_archived
from acme_city.persistence.models import governance, permit
from acme_city.persistence.models import help as help_models
from acme_city.persistence.models.support import SUPPORT_CHANNELS, SupportCase

PERMISSION_LOOKUP = "support.lookup.view"
PERMISSION_ANSWER = "support.help_request.answer"
PERMISSION_RECORD = "support.case.record"

ACTION_ANSWER = "support.help_request.answer"
ACTION_RECORD = "support.case.record"

#: The longest reply and the longest summary.
MAX_REPLY = 2000
MAX_SUMMARY = 1000

#: The words of the channels.
CHANNEL_LABELS: dict[str, str] = {
    "phone": "Phone call",
    "email": "Email",
    "counter": "At the counter",
    "mail": "Mail",
    "other": "Other",
}

#: The short FAQ shown on the support screen (fictional ACME wording only).
FAQ: tuple[tuple[str, str], ...] = (
    (
        "Where does an applicant see the City's answer?",
        "On the tracking page of the case. A reply to a help request that is tied to a "
        "case is written there as a comment the applicant reads; a reply that is not tied "
        "to a case is shown in the applicant's help history.",
    ),
    (
        "Can support change an application?",
        "No. Support reads a case and answers questions. Deciding, issuing, returning "
        "and waiving belong to the Permit Reviewer and the Data Steward.",
    ),
    (
        "What if the case is archived?",
        "An archived case cannot change, so a reply is kept on the help request only. "
        "Restore the case first if the applicant must see the reply on it.",
    ),
)

#: The fictional contact and emergency notice.
CONTACT_NOTICE: dict[str, str] = {
    "desk": "City of Acme Permit Support Desk, 100 Example Plaza, City of Acme (fictional).",
    "phone": "555-0100 (fictional), weekdays 8:00 to 16:30.",
    "emergency": (
        "Emergency notice (fictional): for a danger to life or property call 555-0911. "
        "The support desk does not handle emergencies."
    ),
}


class SupportService:
    """Reads the support screen and writes its two records."""

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or utc_now()
        self._audit = AuditService(session, now=self._now)
        self._permissions = PermissionResolver(session, now=self._now)

    # ----------------------------------------------------------------- grants

    def can(self, actor: ActorContext, permission: str) -> bool:
        """Return whether the actor holds a support grant."""
        return self._permissions.allows(actor, permission, ResourceContext(domain_id=None))

    def _authorize(self, actor: ActorContext, permission: str) -> None:
        self._permissions.authorize(actor, permission, ResourceContext(domain_id=None))

    # ----------------------------------------------------------------- lookup

    def lookup(self, actor: ActorContext, reference: str) -> dict[str, Any] | None:
        """Return the read-only view of one application, or ``None``.

        Args:
            actor: The acting City Administrator.
            reference: The application reference, as the applicant knows it.
        """
        self._authorize(actor, PERMISSION_LOOKUP)
        clean = str(reference or "").strip()
        if not clean:
            return None
        application = self._session.execute(
            select(permit.Application).where(
                permit.Application.source_application_number == clean
            )
        ).scalar_one_or_none()
        if application is None:
            return None
        permit_type = self._session.get(permit.PermitType, application.permit_type_id)
        timeline: list[tuple[datetime, str]] = []
        if application.initial_submitted_at is not None:
            timeline.append((application.initial_submitted_at, "Submitted"))
        if (
            application.revision_submitted_at is not None
            and application.revision_submitted_at != application.initial_submitted_at
        ):
            timeline.append((application.revision_submitted_at, "Applicant response received"))
        for action in self._session.execute(
            select(permit.ApplicationAction).where(
                permit.ApplicationAction.application_id == application.id
            )
        ).scalars():
            label = action.action.replace("_", " ").capitalize()
            if action.reason_code_label:
                label += f" ({action.reason_code_label})"
            timeline.append((action.occurred_at, label))
        for decision in self._session.execute(
            select(permit.Decision).where(permit.Decision.application_id == application.id)
        ).scalars():
            timeline.append(
                (decision.decided_at, f"Decision recorded: {decision.outcome.replace('_', ' ')}")
            )
        for issued in self._session.execute(
            select(permit.Permit).where(permit.Permit.application_id == application.id)
        ).scalars():
            timeline.append((issued.issued_at, f"Permit {issued.permit_number} issued"))
        timeline.sort(key=lambda item: item[0])
        comments = self._session.execute(
            select(permit.ApplicationComment)
            .where(
                permit.ApplicationComment.application_id == application.id,
                permit.ApplicationComment.visibility == "applicant",
            )
            .order_by(permit.ApplicationComment.created_at, permit.ApplicationComment.id)
        ).scalars().all()
        return {
            "application_id": application.id,
            "reference": application.source_application_number,
            "status": application.status,
            "permit_type": permit_type.label if permit_type else "",
            "submitted_at": (
                application.initial_submitted_at.isoformat()
                if application.initial_submitted_at
                else ""
            ),
            "timeline": [
                {"when": when.isoformat(), "what": what} for when, what in timeline
            ],
            "comments": [
                {"created_at": row.created_at.isoformat(), "body": row.body} for row in comments
            ],
        }

    # ----------------------------------------------------------- help requests

    def help_requests(
        self, actor: ActorContext, *, status: str = "open"
    ) -> list[dict[str, Any]]:
        """Return the help requests with the escalated part of each conversation.

        The conversation is shown as it stood when the applicant asked the
        City: the turns up to the request, and nothing the applicant asked
        afterwards.  A conversation with no help request is never listed.
        """
        self._authorize(actor, PERMISSION_ANSWER)
        statement = select(help_models.HelpRequest).order_by(
            help_models.HelpRequest.created_at, help_models.HelpRequest.id
        )
        if status in help_models.HELP_REQUEST_STATUSES:
            statement = statement.where(help_models.HelpRequest.status == status)
        rows = self._session.execute(statement).scalars().all()
        return [self._request_view(row) for row in rows]

    def _request_view(self, row: help_models.HelpRequest) -> dict[str, Any]:
        applicant = self._session.execute(
            select(governance.Actor.label).where(
                governance.Actor.actor_id == row.applicant_actor_id
            )
        ).scalar_one_or_none()
        reference = ""
        archived = False
        if row.application_id:
            application = self._session.get(permit.Application, row.application_id)
            if application is not None:
                reference = application.source_application_number
                archived = is_archived(application)
        snapshot = []
        for turn in self._session.execute(
            select(help_models.HelpTurn)
            .where(
                help_models.HelpTurn.conversation_id == row.conversation_id,
                help_models.HelpTurn.created_at <= row.created_at,
            )
            .order_by(help_models.HelpTurn.turn_number, help_models.HelpTurn.id)
        ).scalars():
            answer = dict(turn.answer or {})
            snapshot.append(
                {
                    "question": turn.question,
                    "outcome": turn.outcome,
                    "label": str(answer.get("label", "")),
                }
            )
        return {
            "request_id": row.id,
            "version": row.version,
            "status": row.status,
            "created_at": row.created_at.isoformat() if row.created_at else "",
            "applicant": applicant or row.applicant_actor_id,
            "application_id": row.application_id or "",
            "reference": reference,
            "archived": archived,
            "question": row.question,
            "reply": row.reply or "",
            "answered_at": row.answered_at.isoformat() if row.answered_at else "",
            "snapshot": snapshot,
        }

    def answer_help_request(
        self,
        actor: ActorContext,
        *,
        request_id: str,
        reply: str,
        expected_version: int | None,
    ) -> help_models.HelpRequest:
        """Answer one help request.

        The reply and the answered status are recorded together.  A request
        tied to a case that can still change also gets an applicant-visible
        comment; an archived case is left untouched.

        Raises:
            PermissionDeniedError: without ``support.help_request.answer``.
            ValidationError: for a missing or stale version, an empty or
                too long reply, or a request that was already answered.
            NotFoundError: when no help request has that identifier.
        """
        self._authorize(actor, PERMISSION_ANSWER)
        if expected_version is None:
            raise ValidationError("an expected version is required to answer a help request")
        row = self._session.get(help_models.HelpRequest, request_id)
        if row is None:
            raise NotFoundError("no help request has that identifier")
        if row.version != expected_version:
            raise ValidationError(
                "the help request changed since it was read; read it again and retry"
            )
        if row.status != "open":
            raise ValidationError("that help request was already answered")
        text = str(reply or "").strip()
        if not text:
            raise ValidationError("write a reply before answering")
        if len(text) > MAX_REPLY:
            raise ValidationError(f"the reply is longer than {MAX_REPLY} characters")
        comment_id = ""
        application = (
            self._session.get(permit.Application, row.application_id)
            if row.application_id
            else None
        )
        if application is not None and not is_archived(application):
            comment = permit.ApplicationComment(
                id=new_id("comment"),
                correlation_id=application.correlation_id or new_id("corr"),
                application_id=application.id,
                body=text,
                visibility="applicant",
                author_actor_id=actor.actor_id,
                version=1,
            )
            self._session.add(comment)
            self._session.flush()
            comment_id = comment.id
            self._audit.append(
                action="application.comment.add",
                actor=actor,
                target_type="application",
                target_id=application.id,
                after_version=application.version,
                references=[comment.id, row.id],
                correlation_id=comment.correlation_id,
                metadata={"comment_id": comment.id, "visibility": "applicant"},
            )
        before = row.version
        row.reply = text
        row.status = "answered"
        row.answered_at = self._now
        row.answered_by_actor_id = actor.actor_id
        row.version += 1
        self._session.flush()
        self._audit.append(
            action=ACTION_ANSWER,
            actor=actor,
            target_type="help_request",
            target_id=row.id,
            before_version=before,
            after_version=row.version,
            reason="a person at the City answered a help request",
            references=[row.conversation_id] + ([comment_id] if comment_id else []),
            correlation_id=row.correlation_id,
            metadata={
                "help_request_id": row.id,
                "conversation_id": row.conversation_id,
                "application_id": row.application_id or "",
                "comment_id": comment_id,
                "replied_on": "request_and_comment" if comment_id else "request_only",
            },
        )
        self._session.flush()
        return row

    # ----------------------------------------------------------- support cases

    def recent_cases(self, actor: ActorContext, limit: int = 15) -> list[dict[str, Any]]:
        """Return the most recent support cases."""
        self._authorize(actor, PERMISSION_RECORD)
        rows = self._session.execute(
            select(SupportCase)
            .order_by(SupportCase.created_at.desc(), SupportCase.id.desc())
            .limit(limit)
        ).scalars().all()
        return [
            {
                "case_id": row.id,
                "created_at": row.created_at.isoformat() if row.created_at else "",
                "reference": row.reference or "",
                "channel": CHANNEL_LABELS.get(row.channel, row.channel),
                "summary": row.summary,
                "recorded_by": row.recorded_by_actor_id,
            }
            for row in rows
        ]

    def record_case(
        self,
        actor: ActorContext,
        *,
        reference: str,
        channel: str,
        summary: str,
        expected_version: int | None,
    ) -> SupportCase:
        """Record assistance given outside the application.

        A new record starts at version 0, exactly like a new conversation; any
        other expected version is refused.
        """
        self._authorize(actor, PERMISSION_RECORD)
        if expected_version is None:
            raise ValidationError("an expected version is required to record a support case")
        if expected_version != 0:
            raise ValidationError(
                "a new support case starts at version 0; read the screen again and retry"
            )
        if channel not in SUPPORT_CHANNELS:
            raise ValidationError("choose one of the channels: " + ", ".join(SUPPORT_CHANNELS))
        text = str(summary or "").strip()
        if not text:
            raise ValidationError("write a short summary of the assistance given")
        if len(text) > MAX_SUMMARY:
            raise ValidationError(f"the summary is longer than {MAX_SUMMARY} characters")
        clean = str(reference or "").strip()
        application_id: str | None = None
        if clean:
            application_id = self._session.execute(
                select(permit.Application.id).where(
                    permit.Application.source_application_number == clean
                )
            ).scalar_one_or_none()
            if application_id is None:
                raise ValidationError(
                    "no application has that reference; leave the reference empty if there is none"
                )
        row = SupportCase(
            id=new_id("support"),
            correlation_id=new_id("corr"),
            created_at=self._now,
            version=1,
            application_id=application_id,
            reference=clean or None,
            channel=channel,
            summary=text,
            recorded_by_actor_id=actor.actor_id,
        )
        self._session.add(row)
        self._session.flush()
        self._audit.append(
            action=ACTION_RECORD,
            actor=actor,
            target_type="support_case",
            target_id=row.id,
            after_version=row.version,
            reason="a support case was recorded",
            references=[application_id] if application_id else [],
            correlation_id=row.correlation_id,
            metadata={
                "support_case_id": row.id,
                "channel": channel,
                "application_id": application_id or "",
            },
        )
        self._session.flush()
        return row


__all__ = [
    "CHANNEL_LABELS",
    "CONTACT_NOTICE",
    "FAQ",
    "MAX_REPLY",
    "PERMISSION_ANSWER",
    "PERMISSION_LOOKUP",
    "PERMISSION_RECORD",
    "SupportService",
]
