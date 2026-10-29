"""The public community pages in a real browser: the list states at 390 and 1280 px."""
# REQUIRES: UX-01, UX-02

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import BrowserServer, assert_no_horizontal_overflow, assert_not_covered

#: The source directory of this worktree.  The persona list is resolved from
#: it, so the checks below cover this branch and not the copy of the package
#: that the test process happens to import.
REPO_SRC = Path(__file__).resolve().parents[2] / "src"

#: The link that opens one public record from a result card.
CARD_LINK = '[data-testid="community-result-table"] .community-card-link'

#: The list states a resident can reach from the community page.
LIST_STATES = (
    "/city/community",
    "/city/community?q=Acme",
    "/city/community?q=ab",
    "/city/community?q=zzqqq",
)

#: The visible task control or the last content element of each list state.
#: A state without a list names the control the resident has to use next:
#: the search button when the search is too short, the notice itself when
#: nothing matched.  Every state names one element, so the fixed mobile
#: navigation and the demo switch are checked against all of them.
LIST_STATE_TARGETS: dict[str, str] = {
    "/city/community": '[data-testid="community-recent"] .community-card-link',
    "/city/community?q=Acme": '[data-testid="community-result-table"] .community-card-link',
    "/city/community?q=ab": '[data-testid="community-search"]',
    "/city/community?q=zzqqq": '[data-testid="community-no-results"]',
}


def test_the_list_states_fit_and_stay_clear_at_both_widths(browser, server: BrowserServer) -> None:
    for width, height in ((1280, 900), (390, 844)):
        context = browser.new_context(viewport={"width": width, "height": height})
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            for path in LIST_STATES:
                page.goto(f"{server.base_url}{path}", wait_until="networkidle")
                assert_no_horizontal_overflow(page)
                if width == 390:
                    # the fixed layers may not cover the control or the content
                    assert_not_covered(page, page.locator(LIST_STATE_TARGETS[path]).last)
        finally:
            context.close()
        assert errors == [], (width, errors)


def test_the_search_panel_and_the_first_card_stay_clear_of_the_demo_switch(
    viewport_390, server: BrowserServer
) -> None:
    page = viewport_390
    page.goto(f"{server.base_url}/city/community?q=Acme", wait_until="networkidle")
    assert_not_covered(page, page.locator('[data-testid="community-search"]'))
    assert_not_covered(
        page, page.locator('[data-testid="community-result-table"] .community-card-link').first
    )


def test_the_results_are_cards_that_lead_with_the_address(browser, server: BrowserServer) -> None:
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    try:
        page.goto(f"{server.base_url}/city/community?q=Acme", wait_until="networkidle")
        assert page.locator('[data-testid="community-result-table"] table').count() == 0
        cards = page.locator('[data-testid="community-result-table"] .community-card')
        assert cards.count() >= 1
        first = cards.first
        assert first.locator(".community-card-address").inner_text().strip()
        assert first.locator(".community-card-type").inner_text().strip()
        assert first.locator(".community-card-link").count() == 1
        href = first.locator(".community-card-link").get_attribute("href")
        assert href.startswith("/city/community/permit/"), href
    finally:
        context.close()


def test_the_overview_fits_a_phone_and_keeps_the_district_table(viewport_390, server: BrowserServer) -> None:
    page = viewport_390
    page.goto(f"{server.base_url}/city/community", wait_until="networkidle")
    assert_no_horizontal_overflow(page)
    overview = page.locator('[data-testid="community-map-section"]')
    assert overview.count() == 1
    assert page.locator('[data-testid="community-district-table"]').is_visible()
    assert page.locator('[data-testid="community-legend"]').is_visible()
    assert page.locator('[data-testid="community-overview-submit"]').is_visible()
    assert_not_covered(page, page.locator('[data-testid="community-overview-submit"]'))


def test_the_overview_filter_narrows_the_district_table(browser, server: BrowserServer) -> None:
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    try:
        page.goto(f"{server.base_url}/city/community", wait_until="networkidle")
        values = [
            option.get_attribute("value")
            for option in page.locator('[data-testid="community-type"] option').all()
        ]
        chosen = next(value for value in values if value)
        page.select_option('[data-testid="community-type"]', chosen)
        page.locator('[data-testid="community-overview-submit"]').click()
        page.wait_for_load_state("networkidle")
        assert f"type={chosen}" in page.url
        assert page.locator('[data-testid="community-district-table"] tr[data-district]').count() >= 1
        # the search stayed where it was
        assert page.locator('[data-testid="community-q"]').input_value() == ""
    finally:
        context.close()


