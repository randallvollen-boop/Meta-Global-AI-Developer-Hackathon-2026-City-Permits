"""The what-if screens in the browser: the demo path, narrow fit, the guarded run button.

The walkthrough follows the video: a suggested what-if, a run on a synthetic
year, the results, the briefing and its downloads.  Every page must fit 390
pixels, the identity drawer must open and close with the keyboard, and a
what-if with an unsupported change must show why Run is unavailable.
"""
# REQUIRES: UX-01, UX-02, UX-03, PER-04

from __future__ import annotations

from conftest import BrowserServer


def overflow(page) -> int:
    return page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")


def open_fence_run(page, server: BrowserServer):
    page.goto(f"{server.base_url}/policy/scenarios", wait_until="domcontentloaded")
    page.locator('[data-testid="policy-suggestion"]').first.click()
    page.wait_for_url("**/policy/scenarios/polscen_*")
    editor = page.url.split("?")[0]
    page.locator('[data-testid="policy-run-count"], #run-count').first.fill("200")
    page.locator('[data-testid="policy-run-submit"]').click()
    page.wait_for_url("**/policy/runs/polrun_*")
    return editor, page.url


def test_the_demo_path_fits_a_phone_and_a_desktop(page, server: BrowserServer, login) -> None:
    login("persona_city_administrator")
    for width, height in ((390, 844), (1280, 900)):
        page.set_viewport_size({"width": width, "height": height})
        editor, run = open_fence_run(page, server)
        briefing = f"{run}/briefing"
        for url in ("/policy/scenarios", editor.replace(server.base_url, ""), run.replace(server.base_url, ""),
                    briefing.replace(server.base_url, "")):
            page.goto(f"{server.base_url}{url}", wait_until="domcontentloaded")
            assert overflow(page) <= 1, (width, url, overflow(page))
            assert page.locator('[data-testid="evidence-panel"]').count() == 1, url
    assert page.recorded_errors == []


def test_the_results_screen_shows_the_labels_and_the_drawer_works_by_keyboard(
    page, server: BrowserServer, login
) -> None:
    login("persona_city_administrator")
    page.set_viewport_size({"width": 1280, "height": 900})
    _editor, run = open_fence_run(page, server)
    assert page.locator('[data-testid="policy-population-label"]').inner_text().startswith("Synthetic year (sample data)")
    assert page.locator('[data-testid="synthetic-badge"]').count() >= 1
    link = page.locator('[data-detail-kind="policy-run"]').first
    link.focus()
    page.keyboard.press("Enter")
    drawer = page.locator('[data-testid="ui-drawer"]')
    drawer.wait_for(state="visible")
    assert "Content hash" in drawer.inner_text()
    page.keyboard.press("Escape")
    drawer.wait_for(state="hidden")
    page.goto(f"{run}/briefing", wait_until="domcontentloaded")
    assert page.locator('[data-testid="policy-briefing-synthetic"]').count() == 1
    assert page.locator('[data-testid="policy-download-html"]').get_attribute("href").endswith("format=html")
    assert page.recorded_errors == []


def test_run_is_guarded_with_its_reason_beside_it(page, server: BrowserServer, login) -> None:
    login("persona_city_administrator")
    page.set_viewport_size({"width": 1280, "height": 900})
    editor, _run = open_fence_run(page, server)
    page.goto(editor, wait_until="domcontentloaded")
    page.locator('[data-testid="policy-unsupported-kinds"] summary').click()
    page.locator('[data-testid="policy-add-unsupported"][data-kind="no_permit_required"]').click()
    page.wait_for_load_state("domcontentloaded")
    assert page.locator('[data-testid="policy-run-submit"]').is_disabled()
    reason = page.locator('[data-testid="policy-run-reason"]')
    assert reason.is_visible()
    assert "not supported in this release" in reason.inner_text()
    assert "Not supported in this release" in page.locator('[data-testid="policy-unsupported"]').inner_text()
