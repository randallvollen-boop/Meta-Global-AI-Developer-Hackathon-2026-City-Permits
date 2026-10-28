"""The archive guard.

Archiving a case is a soft delete: the case and its history stay, but the
case is closed.  The guard is a service-level rule, not a screen check: every
service path that can change an application asks the guard first, so an
archived case cannot be reopened by a revision, a document, an evaluation,
an agent run, a recommendation, a parcel operation, a finance assessment or a
portal upload.

Only a version-checked restore reactivates a case, and a restore never
revives a stale approval or a stale recommendation.
"""
# REQUIRES: PER-03, SEC-02
# An archived application is refused by every service path that could change
# it, and only an authorized, version-checked restore reactivates it.

from __future__ import annotations

from acme_city.core.errors import ValidationError
from acme_city.persistence.models import permit

#: The status an archived case holds.
ARCHIVED_STATUS = "archived"

#: The status a returned case holds.  A returned case is terminal: the
#: applicant starts a new application rather than answering on this one.
RETURNED_STATUS = "returned"


def is_archived(application: permit.Application) -> bool:
    """Return whether the application is archived."""
    return application.status == ARCHIVED_STATUS


def is_returned(application: permit.Application) -> bool:
    """Return whether the application was returned to the applicant."""
    return application.status == RETURNED_STATUS


def require_mutable(application: permit.Application, *, action: str) -> None:
    """Refuse to change an archived application.

    ``action`` names the operation that was refused; it is used in the
    message a person reads, never a private record value.
    """
    if not is_archived(application):
        return
    raise ValidationError(
        f"this application is archived; {action} is refused until an administrator "
        "restores it"
    )


def require_not_returned(application: permit.Application, *, action: str) -> None:
    """Refuse to reopen a returned application.

    A return is terminal.  The applicant starts a new application, so no
    revision, evaluation or agent run may reopen the returned one.
    """
    if not is_returned(application):
        return
    raise ValidationError(
        f"this application was returned to the applicant; {action} is refused because "
        "the applicant starts a new application"
    )


__all__ = [
    "ARCHIVED_STATUS",
    "RETURNED_STATUS",
    "is_archived",
    "is_returned",
    "require_mutable",
    "require_not_returned",
]
