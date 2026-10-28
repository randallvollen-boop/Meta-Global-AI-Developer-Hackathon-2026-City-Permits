"""FastAPI application factory.

The factory wires the governed endpoints onto one local service.  It never
reports a database path or a secret, and it never accepts authority from a
request body.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from acme_city.core.config import Settings
from acme_city.core.errors import AcmeError, PermissionDeniedError
from acme_city.persistence.session import SessionFactory, database_health


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


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the application instance.

    Args:
        settings: Optional pre-loaded settings.  When omitted, settings are
            loaded from the environment and the local key file.
    """
    resolved = settings or Settings.load()
    app = FastAPI(
        title="ACME City Permit Demonstration",
        version="0.1.0",
        description=(
            "Fictional ACME City registry-MDM permit demonstration. "
            "All data, rules, fees and permits in this service are synthetic."
        ),
    )
    app.state.settings = resolved
    app.state.session_factory = SessionFactory(resolved.database_url)

    from acme_city.auth.router import router as session_router
    from acme_city.changes.router import router as changes_router
    from acme_city.city.router import router as city_router
    from acme_city.finance.router import router as finance_router
    from acme_city.gis.simulator import router as gis_simulator_router
    from acme_city.governance.router import router as governance_router
    from acme_city.ingestion.router import router as ingestion_router
    from acme_city.portal_intake.router import router as intake_router
    from acme_city.muse.router import router as muse_router
    from acme_city.permits.router import router as permit_router
    from acme_city.registry.router import router as registry_router
    from acme_city.rules.router import router as rules_router
    from acme_city.ui.router import router as ui_router

    app.include_router(session_router)
    app.include_router(governance_router)
    app.include_router(ingestion_router)
    app.include_router(intake_router)
    app.include_router(registry_router)
    app.include_router(changes_router)
    app.include_router(permit_router)
    app.include_router(rules_router)
    app.include_router(finance_router)
    app.include_router(muse_router)
    app.include_router(gis_simulator_router)
    app.include_router(ui_router)
    app.include_router(city_router)

    @app.exception_handler(AcmeError)
    async def handle_application_error(request: Request, exc: AcmeError) -> JSONResponse:
        """Return the stable error envelope for an application error."""
        if isinstance(exc, PermissionDeniedError):
            _record_denial(request, exc)
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(SQLAlchemyError)
    async def handle_database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        """Report that persistence is unavailable without leaking internals."""
        return JSONResponse(
            status_code=503,
            content={
                "code": "database_unavailable",
                "message": "the demonstration database is not available",
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

    return app


__all__ = ["create_app"]
