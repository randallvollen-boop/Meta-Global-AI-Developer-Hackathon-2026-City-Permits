"""The public community pages in a real browser: the list states at 390 and 1280 px."""
# REQUIRES: UX-01, UX-02

from __future__ import annotations

import pytest

from conftest import BrowserServer, assert_no_horizontal_overflow, assert_not_covered

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
