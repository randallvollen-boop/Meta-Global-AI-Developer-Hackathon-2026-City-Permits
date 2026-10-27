"""Server-held sessions.

A session identifier is random and meaningless on its own: it is signed with
the server secret and it resolves to a stored row that carries the actor and
the expiry.  A client that sends its own actor or role fields changes nothing.
"""
# REQUIRES: SEC-01
# The session identifier is random, signed and meaningless without its server-side
# record, so the acting actor can only come from the server.


from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.clock import utc_now
from acme_city.core.config import Settings
from acme_city.core.errors import AuthenticationRequiredError
from acme_city.persistence.models import governance

DEFAULT_COOKIE_NAME = "acme_session"
DEFAULT_SESSION_TTL_MINUTES = 480


@dataclass(frozen=True)
class SessionCookie:
    """A signed session cookie and what it stands for."""

    value: str
    actor_id: str
    expires_at: datetime
    cookie_name: str = DEFAULT_COOKIE_NAME
    http_only: bool = True
    same_site: str = "Lax"
    secure: bool = False

    def set_cookie_kwargs(self, path: str = "/") -> dict[str, object]:
        """Return the keyword arguments for ``Response.set_cookie``."""
        return {
            "key": self.cookie_name,
            "value": self.value,
            "max_age": int((self.expires_at - utc_now()).total_seconds()),
            "httponly": self.http_only,
            "samesite": self.same_site,
            "secure": self.secure,
            "path": path,
        }


class SessionService:
    """Creates and resolves server-held sessions."""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        *,
        cookie_name: str | None = None,
        ttl_minutes: int | None = None,
        secure_cookies: bool | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self.cookie_name = cookie_name or DEFAULT_COOKIE_NAME
        self.ttl_minutes = ttl_minutes or DEFAULT_SESSION_TTL_MINUTES
        self.secure_cookies = bool(secure_cookies)
        self.same_site = "Lax"
        self.http_only = True

    # ------------------------------------------------------------------ signing

    def _secret(self) -> bytes:
        return self._settings.secret_key.get_secret_value().encode("utf-8")

    def sign(self, session_id: str) -> str:
        """Return the signature of a session identifier."""
        digest = hmac.new(self._secret(), session_id.encode("utf-8"), hashlib.sha256)
        return digest.hexdigest()

    def _cookie_value(self, session_id: str) -> str:
        return f"{session_id}.{self.sign(session_id)}"

    def _verify(self, cookie_value: str) -> str:
        session_id, _, signature = cookie_value.partition(".")
        if not session_id or not signature:
            raise AuthenticationRequiredError("the session cookie is not valid")
        expected = self.sign(session_id)
        if not hmac.compare_digest(expected, signature):
            raise AuthenticationRequiredError("the session cookie is not signed correctly")
        return session_id

    # ------------------------------------------------------------------ lifecycle

    def select_actor(self, actor_id: str) -> SessionCookie:
        """Establish a server-held session for a fictional demo actor.

        Raises:
            NotFoundError-free: an unknown actor raises
                :class:`AuthenticationRequiredError` so that the endpoint
                cannot be used to discover which actors exist.
        """
        actor = self._session.execute(
            select(governance.Actor).where(governance.Actor.actor_id == actor_id)
        ).scalar_one_or_none()
        if actor is None or not actor.active or not actor.selectable:
            # A service identity is never offered a session: only the four
            # selectable personas may act.
            raise AuthenticationRequiredError("that actor is not available for a session")

        now = utc_now()
        expires_at = now + timedelta(minutes=self.ttl_minutes)
        session_id = secrets.token_urlsafe(32)
        self._session.add(
            governance.Session(
                id=f"session_{secrets.token_hex(8)}",
                session_id=session_id,
                actor_id=actor_id,
                issued_at=now,
                expires_at=expires_at,
            )
        )
        self._session.flush()
        return SessionCookie(
            value=self._cookie_value(session_id),
            actor_id=actor_id,
            expires_at=expires_at,
            cookie_name=self.cookie_name,
            http_only=self.http_only,
            same_site=self.same_site,
            secure=self.secure_cookies,
        )

    def resolve_actor(self, request: Request) -> ActorContext:
        """Resolve the acting actor from the request cookie.

        Raises:
            AuthenticationRequiredError: when the cookie is missing, unsigned,
                expired, revoked or unknown.
        """
        cookie_value = request.cookies.get(self.cookie_name)
        if not cookie_value:
            raise AuthenticationRequiredError("no session cookie was presented")
        session_id = self._verify(cookie_value)

        record = self._session.execute(
            select(governance.Session).where(governance.Session.session_id == session_id)
        ).scalar_one_or_none()
        if record is None:
            raise AuthenticationRequiredError("the session is not known to the server")
        if record.revoked_at is not None:
            raise AuthenticationRequiredError("the session was revoked")
        if record.expires_at <= utc_now():
            raise AuthenticationRequiredError("the session expired")

        actor = self._session.execute(
            select(governance.Actor).where(governance.Actor.actor_id == record.actor_id)
        ).scalar_one_or_none()
        if actor is None or not actor.active:
            raise AuthenticationRequiredError("the actor of the session is not active")

        role_ids = frozenset(
            row[0]
            for row in self._session.execute(
                select(governance.ActorRole.role_id).where(
                    governance.ActorRole.actor_id == actor.actor_id
                )
            ).all()
        )
        grants = PermissionResolver(self._session).grants_for(actor.actor_id)
        domain_scope = frozenset(grant.domain_id for grant in grants if grant.domain_id)
        record_scope = frozenset(
            record_id for grant in grants for record_id in grant.record_scope
        )
        return ActorContext(
            actor_id=actor.actor_id,
            role_ids=role_ids,
            domain_scope=domain_scope,
            record_scope=record_scope,
            session_id=record.session_id,
            active=True,
        )

    def revoke(self, session_id: str) -> None:
        """Revoke a stored session."""
        record = self._session.execute(
            select(governance.Session).where(governance.Session.session_id == session_id)
        ).scalar_one_or_none()
        if record is not None and record.revoked_at is None:
            record.revoked_at = utc_now()


__all__ = ["DEFAULT_COOKIE_NAME", "DEFAULT_SESSION_TTL_MINUTES", "SessionCookie", "SessionService"]