def test_the_record_page_fits_a_phone_and_explains_the_status(
    viewport_390, server: BrowserServer
) -> None:
    page = viewport_390
    page.goto(f"{server.base_url}/city/community?q=Acme", wait_until="networkidle")
    href = page.locator(
        '[data-testid="community-result-table"] .community-card-link'
    ).first.get_attribute("href")
    page.goto(f"{server.base_url}{href}", wait_until="networkidle")
    assert_no_horizontal_overflow(page)
    assert page.locator('[data-testid="community-record"]').is_visible()
    assert page.locator('[data-testid="community-status-explanation"]').is_visible()
    assert page.locator("h1.community-record-address").is_visible()
    assert_not_covered(page, page.locator('[data-testid="community-back"]'))


def test_the_record_page_returns_to_the_same_search(browser, server: BrowserServer) -> None:
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    try:
        page.goto(f"{server.base_url}/city/community?q=Acme", wait_until="networkidle")
        page.locator(
            '[data-testid="community-result-table"] .community-card-link'
        ).first.click()
        page.wait_for_load_state("networkidle")
        assert "/city/community/permit/" in page.url
        page.locator('[data-testid="community-back"]').click()
        page.wait_for_load_state("networkidle")
        assert "q=Acme" in page.url
        assert page.locator('[data-testid="community-q"]').input_value() == "Acme"
    finally:
        context.close()


def test_the_search_and_return_sequence_works_on_a_phone(viewport_390, server: BrowserServer) -> None:
    page = viewport_390
    page.goto(f"{server.base_url}/city/community", wait_until="networkidle")
    page.fill('[data-testid="community-q"]', "Acme")
    page.locator('[data-testid="community-search"]').click()
    page.wait_for_load_state("networkidle")
    assert_no_horizontal_overflow(page)
    assert page.locator('[data-testid="community-q"]').input_value() == "Acme"
    link = page.locator('[data-testid="community-result-table"] .community-card-link').first
    href = link.get_attribute("href")
    assert "q=Acme" in href
    link.click()
    page.wait_for_load_state("networkidle")
    assert_no_horizontal_overflow(page)
    page.locator('[data-testid="community-back"]').click()
    page.wait_for_load_state("networkidle")
    assert_no_horizontal_overflow(page)
    assert "q=Acme" in page.url
    assert page.locator('[data-testid="community-q"]').input_value() == "Acme"
    assert_not_covered(page, page.locator('[data-testid="community-search"]'))


def _tab_to(page, selector: str, limit: int = 60) -> None:
    """Move the keyboard focus to the first element the selector names."""
    locator = page.locator(selector).first
    for _ in range(limit):
        if locator.evaluate("el => el === document.activeElement"):
            return
        page.keyboard.press("Tab")
    raise AssertionError(f"the keyboard never reached {selector}")


def _focus_is_visible(page) -> bool:
    """Return whether the focused element draws a visible focus ring."""
    return bool(
        page.evaluate(
            "() => {"
            " const el = document.activeElement;"
            " if (!el || el === document.body) return false;"
            " const style = getComputedStyle(el);"
            " return style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) > 0;"
            "}"
        )
    )


@pytest.mark.parametrize("viewport", [(390, 844), (1280, 900)])
def test_the_search_card_and_back_flow_fits_at_both_widths(
    browser, server: BrowserServer, viewport: tuple[int, int]
) -> None:
    """The whole resident flow fits and stays clear at a phone and a desktop width."""
    width, height = viewport
    context = browser.new_context(viewport={"width": width, "height": height})
    page = context.new_page()
    try:
        page.goto(f"{server.base_url}/city/community", wait_until="networkidle")
        assert_no_horizontal_overflow(page)

        page.fill('[data-testid="community-q"]', "Acme")
        page.locator('[data-testid="community-search"]').click()
        page.wait_for_load_state("networkidle")
        assert "q=Acme" in page.url
        assert page.locator('[data-testid="community-result-total"]').is_visible()
        assert page.locator(CARD_LINK).count() >= 1
        assert_no_horizontal_overflow(page)
        assert_not_covered(page, page.locator('[data-testid="community-search"]'))
        assert_not_covered(page, page.locator(CARD_LINK).first)

        page.locator(CARD_LINK).first.click()
        page.wait_for_load_state("networkidle")
        assert "/city/community/permit/" in page.url
        assert page.locator('[data-testid="community-record"]').is_visible()
        assert_no_horizontal_overflow(page)
        assert_not_covered(page, page.locator('[data-testid="community-back"]'))

        page.locator('[data-testid="community-back"]').click()
        page.wait_for_load_state("networkidle")
        assert "q=Acme" in page.url
        assert page.locator('[data-testid="community-q"]').input_value() == "Acme"
        assert_no_horizontal_overflow(page)
    finally:
        context.close()


