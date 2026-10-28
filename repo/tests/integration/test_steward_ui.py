"""The Data Steward screens: tabs, record profiles, Data issues, the focused case.

Fictional ACME data only.  The Cedarline story (Cedarline Coffee Roasters LLC
against Cedarline Coffee Works LLC, a different license number) is added only
by ``acme_city.fixtures.steward_demo``, never by the reset.
"""
# REQUIRES: UX-01, UX-02, SEC-01, MDM-02, MDM-03

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.fixtures.steward_demo import seed_cedarline
from acme_city.persistence.models import change, registry
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui import display, steward_views
from acme_city.ui.router import router as ui_router


@pytest.fixture()
def environment(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'steward-ui.db'}",
            "ACME_SECRET_KEY": "steward-ui-secret-value",
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


@pytest.fixture()
def client(environment: Settings) -> TestClient:
    app = create_app(environment)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def choose(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def seed(environment: Settings) -> list[str]:
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            return seed_cedarline(session)
    finally:
        factory.dispose()


def text_of(html: str) -> str:
    main = re.search(r'<main id="main">(.*?)</main>', html, re.S)
    body = main.group(1) if main else html
    body = re.sub(r"<(script|style|svg).*?</\1>", "", body, flags=re.S)
    body = re.sub(r'<span class="ui-info-pop".*?</span>', "", body, flags=re.S)
    body = re.sub(r'<details class="ui-info-fallback".*?</details>', "", body, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))


def csrf(client: TestClient, path: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text)
    assert match, path
    return match.group(1)


def link_version(environment: Settings, record: str) -> int:
    """Return the version of the newest link of one source record."""
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            rows = session.execute(
                select(registry.Crosswalk).where(registry.Crosswalk.source_record_id == record)
                .order_by(registry.Crosswalk.created_at)
            ).scalars().all()
            return rows[-1].version
    finally:
        factory.dispose()


def case_path(client: TestClient, record: str) -> str:
    """Return the focused-case address of the issue about one source record."""
    queue = client.get("/steward?filter=needs_review").text
    for href in re.findall(r'href="(/steward/issues/link/[^"]+)"', queue):
        if record in client.get(href).text.split("<h1", 1)[1][:400]:
            return href
    raise AssertionError(f"no issue for {record}")


def post(client: TestClient, action: str, fields: dict[str, str], next_path: str):
    return client.post(
        f"/ui/actions/{action}",
        data={"csrf_token": csrf(client, "/steward"), "next": next_path, **fields},
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )


# ----------------------------------------------------------------------- tabs


def test_master_records_has_four_tabs_and_one_collection_at_a_time(client: TestClient) -> None:
    choose(client, "persona_data_steward")
    page = client.get("/masters")
    assert page.status_code == 200
    tabs = re.findall(r'data-testid="master-tab" data-tab="([a-z]+)"', page.text)
    assert tabs == ["people", "properties", "licenses", "registrations"]
    labels = [
        re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", item)).strip()
        for item in re.findall(r'<a [^>]*data-testid="master-tab"[^>]*>(.*?)</a>', page.text, re.S)
    ]
    assert [label.rsplit(" ", 1)[0] for label in labels] == [
        "People &amp; organizations",
        "Properties",
        "Business licenses",
        "Contractor registrations",
    ]
    # Exactly one tab is current, and exactly one collection table is on the page.
    assert len(re.findall(r'aria-current="page"', page.text.split('data-testid="master-tabs"')[1].split("</nav>")[0])) == 1
    assert 'data-testid="applicant-table"' in page.text
    for other in ("property-table", "business-table", "contractor-table"):
        assert f'data-testid="{other}"' not in page.text
    for tab, table in (
        ("properties", "property-table"),
        ("licenses", "business-table"),
        ("registrations", "contractor-table"),
    ):
        body = client.get(f"/masters?tab={tab}").text
        assert f'data-testid="{table}"' in body
        assert 'data-testid="applicant-table"' not in body
        assert re.search(rf'data-tab="{tab}"[^>]*aria-current="page"', body)
    # An unknown tab falls back to the first one.
    assert 'data-testid="applicant-table"' in client.get("/masters?tab=nonsense").text


def test_applicants_renders_the_people_tab_and_keeps_its_ids(client: TestClient) -> None:
    choose(client, "persona_data_steward")
    page = client.get("/applicants")
    assert page.status_code == 200
    assert 'data-testid="applicant-search"' in page.text
    assert 'data-testid="applicant-table"' in page.text
    assert len(re.findall(r'data-testid="applicant-row"', page.text)) == 9
    assert client.get("/applicants/party_cedarline").status_code == 200
    assert client.get("/masters/party_cedarline").status_code == 200
    # The persona without Master records sees only the People & organizations tab.
    choose(client, "persona_permit_reviewer")
    body = client.get("/applicants").text
    assert re.findall(r'data-testid="master-tab" data-tab="([a-z]+)"', body) == ["people"]
    assert client.get("/masters").status_code == 403


