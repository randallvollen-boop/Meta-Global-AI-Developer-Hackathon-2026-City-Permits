"""The linking service identity and the grants of the steward automation.

The Data Steward authorizes the registry automation: it activates a policy,
pauses it, asks for a scan, reviews a link the service applied and reverses
one.  The linking service identity runs the work.  It is never offered a
session, it holds the run grant of the linking agent and the narrow registry
grants of its own work, and it holds neither the policy controls of the
steward nor a decision grant of a person.

The tests read the persisted grants, because the grants are the authority: a
role label, a client-supplied field or a screen never authorizes an action.
"""
# REQUIRES: SEC-01, SEC-02
# Only the Data Steward authorizes the registry automation, the linking service
# identity may not act as a person, and a service identity is never offered a
# session.

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from acme_city.auth.context import ActorContext, ResourceContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.fixtures.loader import FixtureBundle
from acme_city.persistence.models import governance
from acme_city.persistence.session import SessionFactory
from acme_city.ui import view_models

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.client import client, choose, settings  # noqa: E402,F401

#: The actor id of the linking service identity.
SERVICE = "service_linking_agent"

#: The Data Steward, the persona that authorizes the automation.
STEWARD = "persona_data_steward"

#: The personas that may not authorize the automation.
OUTSIDE = (
    "persona_applicant",
    "persona_permit_reviewer",
    "persona_city_administrator",
    "persona_agent_operator",
)

#: The grants the Data Steward holds to read and authorize the automation.
AUTOMATION_GRANTS = (
    "registry.automation.preview",
    "registry.automation.activate",
    "registry.automation.enqueue",
    "registry.automation.pause",
    "registry.automation.review",
    "registry.automation.undo",
)

#: The grants of the linking service identity: the run grant of the linking
#: agent and the narrow registry grants of its own work.
SERVICE_GRANTS = {
    "agent.run.linking",
    "records.document.view",
    "registry.crosswalk.propose",
    "registry.provenance.view",
}

#: The domains the automation may work in: the domains of its eligible
#: datasets.
REGISTRY_DOMAINS = {
    "applicants",
    "permits",
    "contractors",
    "businesses",
    "parcels",
    "addresses",
}

#: The grants that would let an actor act as a person rather than as a
#: service.
PERSON_GRANTS = (
    "agent.ops.read",
    "agent.run.adjudication",
    "agent.run.intake",
    "agent.toggle",
    "finance.account.link",
    "permit.decide",
    "permit.issue",
    "registry.crosswalk.decide",
    "registry.master.create",
)


@pytest.fixture()
def session(settings) -> Session:  # noqa: F811
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as open_session:
            yield open_session
    finally:
        factory.dispose()


def actor_for(session: Session, actor_id: str) -> ActorContext:
    """Return the actor of a persisted identity, as a session would resolve it."""
    grants = PermissionResolver(session).grants_for(actor_id)
    return ActorContext(
        actor_id=actor_id,
        role_ids=frozenset(),
        domain_scope=frozenset(grant.domain_id for grant in grants if grant.domain_id),
        record_scope=frozenset(record for grant in grants for record in grant.record_scope),
    )


# ------------------------------------------------- the service identity


def test_the_linking_service_identity_is_never_offered_a_session(
    client: TestClient,  # noqa: F811
    session: Session,
) -> None:
    """A service identity is not selectable, and the selector refuses it."""
    offered = {option["actor_id"] for option in view_models.persona_options(session)}
    assert SERVICE not in offered
    row = session.execute(
        select(governance.Actor).where(governance.Actor.actor_id == SERVICE)
    ).scalar_one()
    assert row.active is True
    assert row.selectable is False
    response = client.post("/api/session/select", json={"actor_id": SERVICE})
    assert response.status_code == 401, response.text


def test_the_selector_offers_exactly_the_five_personas(session: Session) -> None:
    """The service identity does not become a sixth persona."""
    offered = [option["actor_id"] for option in view_models.persona_options(session)]
    assert offered == [
        "persona_applicant",
        "persona_data_steward",
        "persona_permit_reviewer",
        "persona_city_administrator",
        "persona_agent_operator",
    ]


def test_the_service_identity_carries_the_grants_of_its_own_role() -> None:
    """The catalog describes the service with the same narrow grant set."""
    bundle = FixtureBundle.load()
    identity = next(
        item for item in bundle.actors.service_identities if item.actor_id == SERVICE
    )
    role = next(
        item for item in bundle.actors.roles if item.role_id == "linking_agent"
    )
    assert identity.selectable is False
    assert identity.role_ids == ["linking_agent"]
    assert {grant.permission_id for grant in identity.grants} == set(role.permission_ids)
    assert set(role.permission_ids) == SERVICE_GRANTS


def test_the_service_identity_holds_the_run_grant_and_nothing_more(
    session: Session,
) -> None:
    """The service runs the linking agent and reads the registry; it decides nothing."""
    resolver = PermissionResolver(session)
    assert set(resolver.permissions_for(SERVICE)) == SERVICE_GRANTS
    for permission in PERSON_GRANTS:
        assert permission not in resolver.permissions_for(SERVICE), permission


