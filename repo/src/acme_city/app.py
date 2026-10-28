"""FastAPI application factory.

The factory wires the governed endpoints onto one local service.  It never
reports a database path or a secret, and it never accepts authority from a
request body.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from acme_city.core.config import Settings
from acme_city.core.errors import AcmeError, PermissionDeniedError
from acme_city.persistence.session import (
    SessionFactory,
    database_health,
    database_is_demo,
    expected_head_revision,
)

logger = logging.getLogger("acme_city")


class ProductionStartupError(RuntimeError):
    """Production mode refuses to start in an unsafe configuration."""


def _record_denial(request: Request, exc: PermissionDeniedError) -> None:
    """Record a denied sensitive write in its own transaction.

    The denial is written without any private record value: the action, the
    actor and the domain are enough to investigate it.
    """
    from acme_city.audit.service import AuditService

    factory = getattr(request.app.state, "session_factory", None)
    if factory is None:
        return
    action = str(exc.details.get("action", "unknown"))
    actor_id = exc.details.get("actor_id")
    try:
        with factory() as session:
            with session.begin():
                AuditService(session).record_denied(
                    action=action,
                    actor=str(actor_id) if actor_id else "unknown",
                    target_type=exc.details.get("target_type"),
                    target_id=exc.details.get("target_id"),
                    denial_reason="outside the granted scope",
                )
    except SQLAlchemyError:
        # A denial must never turn into a server error.
        return


def _install_scenario_clock(settings: Settings, factory: SessionFactory) -> None:
    """Set the demo scenario clock for this process, or clear a previous one."""
    from acme_city.core.clock import set_scenario_clock
    from acme_city.fixtures.scenario_clock import install_scenario_clock

    set_scenario_clock(None)
    if not settings.scenario_clock:
        return
    session = factory()
    try:
        install_scenario_clock(session, settings.scenario_clock)
    except SQLAlchemyError:
        set_scenario_clock(None)
    finally:
        session.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the application instance.

    Args:
        settings: Optional pre-loaded settings.  When omitted, settings are
            loaded from the environment and the local key file.
    """
    resolved = settings or Settings.load()
    production = resolved.is_production
    app = FastAPI(
        title="ACME City Permit Demonstration",
        version="0.1.0",
        description=(
            "Fictional ACME City registry-MDM permit demonstration. "
            "All data, rules, fees and permits in this service are synthetic."
        ),
        # The generated API documentation is a demonstration convenience.
        docs_url=None if production else "/docs",
        redoc_url=None if production else "/redoc",
        openapi_url=None if production else "/openapi.json",
    )
    app.state.settings = resolved
    app.state.session_factory = SessionFactory(resolved.database_url)
    if production:
        if database_is_demo(app.state.session_factory.engine):
            app.state.session_factory.dispose()
            raise ProductionStartupError(
                "production mode refuses to start against a database marked as the "
                "fictional demonstration"
            )
        # The scenario clock is a demonstration device: always off in production.
        from acme_city.core.clock import set_scenario_clock

        set_scenario_clock(None)
        if resolved.scenario_clock:
            logger.warning("ACME_SCENARIO_CLOCK is ignored in production mode")
    else:
        _install_scenario_clock(resolved, app.state.session_factory)
        if resolved.secret_is_ephemeral:
            logger.warning(
                "ACME_SECRET_KEY is not set: sessions are signed with a key generated "
                "for this process and end when it restarts"
            )

    from acme_city.auth.identity import build_identity_provider

    app.state.identity_provider = build_identity_provider(resolved)

    from acme_city.auth.router import router as session_router
    from acme_city.auth.router import selector_router as session_selector_router
    from acme_city.changes.router import router as changes_router
    from acme_city.city.router import router as city_router
    from acme_city.finance.router import router as finance_router
    from acme_city.gis.simulator import router as gis_simulator_router
    from acme_city.portal_intake.router import simulator_router as intake_simulator_router
    from acme_city.governance.router import router as governance_router
    from acme_city.ingestion.router import router as ingestion_router
    from acme_city.portal_intake.router import router as intake_router
    from acme_city.muse.router import router as muse_router
    from acme_city.permits.router import router as permit_router
    from acme_city.registry.router import router as registry_router
    from acme_city.rules.router import router as rules_router
    from acme_city.ui.router import persona_router, signin_router
    from acme_city.ui.router import router as ui_router

    app.include_router(session_router)
    if production:
        # No persona selector, no simulators: the people who act come from a
        # real sign-in (see auth/identity.py), and nothing simulated is mounted.
        app.include_router(signin_router)
    else:
        app.include_router(session_selector_router)
        app.include_router(persona_router)
        app.include_router(intake_simulator_router)
        app.include_router(gis_simulator_router)
    app.include_router(governance_router)
    app.include_router(ingestion_router)
    app.include_router(intake_router)
    app.include_router(registry_router)
    app.include_router(changes_router)
    app.include_router(permit_router)
    app.include_router(rules_router)
    app.include_router(finance_router)
    app.include_router(muse_router)
    app.include_router(ui_router)
    app.include_router(city_router)

    @app.exception_handler(AcmeError)
    async def handle_application_error(request: Request, exc: AcmeError) -> JSONResponse:
        """Return the stable error envelope for an application error."""
        if isinstance(exc, PermissionDeniedError):
            _record_denial(request, exc)
        content = exc.to_public_dict() if production else exc.to_dict()
        return JSONResponse(status_code=exc.status_code, content=content)

    @app.exception_handler(SQLAlchemyError)
    async def handle_database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        """Report that persistence is unavailable without leaking internals."""
        return JSONResponse(
            status_code=503,
            content={
                "code": "database_unavailable",
                "message": (
                    "the database is not available"
                    if production
                    else "the demonstration database is not available"
                ),
            },
        )

    @app.get("/healthz", operation_id="get_health", tags=["system"])
    def healthz() -> dict[str, object]:
        """Report service liveness and the migration state.

        The response never contains a database path or a secret value.
        """
        health = database_health(resolved, engine=app.state.session_factory.engine)
        return {
            "status": "ok" if health.reachable and health.state == "current" else "degraded",
            "database": health.state,
            "schema_revision": health.revision,
        }

    @app.get("/readyz", operation_id="get_readiness", tags=["system"])
    def readyz() -> JSONResponse:
        """Report readiness: reachable, at the expected migration head, bootstrapped.

        Returns 503 when the database is unreachable, the migration revision is
        not the Alembic head of this build, or (production only) the database is
        marked as the fictional demonstration.  The body never contains a path,
        a secret or a revision other than the two revision identifiers.
        """
        health = database_health(resolved, engine=app.state.session_factory.engine)
        head = expected_head_revision(resolved)
        checks = {
            "database_reachable": health.reachable,
            "schema_at_head": bool(health.reachable and head and health.revision == head),
            "bootstrap_ok": not (
                production
                and health.reachable
                and database_is_demo(app.state.session_factory.engine)
            ),
        }
        ready = all(checks.values())
        return JSONResponse(
            status_code=200 if ready else 503,
            content={
                "status": "ready" if ready else "not_ready",
                "mode": resolved.deployment_mode,
                "checks": checks,
                "schema_revision": health.revision,
                "expected_revision": head,
            },
            headers={"Cache-Control": "no-store"},
        )

    # Added last so they wrap every route: headers apply to all responses.
    from acme_city.core.security import SecurityHeadersMiddleware, TrustedProxyMiddleware

    app.add_middleware(SecurityHeadersMiddleware, production=production)
    if resolved.trust_proxy_headers:
        app.add_middleware(TrustedProxyMiddleware)

    return app


__all__ = ["create_app"]
