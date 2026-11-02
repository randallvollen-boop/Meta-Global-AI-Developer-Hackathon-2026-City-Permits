"""More tools starts open on a desktop and shut on a phone.

The side navigation's More tools group is open when a desktop page loads, and
it still closes. The choice is kept in session storage for the session, so a
later page of the same session stays as the person left it. A phone starts
shut, and its bottom bar keeps its own More. If storage is missing the
desktop default still applies.
"""
# REQUIRES: UX-01, UX-04

from __future__ import annotations

from conftest import BrowserServer

KEY = "acme-nav-more"


def _open(page, test_id: str) -> bool:
    """Return whether the named disclosure is open."""
    return page.locator(f'[data-testid="{test_id}"]').evaluate("element => element.open")


def _choice(page) -> str | None:
    """Return the stored choice, or None when the person has not chosen."""
    return page.evaluate(f"() => sessionStorage.getItem({KEY!r})")


def test_more_tools_starts_open_on_a_desktop_and_remembers_the_choice(
    page, server: BrowserServer, login
) -> None:
    """A desktop shows More tools, a close survives navigation, and so does an open."""
    login("persona_data_steward")
    more = page.locator('.side [data-testid="nav-more"]')
    assert _open(page, "nav-more") is True
    assert more.locator("a").first.is_visible()
    assert _choice(page) is None

    more.locator("summary").click()
    page.wait_for_function(f"() => sessionStorage.getItem({KEY!r}) === 'closed'")
    assert _open(page, "nav-more") is False
    assert more.locator("a").first.is_hidden()

    # A screen that lives under More tools does not force the group open again.
    page.goto(f"{server.base_url}/queue/intake", wait_until="load")
    assert _open(page, "nav-more") is False
    assert _choice(page) == "closed"
    assert page.locator('.side [data-testid="nav-more"] a').first.is_hidden()

    page.goto(f"{server.base_url}/steward", wait_until="load")
    assert _open(page, "nav-more") is False
    assert _choice(page) == "closed"

    page.locator('.side [data-testid="nav-more"] summary').click()
    page.wait_for_function(f"() => sessionStorage.getItem({KEY!r}) === 'open'")
    assert _open(page, "nav-more") is True

    page.goto(f"{server.base_url}/masters", wait_until="load")
    assert _open(page, "nav-more") is True
    assert page.locator('.side [data-testid="nav-more"] a').first.is_visible()
    assert _choice(page) == "open"
    assert page.recorded_errors == []


def test_more_tools_starts_closed_on_a_phone(viewport_390, server: BrowserServer, login) -> None:
    """At 390 pixels both disclosures start shut, and the bar's More still opens."""
    page = viewport_390
    login("persona_data_steward")
    mobile = page.locator('[data-testid="nav-more-mobile"]')
    assert _open(page, "nav-more-mobile") is False
    assert mobile.locator("a").first.is_hidden()
    # The side group is shut too, so a phone load does not leave it open.
    assert _open(page, "nav-more") is False
    # A phone load is not a choice, and it must not close the group on a
    # later desktop page of this session.
    assert _choice(page) is None

    mobile.locator("summary").click()
    assert _open(page, "nav-more-mobile") is True
    assert mobile.locator("a").first.is_visible()
    assert _choice(page) is None
    assert page.recorded_errors == []


def test_more_tools_opens_on_a_desktop_when_storage_is_missing(
    page, server: BrowserServer, login
) -> None:
    """Without session storage the desktop still starts open and a close is not kept."""
    page.add_init_script(
        """
        Storage.prototype.getItem = function () { throw new Error("storage blocked"); };
        Storage.prototype.setItem = function () { throw new Error("storage blocked"); };
        """
    )
    login("persona_data_steward")
    assert _open(page, "nav-more") is True
    page.locator('.side [data-testid="nav-more"] summary').click()
    assert _open(page, "nav-more") is False

    page.goto(f"{server.base_url}/masters", wait_until="load")
    assert _open(page, "nav-more") is True
    assert page.recorded_errors == []
