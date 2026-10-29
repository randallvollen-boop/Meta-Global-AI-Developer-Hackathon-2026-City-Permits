"""The City Administrator screens of the ACME City interface.

The planning overview, the rules and fee register, the governance and sources
screen and the reconciliation screen render from the stored records, keep their
states apart and answer 403 to a persona without the grant.  The former rules
and fees address redirects to the current one.
"""
# REQUIRES: UX-01, UX-02, UX-03, UX-04, GOV-04, SEC-01, SEC-02
# The Administrator screens render the counted records, the shared patterns and
# the next authorized action, and they refuse a persona without the grant.

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)


@pytest.fixture()
def environment(tmp_path: Path) -> tuple[Settings, FixtureBundle]:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'admin-pages.db'}",
            "ACME_SECRET_KEY": "admin-pages-secret-value",
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
    return settings, bundle


@pytest.fixture()
def client(environment: tuple[Settings, FixtureBundle]) -> TestClient:
    settings, _ = environment
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def select_persona(client: TestClient, actor_id: str) -> None:
    """Establish a server-held session for one persona."""
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


# --------------------------------------------------------------- the overview


def test_the_planning_overview_renders_for_the_city_administrator(
    client: TestClient,
) -> None:
    select_persona(client, "persona_city_administrator")
    response = client.get("/overview")
    assert response.status_code == 200, response.text[:400]
    assert response.text.count('data-testid="overview-cards"') == 1
    for card in (
        "overview-attention-count",
        "overview-property-count",
        "overview-changes-count",
        "overview-sources-count",
    ):
        assert f'data-testid="{card}"' in response.text, card


def test_the_planning_overview_names_the_scope_of_its_counts(
    client: TestClient,
) -> None:
    select_persona(client, "persona_city_administrator")
    response = client.get("/overview")
    assert "Sample applications · synthetic" in response.text


def test_the_planning_overview_links_the_city_view_and_the_what_if(
    client: TestClient,
) -> None:
    select_persona(client, "persona_city_administrator")
    response = client.get("/overview")
    assert 'href="/insight/city"' in response.text
    assert 'href="/policy/scenarios"' in response.text
    # Changed deliberately (P3c merged): the brief says to link the Operations
    # dashboard from the overview once it exists.
    assert 'href="/ops/dashboard"' in response.text


def test_the_planning_overview_is_refused_to_the_other_personas(
    client: TestClient,
) -> None:
    for actor_id in (
        "persona_applicant",
        "persona_data_steward",
        "persona_permit_reviewer",
    ):
        select_persona(client, actor_id)
        assert client.get("/overview").status_code == 403, actor_id


def test_the_property_context_opens_in_the_shared_flyout(
    client: TestClient,
) -> None:
    select_persona(client, "persona_city_administrator")
    response = client.get("/overview?detail=property-context:app_synth_001")
    assert response.status_code == 200
    assert 'data-testid="ui-drawer"' in response.text
    assert "Property context" in response.text
    assert "ACME-P-1001" in response.text
    assert "400 Lantern Row Unit 2" in response.text
    assert "ACME Code" in response.text


def test_the_property_context_detail_route_checks_the_grant(
    client: TestClient,
) -> None:
    select_persona(client, "persona_city_administrator")
    allowed = client.get("/detail/property-context/app_synth_001")
    assert allowed.status_code == 200
    assert "ACME-P-1001" in allowed.text
    select_persona(client, "persona_data_steward")
    refused = client.get("/detail/property-context/app_synth_001")
    assert refused.status_code == 403
    assert "ACME-P-1001" not in refused.text


def test_the_source_detail_opens_in_the_shared_flyout(
    client: TestClient,
) -> None:
    select_persona(client, "persona_city_administrator")
    response = client.get("/governance?tab=sources&source=gis")
    assert response.status_code == 200
    assert "GIS" in response.text
    assert 'data-testid="ui-drawer"' in response.text


# ---------------------------------------------------------------- rules, fees


