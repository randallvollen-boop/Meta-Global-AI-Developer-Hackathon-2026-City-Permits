"""The shared patterns in a real browser: popover, help and the detail drawer."""
# REQUIRES: UX-01, UX-02, UX-03, SEC-01
# The drawer opens in place, traps and returns focus, closes on Esc, can be
# deep-linked, and never covers the toast corner or the Demo controls button.

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from conftest import BrowserServer, assert_no_horizontal_overflow, assert_not_covered

from acme_city.persistence.models import model_run
from acme_city.persistence.session import SessionFactory, transaction

APPLICATION = "app_synth_001"
RUN_ID = "run_ui_patterns_browser"


@pytest.fixture()
def muse_run(server: BrowserServer) -> str:
    factory = SessionFactory(server.settings.database_url)
    try:
        with transaction(factory) as session:
            session.add(
                model_run.ModelRun(
                    id=RUN_ID,
                    correlation_id="corr_ui_patterns_browser",
                    mode="replay",
                    provider="meta",
                    model="muse-spark-test",
                    prompt_version="extraction-prompt-v1",
                    schema_version="extraction-schema-v1",
                    input_refs={"application_id": APPLICATION, "documents": []},
                    output={},
                    validation_result={"checked": ["fields_present"], "issues": []},
                    usage={"input_tokens": 10, "output_tokens": 5},
                    latency_ms=500,
                    started_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
                    actor_id="persona_data_steward",
                )
            )
    finally:
        factory.dispose()
    return RUN_ID


def inside_drawer(page) -> bool:
    return page.evaluate(
        "() => document.getElementById('ui-drawer').contains(document.activeElement)"
    )


def overlaps(a: dict, b: dict) -> bool:
    return not (
        a["x"] + a["width"] <= b["x"]
        or b["x"] + b["width"] <= a["x"]
        or a["y"] + a["height"] <= b["y"]
        or b["y"] + b["height"] <= a["y"]
    )


def test_drawer_opens_traps_focus_and_returns_it(page, server, login, muse_run) -> None:
    login("persona_data_steward")
    page.goto(f"{server.base_url}/permits/{APPLICATION}", wait_until="domcontentloaded")
    drawer = page.locator("#ui-drawer")
    assert drawer.is_hidden()
    # The workspace header now carries a Technical details link first; this test is about the Muse run drawer.
    link = page.locator('[data-detail-kind="muse-run"]').first
    link.focus()
    link.click()
    drawer.wait_for(state="visible")
    assert "detail=muse-run:" in page.url
    assert page.locator('[data-testid="ui-drawer-title"]').inner_text() == "Muse run details"
    assert inside_drawer(page)
    # The page behind stays on screen.
    assert page.locator('[data-testid="muse-mode"]').is_visible()
    for _ in range(8):
        page.keyboard.press("Tab")
        assert inside_drawer(page)
    for _ in range(4):
        page.keyboard.press("Shift+Tab")
        assert inside_drawer(page)
    page.keyboard.press("Escape")
    assert drawer.is_hidden()
    assert "detail=" not in page.url
    assert page.evaluate("() => document.activeElement.getAttribute('data-detail-kind')") == "muse-run"
    # The close button does the same.
    link.click()
    drawer.wait_for(state="visible")
    page.locator('[data-testid="ui-drawer-close"]').click()
    assert drawer.is_hidden()
    assert page.evaluate("() => document.activeElement.getAttribute('data-detail-kind')") == "muse-run"
    assert page.recorded_errors == []


def test_deep_link_opens_the_drawer_and_closes(page, server, login, muse_run) -> None:
    login("persona_data_steward")
    page.goto(
        f"{server.base_url}/permits/{APPLICATION}?detail=muse-run:{muse_run}",
        wait_until="domcontentloaded",
    )
    drawer = page.locator("#ui-drawer")
    assert drawer.is_visible()
    assert muse_run in drawer.inner_text()
    assert inside_drawer(page)
    page.keyboard.press("Escape")
    assert drawer.is_hidden()
    assert "detail=" not in page.url


def test_info_popover_opens_and_esc_returns_focus(page, server, login, muse_run) -> None:
    login("persona_data_steward")
    page.goto(f"{server.base_url}/permits/{APPLICATION}", wait_until="domcontentloaded")
    # The Review tab now opens with other definitions first; this test is about the Muse label popover.
    button = page.locator('[data-testid="ui-info-btn"][data-info-key="muse_provenance"]').first
    pop = page.locator('[data-ui-info]:has([data-info-key="muse_provenance"]) [data-testid="ui-info-pop"]').first
    assert button.get_attribute("aria-expanded") == "false"
    assert pop.is_hidden()
    button.click()
    assert button.get_attribute("aria-expanded") == "true"
    assert pop.is_visible()
    assert "Replay" in pop.inner_text()
    page.keyboard.press("Escape")
    assert button.get_attribute("aria-expanded") == "false"
    assert pop.is_hidden()
    assert page.evaluate("() => document.activeElement.className") == "ui-info-btn"


def test_help_opens_in_the_drawer(page, server, login) -> None:
    login("persona_data_steward")
    page.goto(f"{server.base_url}/rules-fees", wait_until="domcontentloaded")
    page.locator('[data-testid="ui-help"]').click()
    page.locator("#ui-drawer").wait_for(state="visible")
    text = page.locator("#ui-drawer").inner_text().lower()
    for heading in ("What this screen is for", "What you can do here", "What usually happens next"):
        assert heading.lower() in text


@pytest.mark.parametrize("viewport", [(1280, 900), (390, 844)])
def test_drawer_does_not_cover_toast_or_demo_controls(
    page, server, login, muse_run, viewport
) -> None:
    login("persona_data_steward")
    page.emulate_media(reduced_motion="reduce")  # measure the drawer at rest
    page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
    page.goto(
        f"{server.base_url}/permits/{APPLICATION}?detail=muse-run:{muse_run}",
        wait_until="domcontentloaded",
    )
    box = page.locator("#ui-drawer").bounding_box()
    assert box is not None
    if viewport[0] <= 640:
        assert box["x"] <= 1 and box["width"] >= viewport[0] - 1
    else:
        assert 400 <= box["width"] <= 500
    for selector in (".demo-switch > summary", "#toast"):
        other = page.locator(selector).bounding_box()
        assert other is not None, selector
        assert not overlaps(box, other), selector
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )
    assert overflow <= 0


def test_the_audit_event_row_and_its_drawer_fit_a_phone(page, server, login) -> None:
    login("persona_city_administrator")
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{server.base_url}/ops/checks", wait_until="domcontentloaded")
    page.locator('[data-testid="checks-run"]').click()
    page.wait_for_selector('[data-testid="checks-result"]')
    page.goto(f"{server.base_url}/ops/audit", wait_until="domcontentloaded")
    row = page.locator('[data-testid="audit-row"]').first
    assert row.locator('[data-testid="audit-action-label"]').inner_text().strip()
    assert row.locator('[data-testid="audit-outcome-label"]').inner_text().strip()
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator(".demo-switch > summary"))
    assert_not_covered(page, row.locator('[data-detail-kind="audit-event"]'))
    row.locator('[data-detail-kind="audit-event"]').click()
    drawer = page.locator('[data-testid="ui-drawer"]')
    drawer.wait_for(state="visible")
    text = drawer.inner_text()
    assert "Raw action" in text
    assert "Versions" in text
    assert page.recorded_errors == []
