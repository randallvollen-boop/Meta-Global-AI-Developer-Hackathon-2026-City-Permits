"""Permits in my community: the public read model and its privacy rules."""
# REQUIRES: UX-01, SEC-02

from __future__ import annotations

import json
import re
from dataclasses import fields
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from insight_support import build_environment, open_factory
from sqlalchemy import select, update

from acme_city.app import create_app
from acme_city.insight import public
from acme_city.insight.public import (
    PUBLIC_FIELDS,
    PublicPermit,
    RateLimiter,
    community_summary,
    lookup,
    public_permits,
    public_record,
    suppress,
)
from acme_city.persistence.models import audit, finance, gis, permit, registry
from acme_city.persistence.session import transaction
from acme_city.ui.router import router as ui_router

#: Distinct markers planted in the data a public record must never show.
MARK_COMMENT_INTERNAL = "INTERNALNOTE-7f3a"
MARK_COMMENT_APPLICANT = "APPLICANTCOMMENT-91bc"
MARK_FINDING = "FINDINGMARK-52de"
MARK_DRAFT = "DRAFTMARK-0a17"
MARK_EMAIL = "homeowner.private@example.invalid"
MARK_PHONE = "+1-555-0188"
MARK_DOCUMENT = "document-ref-4c9d.pdf"
MARK_PERSON = "Zelda Quillfeather"
MARK_FEE_CENTS = 987654
MARK_FEE_TEXT = "9,876.54"


@pytest.fixture(scope="module")
def settings(tmp_path_factory):
    return build_environment(tmp_path_factory.mktemp("public"), synthetic=True, name="pub.db")


@pytest.fixture(autouse=True)
def roomy_limiter(monkeypatch):
    monkeypatch.setattr(public, "COMMUNITY_LIMITER", RateLimiter(limit=100000))
    monkeypatch.setattr("acme_city.city.router.community.COMMUNITY_LIMITER", public.COMMUNITY_LIMITER)


@pytest.fixture()
def client(settings):
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def with_session(settings, work):
    factory = open_factory(settings)
    try:
        with transaction(factory) as session:
            return work(session)
    finally:
        factory.dispose()


