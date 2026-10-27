"""The lifecycle of a permit application.

The lifecycle service owns the transitions a person makes on a case: return
it to the applicant, advance it to review, ask the applicant for revisions,
archive it, restore it, change its priority and route it to a staff member.

Every transition is a governed action: it checks the grant, the archived
guard and a mandatory expected version, it records an action record that
snapshots the reason code, and it writes an audit record.  The browser never
decides who may act.

The owner of a case is routing metadata only.  An owner gains no authority
and never becomes a selectable persona.
"""
# REQUIRES: PER-03, PER-04, SEC-02, SEC-03
# A status change is authorized, version-checked, guarded against an
# archived case and audited, and the reason code it used is snapshotted on
# the action record.

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.agents.findings import blocking_findings
from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.configuration.reasons import ReasonCodeSnapshot, reason_code_snapshot
from acme_city.core.clock import utc_now
from acme_city.core.errors import NotFoundError, ValidationError
from acme_city.core.ids import new_id
from acme_city.permits.comments import CommentService
from acme_city.permits.guard import is_archived, require_mutable
from acme_city.persistence.models import permit

#: The grants the lifecycle actions need.
PERMISSION_RETURN = "permit.case.return"
PERMISSION_ADVANCE = "permit.case.advance"
PERMISSION_REQUEST_REVISIONS = "permit.case.request_revisions"
PERMISSION_ARCHIVE = "permit.case.archive"
PERMISSION_RESTORE = "permit.case.restore"

#: The domain every permit action is authorized in.
PERMIT_DOMAIN = "permits"

#: The statuses a case may hold when it is returned to the applicant.
RETURNABLE_STATUSES: frozenset[str] = frozenset({"needs_information"})

#: The statuses a case may hold when it is advanced to review.
ADVANCEABLE_STATUSES: frozenset[str] = frozenset({"needs_information"})

#: The statuses a case may hold when revisions are requested.
REVISION_STATUSES: frozenset[str] = frozenset({"ready_for_review", "under_review"})

#: The statuses a case may hold when it is archived.  An issued case keeps
#: its issued state and is never archived.
ARCHIVABLE_STATUSES: frozenset[str] = frozenset(
    {
        "draft",
        "submitted",
        "needs_information",
        "revisions_requested",
        "ready_for_review",
        "under_review",
        "approved",
        "denied",
        "withdrawn",
        "returned",
    }
)

#: The statuses a case may hold when it is routed to an intake owner.
INTAKE_STAGE_STATUSES: frozenset[str] = frozenset(
    {"submitted", "needs_information", "revisions_requested"}
)

#: The statuses a case may hold when it is routed to a review owner.
REVIEW_STAGE_STATUSES: frozenset[str] = frozenset({"ready_for_review", "under_review"})


