"""The chooser of the applicant: Start an application, three groups, stock icons.

The screen is a statement and one plain line.  The permit types sit in three
groups whose headings name the permits they hold, and every group looks
different from the others.  Every card carries a stock line symbol from the
City sprite, never a generated picture, and every card leads to the form of
its own permit type.
"""
# REQUIRES: PORTAL-01, PORTAL-03, UX-01, UX-02

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "integration"))
from insight_support import build_environment  # noqa: E402

from acme_city.applicant_portal import content  # noqa: E402
from acme_city.app import create_app  # noqa: E402
from acme_city.core.config import Settings  # noqa: E402

APPLICANT = "persona_applicant"
ADMIN = "persona_city_administrator"

#: The seventeen permit types of the chooser, in the order of the groups.
TYPE_KEYS = (
    "deck_fence",
    "patio",
    "shed",
    "pod",
    "hvac",
    "water_heater",
    "residential_electric",
    "res_building",
    "com_ti",
    "sign",
    "fire_alarm",
    "change_occupancy",
    "row_encroachment",
    "site_plan_review",
    "rezoning",
    "zoning_variance",
    "certificate_appropriateness",
)

#: The stock symbols of the City sprite.
CITY_SYMBOLS = {"c-permit", "c-tree", "c-card"}

CSS = ROOT / "src" / "acme_city" / "static" / "city.css"


@pytest.fixture(scope="module")
def settings(tmp_path_factory) -> Settings:
    """A demonstration database with the personas seeded."""
    return build_environment(
        tmp_path_factory.mktemp("portal-chooser"), synthetic=False, name="chooser.db"
    )


@pytest.fixture()
def client(settings: Settings) -> TestClient:
    """A client that acts as the Applicant."""
    with TestClient(create_app(settings)) as test_client:
        response = test_client.post(
            "/api/session/select", json={"actor_id": APPLICANT}
        )
        assert response.status_code == 200, response.text
        yield test_client


def cards_of(page: str) -> list[tuple[str, str]]:
    """Return the type key and the target of every card of the chooser."""
    found: list[tuple[str, str]] = []
    for match in re.finditer(
        r'<a class="card type-card" href="([^"]+)" data-testid="type-card" data-type-key="([^"]+)">',
        page,
    ):
        found.append((match.group(2), match.group(1)))
    return found


# ------------------------------------------------------------------ the head


def test_the_heading_is_a_statement_and_the_title_says_the_same(
    client: TestClient,
) -> None:
    """The page says what it is: Start an application."""
    page = client.get("/apply").text
    assert '<h1 data-testid="chooser-title">Start an application</h1>' in page
    assert "<title>Start an application | City of Acme</title>" in page
    assert "What are you trying to do?" not in page


def test_the_sub_line_is_one_plain_sentence(client: TestClient) -> None:
    """One line, plain words, no "portal" and no awkward sentence."""
    page = client.get("/apply").text
    sub = re.search(r'<p class="sub"[^>]*>(.*?)</p>', page, re.S)
    assert sub is not None, "the chooser has no sub line"
    text = " ".join(sub.group(1).split())
    assert text == (
        "Choose the project you need a permit for. "
        "The form asks only for what that project needs."
    )
    assert text[0].isupper() and text.endswith(".")


def test_the_track_button_leads_to_my_permits(client: TestClient) -> None:
    """The button in the head is a working link."""
    page = client.get("/apply").text
    link = re.search(
        r'<a class="btn" href="([^"]+)" data-testid="track-link">(.*?)</a>', page
    )
    assert link is not None
    assert "Track an existing application" in link.group(2)
    landing = client.get(link.group(1))
    assert landing.status_code == 200
    assert "<h1>My permits</h1>" in landing.text


def test_the_help_launcher_leads_to_the_assistant(client: TestClient) -> None:
    """The launcher of the removed help column opens the assistant's own page."""
    page = client.get("/apply").text
    launcher = re.search(
        r'<a class="btn ghost" href="([^"]+)"[^>]*data-testid="help-launcher">(.*?)</a>',
        page,
    )
    assert launcher is not None, "the chooser has no launcher for the assistant"
    assert "Ask about your permit" in launcher.group(2)
    landing = client.get(launcher.group(1))
    assert landing.status_code == 200
    assert 'data-testid="help-panel"' in landing.text
    assert 'data-testid="help-form"' in landing.text


# ------------------------------------------------------------------ the groups


def test_the_group_headings_name_the_permits_they_hold(client: TestClient) -> None:
    """Three groups, each headed by the permits it holds."""
    page = client.get("/apply").text
    headings = re.findall(r'<h2 id="group-([^"]+)">([^<]+)</h2>', page)
    assert [key for key, _label in headings] == [
        "home_property",
        "business_construction",
        "planning_land_use",
    ]
    for _key, label in headings:
        assert label.endswith("permits"), label
        assert label[0].isupper(), label
        assert label == label[0].upper() + label[1:], label
    # the wording comes from the configuration, not from the template
    for label in content.content()["chooser_groups"].values():
        assert label in page


