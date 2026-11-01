"""The tracker of the applicant: My permits, one column, the case in view.

The tracker shows the case the applicant picked: what happens next, what the
City asked, the documents it received and the way to answer.  The rest sits
behind "More details": the service target, the recent activity and the
search by reference.
"""
# REQUIRES: PORTAL-02, PORTAL-03, UX-01, UX-02

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app  # noqa: E402
from acme_city.core.config import Settings  # noqa: E402
from acme_city.persistence.models import permit  # noqa: E402
from acme_city.persistence.session import SessionFactory, transaction  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "integration"))
from insight_support import build_environment  # noqa: E402

APPLICANT = "persona_applicant"
SEEDED = "SYN-APP-005"
CSS = ROOT / "src" / "acme_city" / "static" / "city.css"

#: The answers of a complete fence application.
FENCE = {
    "applicant_name": "Demo Applicant",
    "applicant_email": "demo.applicant@example.invalid",
    "address_text": "400 Lantren Row",
    "structure_kind": "fence",
    "height_ft": "4",
    "fence_material": "cedar",
    "location": "side_rear",
    "setback_ft": "2",
    "property_line_ack": "on",
    "project_description": "4 ft cedar side fence",
}

FILES = {
    "file__site_plan": ("sketch.txt", b"Site sketch.\n", "text/plain"),
    "file__material_spec": ("spec.txt", b"Cedar panels.\n", "text/plain"),
}