def test_people_list_columns_filters_and_alias(client: TestClient) -> None:
    choose(client, "persona_data_steward")
    body = client.get("/masters").text
    heads = [
        re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", item)).strip()
        for item in re.findall(r"<th scope=\"col\">(.*?)</th>", body.split('data-testid="applicant-table"')[1], re.S)
    ]
    assert [h.split(" i ")[0].split(" A discrepancy")[0].strip() for h in heads][:4] == [
        "Name", "Type", "Primary contact", "Applications",
    ]
    assert "Version" not in heads and "Status" not in heads
    counts = {
        key: int(count)
        for key, count in re.findall(r'data-filter="([a-z]+)">[A-Za-z ]+ <span class="n">(\d+)</span>', body)
    }
    assert counts == {"all": 9, "people": 2, "organizations": 7}
    assert len(re.findall(r'data-testid="applicant-row"', client.get("/masters?kind=people").text)) == 2
    assert len(re.findall(r'data-testid="applicant-row"', client.get("/masters?kind=organizations").text)) == 7
    # Search by alias finds the organization and shows the alias under the name.
    found = client.get("/masters", params={"q": "Cedar Line"}).text
    assert len(re.findall(r'data-testid="applicant-row"', found)) == 1
    assert "Cedarline Coffee Roasters LLC" in found
    assert re.search(r'data-testid="alias-line">Cedar Line Coffee Roasters<', found)
    # Primary contact is one value; the application count opens the related applications.
    row = body.split('data-party-id="party_cedarline"')[1].split("</tr>")[0]
    assert "hello@cedarline.example.invalid" in row and "+1-555-0170" not in row
    assert 'data-detail-kind="applications"' in row and "4 applications" in row


def test_attention_shows_only_for_a_real_open_issue(client: TestClient, environment: Settings) -> None:
    choose(client, "persona_data_steward")
    assert "open issue" not in text_of(client.get("/masters").text)
    seed(environment)
    body = client.get("/masters").text
    row = body.split('data-party-id="party_cedarline"')[1].split("</tr>")[0]
    assert "open issue" in text_of(row)
    quiet = body.split('data-party-id="party_hollis"')[1].split("</tr>")[0]
    assert "open issue" not in text_of(quiet)


# ------------------------------------------------------- record-profile drawers


def test_record_profile_drawer_has_overview_sources_and_history(
    client: TestClient, environment: Settings
) -> None:
    choose(client, "persona_data_steward")
    seed(environment)
    overview = client.get("/detail/record/party_cedarline")
    assert overview.status_code == 200
    text = text_of(overview.text)
    for needle in ("Cedarline Coffee Roasters LLC", "Cedar Line Coffee Roasters", "hello@cedarline.example.invalid",
                   "BL-2026-00412", "SYN-APP-001", "Record status", "PER-AP-0003 may match this record"):
        assert needle in text, needle
    assert overview.text.count('data-testid="ui-drawer-tab"') == 3
    assert re.search(r'data-detail-kind="record"[^>]*aria-current="page"', overview.text)
    sources = client.get("/detail/record-sources/party_cedarline")
    assert sources.status_code == 200
    assert "Permitting: Applicant contact profiles" in sources.text and "PER-AP-0003" in sources.text
    assert "waiting for a decision" in sources.text
    history = client.get("/detail/record-history/party_cedarline")
    assert history.status_code == 200
    assert "Candidate links proposed" in history.text
    # The same drawer renders server-side, without JavaScript, from ?detail=.
    page = client.get("/masters?detail=record-sources:party_cedarline")
    assert 'id="ui-drawer"' in page.text and "is-open" in page.text
    assert "PER-AP-0003" in page.text


def test_other_drawer_kinds_resolve(client: TestClient, environment: Settings) -> None:
    choose(client, "persona_data_steward")
    proposals = seed(environment)
    source = client.get("/detail/source/erp_finance:business_licensing_register:ERP-BL-00413")
    assert source.status_code == 200
    for needle in ("Change this in", "Owner", "Steward", "Open issues", "Last source update", "Last received", "Version"):
        assert needle in source.text, needle
    credential = client.get("/detail/credential/cred_license_cedarline")
    assert credential.status_code == 200
    assert "License or registration status" in credential.text and "Valid through" in credential.text
    parcel = client.get("/detail/parcel/parcel_1001")
    assert parcel.status_code == 200
    text = text_of(parcel.text)
    assert "ACME-P-1001" in text and "Unit 2" in text and "Unit 5" in text
    evidence = client.get(f"/detail/evidence/{proposals[0]}")
    assert evidence.status_code == 200 and "Agreements" in evidence.text
    assert client.get("/detail/applications/party_cedarline").status_code == 200
    assert client.get("/detail/record/party_nobody").status_code == 404
    assert client.get("/detail/source/nowhere:nothing").status_code == 404


