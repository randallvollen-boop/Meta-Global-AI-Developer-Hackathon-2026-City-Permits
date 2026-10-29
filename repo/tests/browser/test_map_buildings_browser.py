"""The town map draws a top down building on every zoned lot, all at one size."""

from __future__ import annotations

from conftest import BrowserServer


def test_every_lot_shows_its_building_at_one_size(page, server: BrowserServer, login) -> None:
    login("persona_permit_reviewer")
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{server.base_url}/map", wait_until="networkidle")
    buildings = page.locator('[data-testid="town-map"] image.gis-building')
    assert buildings.count() == page.locator('[data-testid="town-map"] .gis-parcel').count()
    sizes = set(buildings.evaluate_all("els => els.map(e => e.getAttribute('width'))"))
    assert sizes == {"50.0"}
    loaded = page.evaluate(
        """async () => Promise.all([...new Set([...document.querySelectorAll('image.gis-building')]
              .map(e => e.getAttribute('href')))].map(src => new Promise(ok => {
                const img = new Image(); img.onload = () => ok(img.naturalWidth); img.onerror = () => ok(0); img.src = src; })))"""
    )
    assert loaded and all(width == 256 for width in loaded)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert page.recorded_errors == []