def test_the_former_rules_address_redirects_to_the_current_one(
    client: TestClient,
) -> None:
    select_persona(client, "persona_city_administrator")
    response = client.get("/rules-fees", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/rules"


def test_the_rules_screen_has_the_two_registers_and_the_three_views(
    client: TestClient,
) -> None:
    select_persona(client, "persona_city_administrator")
    response = client.get("/rules")
    assert response.status_code == 200
    assert 'data-testid="rules-tab" data-tab="rules"' in response.text
    assert 'data-testid="rules-tab" data-tab="fees"' in response.text
    for view in ("published", "drafts", "history"):
        assert f'data-testid="rules-view" data-view="{view}"' in response.text


def test_the_register_shows_the_readable_columns_and_the_approver_columns(
    client: TestClient,
) -> None:
    select_persona(client, "persona_city_administrator")
    response = client.get("/rules?tab=rules&view=drafts")
    assert response.status_code == 200
    for heading in (
        "Title",
        "Project type",
        "Version",
        "Status",
        "Proposed effective date",
        "Next action",
        "Assigned approver",
        "Approved by",
        "Approved on",
    ):
        assert heading in response.text, heading
    # The draft is not approved, so nobody is named as its approver.
    assert "not approved yet" in response.text


def test_the_history_view_lists_the_recorded_lifecycle_events(
    client: TestClient,
) -> None:
    select_persona(client, "persona_city_administrator")
    response = client.get("/rules?tab=rules&view=history")
    assert response.status_code == 200
    assert 'data-testid="rule-history-table"' in response.text
    assert "recorded lifecycle event" in response.text


def test_the_selected_draft_version_shows_the_diff_and_the_overlap_warning(
    client: TestClient,
) -> None:
    select_persona(client, "persona_city_administrator")
    drafts = client.get("/rules?tab=rules&view=drafts")
    match = re.search(r'data-rule-id="([^"]+)"', drafts.text)
    assert match is not None
    response = client.get(f"/rules?tab=rules&view=drafts&version={match.group(1)}")
    assert response.status_code == 200
    assert 'data-testid="selected-version"' in response.text
    assert "250000" in response.text
    assert "300000" in response.text
    assert 'data-testid="selected-version-overlap"' in response.text
    assert "initial submission time" in response.text


def test_the_rules_screen_no_longer_carries_the_permit_type_icons(
    client: TestClient,
) -> None:
    select_persona(client, "persona_city_administrator")
    response = client.get("/rules")
    assert 'data-testid="permit-type-icons"' not in response.text
    assert "permit-type-icon-row" not in response.text


def test_the_appearance_tab_carries_the_icons_their_limits_and_provenance(
    client: TestClient,
) -> None:
    select_persona(client, "persona_city_administrator")
    response = client.get("/admin?tab=appearance")
    assert response.status_code == 200
    assert 'data-testid="admin-section" data-section="permit-type-icons"' in response.text
    assert 'data-testid="icon-cost"' in response.text
    assert 'data-testid="icon-per-type-cap"' in response.text
    assert 'data-testid="icon-global-cap"' in response.text
    assert 'data-testid="icon-provenance"' in response.text
    assert 'data-testid="permit-type-icon-row"' in response.text
    assert 'data-testid="icon-generate"' in response.text


# ---------------------------------------------------------------- governance


def test_the_governance_screen_has_the_five_tabs(
    client: TestClient,
) -> None:
    select_persona(client, "persona_city_administrator")
    response = client.get("/governance")
    assert response.status_code == 200
    for tab in ("sources", "responsibilities", "authority", "access", "history"):
        assert f'data-testid="governance-tab" data-tab="{tab}"' in response.text


def test_the_source_overview_names_the_freshness_and_the_open_issues(
    client: TestClient,
) -> None:
    select_persona(client, "persona_city_administrator")
    response = client.get("/governance?tab=sources")
    assert response.status_code == 200
    assert response.text.count('data-testid="source-card"') == 3
    assert "Source last changed" in response.text
    assert "Last received or checked" in response.text
    assert "Open recorded issues" in response.text
    assert "Responsible team" in response.text
    assert "Change this in" in response.text


def test_the_access_tab_shows_the_grants_of_every_persona(
    client: TestClient,
) -> None:
    select_persona(client, "persona_city_administrator")
    response = client.get("/governance?tab=access")
    assert response.status_code == 200
    assert response.text.count('data-testid="access-row"') == 5
    assert "admin.overview.view" in response.text


# ------------------------------------------------------------- reconciliation


def test_the_reconciliation_screen_has_the_three_scopes(
    client: TestClient,
) -> None:
    select_persona(client, "persona_city_administrator")
    response = client.get("/reconciliation")
    assert response.status_code == 200
    for tab in ("assessments", "receipts", "accounts"):
        assert f'data-testid="reconciliation-tab" data-tab="{tab}"' in response.text


def test_the_assessment_list_shows_the_readable_reference(
    client: TestClient,
) -> None:
    select_persona(client, "persona_city_administrator")
    response = client.get("/reconciliation")
    assert response.status_code == 200
    assert "SYN-APP-007" in response.text
    assert 'data-testid="assessment-view-details"' in response.text


def test_the_receipt_register_is_a_tab_of_its_own(
    client: TestClient,
) -> None:
    select_persona(client, "persona_city_administrator")
    response = client.get("/reconciliation?tab=receipts")
    assert response.status_code == 200
    assert 'data-testid="payment-table"' in response.text
    assert 'data-testid="assessment-table"' not in response.text
    # The euro receipt is visibly apart from the dollar receipts.
    assert "EUR" in response.text
    assert "different currency" in response.text  # editorial pass (vollencoms): no "not X"


def test_the_exception_measure_is_not_styled_when_there_is_nothing_to_review(
    client: TestClient,
) -> None:
    select_persona(client, "persona_city_administrator")
    response = client.get("/reconciliation")
    assert response.status_code == 200
    assert 'data-testid="recon-exceptions-tile" data-exception-count="0"' in response.text
    assert "needs review" not in response.text
    assert "none recorded" in response.text


def test_the_selected_assessment_shows_its_receipts_and_its_finance_actions(
    client: TestClient,
) -> None:
    select_persona(client, "persona_city_administrator")
    response = client.get("/reconciliation?tab=assessments&assessment=assess_d07_v1")
    assert response.status_code == 200
    assert 'data-testid="selected-assessment"' in response.text
    assert 'data-testid="assessment-receipt-row"' in response.text
    for action_id in (
        "finance.assess",
        "finance.reassess",
        "finance.import",
        "finance.allocate",
        "finance.reconcile",
    ):
        assert f'data-action-id="{action_id}"' in response.text, action_id
