"""The steward help names the labels the pages really show.

The shared help test is frozen.  This module checks the words of the steward
lane: every label a steward help step quotes is found on the page the step
points at, and the rejection action names the record it rejects.

Fictional ACME City data only.
"""
# REQUIRES: UX-01, UX-02, MDM-02

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.fixtures.steward_demo import seed_cedarline
from acme_city.help_docs import content
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router

#: The guide of the queue and the source records of the steward.
QUEUE_GUIDE = "work-the-queue-and-the-incoming-work"

#: The Cedarline example of the shared help.
EXAMPLE_GUIDE = "resolve-a-data-issue"


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """Return a client that acts as the Data Steward, with the Cedarline story."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'help-steward.db'}",
            "ACME_SECRET_KEY": "help-steward-secret-value",
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
            session.flush()
        with transaction(factory) as session:
            reset_demo(session, bundle, confirmation="--confirm-fictional-demo")
        with transaction(factory) as session:
            seed_cedarline(session)
    finally:
        factory.dispose()
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        assert (
            test_client.post(
                "/api/session/select", json={"actor_id": "persona_data_steward"}
            ).status_code
            == 200
        )
        yield test_client


def case_path(client: TestClient) -> str:
    """Return the address of the Cedarline match case."""
    queue = client.get("/steward").text
    match = re.search(r'href="(/steward/issues/link/[^\"]+)', queue)
    assert match is not None, "the queue holds no match case"
    return match.group(1).replace("&amp;", "&")


def case_pages(client: TestClient, *, candidate: str = "") -> list[str]:
    """Return the rendered match cases of the queue.

    The confirmation names the record the steward chose to compare, so a case
    is opened with that choice when one is asked for.
    """
    queue = client.get("/steward").text
    paths = sorted(set(re.findall(r'href="(/steward/issues/link/[^\"]+)"', queue)))
    assert paths, "the queue holds no match case"
    pages = []
    for path in paths:
        url = path.replace("&amp;", "&")
        if candidate:
            url = f"{url}&candidate={candidate}"
        pages.append(client.get(url).text)
    return pages


def quoted_labels(*slugs: str) -> set[str]:
    """Return every label the steps of the given guides quote."""
    labels: set[str] = set()
    for slug in slugs:
        guide = content.guide(slug)
        assert guide is not None, slug
        for step in guide["steps"]:
            labels.update(re.findall(r'"([^"]{3,})"', step))
    return labels


#: The page each quoted label of the steward help is read on.
LABELS: dict[str, str] = {
    "Data issues": "/steward",
    "Search records": "/steward",
    "More filters": "/steward",
    "Apply filters": "/steward",
    "Muse guide": "/steward",
    "Saved guidance. Live Muse is off.": "/steward",
    "Needs review": "/steward",
    "Review match": "/source-records",
    "Source records": "/source-records",
    "Activity": "/activity",
    "Intake queue": "/queue/intake",
    "Process selected with agent": "/queue/intake",
    "Early resolution": "/queue/early-resolution",
    "5. What will this action do?": "case",
    "6. What happened?": "case",
    "Reject match proposed for": "case",
    "Start": "case",
    "Confirm link to Cedarline Coffee Works LLC": "case with a candidate",
}


def page_of(client: TestClient, path: str) -> str:
    """Return the rendered page the label is read on.

    A match case is read on any of the cases of the queue, because the label
    belongs to the action of a case and every case shows its own actions.
    """
    if path == "case":
        return "\n".join(case_pages(client))
    if path == "case with a candidate":
        # The confirmation names the record the steward chose to compare.
        return "\n".join(case_pages(client, candidate="party_false_friend"))
    return client.get(path).text


def test_every_quoted_label_of_the_steward_help_is_checked() -> None:
    """Every label a steward step quotes has a page that shows it."""
    quoted = quoted_labels(QUEUE_GUIDE, EXAMPLE_GUIDE)
    assert quoted
    assert quoted <= set(LABELS), sorted(quoted - set(LABELS))


@pytest.mark.parametrize("label", sorted(LABELS))
def test_every_quoted_label_is_found_on_its_page(
    client: TestClient, label: str
) -> None:
    """The label a step quotes is on the page the step names."""
    path = LABELS[label]
    assert label in page_of(client, path), (label, path)


def test_the_rejection_action_names_the_record_it_rejects(
    client: TestClient,
) -> None:
    """The rejection action names the record it turns down."""
    pages = "\n".join(case_pages(client))
    assert "Reject match proposed for Cedarline Coffee Works LLC" in pages


def test_the_steward_guide_of_the_queue_opens(client: TestClient) -> None:
    """The guide of the queue and the incoming work opens for the steward."""
    response = client.get(f"/help/how-to/{QUEUE_GUIDE}")
    assert response.status_code == 200, response.text
    assert 'data-testid="help-page"' in response.text


def test_the_steward_sees_its_own_guides_first(client: TestClient) -> None:
    """The list of the guides of the steward holds the guide of the queue."""
    page = client.get("/help/how-to").text
    slugs = re.findall(r'data-testid="howto-item" data-slug="([^"]+)"', page)
    assert slugs[0] == EXAMPLE_GUIDE
    assert QUEUE_GUIDE in slugs


def test_the_steps_of_the_steward_guide_use_no_dash() -> None:
    """The words of the steward help are plain sentences."""
    for slug in (QUEUE_GUIDE, EXAMPLE_GUIDE):
        guide = content.guide(slug)
        assert guide is not None, slug
        for step in guide["steps"]:
            assert not any(mark in step for mark in ("—", "–")), step
