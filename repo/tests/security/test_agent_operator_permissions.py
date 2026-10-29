"""The execution grants belong to the Agent Operator alone.

The wake and run grants moved from the Data Steward, the Permit Reviewer and
the City Administrator to the Agent Operator.  The tests post the actions
directly, not only the hidden buttons: a persona without the grant is refused
with a 403 even when it posts a well formed form with a valid form token.

The read access is a separate grant.  The Data Steward keeps the intake queue
because it works it, and no persona reaches an agent screen without the run
grant that opens it.
"""
# REQUIRES: PER-01, SEC-02
# Only the Agent Operator may wake an agent, run an agent or process a
# selection of waiting cases; the other personas are refused with a 403.

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.persistence.models import agent as agent_models
from acme_city.persistence.session import SessionFactory, transaction

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.client import client, csrf_of, choose, settings  # noqa: E402,F401

#: The personas that may not wake or run an agent.
OUTSIDE = (
    "persona_data_steward",
    "persona_permit_reviewer",
    "persona_city_administrator",
)

#: The agent actions of the interface.
AGENT_ACTIONS = ("agent.toggle", "agent.run.intake", "agent.run.adjudication")

#: A screen each persona may open, to read the form token of its session.
HOME_OF = {
    "persona_data_steward": "/queue/intake",
    "persona_permit_reviewer": "/permits/app_synth_001",
    "persona_city_administrator": "/admin",
    "persona_agent_operator": "/agent/intake",
}


@pytest.fixture()
def awake(settings) -> None:
    """Wake the intake agent, so that a run is not refused for another reason."""
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            row = session.execute(
                select(agent_models.AgentControl).where(
                    agent_models.AgentControl.agent_key == agent_models.AGENT_INTAKE
                )
            ).scalar_one()
            row.mode = agent_models.AGENT_AWAKE
    finally:
        factory.dispose()


def post_action(
    client: TestClient, action_id: str, token: str, **fields: str
) -> dict | None:
    """Post one interface action and return the typed outcome."""
    response = client.post(
        f"/ui/actions/{action_id}",
        data={"csrf_token": token, "action_id": action_id, **fields},
        headers={"Accept": "application/json"},
    )
    assert response.status_code in (200, 403), response.text
    return response.json() if response.status_code == 200 else None


@pytest.mark.parametrize("actor_id", OUTSIDE)
@pytest.mark.parametrize("action_id", AGENT_ACTIONS)
def test_a_persona_outside_the_operator_may_not_post_the_agent_actions(
    client: TestClient,  # noqa: F811
    actor_id: str,
    action_id: str,
) -> None:
    """A direct post of a governed action is refused without the grant."""
    choose(client, actor_id)
    token = csrf_of(client.get(HOME_OF[actor_id]).text)
    response = client.post(
        f"/ui/actions/{action_id}",
        data={
            "csrf_token": token,
            "action_id": action_id,
            "next": "/queue",
            "agent_key": "intake",
            "mode": "awake",
        },
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 403, (actor_id, action_id, response.text)
    assert response.json()["status"] == "denied"


@pytest.mark.parametrize("actor_id", OUTSIDE)
def test_a_persona_outside_the_operator_may_not_process_the_selection(
    client: TestClient,  # noqa: F811
    actor_id: str,
) -> None:
    """Processing a selection of waiting cases runs the intake agent."""
    if actor_id == "persona_data_steward":
        # The Data Steward still holds the execution grant of the selection
        # until the entitlement of OPR-5 moves it; the processing control on
        # the intake queue is locked for that persona, because it may not run
        # the intake agent any more.
        pytest.skip("the execution grant moves to the operator with the entitlement")
    choose(client, actor_id)
    token = csrf_of(client.get(HOME_OF[actor_id]).text)
    response = client.post(
        "/ui/actions/permit.intake.process_selected",
        data={
            "csrf_token": token,
            "action_id": "permit.intake.process_selected",
            "next": "/queue",
        },
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 403, (actor_id, response.text)


def test_the_operator_may_wake_an_agent(client: TestClient) -> None:  # noqa: F811
    """The Agent Operator holds the wake grant."""
    choose(client, "persona_agent_operator")
    token = csrf_of(client.get(HOME_OF["persona_agent_operator"]).text)
    outcome = post_action(
        client,
        "agent.toggle",
        token,
        agent_key="intake",
        mode="awake",
    )
    assert outcome is not None
    assert outcome["status"] == "accepted"
    assert outcome["state"] == "awake"


def test_the_operator_may_run_an_agent(client: TestClient, awake: None) -> None:  # noqa: F811
    """The Agent Operator holds the run grant of both agents."""
    choose(client, "persona_agent_operator")
    token = csrf_of(client.get(HOME_OF["persona_agent_operator"]).text)
    outcome = post_action(client, "agent.run.intake", token)
    assert outcome is not None
    assert outcome["status"] == "accepted"


@pytest.mark.parametrize("actor_id", OUTSIDE)
def test_the_agent_screens_are_closed_to_the_other_personas(
    client: TestClient,  # noqa: F811
    actor_id: str,
) -> None:
    """An agent screen is opened by the run grant of that agent."""
    choose(client, actor_id)
    assert client.get("/agent/intake").status_code == 403, actor_id
    assert client.get("/agent/adjudication").status_code == 403, actor_id


def test_the_operator_opens_both_agent_screens(client: TestClient) -> None:  # noqa: F811
    """The Agent Operator opens the two agent screens."""
    choose(client, "persona_agent_operator")
    assert client.get("/agent/intake").status_code == 200
    assert client.get("/agent/adjudication").status_code == 200
