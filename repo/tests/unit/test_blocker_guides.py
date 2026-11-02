"""Each decision blocker reads in plain words and links to the place it is fixed."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.permits.schemas import Blocker, SubmitApplicationCommand
from acme_city.permits.service import PermitService
from acme_city.persistence.models import gis, permit, registry, source
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.reviewer_views import blocker_guide, workspace_blocker_guides

DECIDED_AT = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
REVIEWER = "persona_permit_reviewer"
STEWARD = "persona_data_steward"
PLACE = "403 Lantern Row"


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'blockers.db'}",
            "ACME_SECRET_KEY": "blocker-guide-test-secret-value",
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
    return settings


def context_for(session, actor_id: str) -> ActorContext:
    resolver = PermissionResolver(session)
    grants = resolver.grants_for(actor_id)
    roles = frozenset(
        row[0]
        for row in session.execute(
            select(ActorRole.role_id).where(ActorRole.actor_id == actor_id)
        ).all()
    )
    return ActorContext(
        actor_id=actor_id,
        role_ids=roles,
        domain_scope=frozenset(grant.domain_id for grant in grants if grant.domain_id),
        record_scope=frozenset(
            record_id for grant in grants for record_id in grant.record_scope
        ),
    )


def test_each_blocker_kind_maps_to_a_fix_link(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            application = session.get(permit.Application, "app_synth_001")
            assert application is not None
            case_id = application.id
            snapshot = session.execute(select(source.SourceSnapshot).limit(1)).scalar_one()
            session.add(
                registry.MatchProposal(
                    id="proposal_blocker_guide",
                    correlation_id="corr_blocker_guide",
                    source_snapshot_id=snapshot.source_snapshot_id,
                    entity_id="party_cedarline",
                    candidate_ids=["party_cedarline"],
                    method="deterministic",
                )
            )
            credential = session.execute(select(registry.Credential).limit(1)).scalar_one()
            session.flush()

            def guide(code: str, **fields) -> dict[str, str]:
                return blocker_guide(
                    session,
                    application,
                    Blocker(code=code, detail=f"raw {code}", **fields),
                )

            parcel = guide("parcel_link_unapproved")
            assert parcel["owner"] == "Data Steward"
            assert parcel["href"] == (
                f"/steward/issues/parcel/{case_id}?from=/permits/{case_id}"
            )
            assert parcel["code"] not in parcel["text"]

            confirm = guide("parcel_unconfirmed")
            assert confirm["owner"] == "Permit Reviewer"
            assert confirm["href"] == "#property-heading"

            identity = guide(
                "identity_link_unapproved",
                subject_type="party",
                subject_id="party_cedarline",
            )
            assert identity["owner"] == "Data Steward"
            assert identity["href"] == (
                f"/steward/issues/link/proposal_blocker_guide?from=/permits/{case_id}"
            )
            assert "party_cedarline" not in identity["text"]

            license_row = guide(
                "credential_expired",
                subject_type="credential",
                subject_id=credential.credential_id,
            )
            assert license_row["owner"] == "City Administrator"
            assert license_row["href"] == (
                f"/detail/credential/{credential.credential_id}?from=/permits/{case_id}"
            )

            failed = guide("rule_fail", subject_type="rule", subject_id="DF-1")
            assert failed["owner"] == "Permit Reviewer"
            assert failed["href"] == "#application-checks"
            assert "Fence height, front yard" in failed["text"]

            review = guide("rule_review", subject_type="rule", subject_id="DF-1")
            assert review["href"] == "#application-checks"
            assert "needs a person" in review["text"]

            stale = guide("evaluation_stale")
            assert stale["owner"] == "Permit Reviewer"
            assert stale["href"] == "#application-checks"

            fee = guide("reconciliation_partial")
            assert fee["owner"] == "City Administrator"
            assert fee["scope"] == "issuance"
            assert fee["href"] == f"/reconciliation?from=/permits/{case_id}"
            assert "fee" in fee["text"].lower()

            missing_fee = guide("no_current_assessment")
            assert missing_fee["href"] == f"/reconciliation?from=/permits/{case_id}"
            assert missing_fee["scope"] == "issuance"
    finally:
        factory.dispose()


def _lantern_case(session) -> permit.Application:
    """Submit a case whose only blocker is an unapproved parcel match."""
    service = PermitService(session)
    steward = context_for(session, STEWARD)
    view = service.submit(
        SubmitApplicationCommand(
            permit_type_key="deck_fence",
            applicant_party_id="party_cedarline",
            facts={
                "parcel_number": "ACME-P-1001",
                "project_description": "Fence at 403 Lantern Row",
                "submitted_parcel": "ACME-P-1001",
                "submitted_site_text": "400 Lantern Row, Suite 2, ACME City",
                "height_ft": 6,
                "setback_ft": 2,
                "structure_kind": "fence",
                "location": "front",
                "valuation": "1200.00",
            },
        ),
        steward,
    )
    application = service.load_application(view.application_id)
    session.add(
        registry.Crosswalk(
            id=f"crosswalk_{application.id}",
            entity_id="party_cedarline",
            entity_type="party",
            source_system_id="permitting",
            source_dataset_key="applicant_profiles",
            source_record_id=f"PER-{application.id}",
            link_status="approved",
            decision="Approved by the data steward.",
            decision_actor_id=STEWARD,
            decided_at=DECIDED_AT,
        )
    )
    session.add(
        gis.ApplicationParcelMatch(
            id=f"pmatch_{application.id}",
            application_id=application.id,
            correlation_id=application.correlation_id,
            version=1,
            submitted_text=PLACE,
            matched_address="403 Lantern Row",
            address_id="address_400_lantern_unit_2",
            parcel_id="parcel_1001",
            parcel_number="ACME-P-1001",
            score=100.0,
            locator_status="M",
            method="locator",
            link_state="proposed",
            note="One candidate scored above the threshold.",
            proposed_by=STEWARD,
        )
    )
    session.flush()
    return application


def test_a_617_style_case_links_the_plain_blocker_to_the_steward_task(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            application = _lantern_case(session)
            application_id = application.id
            guides = workspace_blocker_guides(session, application)
    finally:
        factory.dispose()
    assert [item["code"] for item in guides] == ["parcel_link_unapproved"]
    assert guides[0]["text"] == (
        f"The property match for {PLACE} has not been approved by the Data Steward."
    )
    href = guides[0]["href"]
    assert href == f"/steward/issues/parcel/{application_id}?from=/permits/{application_id}"

    app = create_app(seeded)
    with TestClient(app) as client:
        chosen = client.post("/api/session/select", json={"actor_id": REVIEWER})
        assert chosen.status_code == 200, chosen.text
        page = client.get(f"/permits/{application_id}")
        assert page.status_code == 200, page.text
        panel = re.search(
            r'data-testid="next-action".*?data-testid="issuance-status"',
            page.text,
            re.S,
        )
        assert panel is not None
        body = panel.group(0)
        assert "Data follow-up" in body
        assert "1 blocker still prevents a decision." not in body
        assert guides[0]["text"] in body
        assert "Data Steward" in body
        assert f'href="{href}"' in body
        codes = re.search(r'data-testid="blocker-codes".*</details>', body, re.S)
        assert codes is not None
        assert "parcel_link_unapproved" in codes.group(0)
        visible = re.search(r'data-testid="blocker-text">(.*?)</span>', body, re.S)
        assert visible is not None
        assert "parcel_link_unapproved" not in html.unescape(visible.group(1))

        steward = client.post("/api/session/select", json={"actor_id": STEWARD})
        assert steward.status_code == 200, steward.text
        task = client.get(href)
        assert task.status_code == 200, task.text
        assert "Parcel" in task.text
        assert application_id in task.text or "403 Lantern Row" in task.text
