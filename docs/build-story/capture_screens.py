"""Capture the running ACME City Permits screens for the build story.

Usage (from repo/): uv run python ../docs/build-story/capture_screens.py <base_url> <out_dir> [light|dark]
Logs in as each of the four personas through the real selector and saves one
full-page PNG per screen that persona can open. Fictional ACME data only.
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

SCREENS = {
    "persona_permit_reviewer": ["/queue", "/permits/app_synth_001"],
    "persona_data_steward": ["/steward", "/applicants", "/masters"],
    "persona_city_administrator": ["/reconciliation", "/governance", "/rules-fees"],
    "persona_applicant": ["/queue"],
}


def main() -> int:
    base_url, out_dir = sys.argv[1].rstrip("/"), Path(sys.argv[2])
    scheme = sys.argv[3] if len(sys.argv) > 3 else "light"
    out_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for persona, paths in SCREENS.items():
            context = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme=scheme)
            page = context.new_page()
            page.goto(f"{base_url}/select")
            page.click(f'[data-persona="{persona}"]')
            page.wait_for_load_state("networkidle")
            for path in paths:
                response = page.goto(f"{base_url}{path}", wait_until="networkidle")
                status = response.status if response else 0
                name = f"{persona.removeprefix('persona_')}{path.replace('/', '_')}-{scheme}.png"
                page.screenshot(path=str(out_dir / name), full_page=True)
                print(f"{status} {name}")
            context.close()
        page = browser.new_page(viewport={"width": 1440, "height": 900}, color_scheme=scheme)
        page.goto(f"{base_url}/select")
        page.screenshot(path=str(out_dir / f"select-{scheme}.png"), full_page=True)
        print(f"200 select-{scheme}.png")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
