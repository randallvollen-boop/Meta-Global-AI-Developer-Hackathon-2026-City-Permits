"""The Agent Operator is the fifth selectable persona.

W0-3 adds ``persona_agent_operator`` with the agent operations bundle.  OPR-16
makes its home the agent operations screen.  The four original personas keep
their grants: they equal ``persona_grants_snapshot.json`` with the changes
in ``persona_grant_deltas.json`` applied, and only OPR-3 and STW-18 add to
that whitelist.
"""
# REQUIRES: PER-01, SEC-02
# Exactly five personas are selectable, a service identity never is, and a
# new persona changes the grants of no other persona.

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.agents.bundle import AGENT_OPERATIONS
from acme_city.agents.control import AGENT_KEYS, PERMISSION_RUN
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.fixtures.loader import FixtureBundle
from acme_city.persistence.models import governance
from acme_city.persistence.session import SessionFactory
from acme_city.ui import view_models

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.client import client, settings  # noqa: E402,F401

DATA = Path(__file__).resolve().parents[1] / "regression" / "data"
SNAPSHOT = DATA / "persona_grants_snapshot.json"
DELTAS = DATA / "persona_grant_deltas.json"

OPERATOR = "persona_agent_operator"

#: The five selectable personas, in fixture order.
PERSONAS: tuple[tuple[str, str], ...] = (
    ("persona_applicant", "Applicant"),
    ("persona_data_steward", "Data Steward"),
    ("persona_permit_reviewer", "Permit Reviewer"),
    ("persona_city_administrator", "City Administrator"),
    (OPERATOR, "Agent Operator"),
)


@pytest.fixture(scope="module")
def bundle() -> FixtureBundle:
    return FixtureBundle.load()


@pytest.fixture()
def session(settings) -> Session:  # noqa: F811
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as open_session:
            yield open_session
    finally:
        factory.dispose()


def actor_for(session: Session, actor_id: str) -> ActorContext:
    grants = PermissionResolver(session).grants_for(actor_id)
    return ActorContext(
        actor_id=actor_id,
        role_ids=frozenset(),
        domain_scope=frozenset(grant.domain_id for grant in grants if grant.domain_id),
        record_scope=frozenset(record for grant in grants for record in grant.record_scope),
    )


def _grant_key(grant: dict[str, Any]) -> str:
    return grant["permission_id"]


def _expected_original_grants() -> dict[str, dict[str, dict[str, Any]]]:
    """The snapshot of the four original personas with the deltas applied."""
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))["personas"]
    expected = {
        actor_id: {_grant_key(grant): grant for grant in grants}
        for actor_id, grants in snapshot.items()
    }
    for delta in json.loads(DELTAS.read_text(encoding="utf-8"))["deltas"]:
        grants = expected[delta["actor_id"]]
        if delta["change"] == "remove":
            assert delta["permission_id"] in grants, delta
            grants.pop(delta["permission_id"])
        elif delta["change"] == "add":
            assert delta["permission_id"] not in grants, delta
            grants[delta["permission_id"]] = {
                "permission_id": delta["permission_id"],
                "domains": list(delta.get("domains", [])),
                "record_scope": list(delta.get("record_scope", [])),
                "source": delta.get("source", "explicit"),
            }
        else:
            raise AssertionError(f"unknown delta change: {delta!r}")
    return expected


# ---------------------------------------------------------------- fixtures


def test_exactly_five_personas_are_selectable(bundle: FixtureBundle, session: Session) -> None:
    assert [(p.actor_id, p.label) for p in bundle.actors.personas] == list(PERSONAS)
    assert all(persona.selectable for persona in bundle.actors.personas)
    seeded = session.execute(
        select(governance.Actor.actor_id).where(governance.Actor.selectable.is_(True))
    ).scalars().all()
    assert sorted(seeded) == sorted(actor_id for actor_id, _ in PERSONAS)
    # The selector order follows the story and is pinned in test_view_models.
    assert sorted(label for _, label in PERSONAS) == sorted(view_models.PERSONA_ORDER)


def test_the_service_identities_stay_unselectable(bundle: FixtureBundle, session: Session) -> None:
    identities = {identity.actor_id for identity in bundle.actors.service_identities}
    assert identities
    assert not any(identity.selectable for identity in bundle.actors.service_identities)
    rows = session.execute(
        select(governance.Actor).where(governance.Actor.actor_id.in_(identities))
    ).scalars().all()
    assert len(rows) == len(identities)
    assert not any(row.selectable for row in rows)
    offered = {option["actor_id"] for option in view_models.persona_options(session)}
    assert not offered & identities


def test_the_original_four_keep_their_grants(bundle: FixtureBundle) -> None:
    expected = _expected_original_grants()
    actual = {
        persona.actor_id: {
            grant.permission_id: {
                "permission_id": grant.permission_id,
                "domains": list(grant.domains),
                "record_scope": list(grant.record_scope),
                "source": grant.source,
            }
            for grant in persona.grants
        }
        for persona in bundle.actors.personas
        if persona.actor_id in expected
    }
    assert set(actual) == set(expected) == {actor_id for actor_id, _ in PERSONAS[:4]}
    assert actual == expected


def test_the_operator_holds_exactly_the_agent_operations_bundle(bundle: FixtureBundle) -> None:
    operator = next(p for p in bundle.actors.personas if p.actor_id == OPERATOR)
    assert sorted(grant.permission_id for grant in operator.grants) == sorted(AGENT_OPERATIONS)
    assert "agent.ops.read" in AGENT_OPERATIONS
    role = next(role for role in bundle.actors.roles if role.role_id == "agent_operator")
    assert operator.source_role_ids == ["agent_operator"]
    assert sorted(role.permission_ids) == sorted(AGENT_OPERATIONS)
    # The operator decides, issues and configures nothing.
    for forbidden in ("permit.decide", "permit.issue", "config.manage", "admin.actor.manage"):
        assert forbidden not in AGENT_OPERATIONS


def test_the_linking_key_is_a_contract_only() -> None:
    assert PERMISSION_RUN["linking"] == "agent.run.linking"
    assert "linking" not in AGENT_KEYS


# -------------------------------------------------------------------- homes


def test_each_persona_has_a_home_that_opens(client: TestClient, session: Session) -> None:  # noqa: F811
    for actor_id, label in PERSONAS:
        home = view_models.home_for(session, actor_for(session, actor_id))
        assert home["href"], actor_id
        assert client.post("/api/session/select", json={"actor_id": actor_id}).status_code == 200
        response = client.get(home["href"])
        assert response.status_code == 200, (actor_id, home["href"])
    operator_home = view_models.home_for(session, actor_for(session, OPERATOR))
    assert operator_home == {"label": "Agents", "href": "/agents", "key": "agents_home"}


def test_switching_to_the_operator_redirects_to_its_home(client: TestClient) -> None:  # noqa: F811
    response = client.post(
        "/ui/actor",
        data={"actor_id": OPERATOR, "next": "/queue"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    # The operator may not open the work queue, so it lands on its own home.
    assert response.headers["location"] == "/agents?moved_from=queue"


def test_the_select_screen_shows_five_cards_with_the_operator_icon(
    client: TestClient,  # noqa: F811
) -> None:
    body = client.get("/select").text
    cards = re.findall(r'data-testid="persona-card"', body)
    assert len(cards) == 5
    assert body.count("data-persona=") == 5
    assert 'src="/ui/static/persona-icons/operator.png"' in body
    assert client.get("/ui/static/persona-icons/operator.png").status_code == 200
