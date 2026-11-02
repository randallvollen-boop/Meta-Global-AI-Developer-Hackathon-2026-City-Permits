"""The judge's own visit of the shared demonstration.

The hosted demonstration is shared, so the walkthrough remembers which copy of
the café case belongs to the visitor.  The visitor is a cookie with a random
identifier: never a name, never a persona and never a record of the City.

The identifier gives the visitor a token of their own.  The token proves that
a write of the demonstration came from the page the server sent, so the Start
fresh button may create a copy of the café case even before a persona is
chosen.  A signed-in visitor uses the token of the session instead, and the
cookie is only the fallback.
"""
# REQUIRES: UX-04, SEC-02
# The visitor is a random identifier, never a person, and its token proves
# only that the request came from this server.

from __future__ import annotations

import hmac
import secrets
from typing import Any

from fastapi import Request, Response

from acme_city.auth.context import ActorContext
from acme_city.core.config import Settings
from acme_city.core.errors import PermissionDeniedError

#: The cookie that holds the random identifier of the visitor.
JUDGE_COOKIE = "acme_judge"

#: The cookie that holds the copy of the café case the visitor walks.
CASE_COOKIE = "acme_judge_case"

#: The scope the token of a visitor is derived from.
JUDGE_SCOPE = "judge:"

#: How long the cookies of the visitor live, in seconds.
COOKIE_MAX_AGE = 60 * 60 * 24 * 30


def judge_id(request: Request) -> str:
    """Return the identifier of the visitor, or an empty string."""
    return str(request.cookies.get(JUDGE_COOKIE, "") or "")


def new_judge_id() -> str:
    """Return a fresh random identifier for a visitor."""
    return secrets.token_hex(12)


def judge_token(settings: Settings, judge: str) -> str:
    """Return the token of the visitor with that identifier."""
    from acme_city.ui.router import csrf_token

    return csrf_token(settings, f"{JUDGE_SCOPE}{judge}")


def set_cookie(response: Response, request: Request, name: str, value: str) -> None:
    """Write one cookie of the visitor on the response."""
    response.set_cookie(
        name,
        value,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )


def page_context(request: Request) -> dict[str, Any]:
    """Return the context of the visitor: the token and the copy it walks.

    The identifier of a visitor who arrives for the first time is drawn here,
    and the caller writes it on the response with :func:`attach`.
    """
    judge = judge_id(request) or new_judge_id()
    return {
        "csrf_token": judge_token(request.app.state.settings, judge),
        "case_id": copy_case_id(request),
        "fresh_url": "/walkthrough/start-fresh",
        "judge_id": judge,
        "is_new": not bool(judge_id(request)),
    }


def attach(response: Response, request: Request, context: dict[str, Any]) -> None:
    """Write the cookie of a visitor who arrived for the first time."""
    if context.get("is_new") and context.get("judge_id"):
        set_cookie(response, request, JUDGE_COOKIE, str(context["judge_id"]))


def copy_case_id(request: Request) -> str:
    """Return the copy of the café case the visitor walks, or an empty string."""
    return str(request.cookies.get(CASE_COOKIE, "") or "")


def remember_copy(response: Response, request: Request, application_id: str) -> None:
    """Remember the copy of the café case the visitor walks."""
    set_cookie(response, request, CASE_COOKIE, application_id)


def forget_copy(response: Response, request: Request) -> None:
    """Forget a café copy that no longer exists in the demonstration."""
    response.delete_cookie(
        CASE_COOKIE,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
    )


def expected_tokens(settings: Settings, request: Request, actor: ActorContext | None) -> tuple[str, ...]:
    """Return the tokens a write of the visitor may carry."""
    from acme_city.ui.router import csrf_token

    tokens: list[str] = []
    if actor is not None:
        tokens.append(csrf_token(settings, actor.session_id))
    judge = judge_id(request)
    if judge:
        tokens.append(judge_token(settings, judge))
    return tuple(token for token in tokens if token)


def verify_write(
    settings: Settings,
    request: Request,
    actor: ActorContext | None,
    presented: str,
) -> None:
    """Refuse a write whose token does not belong to the visitor.

    A signed-in visitor proves the write with the token of the session.  A
    visitor who has not chosen a persona proves it with the token of the
    cookie, which only this server can derive.

    Raises:
        PermissionDeniedError: When the token is missing or does not belong
            to the visitor.
    """
    if not presented:
        raise PermissionDeniedError(
            "the form token does not belong to this visit; reload the screen and try again",
            actor_id=actor.actor_id if actor is not None else "",
            action="walkthrough.start_fresh",
        )
    for token in expected_tokens(settings, request, actor):
        if hmac.compare_digest(token, presented):
            return
    raise PermissionDeniedError(
        "the form token does not belong to this visit; reload the screen and try again",
        actor_id=actor.actor_id if actor is not None else "",
        action="walkthrough.start_fresh",
    )


__all__ = [
    "CASE_COOKIE",
    "COOKIE_MAX_AGE",
    "JUDGE_COOKIE",
    "JUDGE_SCOPE",
    "attach",
    "copy_case_id",
    "expected_tokens",
    "forget_copy",
    "judge_id",
    "judge_token",
    "new_judge_id",
    "page_context",
    "remember_copy",
    "set_cookie",
    "verify_write",
]
