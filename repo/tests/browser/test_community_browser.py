"""The public community pages in a real browser: the list states at 390 and 1280 px."""
# REQUIRES: UX-01, UX-02

from __future__ import annotations

from conftest import BrowserServer, assert_no_horizontal_overflow, assert_not_covered

#: The list states a resident can reach from the community page.
LIST_STATES = (
    "/city/community",
    "/city/community?q=Acme",
    "/city/community?q=ab",
    "/city/community?q=zzqqq",
)


def test_the_list_states_have_no_horizontal_overflow(browser, server: BrowserServer) -> None:
    for width, height in ((1280, 900), (390, 844)):
        context = browser.new_context(viewport={"width": width, "height": height})
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            for path in LIST_STATES:
                page.goto(f"{server.base_url}{path}", wait_until="networkidle")
                assert_no_horizontal_overflow(page)
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