@pytest.fixture(scope="module")
def settings(tmp_path_factory) -> Settings:
    """A demonstration database with the personas seeded."""
    return build_environment(
        tmp_path_factory.mktemp("portal-track"), synthetic=False, name="track.db"
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


def token(client: TestClient, path: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text)
    assert match, path
    return match.group(1)


def submit_fence(client: TestClient) -> str:
    """Submit one fence application and return its reference."""
    page = client.get("/apply/deck_fence").text
    data = {
        "csrf_token": token(client, "/apply/deck_fence"),
        "intent": "submit",
        "certification_accepted": "on",
        **FENCE,
    }
    done = client.post(
        "/apply/deck_fence", data=data, files=FILES, follow_redirects=False
    )
    assert done.status_code == 303, done.text
    return done.headers["location"].rsplit("/", 1)[1]


def set_status(settings: Settings, reference: str, status: str) -> None:
    """Move one application to another status."""
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            row = session.execute(
                select(permit.Application).where(
                    permit.Application.source_application_number == reference
                )
            ).scalar_one()
            row.status = status
            session.flush()
    finally:
        factory.dispose()


# --------------------------------------------------------------- the columns


def test_the_tracker_has_no_column_of_help(client: TestClient) -> None:
    """The side column is gone, with the panel and the contact card in it."""
    page = client.get("/apply/track", params={"ref": SEEDED}).text
    assert 'class="tracker-aside"' not in page
    assert 'data-testid="help-panel"' not in page
    assert "Need help?" not in page
    assert 'data-testid="need-help"' not in page


def test_the_launcher_leads_to_the_assistant_with_the_case(
    client: TestClient,
) -> None:
    """The launcher opens the assistant on the panel's own page."""
    page = client.get("/apply/track", params={"ref": SEEDED}).text
    launcher = re.search(
        r'<a class="btn ghost" href="([^"]+)"[^>]*data-testid="help-launcher">', page
    )
    assert launcher is not None, page[:400]
    assert "application_id=" in launcher.group(1)
    landing = client.get(launcher.group(1))
    assert landing.status_code == 200
    assert 'data-testid="help-panel"' in landing.text


def test_the_tracker_is_one_column(client: TestClient) -> None:
    """One column at any width: the side column is gone for good."""
    css = CSS.read_text(encoding="utf-8")
    assert ".tracker-layout" not in css
    assert ".tracker-aside" not in css


# --------------------------------------------------------- the selected case


def test_what_happens_next_is_in_the_case_card(client: TestClient) -> None:
    """The next step belongs to the case, not to a column beside it."""
    page = client.get("/apply/track", params={"ref": SEEDED}).text
    card = page.split('data-testid="permit-card"')[1].split("</article>")[0]
    assert 'data-testid="what-next"' in card
    assert "What happens next" in card
    assert 'data-testid="next-step"' in card
    assert "intake agent" in card


def test_the_service_target_sits_behind_more_details(client: TestClient) -> None:
    """The target is a figure the applicant asks for."""
    page = client.get("/apply/track", params={"ref": SEEDED}).text
    card = page.split('data-testid="permit-card"')[1].split("</article>")[0]
    details = [
        match.group(0)
        for match in re.finditer(r"<details[^>]*>.*?</details>", card, re.S)
        if "target-sentence" in match.group(0)
    ]
    assert details, card
    assert "More details" in details[0]
    assert 'data-testid="target-sentence"' in details[0]
    assert re.search(r"service target for this permit type is \d+ days", details[0])


def test_both_documents_are_listed_as_received(client: TestClient) -> None:
    """Walkthrough step 3: the tracker lists the documents, open."""
    reference = submit_fence(client)
    page = client.get("/apply/track", params={"ref": reference}).text
    listed = page.split('data-testid="tracked-documents"')[1].split("</ul>")[0]
    assert "Site sketch or site plan" in listed and "received" in listed
    assert "Material specification" in listed and "received" in listed
    # the list is not hidden behind a disclosure
    head = page[: page.index('data-testid="tracked-documents"')]
    assert head.count("<details") == head.count("</details>")


def test_the_recent_activity_sits_behind_more_details(client: TestClient) -> None:
    """The history is there, but it is not the first thing to read."""
    page = client.get("/apply/track").text
    assert "<summary>Recent activity</summary>" in page
    activity = page.split('data-testid="recent-activity"')[1].split("</details>")[0]
    assert 'data-testid="activity-item"' in activity


def test_the_search_by_reference_sits_behind_more_details(
    client: TestClient,
) -> None:
    """The lookup is a detail, not a field above the list."""
    page = client.get("/apply/track").text
    position = page.index('data-testid="track-form"')
    opening = page.rfind("<details", 0, position)
    closing = page.index("</details>", position)
    assert opening != -1 and opening < position < closing
    assert "Find an application by reference number" in page[opening:closing]


def test_the_resubmit_text_is_one_line(client: TestClient, settings: Settings) -> None:
    """The answer says what it does, in one line."""
    reference = submit_fence(client)
    set_status(settings, reference, "revisions_requested")
    page = client.get("/apply/track", params={"ref": reference}).text
    section = page.split('data-testid="respond-section"')[1].split("</div>")[0]
    assert "Your answer sends the application back to the City" in section
    assert "The City assesses it again from the start" not in section


# ------------------------------------------------------------------ the clicks


def test_every_tab_leads_to_its_list(client: TestClient) -> None:
    """Click test: the three tabs of My permits."""
    page = client.get("/apply/track").text
    tabs = re.findall(r'<a href="(/apply/track\?tab=\w+)" data-testid="tab-(\w+)"', page)
    assert [key for _href, key in tabs] == ["active", "drafts", "closed"]
    for href, key in tabs:
        landing = client.get(href)
        assert landing.status_code == 200, key
        assert f'data-tab="{key}"' in landing.text


def test_revising_documents_reaches_the_city(
    client: TestClient, settings: Settings
) -> None:
    """Click test: the Submit revised documents button."""
    reference = submit_fence(client)
    set_status(settings, reference, "revisions_requested")
    page = client.get("/apply/track", params={"ref": reference}).text
    assert 'data-testid="revise-form"' in page
    action = re.search(r'action="([^"]+)"[^>]*data-testid="revise-form"', page)
    assert action is not None
    done = client.post(
        action.group(1),
        data={
            "csrf_token": token(client, f"/apply/track?ref={reference}"),
            "reference": reference,
        },
        files={"file__site_plan": ("sketch2.txt", b"Second sketch.\n", "text/plain")},
        follow_redirects=False,
    )
    assert done.status_code == 303, done.text
    assert "revised=1" in done.headers["location"]


def test_sending_the_answer_reaches_the_city(
    client: TestClient, settings: Settings
) -> None:
    """Click test: the Send the answer to the City button."""
    reference = submit_fence(client)
    set_status(settings, reference, "revisions_requested")
    page = client.get("/apply/track", params={"ref": reference}).text
    assert 'data-testid="resubmit-form"' in page
    action = re.search(r'action="([^"]+)"[^>]*data-testid="resubmit-form"', page)
    assert action is not None
    done = client.post(
        action.group(1),
        data={
            "csrf_token": token(client, f"/apply/track?ref={reference}"),
            "reference": reference,
            "expected_version": re.search(
                r'name="expected_version" value="(\d+)"', page
            ).group(1),
        },
        follow_redirects=False,
    )
    assert done.status_code == 303, done.text
    assert "resubmitted=1" in done.headers["location"]


def test_the_case_can_be_opened(client: TestClient) -> None:
    """Click test: the Open the case link."""
    page = client.get("/apply/track", params={"ref": SEEDED}).text
    link = re.search(r'href="([^"]+)" data-testid="open-case"', page)
    assert link is not None
    landing = client.get(link.group(1))
    assert landing.status_code == 200
    assert SEEDED in landing.text
