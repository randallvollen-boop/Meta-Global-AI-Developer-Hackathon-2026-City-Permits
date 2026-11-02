"""A needs-information case opens with the request already written.

The decision form selects Needs information and fills the request from the
open findings the applicant must fix.  The reviewer can edit that text.
A case without those findings still opens on Approve.
"""

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
from acme_city.kernel.intake import duplicate_finding
from acme_city.persistence.models import permit
from acme_city.persistence.models.governance import ActorRole, DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.permits.schemas import SubmitApplicationCommand
from acme_city.permits.service import PermitService
from acme_city.ui.reviewer_views import information_request_preset, information_request_text

REVIEWER = "persona_permit_reviewer"
STEWARD = "persona_data_steward"
SITE_PLAN = "Please upload the site plan (ACME Code §13-502)."
DUPLICATE = (
    "This looks like a second application for the same project as SYN-APP-616. "
    "Please confirm whether it replaces that one."
)
REQUEST = f"{SITE_PLAN}\n\n{DUPLICATE}"
EDITED = "Please upload a signed site plan."
FACTS = {
    "parcel_number": "ACME-P-1001",
    "project_description": "6 ft rear-yard fence",
    "valuation": "1200.00",
    "height_ft": 6,
    "setback_ft": 2,
    "structure_kind": "fence",
    "location": "side_rear",
    "submitted_parcel": "ACME-P-1001",
    "submitted_site_text": "400 Lantern Row, Suite 2, ACME City",
}


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return settings for a freshly reset fictional demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'information.db'}",
            "ACME_SECRET_KEY": "information-request-test-secret-value",
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
    """Return the server-resolved context of a seeded persona."""
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


def _attrs(tag: str) -> dict[str, str]:
    return {name: html.unescape(value) for name, value in re.findall(r'([\w:-]+)="([^"]*)"', tag)}


def form_values(block: str) -> dict[str, str]:
    """Return the fields a browser would post from the first form in ``block``."""
    form = re.search(r"<form\b.*?</form>", block, re.S)
    assert form, block[:120]
    body = form.group(0)
    values: dict[str, str] = {}
    for tag in re.findall(r"<input\b[^>]*>", body):
        attrs = _attrs(tag)
        if "name" in attrs:
            values[attrs["name"]] = attrs.get("value", "")
    for tag, text in re.findall(r"(<textarea\b[^>]*>)(.*?)</textarea>", body, re.S):
        attrs = _attrs(tag)
        if "name" in attrs:
            values[attrs["name"]] = html.unescape(text)
    return values


def details_block(page: str, attr: str, value: str) -> str:
    """Return one details element, including nested details."""
    match = re.search(rf'<details\b[^>]*{attr}="{re.escape(value)}"[^>]*>', page)
    assert match, f"no details {attr}={value}"
    start = match.start()
    depth = 0
    for token in re.finditer(r"</?details\b[^>]*>", page[start:]):
        depth += -1 if token.group(0).startswith("</") else 1
        if depth == 0:
            return page[start : start + token.end()]
    raise AssertionError(f"unclosed details {attr}={value}")


def selected_outcome(form: str) -> str:
    """Return the outcome the decision form has selected."""
    select = re.search(
        r'<select\b[^>]*data-testid="decision-outcome".*?</select>', form, re.S
    )
    assert select, form[:200]
    chosen = ""
    for tag in re.findall(r"<option\b[^>]*>", select.group(0)):
        if re.search(r"(?:^|\s)selected(?:[\s>]|$)", tag):
            chosen = _attrs(tag).get("value", "")
    return chosen


def add_findings(session, application: permit.Application) -> None:
    """Record the site-plan gap and the duplicate the applicant must answer."""
    duplicate = duplicate_finding("SYN-APP-616", "app_other")
    session.add(
        permit.ApplicationFinding(
            id=f"finding_site_{application.id}",
            correlation_id=application.correlation_id,
            application_id=application.id,
            finding_type="missing_document",
            message="The application does not include the site plan.",
            rule="ACME Code §13-502 (deck_fence required documents)",
            applicant_must="Provide the site plan.",
            severity="block",
            state="current",
            revision_number=application.revision,
            created_at=datetime(2026, 10, 1, tzinfo=UTC),
            version=1,
        )
    )
    session.add(
        permit.ApplicationFinding(
            id=f"finding_dup_{application.id}",
            correlation_id=application.correlation_id,
            application_id=application.id,
            finding_type=duplicate.finding_type,
            message=duplicate.message,
            rule=duplicate.rule,
            applicant_must=duplicate.applicant_must,
            severity=duplicate.severity,
            related_application_id=duplicate.related_application_id,
            state="current",
            revision_number=application.revision,
            created_at=datetime(2026, 10, 2, tzinfo=UTC),
            version=1,
        )
    )
    session.flush()


