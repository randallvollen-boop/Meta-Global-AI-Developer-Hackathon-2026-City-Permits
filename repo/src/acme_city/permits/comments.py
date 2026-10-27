"""Comments on a case.

A comment is either visible to the applicant or internal.  The visibility is
enforced by the server on every surface that shows a comment: the applicant
portal, the permit workspace, the history panel, the support lookup and the
API.  The browser never chooses who may read a comment; it only asks.

The audit record of a comment carries the comment identifier and its
visibility.  It never carries the text of the comment, so an internal note
can never travel to an applicant through the audit trail.
"""
# REQUIRES: PER-04, SEC-03, UX-02
# A comment is visible to the applicant or internal, the server enforces that
# choice on every surface, and the audit record carries the comment identifier
# and its visibility but never the text of an internal note.

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
from acme_city.persistence.models import permit

#: The grant that writes a comment.
PERMISSION_COMMENT = "permit.case.comment"

#: The visibilities a comment may carry.
COMMENT_VISIBILITIES: tuple[str, ...] = ("applicant", "internal")

#: The grants that mark an actor as a member of the City rather than an
#: applicant.  An actor that holds one of these may read the internal notes
#: of a case; an applicant never may.
STAFF_MARKER_GRANTS: frozenset[str] = frozenset(
    {
        "admin.actor.manage",
        "agent.run.adjudication",
        "agent.run.intake",
        "application.evaluate",
        "change.case.transition",
        "config.manage",
        "parcel.confirm",
        "permit.case.archive",
        "permit.case.comment",
        "permit.decide",
        "permit.issue",
        "records.audit.view",
        "records.configuration.view",
        "registry.crosswalk.decide",
    }
)


def is_staff(session: Session, actor: ActorContext) -> bool:
    """Return whether the actor is a member of the City rather than an applicant.

    The answer comes from the persisted grants, never from a label that
    arrived with a request.
    """
    held = PermissionResolver(session).permissions_for(actor.actor_id)
    return bool(held & STAFF_MARKER_GRANTS)


def comments_for(
    session: Session, application_id: str, actor: ActorContext
) -> list[permit.ApplicationComment]:
    """Return the comments of a case the actor may read.

    A member of the City reads every comment; an applicant reads only the
    comments that were written for the applicant.
    """
    rows = session.execute(
        select(permit.ApplicationComment)
        .where(permit.ApplicationComment.application_id == application_id)
        .order_by(permit.ApplicationComment.created_at, permit.ApplicationComment.id)
    ).scalars().all()
    if is_staff(session, actor):
        return list(rows)
    return [row for row in rows if row.visibility == "applicant"]


def comment_view(row: permit.ApplicationComment) -> dict[str, Any]:
    """Return the view of one comment."""
    return {
        "comment_id": row.id,
        "application_id": row.application_id,
        "body": row.body,
        "visibility": row.visibility,
        "author_actor_id": row.author_actor_id,
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


class CommentService:
    """Writes the comments of a case."""

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or utc_now()
        self._audit = AuditService(session, now=self._now)
        self._permissions = PermissionResolver(session, now=self._now)

    def add_comment(
        self,
        *,
        application_id: str,
        body: str,
        visibility: str,
        actor: ActorContext,
        expected_version: int | None,
        correlation_id: str | None = None,
    ) -> permit.ApplicationComment:
        """Write one comment on a case.

        The comment never changes the state of the case, so the case version
        is checked but not advanced.  A comment that arrives with a stale
        expected version is refused: the person was looking at an older
        state of the case.
        """
        from acme_city.permits.guard import require_mutable

        clean_visibility = str(visibility or "").strip().lower()
        if clean_visibility not in COMMENT_VISIBILITIES:
            raise ValidationError(
                "a comment is either visible to the applicant or internal; "
                "use one of " + ", ".join(COMMENT_VISIBILITIES)
            )
        text = str(body or "").strip()
        if not text:
            raise ValidationError("a comment needs a text")
        application = self._session.execute(
            select(permit.Application).where(permit.Application.id == application_id)
        ).scalar_one_or_none()
        if application is None:
            raise NotFoundError("that application does not exist")
        self._permissions.authorize(
            actor,
            PERMISSION_COMMENT,
            ResourceContext(
                domain_id="permits",
                record_ids=(
                    application.source_application_number,
                    application.applicant_party_id or "",
                ),
            ),
        )
        require_mutable(application, action="writing a comment")
        if expected_version is None:
            raise ValidationError(
                "an expected version is required to write a comment"
            )
        if application.version != expected_version:
            raise ValidationError(
                "the application changed since it was read; read it again and retry"
            )
        row = permit.ApplicationComment(
            id=new_id("comment"),
            correlation_id=correlation_id or application.correlation_id or new_id("corr"),
            application_id=application.id,
            body=text,
            visibility=clean_visibility,
            author_actor_id=actor.actor_id,
            version=1,
        )
        self._session.add(row)
        self._session.flush()
        # The audit record carries the comment identifier and its visibility.
        # It never carries the text, so an internal note cannot reach an
        # applicant through the audit trail.
        self._audit.append(
            action="application.comment.add",
            actor=actor,
            target_type="application",
            target_id=application.id,
            after_version=application.version,
            references=[row.id],
            correlation_id=row.correlation_id,
            metadata={
                "comment_id": row.id,
                "visibility": clean_visibility,
            },
        )
        self._session.flush()
        return row


__all__ = [
    "COMMENT_VISIBILITIES",
    "PERMISSION_COMMENT",
    "STAFF_MARKER_GRANTS",
    "CommentService",
    "comment_view",
    "comments_for",
    "is_staff",
]
