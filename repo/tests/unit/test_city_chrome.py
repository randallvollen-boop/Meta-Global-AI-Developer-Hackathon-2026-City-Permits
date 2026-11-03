"""The City frame: the disclosure, the footer and the home page.

The City website is the front door of the demonstration.  It shows the permit
path and the community lookup; the demonstration disclosure is one line in the
footer, the public-demo notice is one line that shows once, and the rest of
the City services sit behind a disclosure.
"""
# REQUIRES: UX-01, UX-02

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "integration"))
from insight_support import build_environment  # noqa: E402

from acme_city.app import create_app  # noqa: E402
from acme_city.core.config import Settings  # noqa: E402

#: The one line the public demonstration carries.
NOTICE_LINE = "Fictional data. Rebuilt on every deploy."

#: The one sentence the City footer carries.
FOOTER_NOTE = (
    "Fictional City of Acme website for a software demonstration; "
    "every person, address, rule, fee and permit record shown here is synthetic."
)

#: The City pages that share the frame.
CITY_PAGES = ("/city/", "/city/permits", "/city/community", "/city/contact")


def _client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


@pytest.fixture(scope="module")
def settings(tmp_path_factory) -> Settings:
    """A demonstration database with the City website seeded."""
    return build_environment(
        tmp_path_factory.mktemp("city-chrome"), synthetic=False, name="city-chrome.db"
    )


@pytest.fixture()
def client(settings: Settings) -> TestClient:
    """The City website as it runs locally, without the hosted demonstration."""
    with _client(settings) as test_client:
        yield test_client


@pytest.fixture()
def public_client(settings: Settings, tmp_path: Path) -> TestClient:
    """The same website with the hosted demonstration flag on."""
    public = Settings.load(
        environ={
            "ACME_DATABASE_URL": settings.database_url,
            "ACME_SECRET_KEY": "city-chrome-test-secret-value",
            "ACME_PUBLIC_DEMO": "1",
        },
        key_file=tmp_path / "missing.env",
    )
    with _client(public) as test_client:
        yield test_client


def choose(client: TestClient, actor_id: str) -> None:
    """Establish a server-held session for a persona."""
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def footer_of(body: str) -> str:
    """Return the footer of a rendered City page."""
    match = re.search(r'<footer class="city-footer">(.*?)</footer>', body, re.S)
    assert match is not None, "no city footer"
    return match.group(1)


# ------------------------------------------------------------- the notice


@pytest.mark.parametrize("path", ("/select", *CITY_PAGES))
def test_the_notice_shows_once_when_the_public_demo_is_on(
    public_client: TestClient, path: str
) -> None:
    """One line, once, on the hosted demonstration."""
    response = public_client.get(path)
    assert response.status_code == 200, (path, response.text[:200])
    body = response.text
    assert body.count('data-testid="public-demo-notice"') == 1, path
    notice = re.search(
        r'<p class="public-demo-notice"[^>]*>(.*?)</p>', body, re.S
    )
    assert notice is not None, path
    text = re.sub(r"\s+", " ", notice.group(1)).strip()
    assert text == NOTICE_LINE, (path, text)


@pytest.mark.parametrize("path", ("/select", *CITY_PAGES))
def test_the_notice_is_absent_when_the_public_demo_is_off(
    client: TestClient, path: str
) -> None:
    """Without the flag there is no notice at all."""
    response = client.get(path)
    assert response.status_code == 200, (path, response.text[:200])
    assert 'data-testid="public-demo-notice"' not in response.text, path


def test_the_notice_shows_once_for_an_applicant_on_a_portal_page(
    public_client: TestClient,
) -> None:
    """The applicant pages carry the same single line."""
    choose(public_client, "persona_applicant")
    body = public_client.get("/apply").text
    assert body.count('data-testid="public-demo-notice"') == 1


# ------------------------------------------------------- the frame itself


@pytest.mark.parametrize("path", CITY_PAGES)
def test_the_frame_has_no_disclosure_strip(client: TestClient, path: str) -> None:
    """The City frame carries no banner of its own."""
    body = client.get(path).text
    assert 'data-testid="city-demo-banner"' not in body, path
    assert "Fictional demonstration ·" not in body, path
    assert "All people, addresses and permit records are synthetic" not in body, path


@pytest.mark.parametrize("path", CITY_PAGES)
def test_the_footer_note_is_one_sentence(client: TestClient, path: str) -> None:
    """The footer states the demonstration in a single sentence."""
    footer = footer_of(client.get(path).text)
    notes = re.findall(r'<p class="city-footer-note"[^>]*>(.*?)</p>', footer, re.S)
    assert len(notes) == 1, (path, footer)
    text = re.sub(r"\s+", " ", notes[0]).strip()
    assert text == FOOTER_NOTE, (path, text)
    # One sentence: the disclaimer of the old footer is gone.
    assert "ease of switching" not in text, path
    assert "front door" not in text, path


