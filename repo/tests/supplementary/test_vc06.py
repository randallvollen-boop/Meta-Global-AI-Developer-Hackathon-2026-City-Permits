"""VC06: fictional assets, server-side secrets and an append-only trail.

Every record of the demonstration is fictional, the provider credential never
leaves the server, and the application audit trail only grows: it has no
update and no delete path, and it makes no compliance claim it cannot
support.
"""
# REQUIRES: VC06, SEC-04
# The demonstration records are fictional, the provider credential stays on the server, and the
# application audit trail is append-only and claims no compliance it cannot support.

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import audit, registry
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction

#: The credential the demonstration never records and never returns.
PROVIDER_KEY = "provider-key-that-must-never-be-recorded"

#: The claims no fictional demonstration may make about itself.
COMPLIANCE_WORDS = (
    "soc 2",
    "soc2",
    "hipaa",
    "gdpr",
    "iso 27001",
    "iso27001",
    "pci dss",
    "fedramp",
    "certified",
    "compliant",
)


@pytest.fixture()
def environment(tmp_path: Path) -> tuple[TestClient, Settings]:
    """Return a client and the settings of a freshly reset demonstration."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'vc06.db'}",
            "ACME_SECRET_KEY": "vc06-records-protection-secret-value",
            "META_API_KEY": PROVIDER_KEY,
        },
        key_file=tmp_path / "missing.env",
    )
    initialize_database(settings)
    bundle = FixtureBundle.load()
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            session.add(
                DemoEnvironment(
                    id="demo_environment_local",
                    environment_id=ENVIRONMENT_ID,
                    fictional_demo=True,
                    fixture_version=bundle.fixture_version,
                    label="local fictional demonstration",
                )
            )
        with transaction(factory) as session:
            reset_demo(session, bundle, confirmation="--confirm-fictional-demo")
    finally:
        factory.dispose()
    with TestClient(create_app(settings)) as test_client:
        yield test_client, settings


def test_vc06_every_contact_of_the_demonstration_is_fictional(
    environment: tuple[TestClient, Settings],
) -> None:
    _client, settings = environment
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            contacts = session.execute(select(registry.PartyContact)).scalars().all()
            assert contacts, "the demonstration holds no contact"
            for contact in contacts:
                value = str(contact.value)
                if contact.contact_type == "email":
                    assert "@" in value, f"{contact.id} is not an address"
                    domain = value.rsplit("@", 1)[1]
                    assert domain.endswith(".invalid"), f"{contact.id} is not a fictional address"
                elif contact.contact_type == "phone":
                    assert "555" in value, f"{contact.id} is not a fictional number"
                else:
                    raise AssertionError(f"{contact.id} holds an unknown contact type")
            parties = session.execute(select(registry.Party)).scalars().all()
            for party in parties:
                assert party.entity_id.startswith("party_")
            environment_row = session.get(DemoEnvironment, "demo_environment_local")
            assert environment_row is not None
            assert environment_row.fictional_demo is True
    finally:
        factory.dispose()


def test_vc06_the_provider_credential_stays_on_the_server(
    environment: tuple[TestClient, Settings],
) -> None:
    client, settings = environment
    summary = settings.safe_summary()
    assert summary["meta_api_key_present"] is True
    assert PROVIDER_KEY not in str(summary)

    dumped = settings.model_dump(mode="json")
    assert PROVIDER_KEY not in str(dumped)
    assert dumped["meta_api_key"] == "**********"

    actors = client.get("/api/session/actors")
    assert actors.status_code == 200
    assert PROVIDER_KEY not in actors.text
    health = client.get("/healthz")
    assert health.status_code == 200
    assert PROVIDER_KEY not in health.text
    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    assert PROVIDER_KEY not in schema.text
    assert "META_API_KEY" not in schema.text


def test_vc06_the_audit_trail_only_grows(environment: tuple[TestClient, Settings]) -> None:
    _client, settings = environment
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            service = AuditService(session)
            actor = ActorContext(
                actor_id="persona_data_steward", role_ids=frozenset({"domain_steward"})
            )
            first = service.append(
                action="change.case.request",
                actor=actor,
                target_type="change_case",
                target_id="case_fictional_1",
                reason="a fictional demonstration action",
            )
            second = service.append(
                action="change.case.request",
                actor=actor,
                target_type="change_case",
                target_id="case_fictional_1",
                reason="a fictional demonstration action",
            )
            session.flush()
            assert first.id != second.id
            rows = session.execute(select(audit.AuditEvent)).scalars().all()
            identifiers = {row.id for row in rows}
            assert {first.id, second.id} <= identifiers
            assert all(row.outcome in {"accepted", "denied"} for row in rows)

            # The service exposes no way to change or remove an event.
            assert not hasattr(service, "update")
            assert not hasattr(service, "delete")
            assert not hasattr(service, "remove")
    finally:
        factory.dispose()


def test_vc06_a_denied_action_is_recorded_without_a_private_value(
    environment: tuple[TestClient, Settings],
) -> None:
    client, settings = environment
    client.post("/api/session/select", json={"actor_id": "persona_applicant"})
    refused = client.post(
        "/api/permits/applications/app_synth_001/revisions",
        json={
            "application_id": "app_synth_001",
            "facts": {"contact_email": "private@example.invalid"},
            "reason": "a fictional attempt",
        },
    )
    assert refused.status_code == 403, refused.text

    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            denials = session.execute(
                select(audit.AuditEvent).where(audit.AuditEvent.outcome == "denied")
            ).scalars().all()
            assert denials, "the refusal was not recorded"
            for denial in denials:
                assert denial.actor_id == "persona_applicant"
                assert denial.denial_reason
                assert "private@example.invalid" not in str(denial.reason or "")
                assert "private@example.invalid" not in str(denial.metadata_json or "")
    finally:
        factory.dispose()


def test_vc06_the_application_claims_no_compliance_it_cannot_support() -> None:
    root = Path(__file__).resolve().parents[2]
    searched = 0
    for folder in ("src/acme_city", "config", "fixtures"):
        for path in sorted((root / folder).rglob("*")):
            if not path.is_file() or path.suffix not in {".py", ".json", ".txt", ".html"}:
                continue
            searched += 1
            text = path.read_text(encoding="utf-8").lower()
            for word in COMPLIANCE_WORDS:
                assert word not in text, f"{path.name} claims {word!r}"
    assert searched > 0


def test_vc06_the_application_holds_no_real_looking_identifier() -> None:
    """Every identifier of the demonstration carries a fictional marker."""
    root = Path(__file__).resolve().parents[2]
    pattern = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
    for folder in ("config", "fixtures"):
        for path in sorted((root / folder).rglob("*.json")):
            assert not pattern.search(path.read_text(encoding="utf-8")), (
                f"{path.name} holds an identifier that looks like a real one"
            )
