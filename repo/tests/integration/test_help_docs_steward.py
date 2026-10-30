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


#: The page each quoted label of the steward help is read on, and the chain of
#: elements that hold the label on that page.  A holder is a fragment of the
#: start tag of an element, such as a test id or a class, and the elements are
#: looked up from the outside in.  The label is checked in the element that
#: holds it, not anywhere on the page.
LABELS: dict[str, tuple[str, tuple[str, ...]]] = {
    "Data issues": ("/steward", ('data-screen-key="steward"',)),
    "Search records": ("/steward", ('data-testid="queue-search"', '<label for="queue-query">')),
    "More filters": ("/steward", ('data-testid="queue-filters"', "<summary>")),
    "Apply filters": ("/steward", ('data-testid="queue-filter-submit"',)),
    "Muse guide": ("/steward", ('data-testid="steward-guide"', "<summary>")),
    "Saved guidance. Live Muse is off.": ("/steward", ('data-testid="steward-guide-mode"',)),
    "Needs review": ("/steward", ('data-testid="issue-status"',)),
    "Review match": ("/source-records", ('data-testid="source-action"',)),
    "Source records": ("/source-records", ('data-screen-key="source_records"',)),
    "Activity": ("/activity", ('data-screen-key="activity"',)),
    "Intake queue": ("/queue/intake", ('data-screen-key="intake_queue"',)),
    "Process selected with agent": ("/queue/intake", ('data-testid="intake-bulk-submit"',)),
    "Early resolution": ("/queue/early-resolution", ('data-screen-key="early_resolution"',)),
    "More tools": ("/steward", ('data-testid="nav-more"', "<summary")),
    "3. What are we comparing?": ("case", ('data-testid="case-q3"', "<h2")),
    "Compare with": ("case", ('<label for="candidate-choice">',)),
    "Show this record": ("case", ('data-testid="candidate-choose"',)),
    "5. What will this action do?": ("case", ('data-testid="case-q5"', "<h2")),
    "6. What happened?": ("case", ('data-testid="case-q6"', "<h2")),
    "Reject match proposed for": ("case", ('class="action-label act-title"',)),
    "Start": ("case", ('class="btn sm primary act-open"',)),
    "Confirm link to Cedarline Coffee Works LLC": (
        "case with a candidate",
        ('class="action-label act-title"',),
    ),
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


def _elements(html: str, holder: str) -> list[tuple[int, int, int, int]]:
    """Return the elements of ``html`` whose start tag holds ``holder``.

    Every element is returned as the start of its tag, the end of its start
    tag, the start of its end tag and the end of its end tag.
    """
    spans: list[tuple[int, int, int, int]] = []
    position = 0
    while True:
        index = html.find(holder, position)
        if index == -1:
            return spans
        position = index + len(holder)
        start = html.rfind("<", 0, index)
        if start == -1:
            continue
        match = re.match(r"<([a-zA-Z0-9]+)", html[start:])
        if match is None:
            continue
        tag = match.group(1)
        open_end = html.index(">", start) + 1
        depth = 1
        cursor = open_end
        pattern = re.compile(rf"<(/?){tag}\b[^>]*>")
        while depth:
            closing = pattern.search(html, cursor)
            if closing is None:
                return spans
            cursor = closing.end()
            depth += -1 if closing.group(1) == "/" else 1
        spans.append((start, open_end, closing.start(), cursor))


def element_texts(html: str, holders: tuple[str, ...]) -> list[str]:
    """Return the text of the elements that match the chain of holders."""
    if not holders:
        return []
    outer = _elements(html, holders[0])
    if len(holders) == 1:
        return [
            re.sub(r"<[^>]+>", " ", html[open_end:close_start])
            for _, open_end, close_start, _ in outer
        ]
    texts: list[str] = []
    for start, _, _, end in outer:
        inner = html[start:end]
        for _, open_end, close_start, _ in _elements(inner, holders[1]):
            texts.append(re.sub(r"<[^>]+>", " ", inner[open_end:close_start]))
    return texts


def test_every_quoted_label_of_the_steward_help_is_checked() -> None:
    """Every label a steward step quotes has a page that shows it."""
    quoted = quoted_labels(QUEUE_GUIDE, EXAMPLE_GUIDE)
    assert quoted
    assert quoted <= set(LABELS), sorted(quoted - set(LABELS))


@pytest.mark.parametrize("label", sorted(LABELS))
def test_every_quoted_label_is_found_on_its_page(
    client: TestClient, label: str
) -> None:
    """The label a step quotes is in the element of the page that holds it."""
    path, holders = LABELS[label]
    texts = element_texts(page_of(client, path), holders)
    assert texts, (label, path, holders)
    assert any(label in text for text in texts), (label, path, holders)


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