@pytest.mark.parametrize("path", CITY_PAGES)
def test_the_footer_has_no_address_line(client: TestClient, path: str) -> None:
    """The street address line is gone from the footer."""
    footer = footer_of(client.get(path).text)
    assert "1 Example Plaza" not in footer, path
    assert "Weekdays, 8:30 a.m. to 4:30 p.m." not in footer, path


@pytest.mark.parametrize("path", ("/city/", "/apply", "/apply/track"))
def test_the_footer_help_link_points_at_the_contact_page(
    client: TestClient, path: str
) -> None:
    """The footer Help link goes to the contact page on every City page."""
    choose(client, "persona_applicant")
    footer = footer_of(client.get(path).text)
    assert re.search(r'<a href="/city/contact"[^>]*>Help</a>', footer), (path, footer)
    assert "/apply/help/panel" not in footer, path
    # The link leads to a page that answers.
    assert client.get("/city/contact").status_code == 200


# ------------------------------------------------------------ the home page


def test_the_home_page_keeps_the_permit_paths(client: TestClient) -> None:
    """The home page shows the permit path and the community lookup."""
    body = client.get("/city/").text
    assert 'data-testid="hero-permits"' in body
    assert 'data-testid="tile-permits"' in body
    assert 'data-testid="tile-community"' in body
    # The hero sentence about paying a bill is gone.
    assert "Pay a bill, check collection days" not in body
    # The news column is gone.
    assert "News and notices" not in body
    assert "Fall leaf collection" not in body
    # The screen has no help topic of its own, so it keeps the general help.
    assert 'data-testid="ui-help"' in body


def test_the_other_city_services_sit_behind_a_disclosure(client: TestClient) -> None:
    """The other services are collapsed, and the permit tiles stay open."""
    body = client.get("/city/").text
    disclosure = re.search(
        r'<details class="more-types" data-testid="more-services"[^>]*>(.*?)</details>',
        body,
        re.S,
    )
    assert disclosure is not None, body
    # It starts closed.
    assert " open" not in disclosure.group(0).split(">")[0], disclosure.group(0)[:80]
    assert "<summary>More services</summary>" in disclosure.group(1)
    for slug in ("trash-recycling", "parks", "pay-a-bill"):
        assert f'href="/city/{slug}"' in disclosure.group(1), slug
    # The permit tiles are not in the disclosure.
    assert 'data-testid="tile-permits"' not in disclosure.group(1)
    assert 'data-testid="tile-community"' not in disclosure.group(1)


def test_the_apply_call_to_action_reaches_the_application(client: TestClient) -> None:
    """The home page call to action leads to the application form."""
    home = client.get("/city/").text
    call = re.search(r'<a class="city-cta" href="([^"]+)"[^>]*data-testid="hero-permits"', home)
    assert call is not None, home[:400]
    entry = client.get(call.group(1))
    assert entry.status_code == 200, entry.text[:200]

    # A visitor who is not signed in gets a button that switches to the
    # applicant and opens the form.
    form = re.search(
        r'<form method="post" action="/ui/actor"[^>]*data-testid="permits-start-form">(.*?)</form>',
        entry.text,
        re.S,
    )
    assert form is not None, entry.text[:400]
    actor = re.search(r'name="actor_id" value="([^"]+)"', form.group(1))
    target = re.search(r'name="next" value="([^"]+)"', form.group(1))
    assert actor is not None and target is not None, form.group(1)
    assert target.group(1) == "/apply"
    switched = client.post(
        "/ui/actor",
        data={"actor_id": actor.group(1), "next": target.group(1)},
        follow_redirects=False,
    )
    assert switched.status_code == 303, switched.text[:200]
    assert switched.headers["location"] == "/apply"
    application = client.get("/apply")
    assert application.status_code == 200, application.text[:200]
    assert "Start an application" in application.text


def test_the_permit_path_of_a_signed_in_applicant_leads_to_the_form(
    client: TestClient,
) -> None:
    """An applicant walks from the home page into the form in one click."""
    choose(client, "persona_applicant")
    call = re.search(
        r'<a class="city-cta" href="([^"]+)"[^>]*data-testid="hero-permits"',
        client.get("/city/").text,
    )
    assert call is not None
    entry = client.get(call.group(1))
    assert entry.status_code == 200
    start = re.search(
        r'<a class="city-cta" href="([^"]+)"[^>]*data-testid="permits-start"', entry.text
    )
    assert start is not None, entry.text[:400]
    assert start.group(1) == "/apply"
    assert client.get(start.group(1)).status_code == 200