class LifecycleService:
    """The transitions a person makes on an application."""

    def __init__(self, session: Session, *, now: datetime | None = None) -> None:
        self._session = session
        self._now = now or utc_now()
        self._audit = AuditService(session, now=self._now)
        self._permissions = PermissionResolver(session, now=self._now)
        self._comments = CommentService(session, now=self._now)

    # ----------------------------------------------------------------- loading

    def load_application(self, application_id: str) -> permit.Application:
        """Return the stored application or refuse."""
        application = self._session.execute(
            select(permit.Application).where(permit.Application.id == application_id)
        ).scalar_one_or_none()
        if application is None:
            raise NotFoundError("that application does not exist")
        return application

    # --------------------------------------------------------------- transitions

    def return_application(
        self,
        *,
        application_id: str,
        reason_code: str,
        reason: str = "",
        actor: ActorContext,
        expected_version: int | None,
    ) -> permit.Application:
        """Return a case to the applicant.

        A return is terminal: the applicant starts a new application.  The
        reason code is required and must be an active code of the ``return``
        type.
        """
        application = self._load_for_action(
            application_id,
            actor,
            PERMISSION_RETURN,
            expected_version,
            action="returning the application",
        )
        if application.status not in RETURNABLE_STATUSES:
            raise ValidationError(
                f"an application in status {application.status!r} cannot be returned"
            )
        snapshot = reason_code_snapshot(self._session, reason_code, code_type="return")
        application.status = "returned"
        application.version += 1
        self._session.flush()
        self._record_action(
            application=application,
            action="return",
            actor=actor,
            snapshot=snapshot,
            reason=reason,
            metadata={"status_before": "needs_information", "status_after": "returned"},
        )
        return application

    def advance_to_review(
        self,
        *,
        application_id: str,
        actor: ActorContext,
        expected_version: int | None,
    ) -> permit.Application:
        """Advance a case to the review area of its type.

        The advance is refused while a current, unwaived blocking finding
        stands in the way.
        """
        application = self._load_for_action(
            application_id,
            actor,
            PERMISSION_ADVANCE,
            expected_version,
            action="advancing the application",
        )
        if application.status not in ADVANCEABLE_STATUSES:
            raise ValidationError(
                f"an application in status {application.status!r} cannot be advanced to review"
            )
        blockers = blocking_findings(self._session, application.id)
        if blockers:
            raise ValidationError(
                "the application still has blocking findings that a person must clear "
                "or waive first",
                blockers=[
                    {
                        "finding_id": row.id,
                        "finding_type": row.finding_type,
                        "message": row.message,
                    }
                    for row in blockers
                ],
            )
        application.status = "ready_for_review"
        application.version += 1
        self._session.flush()
        self._record_action(
            application=application,
            action="advance_to_review",
            actor=actor,
            metadata={
                "status_before": "needs_information",
                "status_after": "ready_for_review",
            },
        )
        return application

    def request_revisions(
        self,
        *,
        application_id: str,
        reason_code: str,
        message: str,
        actor: ActorContext,
        expected_version: int | None,
    ) -> permit.Application:
        """Ask the applicant for revisions.

        The reviewer names a reason code and writes a message.  The message
        is written as a comment the applicant may read, so the applicant sees
        why the case came back.
        """
        application = self._load_for_action(
            application_id,
            actor,
            PERMISSION_REQUEST_REVISIONS,
            expected_version,
            action="requesting revisions",
        )
        if application.status not in REVISION_STATUSES:
            raise ValidationError(
                f"an application in status {application.status!r} cannot be sent back "
                "for revisions"
            )
        text = str(message or "").strip()
        if not text:
            raise ValidationError("asking for revisions needs a message for the applicant")
        snapshot = reason_code_snapshot(self._session, reason_code, code_type="revision")
        before_status = application.status
        before_version = application.version
        comment = self._comments.add_comment(
            application_id=application.id,
            body=text,
            visibility="applicant",
            actor=actor,
            expected_version=before_version,
            correlation_id=application.correlation_id,
        )
        application.status = "revisions_requested"
        application.version += 1
        self._session.flush()
        self._record_action(
            application=application,
            action="request_revisions",
            actor=actor,
            snapshot=snapshot,
            reason=text,
            comment_id=comment.id,
            metadata={
                "status_before": before_status,
                "status_after": "revisions_requested",
            },
        )
        return application

    def archive(
        self,
        *,
        application_id: str,
        reason_code: str,
        reason: str = "",
        actor: ActorContext,
        expected_version: int | None,
    ) -> permit.Application:
        """Archive a case.

        Archiving is a soft delete: the case and its history stay, and every
        service path that could change the case refuses it until an
        administrator restores it.
        """
        application = self._load_for_action(
            application_id,
            actor,
            PERMISSION_ARCHIVE,
            expected_version,
            action="archiving the application",
        )
        if application.status == "issued":
            raise ValidationError("an issued permit is never archived")
        if application.status not in ARCHIVABLE_STATUSES:
            raise ValidationError(
                f"an application in status {application.status!r} cannot be archived"
            )
        snapshot = reason_code_snapshot(self._session, reason_code, code_type="archive")
        previous_status = application.status
        application.status = "archived"
        application.status_before_archive = previous_status
        application.archived_at = self._now
        application.archived_by_actor_id = actor.actor_id
        application.archive_reason_code_id = snapshot.reason_code_id
        application.archive_reason = str(reason or "").strip() or None
        application.version += 1
        self._session.flush()
        self._record_action(
            application=application,
            action="archive",
            actor=actor,
            snapshot=snapshot,
            reason=reason,
            metadata={
                "status_before": previous_status,
                "status_after": "archived",
            },
        )
        return application

    def restore(
        self,
        *,
        application_id: str,
        actor: ActorContext,
        expected_version: int | None,
    ) -> permit.Application:
        """Restore an archived case to the status it held.

        A restore never revives a stale approval or a stale recommendation:
        whatever was marked stale stays stale, so the case has to be worked
        again before a decision may be made.
        """
        application = self._load_for_action(
            application_id,
            actor,
            PERMISSION_RESTORE,
            expected_version,
            action="restoring the application",
            allow_archived=True,
        )
        if not is_archived(application):
            raise ValidationError("that application is not archived")
        restored = application.status_before_archive or "submitted"
        application.status = restored
        application.version += 1
        self._session.flush()
        self._record_action(
            application=application,
            action="restore",
            actor=actor,
            metadata={
                "status_before": "archived",
                "status_after": restored,
            },
        )
        return application

    # --------------------------------------------------------------- internals

    def _load_for_action(
        self,
        application_id: str,
        actor: ActorContext,
        permission: str,
        expected_version: int | None,
        *,
        action: str,
        allow_archived: bool = False,
    ) -> permit.Application:
        """Load the application of an action and check it may happen.

        The order is deliberate: the grant first, then the case, then the
        version, then the archive guard.  The restore is the one action the
        archive guard lets through.
        """
        application = self.load_application(application_id)
        self._permissions.authorize(
            actor,
            permission,
            ResourceContext(
                domain_id=PERMIT_DOMAIN,
                record_ids=(
                    application.source_application_number,
                    application.applicant_party_id or "",
                ),
            ),
        )
        if expected_version is None:
            raise ValidationError(f"an expected version is required to {action}")
        if application.version != expected_version:
            raise ValidationError(
                f"the application changed since it was read; read it again and retry"
            )
        if not allow_archived:
            require_mutable(application, action=action)
        return application

    def _record_action(
        self,
        *,
        application: permit.Application,
        action: str,
        actor: ActorContext,
        snapshot: ReasonCodeSnapshot | None = None,
        reason: str = "",
        comment_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> permit.ApplicationAction:
        """Record one lifecycle action and its audit event."""
        row = permit.ApplicationAction(
            id=new_id("appaction"),
            correlation_id=application.correlation_id or new_id("corr"),
            application_id=application.id,
            action=action,
            actor_id=actor.actor_id,
            occurred_at=self._now,
            reason_code_id=None if snapshot is None else snapshot.reason_code_id,
            reason_code=None if snapshot is None else snapshot.code,
            reason_code_label=None if snapshot is None else snapshot.label,
            reason_code_version=None if snapshot is None else snapshot.version,
            reason=str(reason or "").strip() or None,
            comment_id=comment_id,
            metadata_json=dict(metadata) if metadata else None,
        )
        self._session.add(row)
        self._session.flush()
        self._audit.append(
            action=f"application.{action}",
            actor=actor,
            target_type="application",
            target_id=application.id,
            after_version=application.version,
            reason=row.reason,
            references=[row.id] + ([comment_id] if comment_id else []),
            correlation_id=row.correlation_id,
            metadata={
                "action": action,
                "reason_code": row.reason_code,
                "reason_code_label": row.reason_code_label,
                "reason_code_version": row.reason_code_version,
                "comment_id": comment_id or "",
                "detail": dict(metadata) if metadata else {},
            },
        )
        self._session.flush()
        return row


def action_view(row: permit.ApplicationAction) -> dict[str, Any]:
    """Return the readable form of one recorded action."""
    return {
        "action_id": row.id,
        "application_id": row.application_id,
        "action": row.action,
        "actor_id": row.actor_id,
        "occurred_at": row.occurred_at.isoformat() if row.occurred_at else "",
        "reason_code": row.reason_code or "",
        "reason_code_label": row.reason_code_label or "",
        "reason_code_version": row.reason_code_version,
        "reason": row.reason or "",
        "comment_id": row.comment_id or "",
    }


__all__ = [
    "ADVANCEABLE_STATUSES",
    "ARCHIVABLE_STATUSES",
    "PERMISSION_ADVANCE",
    "PERMISSION_ARCHIVE",
    "PERMISSION_REQUEST_REVISIONS",
    "PERMISSION_RESTORE",
    "PERMISSION_RETURN",
    "REVISION_STATUSES",
    "RETURNABLE_STATUSES",
    "LifecycleService",
    "action_view",
]
