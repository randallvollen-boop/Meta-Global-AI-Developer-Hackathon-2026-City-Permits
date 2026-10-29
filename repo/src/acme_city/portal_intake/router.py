"""The simulated outside-intake endpoints.

Every endpoint resolves the actor from the server-held session.  A record
carries no authority; staging is authorized against the submitting actor and
the registered contract, and the application is then created and triaged by
the intake service identity.
"""
# REQUIRES: ING-01, PER-01, AI-04
# Intake posts are idempotent on the portal reference, run the triage
# pipeline synchronously, and never write a table directly.

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext
from acme_city.auth.router import get_actor, get_session
from acme_city.portal_intake.scenarios import SCENARIO_NAMES
from acme_city.portal_intake.schemas import IntakeRecordCommand
from acme_city.portal_intake.service import IntakeService

router = APIRouter(prefix="/api/intake", tags=["intake"])
#: The intake simulator endpoints.  Mounted in demo mode only.
simulator_router = APIRouter(prefix="/api/intake", tags=["intake"])


class SimulateCommand(BaseModel):
    """Run one deterministic intake scenario server-side."""

    model_config = ConfigDict(extra="ignore")

    scenario: str = Field(min_length=1, max_length=64)
    count: int | None = Field(default=None, ge=1, le=50)
    live_muse: bool = False


def _service(request: Request, session: Session) -> IntakeService:
    return IntakeService(session, settings=request.app.state.settings)


@router.post("/records", operation_id="submit_intake_record")
def submit_intake_record(
    record: IntakeRecordCommand,
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Submit one outside intake record and run triage for it."""
    result = _service(request, session).submit_record(record, actor)
    return result.model_dump(mode="json")


@simulator_router.post("/simulate", operation_id="simulate_intake")
def simulate_intake(
    command: SimulateCommand,
    request: Request,
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """Simulate a batch of incoming permits from one named scenario."""
    if command.scenario not in SCENARIO_NAMES:
        from acme_city.core.errors import ValidationError

        raise ValidationError(
            f"unknown intake scenario: {command.scenario!r}; use one of "
            + ", ".join(SCENARIO_NAMES)
        )
    service = IntakeService(
        session,
        settings=request.app.state.settings,
        live_muse=command.live_muse,
    )
    results = service.simulate(command.scenario, count=command.count, actor=actor)
    return {
        "scenario": command.scenario,
        "results": [result.model_dump(mode="json") for result in results],
    }


@simulator_router.get("/scenarios", operation_id="list_intake_scenarios")
def list_intake_scenarios(
    session: Session = Depends(get_session, scope="function"),
    actor: ActorContext = Depends(get_actor),
) -> dict:
    """List the deterministic intake scenarios."""
    return {"scenarios": list(SCENARIO_NAMES)}


__all__ = ["router", "simulator_router"]
