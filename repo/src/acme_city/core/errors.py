"""Typed application errors and their API envelopes.

Error envelopes are stable: ``{"code", "message"}`` plus optional
``current_version`` and ``differences`` for conflicts.  Error messages never
carry private record values.
"""

from __future__ import annotations

from typing import Any


class AcmeError(Exception):
    """Base class for every application error."""

    code: str = "error"
    status_code: int = 400

    def __init__(self, message: str, *, code: str | None = None, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.details: dict[str, Any] = {k: v for k, v in details.items() if v is not None}

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        payload.update(self.details)
        return payload


class AuthenticationRequiredError(AcmeError):
    """No valid server-held session was presented."""

    code = "authentication_required"
    status_code = 401


class PermissionDeniedError(AcmeError):
    """The actor is known but the action is outside its granted scope."""

    code = "permission_denied"
    status_code = 403


class NotFoundError(AcmeError):
    """The requested record does not exist or is outside the actor's scope."""

    code = "not_found"
    status_code = 404


class ValidationError(AcmeError):
    """The command payload failed validation."""

    code = "validation_failed"
    status_code = 422


class ConflictError(AcmeError):
    """An expected version did not match the current stored version."""

    code = "version_conflict"
    status_code = 409


class GovernanceGateError(AcmeError):
    """A governance registration or publication gate blocked the action."""

    code = "governance_gate_blocked"
    status_code = 409


class IncompleteRegistrationError(GovernanceGateError):
    """A dataset is not fully registered, so trusted publication is blocked."""

    code = "incomplete_registration"


__all__ = [
    "AcmeError",
    "AuthenticationRequiredError",
    "ConflictError",
    "GovernanceGateError",
    "IncompleteRegistrationError",
    "NotFoundError",
    "PermissionDeniedError",
    "ValidationError",
]
