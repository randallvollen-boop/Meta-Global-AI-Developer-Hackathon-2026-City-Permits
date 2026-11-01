"""The help window of the applicant.

The assistant opens in a small window of its own, from the header of the
City website.  The window carries the panel and nothing else: it never
carries the application form, so the fields and the files the applicant
typed stay exactly as they were.  The window is a view of the same
conversation: its questions, its rate limit and its ownership are the ones
of the panel it replaced.
"""
# REQUIRES: UX-02, UX-03, PER-04, PER-05, SEC-03

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

#: The panel page, with and without the pop-out placement.
PANEL_PATH = "/apply/help/panel"
POPOUT_PATH = "/apply/help/panel?placement=popout"

#: The pages of the applicant that carry the launcher.
APPLICANT_PAGES = ("/apply", "/apply/track", "/apply/deck_fence")

#: The question the applicant asks in the window.
QUESTION = "Do I need a permit for a 6 ft fence?"


@pytest.fixture(scope="module")
def settings(tmp_path_factory) -> Settings:
    """A demonstration database with the City website seeded."""
    return build_environment(
        tmp_path_factory.mktemp("help-popout"), synthetic=False, name="popout.db"
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


def token(client: TestClient, path: str = PANEL_PATH) -> str:
    """Return the CSRF token of a page of the applicant."""
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text)
    assert match, path
    return match.group(1)


def ask(client: TestClient, question: str, **extra) -> str:
    """Ask a question and return the location the answer is served from."""
    data = {
        "csrf_token": token(client),
        "question": question,
        "conversation_version": extra.pop("conversation_version", "0"),
        "conversation_id": extra.pop("conversation_id", ""),
        "placement": extra.pop("placement", "popout"),
        **extra,
    }
    response = client.post("/apply/help", data=data, follow_redirects=False)
    assert response.status_code == 303, response.text
    return response.headers["location"]


# ------------------------------------------------------------- the launcher


@pytest.mark.parametrize("path", APPLICANT_PAGES)
def test_the_header_carries_the_launcher_of_the_window(
    client: TestClient, path: str
) -> None:
    """The header of every applicant page opens the assistant."""
    choose(client, "persona_applicant")
    body = client.get(path).text
    launcher = re.search(
        r'<a class="city-help-link" href="([^"]+)"[^>]*data-testid="help-popout"',
        body,
    )
    assert launcher is not None, path
    assert launcher.group(1) == POPOUT_PATH, path
    # The launcher is a plain link, so it works without a script.
    assert 'target="_blank"' in launcher.group(0), path
    assert "data-help-popout" in launcher.group(0), path


def test_a_visitor_of_the_city_website_is_offered_no_launcher(
    client: TestClient,
) -> None:
    """The window is the applicant's, not the visitor's."""
    body = client.get("/city/").text
    assert 'data-testid="help-popout"' not in body
    assert 'href="/help" data-testid="help-link"' in body


def test_a_staff_persona_is_offered_no_launcher(client: TestClient) -> None:
    """The staff screens keep their own frame."""
    choose(client, "persona_data_steward")
    body = client.get("/queue").text
    assert 'data-testid="help-popout"' not in body


# --------------------------------------------------------------- the window


def test_the_window_carries_the_panel_and_nothing_else(client: TestClient) -> None:
    """The window is the panel: no page heading, no back buttons, no form."""
    choose(client, "persona_applicant")
    body = client.get(POPOUT_PATH).text
    assert 'data-testid="help-panel"' in body
    assert 'data-placement="popout"' in body
    assert "Help with your permit</h1>" not in body
    assert "Back to the permit list" not in body
    assert "Back to your application form" not in body
    # The application form is never part of the window.
    assert 'data-testid="application-form"' not in body
    assert 'name="height_ft"' not in body
    assert 'data-testid="help-escalate-form"' not in body


def test_the_plain_panel_page_still_opens_on_its_own(client: TestClient) -> None:
    """The page without the placement keeps the placement of the form."""
    choose(client, "persona_applicant")
    body = client.get(PANEL_PATH).text
    assert 'data-placement="form"' in body
    # The answer of the form opens in a browsing context of its own.
    form = re.search(r'<form[^>]*data-testid="help-form".*?>', body, re.S)
    assert form is not None
    assert 'target="_blank"' in form.group(0)


def test_the_window_shows_at_most_three_questions(client: TestClient) -> None:
    """Three questions are offered; the rest sit behind a disclosure."""
    choose(client, "persona_applicant")
    body = client.get(POPOUT_PATH).text
    shown = re.search(
        r'<ul class="help-suggestions"[^>]*data-testid="help-suggestions">(.*?)</ul>',
        body,
        re.S,
    )
    assert shown is not None
    assert shown.group(0).count('data-testid="help-suggestion"') == 3
    rest = re.search(
        r'<details class="detail-more" data-testid="help-more-questions".*?</details>',
        body,
        re.S,
    )
    assert rest is not None
    assert rest.group(0).count('data-testid="help-suggestion"') >= 1


def test_a_question_in_the_window_answers_in_the_window(client: TestClient) -> None:
    """The turn of a question asked in the window stays in the window."""
    choose(client, "persona_applicant")
    location = ask(client, QUESTION)
    assert location.startswith("/apply/help/panel?placement=popout"), location
    body = client.get(location).text
    assert 'data-testid="help-turn"' in body
    assert "ACME Code §14-306" in body


def test_the_conversation_of_another_applicant_is_not_found(
    client: TestClient,
) -> None:
    """The window shows the conversation of its own applicant only."""
    choose(client, "persona_applicant")
    location = ask(client, QUESTION)
    conversation = re.search(r"conversation=([^&]+)", location).group(1)
    choose(client, "persona_data_steward")
    assert client.get(f"{PANEL_PATH}?conversation={conversation}").status_code in {
        403,
        404,
    }


def test_a_request_from_the_window_reaches_the_case_it_is_about(
    client: TestClient, settings: Settings
) -> None:
    """The contact page continues the conversation of the window."""
    choose(client, "persona_applicant")
    location = ask(client, QUESTION, application_id="app_d05")
    conversation = re.search(r"conversation=([^&]+)", location).group(1)

    contact = client.get(f"/city/contact?conversation={conversation}").text
    assert f'name="conversation_id" value="{conversation}"' in contact
    # The question of the window is the one the box starts with.
    assert QUESTION in contact

    response = client.post(
        "/apply/help/escalate",
        data={
            "csrf_token": token(client, "/city/contact"),
            "placement": "contact",
            "conversation_id": conversation,
            "conversation_version": "1",
            "question": QUESTION,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    assert response.headers["location"] == "/city/contact#ask"

    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            request = session.execute(
                select(help_models.HelpRequest)
            ).scalars().one()
            assert request.conversation_id == conversation
            # The request is about the case the window was about.
            assert request.application_id == "app_d05"
    finally:
        factory.dispose()


def test_the_rate_limit_of_the_window_is_the_one_of_the_panel(
    client: TestClient,
) -> None:
    """The window asks no more questions than the panel did."""
    choose(client, "persona_applicant")
    for number in range(12):
        response = client.post(
            "/apply/help",
            data={
                "csrf_token": token(client),
                "question": f"question number {number}",
                "conversation_version": "0",
                "conversation_id": "",
                "placement": "popout",
            },
            follow_redirects=False,
        )
        if response.status_code != 303:
            assert response.status_code == 422, response.text
            assert "asked enough questions" in response.text
            return
    pytest.fail("the rate limit of the window was never reached")
