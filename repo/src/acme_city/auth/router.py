"""The session endpoints.

The actor selector establishes a server-held session.  A client may not send a
role, a permission or a scope: the server resolves the actor and its grants.
"""
# REQUIRES: SEC-01
# The persona selector establishes the server-held session. It offers exactly the four
# selectable personas and never a service identity.


from __future__ import annotations

from collections.abc import Iterator

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.auth.service import SessionService
from acme_city.persistence.models import governance

router = APIRouter(prefix="/api/session", tags=["session"])
#: The demonstration persona selector.  Mounted in demo mode only.
selector_router = APIRouter(prefix="/api/session", tags=["session"])


class SelectActorRequest(BaseModel):
    """The only field a client may send to the actor selector."""

    model_config = ConfigDict(extra="ignore")

    actor_id: str


def get_session(request: Request) -> Iterator[Session]:
    """Yield a database session for the request."""
    factory = request.app.state.session_factory
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_actor(
    request: Request, session: Session = Depends(get_session)
) -> ActorContext:
    """Resolve the acting actor from the server-held session."""
    settings = request.app.state.settings
    return SessionService(session, settings).resolve_actor(request)


def session_service(request: Request, session: Session) -> SessionService:
    """Return a session service bound to the request settings."""
    return SessionService(session, request.app.state.settings)


@selector_router.get("/actors", operation_id="list_demo_actors")
def list_demo_actors(session: Session = Depends(get_session)) -> dict:
    """List the four fictional personas a demonstration session may select.

    Service identities and source role templates are never offered here.
    """
    actors = session.execute(
        select(governance.Actor)
        .where(governance.Actor.active.is_(True), governance.Actor.selectable.is_(True))
        .order_by(governance.Actor.actor_id)
    ).scalars().all()
    return {
        "actors": [
            {"actor_id": actor.actor_id, "label": actor.label, "fictional": actor.fictional}
            for actor in actors
        ]
    }


@selector_router.post("/select", operation_id="select_demo_actor")
def select_demo_actor(
    payload: SelectActorRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> dict:
    """Establish a server-held session for the selected fictional actor."""
    service = session_service(request, session)
    cookie = service.select_actor(payload.actor_id)
    response.set_cookie(**cookie.set_cookie_kwargs())
    actor = session.execute(
        select(governance.Actor).where(governance.Actor.actor_id == cookie.actor_id)
    ).scalar_one()
    return {
        "actor_id": actor.actor_id,
        "label": actor.label,
        "expires_at": cookie.expires_at,
        "cookie": {
            "name": cookie.cookie_name,
            "http_only": cookie.http_only,
            "same_site": cookie.same_site,
            "secure": cookie.secure,
        },
    }


@router.get("", operation_id="get_current_session")
def get_current_session(
    request: Request,
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Return the current actor context."""
    return actor.to_dict()


@router.delete("", operation_id="end_current_session")
def end_current_session(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Revoke the current server-held session."""
    service = session_service(request, session)
    if actor.session_id:
        service.revoke(actor.session_id)
    response.delete_cookie(key=service.cookie_name, path="/")
    return {"revoked": True, "actor_id": actor.actor_id}


__all__ = ["SelectActorRequest", "get_actor", "get_session", "router", "selector_router", "session_service"]