def test_the_search_and_the_record_are_reachable_with_the_keyboard(
    browser, server: BrowserServer
) -> None:
    """A resident who never uses the mouse can search, open a record and go back."""
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    try:
        page.goto(f"{server.base_url}/city/community", wait_until="networkidle")
        _tab_to(page, '[data-testid="community-q"]')
        assert _focus_is_visible(page), "the search field shows where the keyboard is"
        page.keyboard.type("Acme")
        with page.expect_navigation(wait_until="networkidle"):
            page.keyboard.press("Enter")
        assert "q=Acme" in page.url
        assert page.locator('[data-testid="community-result-total"]').is_visible()

        _tab_to(page, CARD_LINK)
        assert _focus_is_visible(page), "the record link shows where the keyboard is"
        with page.expect_navigation(wait_until="networkidle"):
            page.keyboard.press("Enter")
        assert "/city/community/permit/" in page.url
        assert page.locator('[data-testid="community-record"]').is_visible()

        _tab_to(page, '[data-testid="community-back"]')
        with page.expect_navigation(wait_until="networkidle"):
            page.keyboard.press("Enter")
        assert "q=Acme" in page.url
        assert page.locator('[data-testid="community-q"]').input_value() == "Acme"
    finally:
        context.close()


def test_the_search_works_without_javascript(browser, server: BrowserServer) -> None:
    """The resident flow is plain HTML: it works with scripting switched off."""
    context = browser.new_context(
        viewport={"width": 390, "height": 844}, java_script_enabled=False
    )
    page = context.new_page()
    try:
        page.goto(f"{server.base_url}/city/community", wait_until="networkidle")
        page.fill('[data-testid="community-q"]', "Acme")
        page.locator('[data-testid="community-search"]').click()
        page.wait_for_load_state("networkidle")
        assert "q=Acme" in page.url
        assert page.locator('[data-testid="community-result-total"]').is_visible()
        assert page.locator(CARD_LINK).count() >= 1
        assert_no_horizontal_overflow(page)
    finally:
        context.close()


def test_a_long_search_wraps_instead_of_widening_the_page(
    browser, server: BrowserServer
) -> None:
    """A long search text is echoed in full and wraps instead of widening the page."""
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    try:
        long_query = "Acme" * 20
        page.goto(f"{server.base_url}/city/community?q={long_query}", wait_until="networkidle")
        count = page.locator('[data-testid="community-result-total"]')
        assert long_query in count.inner_text()
        assert_no_horizontal_overflow(page)
        lines = count.evaluate(
            "el => {"
            " const style = getComputedStyle(el);"
            " const line = parseFloat(style.lineHeight) || parseFloat(style.fontSize) * 1.2;"
            " return el.getBoundingClientRect().height / line;"
            "}"
        )
        assert lines > 1, "the long search text wraps onto more than one line"
    finally:
        context.close()


#: A probe that asks this worktree which personas the demo switch offers.
#: It runs in its own process with the source of this worktree first on the
#: path, and it seeds a throwaway database, so the answer comes from the
#: same ``persona_options`` the application uses.  The probe refuses to
#: answer when it imports any other tree.
PERSONA_PROBE = """
import json
import os
import sys
import tempfile
from pathlib import Path

source = Path(os.environ["ACME_SOURCE"]).resolve()
sys.path.insert(0, str(source))

import acme_city
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)
from acme_city.ui.view_models import PERSONA_PROFILES, persona_options

if not Path(acme_city.__file__).resolve().is_relative_to(source):
    raise SystemExit(f"the probe imported {acme_city.__file__} instead of {source}")

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{root / 'personas.db'}",
            "ACME_SECRET_KEY": "browser-acceptance-secret-value",
        },
        key_file=root / "missing.env",
    )
    initialize_database(settings)
    bundle = FixtureBundle.load()
    factory = SessionFactory(settings.database_url)
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
    with transaction(factory) as session:
        reset_demo(session, bundle, confirmation="--confirm-fictional-demo")
    with transaction(factory) as session:
        options = persona_options(session)

print(
    "PERSONAS "
    + json.dumps(
        {
            "options": [
                {"actor_id": option["actor_id"], "label": option["label"]}
                for option in options
            ],
            "profile_labels": sorted(PERSONA_PROFILES),
        }
    )
)
"""