def test_drawer_refusals_carry_no_data(client: TestClient, environment: Settings) -> None:
    seed(environment)
    # No persona: 401.  The Applicant and the Permit Reviewer hold no source or master grant: 403.
    assert client.get("/detail/source/permitting:applicant_profiles:PER-AP-0003").status_code == 401
    for actor, path in (
        ("persona_applicant", "/detail/source/permitting:applicant_profiles:PER-AP-0003"),
        ("persona_applicant", "/detail/credential/cred_license_cedarline"),
        ("persona_applicant", "/detail/parcel/parcel_1001"),
        ("persona_permit_reviewer", "/detail/credential/cred_license_cedarline"),
        ("persona_permit_reviewer", "/detail/source/erp_finance:business_licensing_register:ERP-BL-00413"),
    ):
        choose(client, actor)
        response = client.get(path)
        assert response.status_code == 403, (actor, path)
        assert response.headers["cache-control"] == "no-store"
        for leaked in ("Cedarline", "PER-AP-0003", "BL-2026", "ACME-P-1001", "Lantern"):
            assert leaked not in response.text, (actor, path, leaked)
    # The Applicant may open the profile of their own record, never another's (404, no value).
    choose(client, "persona_applicant")
    assert client.get("/detail/record/party_applicant_1").status_code == 200
    other = client.get("/detail/record/party_cedarline")
    assert other.status_code == 404 and "Cedarline" not in other.text
    assert client.get("/detail/record-history/party_cedarline").status_code == 404
    page = client.get("/applicants?detail=record:party_cedarline")
    assert "Cedarline" not in text_of(page.text)


# ----------------------------------------- the three labels, readable values


def test_record_status_license_status_and_data_issue_are_separate_labels(
    client: TestClient, environment: Settings
) -> None:
    choose(client, "persona_data_steward")
    registrations = client.get("/masters?tab=registrations").text
    halcyon = registrations.split("Halcyon Framing and Build LLC")[1].split("</tr>")[0]
    assert "Record status: Active" in text_of(halcyon)
    assert 'data-testid="credential-status">Expired<' in halcyon
    assert "Data issue" not in text_of(halcyon)
    for header in ("Registration number", "Registration status", "Valid through", "Source"):
        assert header in registrations
    licenses = client.get("/masters?tab=licenses").text
    for header in ("License number", "License status", "Valid through", "Source"):
        assert header in licenses
    page = client.get("/masters/party_halcyon").text
    assert 'data-testid="record-status-label"' in page
    assert "License or registration status" in page
    assert "Record status" in page
    assert 'data-testid="record-data-issue"' not in page
    # A real discrepancy adds the third label, on its own.
    seed(environment)
    cedarline = client.get("/masters/party_cedarline").text
    assert 'data-testid="record-data-issue"' in cedarline
    drawer = client.get("/detail/credential/cred_license_cedarline").text
    assert "Data issue" in drawer and "License or registration status" in drawer and "Record status" in drawer
    # The glossary gives each label its popover.
    for key in ("party_record_status", "license_status", "data_issue"):
        assert f'data-info-key="{key}"' in cedarline + registrations


def test_stored_keys_read_as_words_and_timestamps_as_dates(client: TestClient) -> None:
    choose(client, "persona_data_steward")
    properties = client.get("/masters?tab=properties").text
    visible = text_of(properties)
    assert "City of Acme" in visible and "acme_city" not in visible
    assert "ACME-P-1001" in visible and "Units 2 and 5" in visible
    licenses = client.get("/masters?tab=licenses").text
    assert "Business license" in text_of(client.get("/masters/party_cedarline").text)
    assert "business_license" not in text_of(licenses)
    # A timestamp is a readable date with the precise time on hover.
    assert re.search(r'<time datetime="2026-12-31T00:00:00\+00:00" title="2026-12-31 00:00:00 UTC">31 Dec 2026</time>', licenses)
    assert "erp_finance:business_licensing_register" not in text_of(licenses)
    assert "ERP/Finance: Business licences" in licenses
    # The full identifiers stay in the details.
    detail = client.get("/detail/source/erp_finance:business_licensing_register:ERP-BL-00412").text
    assert "erp_finance" in detail and "business_licensing_register" in detail and "2026-09-02 08:30:00 UTC" in detail


def test_display_helpers() -> None:
    assert display.pretty("business_license") == "Business license"
    assert display.pretty("acme_city") == "City of Acme"
    assert display.pretty("some_new_key") == "Some new key"
    assert display.pretty("PER-AP-0003") == "PER-AP-0003"
    assert display.readable_date("2026-09-07T16:45:00+00:00") == "7 Sep 2026"
    assert display.readable_date(None) == ""
    assert display.precise_time("2026-09-07T16:45:00+00:00") == "2026-09-07 16:45:00 UTC"
    assert str(display.time_tag(datetime(2026, 1, 5, tzinfo=UTC))).startswith('<time datetime="2026-01-05T00:00:00+00:00"')


def test_collection_level_no_evidence_message_is_gone(client: TestClient) -> None:
    choose(client, "persona_data_steward")
    for path in ("/masters", "/masters?tab=properties", "/steward", "/source-records", "/activity"):
        assert "No evidence is recorded" not in client.get(path).text, path
    # Evidence moved into the selected record.
    assert 'data-testid="evidence-panel"' in client.get("/masters/party_cedarline?view=sources").text


