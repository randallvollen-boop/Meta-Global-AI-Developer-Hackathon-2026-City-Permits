"""The contact page of the City website.

The page is the one place a resident reaches the City: it lists the
departments and their numbers, says when City Hall is open, and gives the
applicant a form that sends a question to the City's support desk.  A visitor
who is not signed in reads the numbers; only an applicant may send a question.
"""
# REQUIRES: UX-01, UX-02, PER-04, PER-05

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "integration"))
from insight_support import build_environment  # noqa: E402

from acme_city.app import create_app  # noqa: E402
from acme_city.core.config import Settings  # noqa: E402
from acme_city.persistence.models import help as help_models  # noqa: E402
from acme_city.persistence.session import SessionFactory  # noqa: E402

#: The two numbers a permit applicant needs.
CITY_HALL_NUMBER = "(555) 010-0100"
PLANNING_NUMBER = "(555) 010-0120"

#: The question the applicant sends to the City.
QUESTION = "Do I need a permit for a 6 ft fence?"


@pytest.fixture(scope="module")
def settings(tmp_path_factory) -> Settings:
    """A demonstration database with the City website seeded."""
    return build_environment(
        tmp_path_factory.mktemp("contact-page"), synthetic=False, name="contact.db"
    )


@pytest.fixture()
def client(settings: Settings) -> TestClient:
    """The City website as it runs locally."""
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def choose(client: TestClient, actor_id: str) -> None:
    """Establish a server-held session for a persona."""
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def token(client: TestClient) -> str:
    """Return the CSRF token of the contact page."""
    match = re.search(
        r'name="csrf_token" value="([^"]+)"', client.get("/city/contact").text
    )
    assert match, "no form token on the contact page"
    return match.group(1)


def send(client: TestClient, question: str) -> str:
    """Send the question of the contact page and return the answer."""
    response = client.post(
        "/apply/help/escalate",
        data={
            "csrf_token": token(client),
            "placement": "contact",
            "conversation_id": "",
            "conversation_version": "0",
            "question": question,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return response.headers["location"]


# ------------------------------------------------------------- the page itself


def test_the_page_lists_the_departments_the_visit_and_the_after_hours_line(
    client: TestClient,
) -> None:
    """One page carries every way to reach the City."""
    response = client.get("/city/contact")
    assert response.status_code == 200, response.text[:200]
    body = response.text
    assert CITY_HALL_NUMBER in body
    assert PLANNING_NUMBER in body
    assert "1 Example Plaza" in body
    assert "8:30 a.m. to 4:30 p.m." in body
    assert "(555) 010-0199" in body
    # The page is one page: it carries no second contact page of its own.
    assert body.count('data-testid="contact-departments"') == 1


def test_a_visitor_reads_the_numbers_and_is_offered_no_form(
    client: TestClient,
) -> None:
    """A visitor who is not signed in may not send a question."""
    body = client.get("/city/contact").text
    assert 'data-testid="contact-form"' not in body
    assert 'data-testid="contact-submit"' not in body
    # The numbers are still there.
    assert PLANNING_NUMBER in body


def test_a_staff_persona_is_offered_no_form(client: TestClient) -> None:
    """Only an applicant sends a question to the City."""
    choose(client, "persona_city_administrator")
    body = client.get("/city/contact").text
    assert 'data-testid="contact-form"' not in body
    assert PLANNING_NUMBER in body


def test_an_applicant_is_offered_the_form(client: TestClient) -> None:
    """The applicant may ask a person at the City."""
    choose(client, "persona_applicant")
    body = client.get("/city/contact").text
    assert 'data-testid="contact-form"' in body
    assert 'data-testid="contact-submit"' in body
    assert 'action="/apply/help/escalate"' in body
    # The form asks for a question and nothing else.
    assert 'name="question"' in body


# --------------------------------------------------------------- sending it


def test_an_applicant_submit_creates_a_request_and_returns_to_the_page(
    client: TestClient, settings: Settings
) -> None:
    """The request exists, and the applicant lands back on the contact page."""
    choose(client, "persona_applicant")
    location = send(client, QUESTION)
    assert location == "/city/contact#ask", location

    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            requests = session.execute(select(help_models.HelpRequest)).scalars().all()
            assert len(requests) == 1
            assert requests[0].status == "open"
            assert requests[0].question == QUESTION
    finally:
        factory.dispose()

    # The applicant sees the request they sent.
    body = client.get("/city/contact").text
    assert 'data-testid="contact-request"' in body
    assert QUESTION in body


def test_an_empty_submit_gives_a_visible_error(client: TestClient) -> None:
    """An empty question is refused, and the reason is shown on the page."""
    choose(client, "persona_applicant")
    response = client.post(
        "/apply/help/escalate",
        data={
            "csrf_token": token(client),
            "placement": "contact",
            "conversation_id": "",
            "conversation_version": "0",
            "question": "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    assert response.headers["location"].startswith("/city/contact?"), response.headers
    body = client.get(response.headers["location"]).text
    assert 'data-testid="contact-error"' in body
    assert "question" in body.lower()


def test_a_request_without_the_form_token_is_refused(client: TestClient) -> None:
    """The write still checks the token of the session."""
    choose(client, "persona_applicant")
    response = client.post(
        "/apply/help/escalate",
        data={
            "csrf_token": "forged",
            "placement": "contact",
            "conversation_id": "",
            "conversation_version": "0",
            "question": QUESTION,
        },
        follow_redirects=False,
    )
    assert response.status_code == 403, response.text


# ------------------------------------------------------------------ the links


@pytest.mark.parametrize(
    "path", ("/city/", "/city/permits", "/city/community", "/apply", "/apply/track")
)
def test_the_footer_help_link_points_at_the_contact_page(
    client: TestClient, path: str
) -> None:
    """Every page of the City website points at the one contact page."""
    choose(client, "persona_applicant")
    body = client.get(path).text
    assert re.search(r'<a href="/city/contact"[^>]*>Help</a>', body), path