def _worktree_personas() -> tuple[tuple[tuple[str, str], ...], tuple[str, ...]]:
    """Return the personas this worktree offers and its persona profile labels.

    The list comes from the source of this worktree, so the parametrization
    follows the code that renders the demo switch instead of a copy of it.
    """
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "-c", PERSONA_PROBE],
        cwd=str(repo_root),
        env={
            **os.environ,
            "PYTHONPATH": str(REPO_SRC),
            "ACME_SOURCE": str(REPO_SRC),
        },
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    marked = [
        line for line in result.stdout.splitlines() if line.startswith("PERSONAS ")
    ]
    assert len(marked) == 1, result.stdout
    payload = json.loads(marked[0][len("PERSONAS ") :])
    personas = tuple(
        (option["actor_id"], option["label"]) for option in payload["options"]
    )
    return personas, tuple(payload["profile_labels"])


#: The personas the demo switch of this worktree offers, in selector order.
DEMO_PERSONAS, PERSONA_PROFILE_LABELS = _worktree_personas()

#: The community pages the provider probe renders.
COMMUNITY_PAGES = (
    "/city/community",
    "/city/community?q=Acme",
    "/city/community/permit/ACME-2026-000731",
)

#: A probe that renders the community pages with a transport that fails every
#: call.  It runs in its own process, with the source of this worktree on the
#: path, so the check covers the code that is shipped and not the copy the
#: test process happens to import.
#:
#: The probe closes both dispatch methods of the provider clients, so an
#: attempted call raises instead of returning quietly.  Without that, a
#: missing credential would let the check pass without a call ever reaching
#: the transport.  The probe then checks that its own guards really raise,
#: so a guard that no longer covers the dispatch fails the probe instead of
#: passing it.
PROVIDER_PROBE = """
import json
import os
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

calls = []


def refuse(self, request):
    calls.append(str(request.url))
    raise httpx.ConnectError("the community pages must never call the provider")


httpx.HTTPTransport.handle_request = refuse

from acme_city.muse.client import MuseClient
from acme_city.muse.image_client import MuseImageClient


def refuse_dispatch(self, *args, **kwargs):
    raise AssertionError("the community pages must never call the model provider")


MuseClient.create_response = refuse_dispatch
MuseImageClient.generate = refuse_dispatch

# The guards have to be able to fail, otherwise the probe says nothing.
for owner, name in ((MuseClient, "create_response"), (MuseImageClient, "generate")):
    guard = getattr(owner, name)
    if guard is not refuse_dispatch:
        raise SystemExit(f"the {name} guard is not in place, so the probe is vacuous")
    try:
        guard(None, "payload")
    except AssertionError:
        continue
    raise SystemExit(f"the {name} guard does not raise, so the probe is vacuous")

from acme_city.app import create_app
from acme_city.core.config import Settings

settings = Settings.load(
    environ={
        "ACME_DATABASE_URL": os.environ["ACME_DATABASE_URL"],
        "ACME_SECRET_KEY": os.environ["ACME_SECRET_KEY"],
        # The provider is enabled and carries an inert test only credential,
        # so a call that reached the client would reach the raising transport
        # as well.  The value is not a secret and never leaves this process.
        "META_API_KEY": "probe-only-not-a-real-credential",
        "ACME_MUSE_PROVIDER_ENABLED": "true",
    },
    key_file=Path(os.environ["ACME_KEY_FILE"]),
)
app = create_app(settings)
paths = json.loads(os.environ["ACME_COMMUNITY_PAGES"])
with TestClient(app) as client:
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, (path, response.status_code)
        assert "Muse" not in response.text, path
assert calls == [], calls
print("no provider call")
"""


