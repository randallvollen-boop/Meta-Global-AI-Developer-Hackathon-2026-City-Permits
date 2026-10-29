"""The persona selector offers the tour video without playing it and fits a phone."""

from __future__ import annotations

from conftest import BrowserServer


def test_demo_video_waits_for_play_shows_its_poster_and_fits_390px(page, server: BrowserServer) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{server.base_url}/select", wait_until="networkidle")
    video = page.locator('[data-testid="demo-video-player"]')
    assert video.count() == 1
    assert video.evaluate("v => v.controls && !v.autoplay && v.preload === 'none' && v.paused")
    assert page.locator('[data-testid="demo-video"] figcaption').inner_text().strip()
    poster = video.get_attribute("poster")
    assert page.evaluate(
        """src => new Promise(done => { const img = new Image();
             img.onload = () => done(img.naturalWidth > 0); img.onerror = () => done(false); img.src = src; })""",
        poster,
    )
    source = page.request.head(f"{server.base_url}/ui/static/video/demo-video.mp4")
    assert source.ok and source.headers["content-type"] == "video/mp4"
    box = video.bounding_box()
    assert box is not None and box["x"] >= 0 and box["x"] + box["width"] <= 390
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert page.locator('[data-testid="persona-card"]').count() == 5
    assert page.recorded_errors == []
