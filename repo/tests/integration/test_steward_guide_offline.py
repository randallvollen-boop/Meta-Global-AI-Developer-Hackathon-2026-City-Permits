"""The rendered steward guide always uses saved guidance.

Fictional ACME City data only.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.fixtures.steward_demo import seed_cedarline
from acme_city.muse.client import MuseClient
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import router as ui_router

#: A credential that is not a credential.  The guide has one available and
#: must never use it.
FAKE_KEY = "guide-offline-fake-key-not-a-real-credential"


class TripwireTransport(httpx.BaseTransport):
    """A transport stub that records a call and fails the test."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        raise AssertionError("the rendered guide must never reach a model")


@pytest.fixture()
def tripwire(monkeypatch: pytest.MonkeyPatch) -> TripwireTransport:
    """Make every path to the model fail the test.

    The transport catches a dispatch that goes straight to the network.  The
    client is caught too, because the hosted lock refuses a live call before
    the transport is reached, and a refused call would otherwise be swallowed
    by the caller and read as a normal answer.
    """
    stub = TripwireTransport()
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", stub.handle_request)

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("the rendered guide must never reach a model")

    monkeypatch.setattr(MuseClient, "create_response", refuse)
    return stub


@pytest.fixture()
def client(tmp_path: Path, tripwire: TripwireTransport) -> TestClient:
    """Return a hosted-mode client whose Muse calls fail the test."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'guide.db'}",
            "ACME_SECRET_KEY": "guide-offline-secret-value",
            # A fake credential is set: the guide must not need one, and a
            # missing credential would let a Muse path fall back on its own.
            "META_API_KEY": FAKE_KEY,
            # The hosted demonstration: the demo deployment with the public
            # demonstration on.  Never the production mode.
            "ACME_DEPLOYMENT_MODE": "demo",
            "ACME_PUBLIC_DEMO": "1",
        },
        key_file=tmp_path / "missing.env",
    )
    assert settings.meta_api_key is not None
    assert settings.public_demo
    initialize_database(settings)
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            bundle = FixtureBundle.load()
            session.add(DemoEnvironment(id="demo_environment_local", environment_id=ENVIRONMENT_ID, fictional_demo=True, fixture_version=bundle.fixture_version, label="local fictional demonstration"))
            # The session does not autoflush, so the marker has to reach the
            # database before the reset looks for it.
            session.flush()
            reset_demo(session, bundle, confirmation="--confirm-fictional-demo")
            seed_cedarline(session)
    finally:
        factory.dispose()
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        assert test_client.post("/api/session/select", json={"actor_id": "persona_data_steward"}).status_code == 200
        yield test_client


#: The screens of the steward that carry the saved guide, and the address of
#: each one.
GUIDE_SCREENS: dict[str, str] = {
    "queue": "/steward",
    "profile": "/masters/party_cedarline",
    "masters": "/masters",
    "sources": "/source-records",
    "incoming": "/queue/intake",
    "early_resolution": "/queue/early-resolution",
    "activity": "/activity",
}


@pytest.mark.parametrize("screen", sorted(GUIDE_SCREENS))
def test_guide_is_saved_and_repeatable_without_muse(
    client: TestClient, tripwire: TripwireTransport, screen: str
) -> None:
    """Every guide screen renders the same saved guide twice in hosted mode."""
    path = GUIDE_SCREENS[screen]
    first = client.get(path)
    second = client.get(path)
    assert first.status_code == second.status_code == 200
    marker = 'data-testid="steward-guide-answer">'
    first_answer = first.text.split(marker, 1)[1].split("</p>", 1)[0]
    second_answer = second.text.split(marker, 1)[1].split("</p>", 1)[0]
    assert first_answer == second_answer
    assert "Saved guidance." in first.text
    # No call to the model was made on the way to the saved answer.
    assert tripwire.calls == []


def test_the_focused_case_renders_the_same_saved_guide_twice(
    client: TestClient, tripwire: TripwireTransport
) -> None:
    """The case renders the same saved guide twice in hosted mode."""
    queue = client.get("/steward").text
    match = re.search(r'href="(/steward/issues/link/[^\"]+)', queue)
    assert match is not None
    path = match.group(1).replace("&amp;", "&")
    first = client.get(path)
    second = client.get(path)
    assert first.status_code == second.status_code == 200
    marker = 'data-testid="steward-guide-answer">'
    first_answer = first.text.split(marker, 1)[1].split("</p>", 1)[0]
    second_answer = second.text.split(marker, 1)[1].split("</p>", 1)[0]
    assert first_answer == second_answer
    assert "Saved guidance." in first.text
    assert tripwire.calls == []


def test_the_guide_names_only_the_evidence_the_page_shows(client: TestClient) -> None:
    """The guide holds no evidence the page does not show."""
    queue = client.get("/steward").text
    # The queue shows no evidence, so the guide names none.
    assert "Recorded evidence" not in queue
    match = re.search(r'href="(/steward/issues/link/[^\"]+)', queue)
    assert match is not None
    case = client.get(match.group(1).replace("&amp;", "&")).text
    guide_evidence = case.split("<b>Recorded evidence:</b>", 1)[1].split("</p>", 1)[0]
    assert guide_evidence
    for phrase in guide_evidence.split("; "):
        assert phrase in case, phrase
    # The record has no document, so the guide names no evidence there either.
    profile = client.get("/masters/party_cedarline?view=sources").text
    assert "No evidence is recorded for this record." in profile
    assert "Recorded evidence" not in profile


def guide_links(html: str) -> list[str]:
    """Return the links of the rendered guide."""
    guide = html.split('data-testid="steward-guide"', 1)[1].split("</details>", 1)[0]
    return re.findall(r'<a href="([^"]+)"', guide)


@pytest.mark.parametrize("screen", sorted(GUIDE_SCREENS))
def test_every_guide_link_lands_on_a_real_target(client: TestClient, screen: str) -> None:
    """No link of the guide points at a target the page does not have."""
    path = GUIDE_SCREENS[screen]
    html = client.get(path).text
    for href in guide_links(html):
        # A link never points back at the page it is read on.
        assert href != path, href
        if href.startswith("#"):
            assert f'id="{href[1:]}"' in html, href
        else:
            assert client.get(href).status_code == 200, href


def test_the_guide_link_of_the_case_lands_on_a_real_target(client: TestClient) -> None:
    """No link of the guide of the case points at a target it does not have."""
    queue = client.get("/steward").text
    match = re.search(r'href="(/steward/issues/link/[^\"]+)', queue)
    assert match is not None
    path = match.group(1).replace("&amp;", "&")
    html = client.get(path).text
    for href in guide_links(html):
        assert href != path, href
        if href.startswith("#"):
            assert f'id="{href[1:]}"' in html, href
        else:
            assert client.get(href).status_code == 200, href