def test_the_demo_switch_offers_the_five_personas(browser, server: BrowserServer) -> None:
    """The switch names the five personas and keeps its own label."""
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    try:
        page.goto(f"{server.base_url}/city/community", wait_until="networkidle")
        switch = page.locator('[data-testid="demo-switch"]')
        assert switch.count() == 1
        summary = switch.locator("summary")
        # the visible label stays as it is, and the control still says what it does
        assert summary.inner_text().strip() == "Demo controls"
        assert "switch user" in (summary.get_attribute("aria-label") or "")
        buttons = switch.locator("button[data-demo-persona]")
        assert len(DEMO_PERSONAS) == 5
        assert buttons.count() == len(DEMO_PERSONAS)
        labels = buttons.evaluate_all(
            "buttons => buttons.map(b => b.childNodes[0].textContent.trim())"
        )
        assert labels == [label for _, label in DEMO_PERSONAS]
        assert sorted(labels) == sorted(PERSONA_PROFILE_LABELS)
        # the closed switch covers nothing of the resident page
        assert_not_covered(page, page.locator('[data-testid="community-q"]'))
    finally:
        context.close()


@pytest.mark.parametrize("actor_id,label", DEMO_PERSONAS)
def test_the_demo_switch_works_at_390_pixels(
    browser, server: BrowserServer, actor_id: str, label: str
) -> None:
    """Every persona can be chosen from the switch, and the public pages still work."""
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    try:
        page.goto(f"{server.base_url}/city/community", wait_until="networkidle")
        switch = page.locator('[data-testid="demo-switch"]')
        # the closed switch covers nothing of the resident page
        assert_not_covered(page, page.locator('[data-testid="community-q"]'))

        switch.locator("summary").click()
        assert switch.locator(".demo-switch-panel").is_visible()
        with page.expect_navigation(wait_until="networkidle"):
            switch.locator(f'button[data-demo-persona="{actor_id}"]').click()

        # the chosen persona acts on the public pages too
        page.goto(f"{server.base_url}/city/community?q=Acme", wait_until="networkidle")
        switch = page.locator('[data-testid="demo-switch"]')
        switch.locator("summary").click()
        current = switch.locator(".demo-switch-current").inner_text().strip()
        assert current == f"Now acting as {label}"
        switch.locator("summary").click()

        assert page.locator('[data-testid="community-result-total"]').is_visible()
        assert page.locator(CARD_LINK).count() >= 1
        assert_no_horizontal_overflow(page)
        assert_not_covered(page, page.locator('[data-testid="community-search"]'))
    finally:
        context.close()


def test_the_community_pages_never_call_the_model_provider(
    server: BrowserServer, tmp_path: Path
) -> None:
    """A closed dispatch and a raising transport prove the pages make no model call.

    The probe closes both dispatch methods of the provider clients and
    carries an enabled provider with an inert test only credential, so a
    call on a community page raises instead of failing quietly.  The
    transport stub catches anything that reaches the network.
    """
    repo_root = Path(__file__).resolve().parents[2]
    environment = {
        **os.environ,
        "PYTHONPATH": str(repo_root / "src"),
        "ACME_DATABASE_URL": server.settings.database_url,
        "ACME_SECRET_KEY": "browser-acceptance-secret-value",
        "ACME_KEY_FILE": str(tmp_path / "missing.env"),
        "ACME_COMMUNITY_PAGES": json.dumps(COMMUNITY_PAGES),
    }
    result = subprocess.run(
        [sys.executable, "-c", PROVIDER_PROBE],
        cwd=str(repo_root),
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no provider call" in result.stdout


def test_the_browser_never_leaves_the_loopback_origin(
    browser, server: BrowserServer
) -> None:
    """The resident flow asks the local server for everything, including any model."""
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    outside: list[str] = []

    def guard(route) -> None:
        url = route.request.url
        if url.startswith(server.base_url) or url.startswith(("data:", "blob:")):
            route.continue_()
            return
        outside.append(url)
        route.abort()

    page.route("**/*", guard)
    try:
        page.goto(f"{server.base_url}/city/community", wait_until="networkidle")
        page.fill('[data-testid="community-q"]', "Acme")
        page.locator('[data-testid="community-search"]').click()
        page.wait_for_load_state("networkidle")
        page.locator(CARD_LINK).first.click()
        page.wait_for_load_state("networkidle")
        assert outside == []
    finally:
        context.close()