def test_the_service_identity_may_not_authorize_the_policy(session: Session) -> None:
    """The policy controls belong to the steward; the service never holds them."""
    resolver = PermissionResolver(session)
    service = actor_for(session, SERVICE)
    for permission in AUTOMATION_GRANTS:
        assert not resolver.allows(
            service, permission, ResourceContext(domain_id="applicants")
        ), permission
        assert not resolver.allows(
            service, permission, ResourceContext(domain_id="permits")
        ), permission


def test_the_service_identity_may_not_open_the_reserved_steward_screens(
    session: Session,
) -> None:
    """The service is not a steward: it opens neither reserved steward screen.

    The automation screen is closed because the service lacks its preview
    grant. The new master screen is closed because it lacks the creation
    grant. It never receives a session, so it reaches no interface screen.
    """
    service = actor_for(session, SERVICE)
    for key in ("steward_automation", "steward_new_master"):
        assert not view_models.may_open_screen(session, service, key), key


def test_the_service_identity_reaches_only_the_registry_domains(
    session: Session,
) -> None:
    """The service works in the domains of its datasets, nowhere else."""
    grants = PermissionResolver(session).grants_for(SERVICE)
    domains = {grant.domain_id for grant in grants if grant.domain_id}
    assert domains == REGISTRY_DOMAINS
    for outside in ("finance", "zoning", "building_rules", "records"):
        assert outside not in domains, outside


def test_the_service_identity_inherits_no_record_scope(session: Session) -> None:
    """The service never carries the record scope of a person."""
    grants = PermissionResolver(session).grants_for(SERVICE)
    assert all(not grant.record_scope for grant in grants)
    service = actor_for(session, SERVICE)
    assert not service.record_scope


def test_the_service_identity_may_not_reach_an_applicant_record(
    session: Session,
) -> None:
    """The record scope of the Applicant stays with the Applicant."""
    resolver = PermissionResolver(session)
    service = actor_for(session, SERVICE)
    for permission in ("applicant.profile.edit", "applicant.case.respond"):
        assert not resolver.allows(
            service,
            permission,
            ResourceContext(
                domain_id="applicants", record_ids=("party_applicant_1",)
            ),
        ), permission


def test_the_service_identity_never_inherits_the_operator_bundle(
    session: Session,
) -> None:
    """The linking service is not an agent operator, whatever its role says."""
    resolver = PermissionResolver(session)
    assert "agent.ops.read" not in resolver.permissions_for(SERVICE)
    assert "agent.run.intake" not in resolver.permissions_for(SERVICE)
    assert "agent.toggle" not in resolver.permissions_for(SERVICE)


# ------------------------------------------------- the steward's grants


def test_the_data_steward_holds_the_automation_grants(session: Session) -> None:
    """The steward authorizes the automation in the domains of its datasets."""
    resolver = PermissionResolver(session)
    held = resolver.permissions_for(STEWARD)
    for permission in AUTOMATION_GRANTS:
        assert permission in held, permission
    steward = actor_for(session, STEWARD)
    for permission in AUTOMATION_GRANTS:
        assert resolver.allows(
            steward, permission, ResourceContext(domain_id="applicants")
        ), permission
        assert resolver.allows(
            steward, permission, ResourceContext(domain_id="parcels")
        ), permission


@pytest.mark.parametrize("actor_id", OUTSIDE)
def test_no_other_persona_may_authorize_the_automation(
    session: Session, actor_id: str
) -> None:
    """The policy controls belong to the Data Steward alone."""
    resolver = PermissionResolver(session)
    actor = actor_for(session, actor_id)
    for permission in AUTOMATION_GRANTS:
        assert not resolver.allows(
            actor, permission, ResourceContext(domain_id="applicants")
        ), (actor_id, permission)


def test_a_forged_role_does_not_authorize_the_automation(session: Session) -> None:
    """Persisted grants, rather than a role string, authorize an action."""
    resolver = PermissionResolver(session)
    forged = ActorContext(
        actor_id="persona_permit_reviewer",
        role_ids=frozenset({"domain_steward", "linking_agent"}),
        domain_scope=frozenset(REGISTRY_DOMAINS),
        record_scope=frozenset(),
    )
    assert not resolver.allows(
        forged, "registry.automation.activate", ResourceContext(domain_id="applicants")
    )
    steward_without_roles = ActorContext(
        actor_id=STEWARD,
        role_ids=frozenset(),
        domain_scope=frozenset(),
        record_scope=frozenset(),
    )
    assert resolver.allows(
        steward_without_roles,
        "registry.automation.activate",
        ResourceContext(domain_id="applicants"),
    )


def test_a_forged_actor_field_does_not_open_the_automation(
    client: TestClient,  # noqa: F811
) -> None:
    """A request body never names the actor; the session does."""
    choose(client, "persona_permit_reviewer")
    response = client.post(
        "/api/session/select",
        json={"actor_id": SERVICE, "role": "linking_agent"},
    )
    assert response.status_code == 401, response.text
    # The session of the reviewer is unchanged.
    offered = client.get("/api/session/actors").json()["actors"]
    assert [actor["actor_id"] for actor in offered] == [
        "persona_agent_operator",
        "persona_applicant",
        "persona_city_administrator",
        "persona_data_steward",
        "persona_permit_reviewer",
    ]
