"""The public City pages: the search a resident runs and the record it opens.

The community page offers the search and the cards, and the overview of the
city sits behind a disclosure.  The record of one permit shows the permit,
the parcel and the outcome in one column, and nothing about the household.
"""
# REQUIRES: UX-01, UX-02

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.client import client, settings  # noqa: E402,F401

#: The fields one public record shows.  The list is the allowlist of the
#: public view model; a field that is not on it never reaches the page.
PUBLIC_FIELDS = (
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

#: The facts of the record that never reach the public page.
PRIVATE_FIELDS = ("applicant_phone", "draft_note", "fee_total")


@pytest.fixture()
def searched(client: TestClient) -> str:
    """The community page after a search for a street name."""
    response = client.get("/city/community?q=Acme")
    assert response.status_code == 200, response.text[:200]
    return response.text


def test_the_community_page_offers_the_search(searched: str) -> None:
    assert 'data-testid="community-lookup"' in searched
    assert 'action="/city/community"' in searched
    assert 'data-testid="community-q"' in searched
    assert 'data-testid="community-search"' in searched
    assert ">Search permits</button>" in searched


def test_a_search_by_street_name_returns_cards_that_open_a_record(searched: str) -> None:
    assert 'data-testid="community-result-total"' in searched
    cards = re.search(
        r'<ul[^>]*data-testid="community-result-table"[^>]*>(.*?)</ul>', searched, re.S
    )
    assert cards is not None, "the search returned cards"
    hrefs = re.findall(r'href="(/city/community/permit/[^"]+)"', cards.group(1))
    assert hrefs, "a card links to its record"
    assert 'class="community-card"' in cards.group(1)
    assert 'class="community-card-link"' in cards.group(1)


def test_the_record_of_a_card_shows_the_permit_the_parcel_and_the_outcome(
    client: TestClient, searched: str
) -> None:
    href = re.search(r'href="(/city/community/permit/[^"]+)"', searched).group(1)
    response = client.get(href)
    assert response.status_code == 200, response.text[:200]
    body = response.text
    for field in PUBLIC_FIELDS:
        assert f'data-field="{field}"' in body, field
    # The record is one column now: the side column is gone.
    assert "community-record-side" not in body
    assert "community-record-columns" not in body
    # The general help button is gone from the record.
    assert 'data-testid="ui-help"' not in body


def test_the_public_record_names_no_household_no_document_and_no_fee(
    client: TestClient, searched: str
) -> None:
    href = re.search(r'href="(/city/community/permit/[^"]+)"', searched).group(1)
    body = client.get(href).text
    for field in PRIVATE_FIELDS:
        assert f'data-field="{field}"' not in body, field
    for word in ("homeowner", "Homeowner", "document", "Document"):
        assert word not in body, word


def test_the_record_keeps_one_back_link(client: TestClient, searched: str) -> None:
    href = re.search(r'href="(/city/community/permit/[^"]+)"', searched).group(1)
    body = client.get(href).text
    assert 'data-testid="community-back"' in body
    assert 'data-testid="community-back-bottom"' not in body


def test_the_overview_of_the_city_sits_behind_a_disclosure(client: TestClient) -> None:
    body = client.get("/city/community").text
    assert '<details class="community-overview" data-testid="community-map-section">' in body
    assert "Recently submitted" in body
    assert '<details class="community-recent"' in body
    # The hint no longer tells the resident which addresses to use.
    assert "Use a fictional ACME City address" not in body


def test_the_service_page_keeps_its_lists_and_collapses_the_aside(client: TestClient) -> None:
    body = client.get("/city/parks").text
    assert "<h1>Parks and recreation</h1>" in body
    assert "Mill Pond Park" in body
    assert '<details class="city-aside">' in body
    assert "Recreation Office" in body
    # The help button and the duplicate permits link are gone.
    assert 'data-testid="ui-help"' not in body
    assert "Looking for permits?" not in body


def test_the_permits_entry_keeps_its_two_calls_to_action(client: TestClient) -> None:
    body = client.get("/city/permits").text
    assert 'data-testid="permits-start"' in body
    assert 'data-testid="permits-track"' in body
    assert 'data-testid="permits-community-link"' in body
    # What you need sits behind a disclosure.
    assert "<summary id=\"need-h\">What you'll need</summary>" in body
    assert "In this demonstration these buttons switch" not in body


def test_the_walkthrough_page_hides_the_look_for_line(client: TestClient) -> None:
    body = client.get("/walkthrough").text
    assert 'data-testid="walkthrough-step"' in body
    assert "<summary>More details</summary>" in body
    assert "The button on each step switches to the persona who does that job" not in body