def test_each_group_looks_different_from_the_others(client: TestClient) -> None:
    """Every group carries its own accent, keyed on the group it holds."""
    page = client.get("/apply").text
    groups = re.findall(r'data-testid="portal-group" data-group="([^"]+)"', page)
    assert groups == ["home_property", "business_construction", "planning_land_use"]
    css = CSS.read_text(encoding="utf-8")
    accents: dict[str, str] = {}
    for key in groups:
        match = re.search(
            rf'\.chooser-group\[data-group="{key}"\] \{{ border-top-color: ([^;]+);', css
        )
        assert match is not None, key
        accents[key] = match.group(1)
    # the accents are three different colours of the City palette
    assert len(set(accents.values())) == len(groups), accents


# ------------------------------------------------------------------ the cards


def test_no_card_shows_a_generated_picture(client: TestClient) -> None:
    """The applicant sees the stock line symbols, not the Muse-made pictures."""
    page = client.get("/apply").text
    assert "<img" not in page
    assert "permit-type-icons" not in page
    symbols = re.findall(r'<use href="#([^"]+)"/>', page)
    assert len(symbols) == 17
    assert set(symbols) <= CITY_SYMBOLS, sorted(set(symbols))


def test_the_symbol_of_a_card_follows_the_configured_map(client: TestClient) -> None:
    """A deck or a patio is a tree, a sign or an electric job is a card."""
    icons = content.content()["type_icons"]
    assert icons, "the configuration names no symbol"
    for key, symbol in icons.items():
        assert symbol in CITY_SYMBOLS, (key, symbol)
    page = client.get("/apply").text
    for key, symbol in icons.items():
        card = re.search(
            rf'<a class="card type-card"[^>]*data-type-key="{key}">(.*?)</a>', page, re.S
        )
        assert card is not None, key
        assert f'<use href="#{symbol}"/>' in card.group(1), key


def test_the_seventeen_types_are_all_on_the_page(client: TestClient) -> None:
    """Every permit type of the City is offered to the applicant."""
    page = client.get("/apply").text
    assert sorted(key for key, _href in cards_of(page)) == sorted(TYPE_KEYS)
    assert page.count('data-testid="type-card"') == 17


@pytest.mark.parametrize("type_key", TYPE_KEYS)
def test_every_card_leads_to_the_form_of_its_permit_type(
    client: TestClient, type_key: str
) -> None:
    """Click test: each card opens the form of its own permit type."""
    page = client.get("/apply").text
    cards = dict(cards_of(page))
    assert type_key in cards, (type_key, sorted(cards))
    landing = client.get(cards[type_key])
    assert landing.status_code == 200, type_key
    assert 'data-testid="application-form"' in landing.text, type_key
    assert 'data-testid="form-title"' in landing.text, type_key


def test_the_rest_of_each_group_is_behind_one_disclosure(client: TestClient) -> None:
    """The six common projects are open; the rest is behind one summary."""
    page = client.get("/apply").text
    assert page.count('data-testid="more-types"') == 3
    summaries = re.findall(r"<summary>(.*?)</summary>", page)
    assert len(summaries) == 3
    for summary in summaries:
        text = " ".join(summary.split())
        assert text.startswith("More ") or text.startswith("All "), text
        assert text.endswith(")"), text
        assert "permits" in text, text


# ------------------------------------------------------------------ the notice


def test_the_notice_is_one_line_at_the_bottom_and_not_a_banner(
    client: TestClient,
) -> None:
    """The gift-card warning is a line of the page, not a banner above it."""
    page = client.get("/apply").text
    tag = re.search(r'<p class="([^"]*)"[^>]*data-testid="portal-notice">', page)
    assert tag is not None
    assert "notice" not in tag.group(1).split(), tag.group(1)
    # it carries no warning icon any more
    assert "<svg" not in page.split('data-testid="portal-notice"')[1].split("</p>")[0]
    # it stands below the groups, not above them
    assert page.index('data-testid="portal-notice"') > page.index(
        'data-testid="portal-group"'
    )


# ------------------------------------------------------------------ the staff


def test_the_staff_screens_keep_the_pictures(client: TestClient) -> None:
    """Only the applicant sees the line symbols; the staff keep the images."""
    response = client.post("/api/session/select", json={"actor_id": ADMIN})
    assert response.status_code == 200, response.text
    queue = client.get("/queue?view=all")
    assert queue.status_code == 200
    assert 'data-testid="permit-type-icon"' in queue.text
    assert "permit-type-icons/" in queue.text
    admin = client.get("/admin?tab=appearance")
    assert admin.status_code == 200
    assert admin.text.count('data-testid="permit-type-icon-row"') == 17
