"""Agent recommendation tags on the work queue and the review queue.

The tags are read from the recommendation, the intake findings and the parcel
link. The seeded cases stay as they were. These cases exist only here.
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.config import Settings
from acme_city.core.ids import new_id
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.permits.router import router as permit_router
from acme_city.permits.schemas import SubmitApplicationCommand
from acme_city.permits.service import PermitService
from acme_city.persistence.models import gis, permit
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.queue_tags import plain_reason, tags_for
from acme_city.ui.router import router as ui_router

REVIEWER = "persona_permit_reviewer"
STEWARD = "persona_data_steward"
DENY = "SYN-APP-801"
APPROVE = "SYN-APP-802"
EARLY = "SYN-APP-803"
DENY_REASON = "Rule(s) DF-1 fail, so the agent recommends denial."
APPROVE_REASON = "Every applicable rule passes, so the agent recommends approval."
EARLY_REASON = "Route to early resolution: 1 blocking finding(s) must be cleared first."
DUPLICATE_REASON = "This case may repeat SYN-APP-001."
PARCEL_REASON = (
    "the parcel link proposed by the address locator has not been approved "
    "by the Data Steward"
)
OLDER = datetime(2026, 10, 1, tzinfo=UTC)
NEWER = datetime(2026, 10, 2, tzinfo=UTC)


def _context(session, actor_id: str) -> ActorContext:
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


def _submit(permits: PermitService, session, actor: ActorContext, number: str, name: str):
    view = permits.submit(
        SubmitApplicationCommand(
            permit_type_key="com_ti",
            source_application_number=number,
            facts={
                "project_description": "A fictional fence",
                "applicant_name": name,
                "submitted_site_text": f"1 {name} Lane, ACME City",
            },
        ),
        actor,
    )
    row = session.get(permit.Application, view.application_id)
    assert row is not None
    return row


def _recommend(session, application, outcome: str, rationale: str, status: str, when):
    session.add(
        permit.Recommendation(
            id=new_id("rec"),
            application_id=application.id,
            proposed_outcome=outcome,
            status=status,
            rationale=rationale,
            created_at=when,
        )
    )


def _seed(settings: Settings) -> None:
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            actor = _context(session, STEWARD)
            permits = PermitService(session)
            denied = _submit(permits, session, actor, DENY, "Deny Builder")
            denied.status = "ready_for_review"
            _recommend(
                session,
                denied,
                "deny",
                f"{DENY_REASON} DF-1: the fence is too tall.",
                "pending",
                OLDER,
            )
            session.add(
                permit.ApplicationFinding(
                    id=new_id("finding"),
                    correlation_id=denied.correlation_id,
                    application_id=denied.id,
                    finding_type="duplicate",
                    message=DUPLICATE_REASON,
                    severity="review",
                    state="current",
                    revision_number=denied.revision,
                    version=1,
                )
            )
            approved = _submit(permits, session, actor, APPROVE, "Approve Builder")
            approved.status = "ready_for_review"
            _recommend(session, approved, "approve", APPROVE_REASON, "pending", OLDER)
            _recommend(session, approved, "deny", DENY_REASON, "superseded", NEWER)
            session.add(
                gis.ApplicationParcelMatch(
                    id=new_id("pmatch"),
                    application_id=approved.id,
                    correlation_id=approved.correlation_id,
                    submitted_text="1 Approve Builder Lane, ACME City",
                    link_state="proposed",
                    confirmed_at=None,
                )
            )
            early = _submit(permits, session, actor, EARLY, "Early Builder")
            early.status = "needs_information"
            session.add(
                permit.ApplicationFinding(
                    id=new_id("finding"),
                    correlation_id=early.correlation_id,
                    application_id=early.id,
                    finding_type="missing_document",
                    message="The site plan is missing.",
                    severity="block",
                    state="current",
                    revision_number=early.revision,
                    version=1,
                )
            )
    finally:
        factory.dispose()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    directory = tmp_path_factory.mktemp("queue-tags")
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{directory / 'queue-tags.db'}",
            "ACME_SECRET_KEY": "queue-tags-test-secret-value",
        },
        key_file=directory / "missing.env",
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
    _seed(settings)
    app = create_app(settings)
    app.include_router(ui_router)
    app.include_router(permit_router)
    with TestClient(app) as test_client:
        assert test_client.post(
            "/api/session/select", json={"actor_id": REVIEWER}
        ).status_code == 200
        yield test_client


def _row(page: str, reference: str) -> str:
    rows = re.findall(r'<tr class="row" data-testid="queue-item".*?</tr>', page, re.S)
    return next(row for row in rows if f">{reference}<" in row)


def _title(row: str, label: str) -> str:
    match = re.search(
        rf'data-testid="queue-tag" data-tag="[^"]*" title="([^"]*)">{re.escape(label)}',
        row,
    )
    assert match is not None, row
    return html.unescape(match.group(1))


def test_plain_reason_is_the_only_sentence_lookup() -> None:
    assert plain_reason("", "  ", "First sentence. Second sentence.") == "First sentence."
    held = permit.Recommendation(
        id="rec_held",
        application_id="app_held",
        proposed_outcome="hold",
        status="pending",
        rationale="No published rule applies, so the agent holds it for a person. Extra.",
    )
    tags = tags_for(
        status="ready_for_review",
        recommendation=held,
        findings=[],
        parcel_match=None,
    )
    assert [tag["label"] for tag in tags] == ["Agent: verify"]
    assert tags[0]["title"] == "No published rule applies, so the agent holds it for a person."
    conditioned = permit.Recommendation(
        id="rec_cond",
        application_id="app_cond",
        proposed_outcome="approve_with_conditions",
        status="pending",
        rationale=(
            "2 condition(s) of approval apply, so the agent "
            "recommends approval with conditions."
        ),
    )
    assert tags_for(
        status="submitted",
        recommendation=conditioned,
        findings=[],
        parcel_match=None,
    )[0]["label"] == "Agent: approve"


def test_tags_render_for_deny_approve_and_early_resolution(client: TestClient) -> None:
    page = client.get("/queue?view=all").text
    denied = _row(page, DENY)
    approved = _row(page, APPROVE)
    early = _row(page, EARLY)
    assert "Agent: deny" in denied
    assert "Intake: duplicate?" in denied
    assert _title(denied, "Agent: deny") == DENY_REASON
    assert _title(denied, "Intake: duplicate?") == DUPLICATE_REASON
    assert "Agent: approve" in approved
    assert "Cannot recommend: parcel not confirmed" in approved
    assert "Agent: deny" not in approved
    assert _title(approved, "Agent: approve") == APPROVE_REASON
    assert _title(approved, "Cannot recommend: parcel not confirmed") == PARCEL_REASON
    assert "Intake: early resolution" in early
    assert _title(early, "Intake: early resolution") == EARLY_REASON

    review = client.get("/queue/review").text
    assert "Agent: deny" in review
    assert "Agent: approve" in review
    assert "Intake: early resolution" not in review
    assert DENY_REASON in review
    assert APPROVE_REASON in review


def test_a_tag_chip_filters_and_combines_with_search(client: TestClient) -> None:
    denied = client.get("/queue?view=all&tag=agent_deny").text
    assert DENY in denied
    assert APPROVE not in denied
    assert EARLY not in denied
    assert 'data-tag="agent_deny" aria-selected="true"' in denied
    early = client.get("/queue?view=all&tag=intake_early").text
    assert EARLY in early and DENY not in early and APPROVE not in early
    both = client.get("/queue?view=all&tag=agent_deny&q=801").text
    assert DENY in both and "1 match for 801" in both
    missed = client.get("/queue?view=all&tag=agent_deny&q=802").text
    assert "No match for 802." in missed
    assert DENY not in missed
    review = client.get("/queue/review?tag=agent_approve").text
    assert APPROVE in review
    assert DENY not in review
    assert "Cannot recommend: parcel not confirmed" in review
