"""The More tools group of the navigation in a browser.

The page is rendered in process with a dummy navigation profile against the
database of the isolated server, and the browser loads that page from the
server's own origin so the real stylesheets apply.  The group must fit inside
390 pixels, open or closed.
"""
# REQUIRES: UX-01, UX-04
# The navigation stays inside a 390 pixel viewport and every entry is reached.

from __future__ import annotations

from fastapi.testclient import TestClient

from acme_city.app import create_app
from acme_city.ui import view_models
from acme_city.ui.router import router as ui_router
from conftest import BrowserServer

OVERFLOW = "() => document.documentElement.scrollWidth - window.innerWidth"

#: Whether the centre of an element is the element itself or inside it, so no
#: fixed layer such as the demo switch or the mobile bar covers it.
#: Replace with the shared not-covered helper once tests/browser has one.
NOT_COVERED = """(element) => {
  const box = element.getBoundingClientRect();
  const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
  return hit !== null && (hit === element || element.contains(hit));
}"""


def _secondary_last_two(items: list[dict]) -> list[dict]:
    items = [dict(item) for item in items]
    for item in items[-2:]:
        item["group"] = "secondary"
    return items


def _queue_with_more_tools(server: BrowserServer, actor_id: str) -> str:
    """Return the /queue page of one persona with two entries under More tools."""
    app = create_app(server.settings)
    app.include_router(ui_router)
    # The profile of the lane is put back afterwards: a lane may register one
    # for this persona, and the dummy profile is only a probe of the group.
    saved = view_models.NAV_PROFILES.get(actor_id)
    view_models.NAV_PROFILES[actor_id] = _secondary_last_two
    try:
        with TestClient(app) as client:
            response = client.post("/api/session/select", json={"actor_id": actor_id})
            assert response.status_code == 200, response.text
            page = client.get("/queue")
            assert page.status_code == 200
            return page.text
    finally:
        if saved is None:
            view_models.NAV_PROFILES.pop(actor_id, None)
        else:
            view_models.NAV_PROFILES[actor_id] = saved


def test_the_more_tools_group_fits_at_390_pixels(page, server: BrowserServer) -> None:
    html = _queue_with_more_tools(server, "persona_city_administrator")
    assert "More tools" in html
    probe = f"{server.base_url}/nav-more-probe"
    page.route(probe, lambda route: route.fulfill(status=200, content_type="text/html", body=html))

    page.goto(probe, wait_until="load")
    desktop = page.locator('.side [data-testid="nav-more"]')
    assert desktop.is_visible()
    desktop.locator("summary").click()
    assert desktop.locator("a").count() == 2
    assert desktop.locator("a").first.is_visible()
    assert page.evaluate(OVERFLOW) <= 1

    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(probe, wait_until="load")
    assert page.evaluate(OVERFLOW) <= 1
    mobile = page.locator('.mobile-nav [data-testid="nav-more-mobile"]')
    assert mobile.is_visible()
    summary = mobile.locator("summary")
    # The bar scrolls sideways, so the last entry is brought into view first.
    summary.scroll_into_view_if_needed()
    assert summary.evaluate(NOT_COVERED), "the More tools summary is covered"
    summary.click()
    links = mobile.locator(".nav-more-panel a")
    assert links.count() == 2
    for index in range(links.count()):
        box = links.nth(index).bounding_box()
        assert box is not None
        assert box["x"] >= 0 and box["x"] + box["width"] <= 390, box
        assert links.nth(index).evaluate(NOT_COVERED), f"More tools link {index} is covered"
    panel = mobile.locator(".nav-more-panel").bounding_box()
    assert panel is not None
    assert panel["x"] >= 0 and panel["x"] + panel["width"] <= 390, panel
    assert panel["y"] >= 0, panel
    assert page.evaluate(OVERFLOW) <= 1
    assert page.recorded_errors == []