def test_source_summary_and_freshness_warning_only_when_configured(client: TestClient) -> None:
    choose(client, "persona_data_steward")
    body = client.get("/masters?tab=licenses").text
    assert 'data-testid="source-summary"' in body
    assert "Source last changed" in body and "Last received" in body and "View source details" in body
    assert 'data-testid="freshness-warning"' not in body
    old = datetime(2026, 1, 1, tzinfo=UTC)
    now = datetime(2026, 3, 1, tzinfo=UTC)
    contract = {"source_system_id": "gis", "dataset_key": "parcel_register", "refresh_expectation_days": 7}
    assert "expected to refresh every 7 days" in steward_views.freshness_warning(
        "gis", "parcel_register", old, contracts=[contract], now=now
    )
    assert steward_views.freshness_warning("gis", "parcel_register", old, contracts=[{**contract, "refresh_expectation_days": None}], now=now) == ""
    assert steward_views.freshness_warning("gis", "parcel_register", old, contracts=[], now=now) == ""
    assert steward_views.freshness_warning("gis", "parcel_register", old, now=now) == ""  # nothing in the real config


# ------------------------------------------------------------- Data issues queue


def test_a_fresh_reset_holds_no_steward_issue(client: TestClient) -> None:
    choose(client, "persona_data_steward")
    body = client.get("/steward").text
    counts = re.findall(r'data-filter="([a-z_]+)"[^>]*>\s*[A-Za-z ]+<span class="n" data-testid="issue-filter-count">(\d+)</span>', body)
    assert counts == [("needs_review", "0"), ("assigned_to_me", "0"), ("awaiting_source", "0"), ("resolved", "0")]
    assert "No action has been performed in this session yet" not in body
    assert 'data-testid="queue-empty"' in body


def test_queue_columns_and_filters_use_real_counts(client: TestClient, environment: Settings) -> None:
    choose(client, "persona_data_steward")
    seed(environment)
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            session.add(
                change.ChangeCase(
                    id="case_mine", target_type="party", target_id="party_halcyon", change_kind="factual", correlation_id="corr_mine",
                    title="Correct the Halcyon trading name", status="in_review",
                    assignee_actor_id="persona_data_steward", destination="Permitting applicant profile",
                )
            )
            session.add(
                change.ChangeCase(
                    id="case_waiting", target_type="party", target_id="party_quarry", change_kind="factual", correlation_id="corr_waiting",
                    title="Correct the Quarry Lane address", status="sent_to_source",
                    destination="ERP/Finance business licensing register",
                )
            )
            session.add(
                change.ChangeCase(
                    id="case_done", target_type="party", target_id="party_hollis", change_kind="factual", correlation_id="corr_done",
                    title="Correct the Hollis phone", status="closed",
                )
            )
    finally:
        factory.dispose()

    def counts(body: str) -> dict[str, int]:
        return {
            key: int(n)
            for key, n in re.findall(r'data-filter="([a-z_]+)"[^>]*>\s*[A-Za-z ]+<span class="n" data-testid="issue-filter-count">(\d+)</span>', body)
        }

    body = client.get("/steward").text
    assert counts(body) == {"needs_review": 4, "assigned_to_me": 1, "awaiting_source": 1, "resolved": 1}
    heads = [re.sub(r"<[^>]+>", "", h).strip() for h in re.findall(r'<th scope="col">(.*?)</th>', body.split('data-testid="issue-table"')[1].split("</thead>")[0], re.S)]
    assert heads[:5] == ["Issue", "Record", "Affected application", "Source", "Status"]
    assert "Assigned" in heads  # an assignment exists, so the column appears
    assert len(re.findall(r"data-issue-row", body)) == 4
    mine = client.get("/steward?filter=assigned_to_me").text
    assert len(re.findall(r"data-issue-row", mine)) == 1 and "Halcyon trading name" in mine
    waiting = client.get("/steward?filter=awaiting_source").text
    assert len(re.findall(r"data-issue-row", waiting)) == 1 and "Quarry Lane address" in waiting
    done = client.get("/steward?filter=resolved").text
    assert len(re.findall(r"data-issue-row", done)) == 1 and "Hollis phone" in done
    # Deciding a match moves it from Needs review to Resolved.
    link = case_path(client, "PER-AP-0003")
    assert post(client, "registry.decide", {
        "source_system_id": "permitting", "dataset_key": "applicant_profiles", "source_record_id": "PER-AP-0003",
        "decision": "approve", "reason": "alias and reference agree",
    }, "/steward").status_code == 200
    after = client.get("/steward").text
    assert counts(after) == {"needs_review": 3, "assigned_to_me": 1, "awaiting_source": 1, "resolved": 2}
    # A short confirmation replaces the old "No action has been performed" banner.
    assert 'data-testid="queue-confirmation"' in after and "Recorded the approve decision for PER-AP-0003" in after


