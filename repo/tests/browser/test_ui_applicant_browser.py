"""The applicant screens in a real browser: layout at 1280 and 390 px, the choice, the toasts."""
# REQUIRES: UX-01, UX-02, PORTAL-02

from __future__ import annotations

from conftest import BrowserServer

SCREENS = (
    "/city/",
    "/city/permits",
    "/apply",
    "/apply/deck_fence",
    "/apply/track",
    "/apply/track?ref=SYN-APP-005",
    "/apply/help/panel",
)


def _rect(page, selector: str) -> dict:
    return page.evaluate(
        "(s) => { const r = document.querySelector(s).getBoundingClientRect();"
        " return {l: r.left, t: r.top, r: r.right, b: r.bottom}; }",
        selector,
    )


def _overlap(a: dict, b: dict) -> bool:
    return not (a["r"] <= b["l"] or b["r"] <= a["l"] or a["b"] <= b["t"] or b["b"] <= a["t"])


def _sign_in(page, server: BrowserServer) -> None:
    page.goto(f"{server.base_url}/select", wait_until="domcontentloaded")
    page.locator('button[data-persona="persona_applicant"]').click()
    page.wait_for_url(f"{server.base_url}/city/")


def test_no_horizontal_scroll_and_demo_controls_stay_clear_at_both_widths(browser, server: BrowserServer) -> None:
    for width, height in ((1280, 900), (390, 844)):
        context = browser.new_context(viewport={"width": width, "height": height})
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            _sign_in(page, server)
            for path in SCREENS:
                page.goto(f"{server.base_url}{path}", wait_until="networkidle")
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (width, path)
                demo = _rect(page, ".demo-switch > summary")
                assert demo["l"] >= 0 and demo["b"] <= height, (width, path)
                assert demo["l"] < width / 2 and demo["t"] > height / 2, (width, path, demo)
        finally:
            context.close()
        assert errors == [], (width, errors)


def test_a_toast_is_top_right_under_the_header_and_clear_of_demo_controls(browser, server: BrowserServer) -> None:
    for width, height in ((1280, 900), (390, 844)):
        context = browser.new_context(viewport={"width": width, "height": height})
        page = context.new_page()
        try:
            _sign_in(page, server)
            page.goto(f"{server.base_url}/apply/track?tab=active&saved=DRAFT-TEST", wait_until="networkidle")
            toast = _rect(page, ".city-toast")
            header = _rect(page, ".city-header")
            demo = _rect(page, ".demo-switch > summary")
            assert not _overlap(toast, demo), (width, toast, demo)
            assert toast["t"] >= header["b"] - 1, (width, toast, header)
            assert toast["r"] > width / 2 and toast["r"] <= width, (width, toast)
            page.locator(".demo-switch > summary").click()
            panel = _rect(page, ".demo-switch-panel")
            assert panel["b"] <= demo["t"] and panel["l"] >= 0 and panel["r"] <= width
        finally:
            context.close()


def test_the_deck_or_fence_choice_swaps_the_question_groups_and_submits(page, server: BrowserServer, login) -> None:
    login("persona_applicant")
    page.goto(f"{server.base_url}/apply/deck_fence", wait_until="networkidle")
    fence = page.locator('[data-when-group="fence"]')
    deck = page.locator('[data-when-group="deck"]')
    assert fence.is_visible() and not deck.is_visible()
    page.get_by_label("Deck", exact=True).check()
    assert deck.is_visible() and not fence.is_visible()
    page.get_by_label("Fence", exact=True).check()
    assert fence.is_visible() and not deck.is_visible()
    # a chosen file with a bad type is named as a problem straight away
    page.set_input_files("#file-site_plan", {"name": "x.exe", "mimeType": "application/octet-stream", "buffer": b"MZ"})
    assert "not accepted" in page.locator('[data-js-problem]').inner_text()
    page.set_input_files("#file-site_plan", {"name": "sketch.txt", "mimeType": "text/plain", "buffer": b"sketch"})
    assert "sketch.txt" in page.locator('[data-doc-chosen]').first.inner_text()
    page.get_by_label("Deck", exact=True).check()
    page.fill("#f-applicant_email", "t.aldous@example.invalid")
    page.fill("#f-address_text", "400 Lantren Row")
    page.fill("#f-deck_height_ft", "3")
    page.fill("#f-deck_setback_ft", "10")
    page.fill("#f-project_description", "Rear deck")
    page.set_input_files("#file-material_spec", {"name": "spec.txt", "mimeType": "text/plain", "buffer": b"cedar"})
    page.check("#f-certification_accepted")
    page.locator('[data-testid="submit-application"]').click()
    page.wait_for_url(lambda url: "/apply/submitted/" in url)
    assert page.locator('[data-testid="submitted-title"]').inner_text() == "Application received"
    assert page.locator('[data-testid="download-copy"]').count() == 1
    page.goto(f"{server.base_url}/apply/track", wait_until="networkidle")
    assert page.locator('[data-testid="permit-tabs"]').count() == 1
    assert page.recorded_errors == []
