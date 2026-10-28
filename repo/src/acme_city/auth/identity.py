"""The sign-in seam.

Who a person is comes from an identity provider; what they may do comes from
the persisted grants (``auth/permissions.py``).  This module defines the
contract between the two and nothing else.  No OpenID Connect (OIDC) client is
implemented here.

How to plug a real provider in (documented in
``docs/operations/PRODUCTION_READINESS.md``):

1. Implement :class:`IdentityProvider`.  ``begin_login`` returns the redirect to
   the provider.  ``complete_login`` verifies the provider's answer and returns
   a :class:`VerifiedIdentity` (issuer and subject, never a role).
2. Map the verified identity to one persisted actor (a table keyed by issuer and
   subject), then call ``SessionService.establish_session(actor_id)`` and set
   the cookie it returns.  Grants stay server-side; the provider never states a
   role.
3. Return the provider from :func:`build_identity_provider` when it is
   configured, and mount its login and callback routes in ``create_app`` in
   production mode only.

Until a provider is configured, production mode has the
:class:`NotConfiguredIdentityProvider`: every staff route answers with the
"Sign-in is not configured" page.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from fastapi import Request
from fastapi.responses import Response

from acme_city.core.config import Settings

SIGN_IN_NOT_CONFIGURED_TITLE = "Sign-in is not configured"
SIGN_IN_NOT_CONFIGURED_MESSAGE = (
    "This deployment runs in production mode and no sign-in provider is configured, "
    "so nobody can act as a staff member or an applicant yet. An administrator must "
    "connect the City's identity provider before staff screens can be opened."
)


@dataclass(frozen=True)
class VerifiedIdentity:
    """A person the identity provider has verified.

    ``issuer`` and ``subject`` together identify the person.  A role is never
    part of it: the server maps the pair to one actor and resolves grants itself.
    """

    issuer: str
    subject: str
    display_name: str = ""


@runtime_checkable
class IdentityProvider(Protocol):
    """What the application needs from a sign-in provider."""

    #: Whether people can sign in through this provider right now.
    configured: bool

    def begin_login(self, request: Request) -> Response:
        """Return the response that starts a sign-in (usually a redirect)."""
        ...

    def complete_login(self, request: Request) -> VerifiedIdentity:
        """Verify the provider's answer and return who signed in.

        Raises:
            AuthenticationRequiredError: when the answer cannot be verified.
        """
        ...


class NotConfiguredIdentityProvider:
    """The production default: nobody can sign in."""

    configured = False

    def begin_login(self, request: Request) -> Response:
        from acme_city.core.errors import AuthenticationRequiredError

        raise AuthenticationRequiredError(SIGN_IN_NOT_CONFIGURED_TITLE)

    def complete_login(self, request: Request) -> VerifiedIdentity:
        from acme_city.core.errors import AuthenticationRequiredError

        raise AuthenticationRequiredError(SIGN_IN_NOT_CONFIGURED_TITLE)


def build_identity_provider(settings: Settings) -> IdentityProvider | None:
    """Return the identity provider of this deployment.

    Demo mode has none: the persona selector is its sign-in.  Production mode
    returns the configured provider; this is the place to construct one.
    """
    if not settings.is_production:
        return None
    return NotConfiguredIdentityProvider()


__all__ = [
    "SIGN_IN_NOT_CONFIGURED_MESSAGE",
    "SIGN_IN_NOT_CONFIGURED_TITLE",
    "IdentityProvider",
    "NotConfiguredIdentityProvider",
    "VerifiedIdentity",
    "build_identity_provider",
]