def test_synthetic_rows_never_enter_the_steward_queue(client: TestClient, environment: Settings) -> None:
    choose(client, "persona_data_steward")
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            session.add(registry.CanonicalEntity(id="entity_party_synth", entity_id="party_synth", entity_type="party", label="Synthetic Cafe", synthetic=True))
            session.flush()
            session.add(registry.Party(id="party_synth", entity_id="party_synth", party_type="organization", display_name="Synthetic Cafe LLC", synthetic=True))
            session.flush()
            session.add(change.ChangeCase(id="case_synth", target_type="party", target_id="party_synth", change_kind="factual", correlation_id="corr_synth", title="Synthetic correction", status="requested"))
            session.add(change.GovernanceIssue(id="issue_synth", subject_type="party", subject_id="party_synth", issue_type="x", description="Synthetic issue", blocking=True, status="open"))
    finally:
        factory.dispose()
    body = client.get("/steward").text
    assert "Synthetic" not in text_of(body)
    assert 'data-issue-row' not in body


def test_governance_issue_appears_with_blocking_priority(client: TestClient, environment: Settings) -> None:
    choose(client, "persona_data_steward")
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            session.add(change.GovernanceIssue(id="issue_real", subject_type="party", subject_id="party_halcyon", issue_type="registration", description="Registration looks out of step with the record", responsible_queue_id="queue_contractors", assigned_actor_id="persona_data_steward", blocking=True, status="open"))
    finally:
        factory.dispose()
    body = client.get("/steward").text
    assert "Registration looks out of step" in body and "Blocking" in body and "Priority" in body
    case = client.get("/steward/issues/issue/issue_real")
    assert case.status_code == 200 and 'data-question="6"' in case.text
    assert client.get("/steward?filter=assigned_to_me").text.count("data-issue-row") == 1


# --------------------------------------------------------------- focused case


def test_the_focused_case_answers_six_questions_in_order(client: TestClient, environment: Settings) -> None:
    choose(client, "persona_data_steward")
    seed(environment)
    path = case_path(client, "ERP-BL-00413")
    html = client.get(path).text
    order = [int(n) for n in re.findall(r'data-question="(\d)"', html)]
    assert order == [1, 2, 3, 4, 5, 6]
    headings = re.findall(r"<h2 id=\"q\d\">(.*?)</h2>", html, re.S)
    assert [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", h)).strip().split(" i ")[0].strip() for h in headings][:6] == [
        "1. What is the problem?", "2. Why does it matter?", "3. What are we comparing?",
        "4. What supports the decision?", "5. What will this action do?", "6. What happened?",
    ]
    q3 = html.split('data-question="3"')[1].split('data-question="4"')[0]
    q4 = html.split('data-question="4"')[1].split('data-question="5"')[0]
    # Side by side: the submitted value against the master record, field by field.
    assert 'data-testid="compare-table"' in q3 and "Source record" in q3 and "Master record" in q3
    assert q3.count('data-testid="candidate"') == 2
    works, roasters = q3.split('data-testid="candidate"')[1:3]
    assert "Cedarline Coffee Works LLC" in works and 'data-result="conflicts"' not in works
    assert 'data-result="conflicts"' in roasters and "BL-2026-00412" in roasters
    assert 'data-result="agrees"' in works
    # The similarly named organization stays visible as its own record, with a link to its source.
    assert 'data-testid="similar-note"' in q4 and "Cedarline Coffee Roasters LLC" in q4
    assert 'data-detail-kind="source"' in q4
    # Evidence comes before the score, the score is explained, and no percentage is invented.
    assert q4.index("Agreements") < q4.index('data-testid="score-line"')
    assert "It adds up from" in q4 and "does not state the probability" in q4
    assert "%" not in q4.split('data-testid="score-line"')[1].split("</p>")[0]
    # The provenance label stays on screen even for the deterministic matcher.
    assert 'data-testid="provenance"' in q4 and "Deterministic matcher" in q4
    # A separate-event note keeps the permit visible.
    q2 = html.split('data-question="2"')[1].split('data-question="3"')[0]
    assert "No permit decision has been made" in q2
    assert "does not decide any permit" in html.split('data-question="6"')[1]


def test_missing_values_read_no_comparison(client: TestClient, environment: Settings) -> None:
    choose(client, "persona_data_steward")
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            # Halcyon holds no contact: a source email for it has nothing to compare with.
            comparison = steward_views.compare_with_party(
                session,
                {"organization_name": "Halcyon Build", "contact_email": "info@halcyon.example.invalid"},
                session.get(registry.Party, "party_halcyon"),
            )
    finally:
        factory.dispose()
    by_field = {row["field"]: row for row in comparison}
    assert by_field["Email"]["result"] == "no_comparison" and by_field["Email"]["master"] == "No value"
    assert by_field["Name"]["result"] == "agrees"