def prepare(session, *, findings: bool) -> str:
    """Submit a fence, optionally record the findings, and run the checks."""
    service = PermitService(session)
    view = service.submit(
        SubmitApplicationCommand(
            permit_type_key="deck_fence",
            facts=dict(FACTS),
            applicant_party_id="party_cedarline",
        ),
        context_for(session, STEWARD),
    )
    application = service.load_application(view.application_id)
    if findings:
        add_findings(session, application)
    service.evaluate(application.id, context_for(session, REVIEWER))
    return application.id


def decision_form(client: TestClient, application_id: str) -> str:
    """Return the decision form of one case."""
    page = client.get(f"/permits/{application_id}")
    assert page.status_code == 200, page.text
    return details_block(page.text, "data-testid", "decision-form")


def test_the_sentences_name_the_site_plan_and_the_other_case() -> None:
    findings = [
        {
            "state": "current",
            "waived": False,
            "finding_type": "missing_document",
            "message": "The application does not include the site plan.",
            "rule": "ACME Code §13-502 (deck_fence required documents)",
            "applicant_must": "Provide the site plan.",
        },
        {
            "state": "current",
            "waived": False,
            "finding_type": "duplicate",
            "message": duplicate_finding("SYN-APP-616", "app_other").message,
            "rule": "ACME Code §13-401",
            "applicant_must": duplicate_finding("SYN-APP-616", "app_other").applicant_must,
        },
        {
            "state": "current",
            "waived": False,
            "finding_type": "judgment",
            "message": "A person at the City reviews these known issues.",
            "rule": "ACME Code §13-401",
            "applicant_must": "A person at the City reviews these known issues.",
        },
    ]
    assert information_request_text(findings) == REQUEST
    assert information_request_preset("needs_information", []) == {
        "outcome": "information_requested",
        "text": "",
    }
    assert information_request_preset("ready_for_review", []) is None


def test_the_form_opens_on_needs_information_and_records_the_request(
    seeded: Settings,
) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            application_id = prepare(session, findings=True)
            plain_id = prepare(session, findings=False)
    finally:
        factory.dispose()

    app = create_app(seeded)
    with TestClient(app) as client:
        chosen = client.post("/api/session/select", json={"actor_id": REVIEWER})
        assert chosen.status_code == 200, chosen.text
        form = decision_form(client, application_id)
        assert selected_outcome(form) == "information_requested"
        fields = form_values(form)
        fields["outcome"] = selected_outcome(form)
        assert fields["reason"] == REQUEST
        recorded = client.post(
            "/ui/actions/permit.decide",
            data=fields,
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )
        assert recorded.status_code == 200, recorded.text
        assert recorded.json()["state"] == "information_requested"

        plain = decision_form(client, plain_id)
        assert selected_outcome(plain) == "approved"
        assert form_values(plain)["reason"] == ""
        assert 'value="information_requested" selected' not in plain

    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            decision = PermitService(session).current_decision(application_id)
            assert decision is not None
            assert decision.outcome == "information_requested"
            assert decision.reason == REQUEST
            assert PermitService(session).load_application(application_id).status == (
                "needs_information"
            )
    finally:
        factory.dispose()


def test_an_edited_request_is_what_gets_recorded(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            application_id = prepare(session, findings=True)
    finally:
        factory.dispose()

    app = create_app(seeded)
    with TestClient(app) as client:
        chosen = client.post("/api/session/select", json={"actor_id": REVIEWER})
        assert chosen.status_code == 200, chosen.text
        form = decision_form(client, application_id)
        fields = form_values(form)
        fields["outcome"] = selected_outcome(form)
        assert fields["reason"] == REQUEST
        assert fields["outcome"] == "information_requested"
        fields["reason"] = EDITED
        recorded = client.post(
            "/ui/actions/permit.decide",
            data=fields,
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )
        assert recorded.status_code == 200, recorded.text

    factory = SessionFactory(seeded.database_url)
    try:
        with factory() as session:
            decision = PermitService(session).current_decision(application_id)
            assert decision is not None
            assert decision.reason == EDITED
            assert REQUEST not in (decision.reason or "")
    finally:
        factory.dispose()