@pytest.fixture(scope="module")
def sensitive_case(settings):
    """One issued synthetic case with private data of every forbidden kind planted on it."""

    def plant(session):
        row = session.execute(
            select(permit.Application)
            .join(permit.Permit, permit.Permit.application_id == permit.Application.id)
            .join(
                permit.ApplicationParty,
                (permit.ApplicationParty.application_id == permit.Application.id)
                & (permit.ApplicationParty.party_role == "contractor"),
            )
            .where(permit.Application.synthetic.is_(True))
            .order_by(permit.Application.source_application_number)
            .limit(1)
        ).scalar_one()
        issued = session.execute(
            select(permit.Permit).where(permit.Permit.application_id == row.id)
        ).scalar_one()
        person_entity = registry.CanonicalEntity(
            id="entity_planted_person", entity_id="party_planted_person", entity_type="party",
            label=MARK_PERSON, status="active",
        )
        session.add(person_entity)
        session.flush()
        session.add(
            registry.Party(
                id="party_planted_person", entity_id="party_planted_person", party_type="person",
                display_name=MARK_PERSON, legal_name=MARK_PERSON, status="active",
            )
        )
        session.flush()
        session.add(
            registry.PartyContact(
                id="contact_planted_email", party_id="party_planted_person",
                contact_type="email", value=MARK_EMAIL,
            )
        )
        session.add(
            registry.PartyContact(
                id="contact_planted_phone", party_id="party_planted_person",
                contact_type="phone", value=MARK_PHONE,
            )
        )
        row.applicant_party_id = "party_planted_person"
        session.add(
            permit.ApplicationParty(
                id="appparty_planted", application_id=row.id, party_id="party_planted_person",
                party_role="property_owner", is_primary=False,
            )
        )
        for index, (visibility, body) in enumerate(
            (("internal", MARK_COMMENT_INTERNAL), ("applicant", MARK_COMMENT_APPLICANT))
        ):
            session.add(
                permit.ApplicationComment(
                    id=f"comment_planted_{index}", correlation_id="corr_planted",
                    application_id=row.id, body=body, visibility=visibility,
                    author_actor_id="persona_permit_reviewer",
                )
            )
        session.add(
            permit.ApplicationFinding(
                id="finding_planted", correlation_id="corr_planted", application_id=row.id,
                finding_type="judgment", message=MARK_FINDING, severity="review",
            )
        )
        session.add(
            permit.Document(
                id="document_planted", application_id=row.id, document_type="site_plan",
                version=1, file_ref=MARK_DOCUMENT, content_hash="a" * 64,
                received_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        row.submitted_facts = {**(row.submitted_facts or {}), "applicant_email": MARK_EMAIL,
                               "applicant_phone": MARK_PHONE, "draft_note": MARK_DRAFT,
                               "fee_total": MARK_FEE_TEXT}
        session.flush()
        return {"reference": issued.permit_number, "application_id": row.id}

    return with_session(settings, plant)


FORBIDDEN_TEXT = (
    MARK_COMMENT_INTERNAL, MARK_COMMENT_APPLICANT, MARK_FINDING, MARK_DRAFT, MARK_EMAIL,
    MARK_PHONE, MARK_DOCUMENT, MARK_PERSON, MARK_FEE_TEXT, str(MARK_FEE_CENTS),
    "Quillfeather",
)

#: The selector contract of "Permits in my community".  The two public pages
#: keep every one of these test ids: a redesign may change the markup around
#: them, never the ids themselves.
LIST_SELECTORS: tuple[str, ...] = (
    "community-synthetic-note",
    "community-lookup",
    "community-q",
    "community-search",
    "community-results",
    "community-too-short",
    "community-result-total",
    "community-result-table",
    "community-no-results",
    "community-map-section",
    "community-type",
    "community-total",
    "community-district-table",
    "community-recent",
    "synthetic-badge",
    "insight-map",
)

#: The selectors every list page carries, whatever the search state is.
LIST_ALWAYS: frozenset[str] = frozenset(
    {
        "community-synthetic-note",
        "community-lookup",
        "community-q",
        "community-search",
        "community-map-section",
        "community-type",
        "community-total",
        "community-district-table",
        "community-recent",
        "insight-map",
    }
)

#: The selector contract of one public permit record.
DETAIL_SELECTORS: tuple[str, ...] = (
    "community-record",
    "record-synthetic-note",
    "synthetic-badge",
)

#: The public facts one permit record shows.  Every one keeps its data-field.
DETAIL_FIELDS: tuple[str, ...] = (
    "reference",
    "permit_type",
    "parcel",
    "address",
    "district",
    "work_description",
    "status",
    "submitted_on",
    "decided_on",
    "issued_on",
    "outcome",
    "conditions",
    "exception",
    "contractor_business",
)


def assert_clean(text: str) -> None:
    lowered = text.lower()
    for marker in FORBIDDEN_TEXT:
        assert marker.lower() not in lowered, marker


def page_testids(body: str) -> set[str]:
    """Return every test id the page carries."""
    return set(re.findall(r'data-testid="([^"]+)"', body))


def test_the_list_page_keeps_its_selector_contract(client, sensitive_case) -> None:
    """Every selector of the contract survives, in at least one search state."""
    reference = sensitive_case["reference"]
    pages = (
        client.get("/city/community").text,
        client.get(f"/city/community?q={reference}").text,
        client.get("/city/community?q=ab").text,
        client.get("/city/community?q=zzqqq").text,
    )
    found: set[str] = set()
    for page in pages:
        found |= page_testids(page)
    missing = sorted(set(LIST_SELECTORS) - found)
    assert not missing, missing
    assert LIST_ALWAYS <= page_testids(pages[0])


def test_the_list_page_states_keep_their_own_contract(client, sensitive_case) -> None:
    reference = sensitive_case["reference"]
    results = client.get(f"/city/community?q={reference}").text
    too_short = client.get("/city/community?q=ab").text
    empty = client.get("/city/community?q=zzqqq").text
    assert {"community-results", "community-result-total", "community-result-table"} <= page_testids(results)
    assert "community-too-short" not in page_testids(results)
    assert "community-no-results" not in page_testids(results)
    assert "community-too-short" in page_testids(too_short)
    assert "community-result-total" not in page_testids(too_short)
    assert "community-no-results" in page_testids(empty)
    assert "community-too-short" not in page_testids(empty)


def test_the_detail_page_keeps_its_selector_and_field_contract(client, sensitive_case) -> None:
    body = client.get(f"/city/community/permit/{sensitive_case['reference']}").text
    found = page_testids(body)
    assert set(DETAIL_SELECTORS) <= found, sorted(set(DETAIL_SELECTORS) - found)
    for name in DETAIL_FIELDS:
        assert f'data-field="{name}"' in body, name


def test_the_two_public_pages_carry_no_private_marker(client, sensitive_case) -> None:
    for url in ("/city/community", f"/city/community/permit/{sensitive_case['reference']}"):
        assert_clean(client.get(url).text)


def test_the_district_table_keeps_its_markup(client) -> None:
    body = client.get("/city/community").text
    table = re.search(
        r'<table[^>]*data-testid="community-district-table".*?</table>', body, re.S
    )
    assert table, "the district table is there"
    assert 'data-district="' in table.group(0)
    assert '<th scope="row">' in table.group(0)


def test_the_district_table_prints_no_exact_total_under_three(client, settings) -> None:
    summary = with_session(settings, lambda s: community_summary(s, type="rezoning"))
    codes = [district["code"] for district in summary["districts"]]
    raw = with_session(
        settings,
        lambda s: {
            code: sum(
                1 for p in public_permits(s) if p.district == code and p.permit_type == "Rezoning"
            )
            for code in codes
        },
    )
    body = client.get("/city/community?type=rezoning").text
    table = re.search(
        r'<table[^>]*data-testid="community-district-table".*?</table>', body, re.S
    )
    assert table
    for code, count in raw.items():
        if count < 3:
            assert f"<td>{count}</td>" not in table.group(0), code


def test_every_result_item_carries_its_reference(client, sensitive_case) -> None:
    reference = sensitive_case["reference"]
    body = client.get(f"/city/community?q={reference}").text
    assert f'data-reference="{reference}"' in body


def test_the_results_are_cards_and_not_a_table(client, sensitive_case) -> None:
    body = client.get(f"/city/community?q={sensitive_case['reference']}").text
    results = re.search(r'<ul[^>]*data-testid="community-result-table".*?</ul>', body, re.S)
    assert results, "the results are a list of cards"
    assert "<table" not in results.group(0)
    assert "<tr" not in results.group(0)
    assert '<table class="data-table" data-testid="community-district-table">' in body


def test_a_result_card_leads_with_the_address_and_carries_one_link(client, sensitive_case) -> None:
    reference = sensitive_case["reference"]
    body = client.get(f"/city/community?q={reference}").text
    card = re.search(r'<li class="community-card"[^>]*>.*?</li>', body, re.S)
    assert card, "the card is there"
    text = card.group(0)
    assert text.count("<a ") == 1
    assert f'href="/city/community/permit/{reference}' in text
    assert "View public record" in text
    assert 'aria-label="View the public record for' in text
    assert '<p class="community-card-address">' in text
    assert '<p class="community-card-type">' in text
    assert "<time datetime=" in text


def test_the_recent_records_show_only_without_a_query(client, sensitive_case) -> None:
    assert 'data-testid="community-recent"' in client.get("/city/community").text
    body = client.get(f"/city/community?q={sensitive_case['reference']}").text
    assert 'data-testid="community-recent"' not in body


def test_a_long_search_explains_the_limit(client, settings) -> None:
    result = with_session(settings, lambda s: lookup(s, "Acme"))
    assert result["truncated"] is True
    assert len(result["records"]) == 40
    body = client.get("/city/community?q=Acme").text
    assert 'data-testid="community-truncated"' in body
    assert "Showing the first 40 matching records." in body


def test_a_short_search_marks_the_field(client) -> None:
    body = client.get("/city/community?q=ab").text
    field = re.search(r'<input[^>]*data-testid="community-q"[^>]*>', body).group(0)
    assert 'aria-invalid="true"' in field
    assert "community-q-too-short" in field
    assert 'data-testid="community-too-short"' in body
    assert "Type at least three characters." in body


def test_a_valid_search_does_not_mark_the_field(client, sensitive_case) -> None:
    body = client.get(f"/city/community?q={sensitive_case['reference']}").text
    field = re.search(r'<input[^>]*data-testid="community-q"[^>]*>', body).group(0)
    assert "aria-invalid" not in field


def test_the_privacy_explanation_is_in_a_disclosure(client) -> None:
    body = client.get("/city/community").text
    details = re.search(
        r'<details[^>]*data-testid="community-privacy".*?</details>', body, re.S
    )
    assert details, "the explanation is in a disclosure"
    assert "names and contact details" in details.group(0)
    assert "documents, notes, fees and findings" in details.group(0)


def test_the_json_contract_of_the_community_pages_is_unchanged(client, sensitive_case) -> None:
    body = client.get("/city/community?format=json").json()
    assert list(body) == ["fields", "total", "districts", "synthetic_present"]
    assert body["fields"] == list(PUBLIC_FIELDS)
    assert list(body["total"]) == ["value", "display", "suppressed"]
    assert list(body["districts"][0]) == ["code", "total"]
    query = client.get("/city/community?q=Acme&format=json").json()
    assert list(query) == [
        "fields", "total", "districts", "synthetic_present",
        "query", "result_total", "permits",
    ]
    assert list(query["permits"][0]) == list(PUBLIC_FIELDS)
    record = client.get(f"/city/community/permit/{sensitive_case['reference']}?format=json").json()
    assert list(record) == list(PUBLIC_FIELDS)


def test_the_forms_keep_each_others_state(client, sensitive_case) -> None:
    reference = sensitive_case["reference"]
    body = client.get("/city/community", params={"q": reference, "type": "rezoning"}).text
    assert f'name="q" value="{reference}"' in body
    assert 'name="type" value="rezoning"' in body
    search = re.search(r'<form[^>]*data-testid="community-lookup".*?</form>', body, re.S)
    assert search and 'name="type" value="rezoning"' in search.group(0)
    overview = re.search(
        r'<form[^>]*action="/city/community"[^>]*class="insight-filters".*?</form>', body, re.S
    )
    assert overview and f'name="q" value="{reference}"' in overview.group(0)


def test_an_unknown_type_is_not_carried(client, sensitive_case) -> None:
    reference = sensitive_case["reference"]
    body = client.get("/city/community", params={"q": reference, "type": "not-a-type"}).text
    assert 'name="type" value="not-a-type"' not in body
    assert 'name="type" value=""' in body


def test_the_clear_link_clears_the_search_and_keeps_the_type(client) -> None:
    body = client.get("/city/community", params={"q": "Acme", "type": "rezoning"}).text
    clear = re.search(r'<a[^>]*data-testid="community-clear-search"[^>]*>', body)
    assert clear
    assert 'href="/city/community?type=rezoning"' in clear.group(0)


def test_a_record_link_carries_the_search_and_the_type(client, sensitive_case) -> None:
    reference = sensitive_case["reference"]
    body = client.get("/city/community", params={"q": reference, "type": "rezoning"}).text
    card = re.search(r'<li class="community-card"[^>]*>.*?</li>', body, re.S)
    assert card
    href = re.search(r'href="([^"]+)"', card.group(0)).group(1)
    assert href.startswith(f"/city/community/permit/{reference}")
    assert "q=" in href
    assert "type=rezoning" in href


def test_the_record_page_returns_to_the_same_search(client, sensitive_case) -> None:
    reference = sensitive_case["reference"]
    body = client.get(
        f"/city/community/permit/{reference}", params={"q": "Acme", "type": "rezoning"}
    ).text
    back = re.search(r'<a[^>]*data-testid="community-back"[^>]*>', body)
    assert back
    assert 'href="/city/community?q=Acme&amp;type=rezoning#community-results"' in back.group(0)
    assert "Back to search results" in body


def test_a_direct_record_link_offers_the_plain_way_back(client, sensitive_case) -> None:
    body = client.get(f"/city/community/permit/{sensitive_case['reference']}").text
    back = re.search(r'<a[^>]*data-testid="community-back"[^>]*>', body)
    assert back
    assert 'href="/city/community#community-recent"' in back.group(0)
    assert "Back to community permits" in body


def test_the_return_link_is_always_local(client, sensitive_case) -> None:
    reference = sensitive_case["reference"]
    body = client.get(
        f"/city/community/permit/{reference}",
        params={"q": "https://example.invalid/evil", "type": "not-a-type"},
    ).text
    back = re.search(r'<a[^>]*data-testid="community-back"[^>]*>', body)
    assert back
    href = re.search(r'href="([^"]+)"', back.group(0)).group(1)
    assert href.startswith("/city/community")
    assert href.split("?")[0] == "/city/community"
    assert "://" not in href


def test_the_public_record_is_an_allowlist_pinned_by_a_test() -> None:
    assert tuple(field.name for field in fields(PublicPermit)) == PUBLIC_FIELDS
    assert PUBLIC_FIELDS == (
        "reference", "permit_number", "permit_type", "parcel", "address", "district",
        "work_description", "status", "submitted_on", "decided_on", "issued_on", "outcome",
        "conditions", "exception", "exception_kinds", "contractor_business", "synthetic",
    )
    for banned in ("applicant", "owner", "email", "phone", "fee", "amount", "comment", "note",
                   "document", "finding", "draft", "contact", "party", "person", "homeowner"):
        assert not [name for name in PUBLIC_FIELDS if banned in name], banned


def test_a_record_shows_no_forbidden_field_in_html_or_json(client, sensitive_case) -> None:
    reference = sensitive_case["reference"]
    html = client.get(f"/city/community/permit/{reference}")
    as_json = client.get(f"/city/community/permit/{reference}?format=json")
    by_header = client.get(f"/city/community/permit/{reference}", headers={"Accept": "application/json"})
    assert html.status_code == as_json.status_code == by_header.status_code == 200
    assert_clean(html.text)
    assert_clean(as_json.text)
    assert as_json.json() == by_header.json()
    assert list(as_json.json()) == list(PUBLIC_FIELDS)  # exactly the allowlist, in order
    # the permit's own public facts are there
    record = as_json.json()
    assert record["reference"] == record["permit_number"] == reference
    assert record["status"] == "Permit issued"
    assert record["contractor_business"]
    assert record["contractor_business"] in html.text
    assert record["parcel"] in html.text and record["address"] in html.text


def test_lookup_and_the_community_page_show_no_forbidden_field(client, sensitive_case) -> None:
    reference = sensitive_case["reference"]
    for url in (
        f"/city/community?q={reference}",
        f"/city/community?q={reference}&format=json",
        "/city/community?q=Street&format=json",
        "/city/community",
        "/city/community?format=json",
    ):
        response = client.get(url)
        assert response.status_code == 200, url
        assert_clean(response.text)
    body = client.get(f"/city/community?q={reference}&format=json").json()
    assert [p["reference"] for p in body["permits"]] == [reference]
    for permit_json in body["permits"]:
        assert list(permit_json) == list(PUBLIC_FIELDS)


def test_the_contractor_business_name_appears_and_no_person_name_does(client, settings) -> None:
    def people(session):
        return {
            row.display_name
            for row in session.execute(
                select(registry.Party).where(registry.Party.party_type == "person")
            ).scalars()
        }

    names = with_session(settings, people)
    assert len(names) > 10
    records = with_session(settings, lambda session: [p.reference for p in public_permits(session)])
    assert len(records) > 200
    contractors_seen = 0
    for reference in records[::5][:60]:
        for suffix in ("", "?format=json"):
            text = client.get(f"/city/community/permit/{reference}{suffix}").text
            for name in names:
                assert name not in text, (reference, name)
            if suffix and '"contractor_business": ""' not in text and '"contractor_business":""' not in text:
                contractors_seen += 1
    assert contractors_seen > 0
    page = client.get("/city/community?q=a&format=json").text
    page += client.get("/city/community?q=Lantern").text
    for name in names:
        assert name not in page


def test_a_record_without_a_contractor_leaves_the_field_blank(client, settings) -> None:
    def pick(session):
        return next(p.reference for p in public_permits(session) if not p.contractor_business)

    reference = with_session(settings, pick)
    record = client.get(f"/city/community/permit/{reference}?format=json").json()
    assert record["contractor_business"] == ""


@pytest.mark.parametrize("status", ["archived", "returned", "withdrawn", "draft"])
def test_non_public_cases_are_excluded_and_answer_like_a_missing_one(client, settings, status: str) -> None:
    def pick(session):
        return session.execute(
            select(permit.Application)
            .where(permit.Application.synthetic.is_(True), permit.Application.status == "issued")
            .order_by(permit.Application.source_application_number.desc())
            .limit(1)
        ).scalar_one()

    application = with_session(settings, pick)
    with_session(settings, lambda s: None)

    def set_status(session, value, archived):
        session.execute(
            update(permit.Application)
            .where(permit.Application.id == application.id)
            .values(status=value, archived_at=archived)
        )

    permit_number = with_session(
        settings,
        lambda s: s.execute(
            select(permit.Permit.permit_number).where(permit.Permit.application_id == application.id)
        ).scalar_one(),
    )
    assert client.get(f"/city/community/permit/{permit_number}").status_code == 200
    try:
        with_session(
            settings,
            lambda s: set_status(s, status, datetime(2026, 5, 1, tzinfo=UTC) if status == "archived" else None),
        )
        hidden = client.get(f"/city/community/permit/{permit_number}")
        missing = client.get("/city/community/permit/ACME-SYN-999999")
        assert hidden.status_code == missing.status_code == 404
        assert hidden.text == missing.text            # indistinguishable
        hidden_json = client.get(f"/city/community/permit/{permit_number}?format=json")
        missing_json = client.get("/city/community/permit/ACME-SYN-999999?format=json")
        assert hidden_json.status_code == missing_json.status_code == 404
        assert hidden_json.json() == missing_json.json()
        found = client.get(f"/city/community?q={permit_number}&format=json").json()
        assert found["permits"] == []
        everyone = with_session(settings, lambda s: [p.reference for p in public_permits(s)])
        assert permit_number not in everyone
    finally:
        with_session(settings, lambda s: set_status(s, "issued", None))
    assert client.get(f"/city/community/permit/{permit_number}").status_code == 200


def test_archived_status_with_a_stale_status_column_is_still_excluded(settings) -> None:
    """An archive date alone keeps a case out, whatever the status column says."""
    def run(session):
        row = session.execute(
            select(permit.Application)
            .where(permit.Application.synthetic.is_(True), permit.Application.status == "issued")
            .limit(1)
        ).scalar_one()
        before = {p.reference for p in public_permits(session)}
        row.archived_at = datetime(2026, 5, 1, tzinfo=UTC)
        session.flush()
        after = {p.reference for p in public_permits(session)}
        row.archived_at = None
        session.flush()
        return before - after

    assert len(with_session(settings, run)) == 1


def test_only_the_five_public_statuses_are_shown(settings) -> None:
    labels = with_session(settings, lambda s: {p.status for p in public_permits(s)})
    assert labels <= {"Received", "In review", "Approved", "Denied", "Permit issued"}
    assert {"Approved", "Denied", "Permit issued", "Received"} <= labels
    assert set(public.PUBLIC_STATUS) == {
        "submitted", "needs_information", "revisions_requested", "ready_for_review",
        "under_review", "approved", "denied", "issued",
    }


def test_nothing_before_submission_is_public(settings) -> None:
    def run(session):
        row = session.execute(
            select(permit.Application).where(permit.Application.synthetic.is_(True)).limit(1)
        ).scalar_one()
        reference = row.source_application_number
        permit_row = session.execute(
            select(permit.Permit.permit_number).where(permit.Permit.application_id == row.id)
        ).scalar_one_or_none()
        key = permit_row or reference
        row.initial_submitted_at = None
        session.flush()
        gone = public_record(session, key) is None
        row.initial_submitted_at = datetime(2026, 1, 1, tzinfo=UTC)
        return gone

    assert with_session(settings, run) is True


@pytest.mark.parametrize(("total", "shown"), [(0, "fewer than 3"), (1, "fewer than 3"), (2, "fewer than 3"), (3, "3"), (40, "40")])
def test_small_totals_are_suppressed(total: int, shown: str) -> None:
    result = suppress(total)
    assert result["display"] == shown
    assert result["suppressed"] is (total < 3)
    assert (result["value"] is None) is (total < 3)


def test_district_and_filter_totals_under_three_show_fewer_than_three(client, settings) -> None:
    summary = with_session(settings, lambda s: community_summary(s, type="rezoning"))
    shown = {d["code"]: d["total"] for d in summary["districts"]}
    raw = with_session(
        settings,
        lambda s: {
            code: sum(1 for p in public_permits(s) if p.district == code and p.permit_type == "Rezoning")
            for code in shown
        },
    )
    assert any(count < 3 for count in raw.values())
    for code, total in shown.items():
        assert total["suppressed"] is (raw[code] < 3)
        assert total["display"] == ("fewer than 3" if raw[code] < 3 else str(raw[code]))
    body = client.get("/city/community?type=rezoning").text
    row = re.search(r'<tr data-district="R-1"><th scope="row">R-1</th><td>([^<]+)</td>', body)
    assert row and row.group(1) == shown["R-1"]["display"]
    suppressed_code = next(code for code, total in shown.items() if total["suppressed"])
    assert "fewer than 3" in body
    # the raw small number is never printed for a suppressed district
    assert f'<tr data-district="{suppressed_code}"><th scope="row">{suppressed_code}</th><td>{raw[suppressed_code]}</td>' not in body
    assert 'insight-hatch' in body                      # a suppressed district is hatched, not shaded
    as_json = client.get("/city/community?type=rezoning&format=json").json()
    assert all(d["total"]["value"] is None for d in as_json["districts"] if d["total"]["suppressed"])


def test_a_lookup_with_fewer_than_three_matches_does_not_print_the_count(client, sensitive_case) -> None:
    body = client.get(f"/city/community?q={sensitive_case['reference']}").text
    assert "fewer than 3 permits found" in body
    assert "1 permits found" not in body
    broad = client.get("/city/community?q=Street").text
    assert re.search(r"\d+ permits found", broad) or "fewer than 3 permits found" in broad


def test_lookup_finds_by_address_street_and_permit_number(client, settings) -> None:
    def pick(session):
        record = next(p for p in public_permits(session) if p.permit_number)
        return record.reference, record.address

    reference, address = with_session(settings, pick)
    street = address.split(",")[0].split(" ", 1)[1]
    for query in (reference, reference.lower(), address, address.split(",")[0], street):
        body = client.get("/city/community", params={"q": query, "format": "json"}).json()
        assert reference in [p["reference"] for p in body["permits"]], query
    assert client.get("/city/community?q=zz&format=json").json()["permits"] == []
    assert client.get("/city/community?q=zz").text.count("Type at least three characters") == 1
    assert client.get("/city/community", params={"q": "x" * 500, "format": "json"}).status_code == 200


def test_the_public_pages_need_no_persona_and_are_read_only(client, sensitive_case) -> None:
    for url in ("/city/community", f"/city/community/permit/{sensitive_case['reference']}"):
        assert client.get(url).status_code == 200
        for method in ("post", "put", "patch", "delete"):
            assert getattr(client, method)(url).status_code in {403, 404, 405}, (method, url)


def test_the_public_pages_use_the_city_frame_and_no_staff_chrome(client, sensitive_case) -> None:
    for url in ("/city/community", f"/city/community/permit/{sensitive_case['reference']}"):
        body = client.get(url).text
        assert 'data-city-site="true"' in body
        for marker in ('class="side"', "app-nav", 'data-testid="persona-select"', 'href="/queue"'):
            assert marker not in body


def test_the_community_view_is_linked_from_permits_and_the_city_home(client) -> None:
    permits = client.get("/city/permits").text
    assert 'data-testid="permits-community-link"' in permits and 'href="/city/community"' in permits
    home = client.get("/city/").text
    assert 'data-testid="tile-community"' in home and "Permits in my community" in home


def test_every_synthetic_record_carries_the_badge(client, settings) -> None:
    def pick(session):
        records = public_permits(session)
        return (
            next(p.reference for p in records if p.synthetic),
            next((p.reference for p in records if not p.synthetic), None),
        )

    synthetic_ref, real_ref = with_session(settings, pick)
    assert 'data-testid="synthetic-badge"' in client.get(f"/city/community/permit/{synthetic_ref}").text
    assert client.get(f"/city/community/permit/{synthetic_ref}?format=json").json()["synthetic"] is True
    assert "synthetic data" in client.get("/city/community").text
    assert real_ref is not None
    assert 'data-testid="synthetic-badge"' not in client.get(f"/city/community/permit/{real_ref}").text
    assert client.get(f"/city/community/permit/{real_ref}?format=json").json()["synthetic"] is False


def test_a_fixture_permit_has_a_public_record(client) -> None:
    body = client.get("/city/community/permit/ACME-2026-000731?format=json").json()
    assert body["status"] == "Permit issued" and body["outcome"] == "Approved"
    assert body["permit_number"] == "ACME-2026-000731"
    assert body["synthetic"] is False


def test_the_conditions_of_an_approval_are_public_and_an_exception_is_marked(client, settings) -> None:
    def pick(session):
        return next(p for p in public_permits(session) if p.conditions)

    record = with_session(settings, pick)
    body = client.get(f"/city/community/permit/{record.reference}?format=json").json()
    assert body["conditions"] and body["exception"] is True
    assert "Approved with conditions" in body["exception_kinds"]
    assert body["outcome"] == "Approved with conditions"
    assert body["decided_on"] and body["submitted_on"] <= body["decided_on"]


def test_the_rate_limit_answers_429_after_the_allowance(client, monkeypatch, sensitive_case) -> None:
    limiter = RateLimiter(limit=3, window_seconds=60)
    monkeypatch.setattr("acme_city.city.router.community.COMMUNITY_LIMITER", limiter)
    url = f"/city/community/permit/{sensitive_case['reference']}"
    assert [client.get(url).status_code for _ in range(3)] == [200, 200, 200]
    limited = client.get(url)
    assert limited.status_code == 429 and limited.headers["Retry-After"] == "60"
    assert_clean(limited.text)
    limited_json = client.get("/city/community?format=json")
    assert limited_json.status_code == 429 and "detail" in limited_json.json()


def test_the_rate_limiter_is_a_sliding_window() -> None:
    now = [0.0]
    limiter = RateLimiter(limit=2, window_seconds=10, clock=lambda: now[0])
    assert limiter.allow("a") and limiter.allow("a") and not limiter.allow("a")
    assert limiter.allow("b")                       # another client is unaffected
    now[0] = 10.5
    assert limiter.allow("a")                        # the window moved on


def test_the_read_model_writes_nothing(settings) -> None:
    def run(session):
        before = session.execute(select(audit.AuditEvent.id)).all()
        public_permits(session)
        lookup(session, "Street")
        community_summary(session)
        assert not session.new and not session.dirty and not session.deleted
        return before == session.execute(select(audit.AuditEvent.id)).all()

    assert with_session(settings, run) is True


def test_no_fee_or_finance_row_reaches_the_public_model(settings) -> None:
    def run(session):
        assessments = session.execute(select(finance.Assessment)).scalars().all()
        records = [p.as_dict() for p in public_permits(session)]
        return [a.assessed_total_cents for a in assessments], records

    totals, records = with_session(settings, run)
    assert totals and all(total > 0 for total in totals)  # the fixtures hold fees
    text = json.dumps(records)
    for key in {key for record in records for key in record}:
        assert not any(word in key for word in ("fee", "amount", "cents", "assess", "payment", "balance"))
    for cents in totals:
        assert f"${cents / 100:,.2f}" not in text
        assert not re.search(rf"(?<!\d){cents}(?!\d)", text)
        assert not re.search(rf"(?<!\d){cents / 100:.2f}(?!\d)", text)