def test_every_action_previews_what_it_will_do(client: TestClient, environment: Settings) -> None:
    choose(client, "persona_data_steward")
    seed(environment)
    html = client.get(case_path(client, "PER-AP-0003")).text
    blocks = html.split('data-testid="action-preview-block"')[1:]
    labels = re.findall(r'data-testid="action-preview-block" data-action-label="([^"]+)"', html)
    assert labels == [
        "Confirm link to Cedarline Coffee Roasters LLC", "Reject match", "Defer", "Request source correction",
    ]
    for block in blocks:
        for label in ("Records linked", "Application relationship", "Source values kept", "Issue afterwards"):
            assert label in block
    confirm = blocks[0]
    assert "Links PER-AP-0003" in confirm and "no master value is overwritten" in confirm
    assert "marked for recheck" in confirm and "No conflicting value remains" in confirm
    assert "stays unlinked" in blocks[1]
    assert "stays in Needs review" in blocks[2]
    assert "only after" in blocks[3] and "accepts the request" in blocks[3]
    # No generic "Approve" button anywhere.
    assert not re.search(r">\s*Approve\s*<", html)
    # Required inputs show a visible * and the legend is present.
    assert 'class="req-star"' in html and "* Required" in html


def test_a_decision_is_recorded_and_the_case_confirms_it(client: TestClient, environment: Settings) -> None:
    choose(client, "persona_data_steward")
    seed(environment)
    path = case_path(client, "PER-AP-0003")
    assert 'data-testid="case-confirmation"' not in client.get(path).text
    response = client.post(
        "/ui/actions/registry.decide",
        data={
            "csrf_token": csrf(client, path), "next": path,
            "source_system_id": "permitting", "dataset_key": "applicant_profiles", "source_record_id": "PER-AP-0003",
            "decision": "approve", "entity_id": "party_cedarline",
            "reason": "the recorded alias and the declared reference agree",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303 and response.headers["location"] == path
    html = client.get(path).text
    assert 'data-testid="case-confirmation"' in html and "Recorded the approve decision" in html
    q6 = html.split('data-question="6"')[1]
    assert "Linked to Cedarline Coffee Roasters LLC" in q6
    assert "Data Steward" in q6 and "the recorded alias and the declared reference agree" in q6
    assert re.search(r'<time datetime="\d{4}-\d\d-\d\dT[^"]+" title="[^"]+ UTC">\d{1,2} [A-Z][a-z]{2} \d{4}</time>', q6)
    assert 'data-testid="case-status"' in html and ">Resolved<" in html
    # A resolved link offers "Remove link", with a reason, and the Activity screen records both.
    assert "Remove link" in html
    activity = text_of(client.get("/activity").text)
    assert "Link decision" in activity and "the recorded alias and the declared reference agree" in activity
    assert "ui." not in activity  # this is the steward's record, not the audit log


def test_defer_keeps_the_issue_open_and_remove_link_takes_a_link_away(client: TestClient, environment: Settings) -> None:
    choose(client, "persona_data_steward")
    seed(environment)
    path = case_path(client, "PER-AP-0003")
    deferred = post(client, "registry.defer", {
        "source_system_id": "permitting", "dataset_key": "applicant_profiles", "source_record_id": "PER-AP-0003",
        "expected_version": str(link_version(environment, "PER-AP-0003")),
        "reason": "waiting for the owner to confirm the trading name",
    }, path)
    assert deferred.status_code == 200 and deferred.json()["pending"] is True
    html = client.get(path).text
    assert "Needs review" in html and "waiting for the owner to confirm the trading name" in html
    # A deferral needs a reason.
    refused = post(client, "registry.defer", {
        "source_system_id": "permitting", "dataset_key": "applicant_profiles", "source_record_id": "PER-AP-0003", "reason": " ",
        "expected_version": str(link_version(environment, "PER-AP-0003")),
    }, path)
    assert refused.status_code == 422
    # Confirm, then remove the link with a reason.
    assert post(client, "registry.decide", {
        "source_system_id": "permitting", "dataset_key": "applicant_profiles", "source_record_id": "PER-AP-0003",
        "decision": "approve", "reason": "ok",
    }, path).status_code == 200
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            approved = session.execute(select(registry.Crosswalk).where(registry.Crosswalk.link_status == "approved")).scalar_one()
            crosswalk_id, version = approved.id, approved.version
    finally:
        factory.dispose()
    removed = post(client, "registry.decide", {
        "source_system_id": "permitting", "dataset_key": "applicant_profiles", "source_record_id": "PER-AP-0003",
        "decision": "remove", "crosswalk_id": crosswalk_id, "expected_version": str(version), "reason": "recorded against the wrong organization",
    }, path)
    assert removed.status_code == 200, removed.text
    html = client.get(path).text
    assert "Link to Cedarline Coffee Roasters LLC removed" in html and "recorded against the wrong organization" in html
    assert "removed" in client.get("/steward?filter=resolved").text.lower()
    # Proposing the record again opens the issue again: it is back under Needs review.
    again_proposed = post(client, "registry.propose", {
        "source_system_id": "permitting", "dataset_key": "applicant_profiles", "source_record_id": "PER-AP-0003",
    }, "/steward")
    assert again_proposed.status_code == 200
    queue = client.get("/steward").text
    assert "Is PER-AP-0003" in queue
    assert "is no longer linked" not in client.get("/steward?filter=resolved").text
    # Removing a link that is not approved is refused.
    again = post(client, "registry.decide", {
        "source_system_id": "permitting", "dataset_key": "applicant_profiles", "source_record_id": "PER-AP-0003",
        "decision": "remove", "crosswalk_id": crosswalk_id, "reason": "again",
    }, path)
    assert again.status_code == 422


def test_reject_match_closes_the_issue_and_keeps_the_master_unlinked(client: TestClient, environment: Settings) -> None:
    choose(client, "persona_data_steward")
    seed(environment)
    path = case_path(client, "ERP-BL-00413")
    assert post(client, "registry.decide", {
        "source_system_id": "erp_finance", "dataset_key": "business_licensing_register", "source_record_id": "ERP-BL-00413",
        "decision": "reject", "reason": "the license number belongs to another organization",
    }, path).status_code == 200
    html = client.get(path).text
    assert "Rejected" in html.split('data-question="6"')[1]
    records = text_of(client.get("/source-records?system=erp_finance").text)
    assert "ERP-BL-00413" in records
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            states = {row.source_record_id: row.link_status for row in session.execute(select(registry.Crosswalk)).scalars()}
    finally:
        factory.dispose()
    assert states["ERP-BL-00413"] == "rejected" and "ERP-BL-00412" in states and states["ERP-BL-00412"] == "proposed"


def test_guarded_actions_say_your_role_cannot_do_this(client: TestClient, environment: Settings) -> None:
    # The City Administrator may open the screen but holds no grant to move a change case.
    choose(client, "persona_city_administrator")
    body = client.get("/steward").text
    denied = body.split('data-action-id="change.transition"')[1].split("</details>")[0]
    assert 'data-permitted="false"' in body.split('data-action-id="change.transition"')[1][:80]
    assert "Your role cannot do this." in denied
    # The Data Steward can move a change case.
    choose(client, "persona_data_steward")
    steward = client.get("/steward").text
    assert 'data-action-id="change.transition" data-permitted="true"' in steward
    # The Permit Reviewer has no grant for the steward screens at all.
    choose(client, "persona_permit_reviewer")
    for path in ("/steward", "/source-records", "/activity", "/steward/issues/link/x"):
        assert client.get(path).status_code == 403, path


def test_source_records_catalogue_filters_and_links(client: TestClient, environment: Settings) -> None:
    choose(client, "persona_data_steward")
    body = client.get("/source-records").text
    counts = dict(re.findall(r'data-system="([a-z_]*)"[^>]*>\s*([A-Za-z/ ]+) <span class="n">\d+', body))
    assert "" in counts and "permitting" in counts and "erp_finance" in counts
    erp = client.get("/source-records?system=erp_finance").text
    assert "ERP-BL-00412" in erp and "PER-AP-0003" not in erp
    assert "Not linked" in erp
    seed(environment)
    assert "Match waiting for a decision" in client.get("/source-records?system=erp_finance").text
    # The catalogue moved here; the Data issues screen no longer carries it.
    assert 'data-testid="source-record-table"' not in client.get("/steward").text
    assert 'data-testid="source-record-table"' in body


def test_activity_lists_decisions_not_the_audit_log(client: TestClient, environment: Settings) -> None:
    choose(client, "persona_data_steward")
    assert 'data-testid="activity-empty"' in client.get("/activity").text
    seed(environment)
    body = client.get("/activity").text
    assert body.count('data-testid="activity-row"') == 3
    assert "Candidate links proposed" in body
    choose(client, "persona_applicant")
    assert client.get("/activity").status_code == 403


# ------------------------------------------------------- registry service level


def test_the_demo_seed_is_not_part_of_the_reset(environment: Settings) -> None:
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            assert session.execute(select(registry.MatchProposal)).first() is None
    finally:
        factory.dispose()
    source = Path(steward_views.__file__).parents[1].joinpath("fixtures", "reset.py").read_text(encoding="utf-8")
    assert "steward_demo" not in source
    assert len(seed(environment)) == 3


# ------------------------------------------- the other kinds of focused case


def test_a_change_case_and_a_parcel_link_open_as_focused_cases(client: TestClient, environment: Settings) -> None:
    choose(client, "persona_data_steward")
    factory = SessionFactory(environment.database_url)
    try:
        with transaction(factory) as session:
            session.add(
                change.ChangeCase(
                    id="case_trade_name", target_type="party", target_id="party_halcyon", change_kind="factual",
                    correlation_id="corr_trade", title="Correct the Halcyon trading name",
                    reason="The trading name on the permit does not match the registration",
                    old_value={"alias": "Halcyon Build"}, proposed_value={"alias": "Halcyon Framing"},
                    destination="Permitting applicant profile", status="requested", assignee_actor_id="persona_data_steward",
                )
            )
    finally:
        factory.dispose()
    html = client.get("/steward/issues/case/case_trade_name").text
    assert [int(n) for n in re.findall(r'data-question="(\d)"', html)] == [1, 2, 3, 4, 5, 6]
    q3 = text_of(html.split('data-question="3"')[1].split('data-question="4"')[0])
    assert "Halcyon Build" in q3 and "Halcyon Framing" in q3
    assert "A corrected value appears only after the source changes" in html
    assert "Permitting applicant profile" in html
    # The acknowledgement tables of the old Steward review live on the case.
    assert 'data-testid="command-table"' in html and 'data-testid="delivery-table"' in html
    assert client.get("/steward/issues/case/does-not-exist").status_code == 404
    assert client.get("/steward/issues/bogus/x").status_code == 404

    # A parcel link: the locator proposes, the steward decides, in the same six questions.
    choose(client, "persona_city_administrator")
    simulated = client.post("/api/intake/simulate", json={"scenario": "address-typo"})
    assert simulated.status_code == 200, simulated.text
    application_id = simulated.json()["results"][0]["application_id"]
    token = csrf(client, "/agent/intake")
    for action, fields, nxt in (
        ("agent.toggle", {"agent_key": "intake", "mode": "awake"}, "/agent/intake"),
    ):
        assert client.post(f"/ui/actions/{action}", data={"csrf_token": token, "next": nxt, **fields}, headers={"Accept": "application/json"}).status_code == 200
    choose(client, "persona_data_steward")
    token = csrf(client, "/agent/intake")
    assert client.post("/ui/actions/agent.run.intake", data={"csrf_token": token, "next": "/agent/intake"}, headers={"Accept": "application/json"}).status_code == 200
    queue = client.get("/steward").text
    assert 'data-testid="parcel-proposal"' in queue and "ACME-P-1004" in queue
    parcel = client.get(f"/steward/issues/parcel/{application_id}")
    assert parcel.status_code == 200
    assert [int(n) for n in re.findall(r'data-question="(\d)"', parcel.text)] == [1, 2, 3, 4, 5, 6]
    assert "412 Mapel Rdg Dr" in parcel.text and "Approve parcel link" in parcel.text
    assert "The Permit Reviewer still confirms the parcel" in parcel.text


# ------------------------- mandatory version, CSRF and grant on defer and remove

RECORD = {"source_system_id": "permitting", "dataset_key": "applicant_profiles", "source_record_id": "PER-AP-0003"}


def _approved_link(client: TestClient, environment: Settings) -> tuple[str, int]:
    seed(environment)
    assert post(client, "registry.decide", {**RECORD, "decision": "approve", "reason": "ok"}, "/steward").status_code == 200
    factory = SessionFactory(environment.database_url)
    try:
        with factory() as session:
            row = session.execute(select(registry.Crosswalk).where(registry.Crosswalk.link_status == "approved")).scalar_one()
            return row.id, row.version
    finally:
        factory.dispose()


def test_defer_needs_the_version_csrf_and_the_grant(client: TestClient, environment: Settings) -> None:
    choose(client, "persona_data_steward")
    seed(environment)
    version = link_version(environment, "PER-AP-0003")
    fields = {**RECORD, "reason": "waiting"}
    assert post(client, "registry.defer", fields, "/steward").status_code == 422  # missing version
    stale = post(client, "registry.defer", {**fields, "expected_version": str(version + 5)}, "/steward")
    assert stale.status_code == 409
    token_less = client.post(
        "/ui/actions/registry.defer",
        data={"next": "/steward", **fields, "expected_version": str(version)},
        headers={"Accept": "application/json"}, follow_redirects=False,
    )
    assert token_less.status_code in (400, 403)
    assert "Deferred" not in client.get("/activity").text
    choose(client, "persona_city_administrator")
    token = csrf(client, "/steward")
    choose(client, "persona_permit_reviewer")
    denied = client.post(
        "/ui/actions/registry.defer",
        data={"csrf_token": token, "next": "/steward", **fields, "expected_version": str(version)},
        headers={"Accept": "application/json"}, follow_redirects=False,
    )
    assert denied.status_code in (400, 403)
    choose(client, "persona_data_steward")
    ok = post(client, "registry.defer", {**fields, "expected_version": str(version)}, "/steward")
    assert ok.status_code == 200


def test_remove_needs_the_version_csrf_and_the_grant(client: TestClient, environment: Settings) -> None:
    choose(client, "persona_data_steward")
    crosswalk_id, version = _approved_link(client, environment)
    fields = {**RECORD, "decision": "remove", "crosswalk_id": crosswalk_id, "reason": "wrong organization"}
    assert post(client, "registry.decide", fields, "/steward").status_code == 422  # missing version
    stale = post(client, "registry.decide", {**fields, "expected_version": str(version + 5)}, "/steward")
    assert stale.status_code == 409
    token_less = client.post(
        "/ui/actions/registry.decide",
        data={"next": "/steward", **fields, "expected_version": str(version)},
        headers={"Accept": "application/json"}, follow_redirects=False,
    )
    assert token_less.status_code in (400, 403)
    choose(client, "persona_permit_reviewer")
    reviewer_token = csrf(client, "/agent/adjudication")
    denied = client.post(
        "/ui/actions/registry.decide",
        data={"csrf_token": reviewer_token, "next": "/steward", **fields, "expected_version": str(version)},
        headers={"Accept": "application/json"}, follow_redirects=False,
    )
    assert denied.status_code == 403
    choose(client, "persona_data_steward")
    assert link_version(environment, "PER-AP-0003") == version  # nothing changed so far
    ok = post(client, "registry.decide", {**fields, "expected_version": str(version)}, "/steward")
    assert ok.status_code == 200
