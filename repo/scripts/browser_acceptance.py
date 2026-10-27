#!/usr/bin/env python3
"""Walk the eight screens of a running demonstration in a real browser.

The script talks to a server that already runs on the loopback interface.  It
never starts a server of its own, it never writes to the database directly
and it never records a session cookie or an authorization header.  The
manifest it writes holds the route checks, the viewport checks, the page
errors, the action outcomes and the hashes of the screenshots it captured.

Usage:

    uv run python scripts/browser_acceptance.py --base-url http://127.0.0.1:8266 \
        --output evidence/runs/browser.json
"""
# REQUIRES: UX-01, UX-02, UX-03, UX-04, GOV-04, SEC-01, SEC-02
# The walkthrough visits the eight screens, checks the 390 pixel layout, the
# scoped denials and the persistence of the exercised actions, and writes a
# manifest that carries no credential.

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

#: The eight screens of the demonstration and the persona that may open them.
SCREENS: tuple[tuple[str, str], ...] = (
    ("/queue", "Work queue"),
    ("/applicants", "Applicants"),
    ("/masters", "Properties, businesses and contractors"),
    ("/permits/app_synth_001", "Permit workspace"),
    ("/steward", "Steward review"),
    ("/rules-fees", "Rules and fees"),
    ("/reconciliation", "Reconciliation"),
    ("/governance", "Governance and sources"),
)

#: The viewports the walkthrough checks.
VIEWPORTS: tuple[tuple[str, int, int], ...] = (
    ("mobile", 390, 844),
    ("desktop", 1280, 900),
)

#: The persona that may open the eight screens.
ADMINISTRATOR = "persona_city_administrator"

#: The persona whose scope is checked.
APPLICANT = "persona_applicant"


def sign_in(page: Page, base_url: str, actor_id: str) -> None:
    """Establish a server-held session for one persona."""
    page.goto(f"{base_url}/select", wait_until="domcontentloaded")
    page.locator(f'button[data-persona="{actor_id}"]').click()
    page.wait_for_url(f"{base_url}/queue")


def overflow_of(page: Page) -> int:
    """Return the horizontal overflow of the page in pixels."""
    return int(
        page.evaluate(
            "() => document.documentElement.scrollWidth - window.innerWidth"
        )
    )


def sha256_of(path: Path) -> str:
    """Return the SHA-256 hash of a captured screenshot."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_routes(page: Page, base_url: str, output: Path) -> list[dict[str, Any]]:
    """Visit the eight screens and record what each of them answered."""
    results: list[dict[str, Any]] = []
    for path, title in SCREENS:
        response = page.goto(f"{base_url}{path}", wait_until="domcontentloaded")
        status = response.status if response is not None else 0
        screenshot = output.parent / "screenshots" / (
            f"{path.strip('/').replace('/', '_') or 'root'}.png"
        )
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(screenshot), full_page=True)
        results.append(
            {
                "path": path,
                "title": title,
                "status": status,
                "ok": status == 200,
                "screenshot": str(screenshot),
                "screenshot_sha256": sha256_of(screenshot),
            }
        )
    return results


def check_viewports(page: Page, base_url: str) -> list[dict[str, Any]]:
    """Check every screen at the mobile and the desktop viewport."""
    results: list[dict[str, Any]] = []
    for name, width, height in VIEWPORTS:
        page.set_viewport_size({"width": width, "height": height})
        for path, _title in SCREENS:
            page.goto(f"{base_url}{path}", wait_until="domcontentloaded")
            overflow = overflow_of(page)
            results.append(
                {
                    "viewport": name,
                    "width": width,
                    "path": path,
                    "overflow_px": overflow,
                    "ok": overflow <= 1,
                }
            )
    page.set_viewport_size({"width": 1280, "height": 900})
    return results


def check_scope(
    page: Page, base_url: str, collecting: dict[str, bool]
) -> list[dict[str, Any]]:
    """Check that the scope of a persona reaches the direct links.

    The refusals of this check are expected, so the page errors are not
    recorded while it runs.
    """
    results: list[dict[str, Any]] = []
    sign_in(page, base_url, APPLICANT)
    collecting["value"] = False
    for path, expected in (
        ("/applicants/party_cedarline", 404),
        ("/permits/app_synth_001", 404),
        ("/steward", 403),
        ("/reconciliation", 403),
        ("/governance", 403),
    ):
        response = page.goto(f"{base_url}{path}", wait_until="domcontentloaded")
        status = response.status if response is not None else 0
        results.append(
            {
                "actor_id": APPLICANT,
                "path": path,
                "status": status,
                "expected_status": expected,
                "ok": status == expected,
            }
        )
    collecting["value"] = True
    return results


def check_actions(page: Page, base_url: str) -> list[dict[str, Any]]:
    """Exercise two actions and check that they survive a reload."""
    results: list[dict[str, Any]] = []
    sign_in(page, base_url, "persona_permit_reviewer")
    page.goto(f"{base_url}/permits/app_synth_001", wait_until="domcontentloaded")
    outcome = submit(page, "permit.evaluate", {"application_id": "app_synth_001"})
    page.reload(wait_until="domcontentloaded")
    survived = "Validation finished" in page.locator('[data-testid="feedback-message"]').inner_text()
    results.append(
        {
            "action_id": "permit.evaluate",
            "outcome": outcome,
            "survives_reload": survived,
            "ok": bool(outcome) and survived,
        }
    )
    sign_in(page, base_url, "persona_data_steward")
    page.goto(f"{base_url}/steward", wait_until="domcontentloaded")
    outcome = submit(
        page,
        "registry.propose",
        {
            "source_system_id": "permitting",
            "dataset_key": "applicant_profiles",
            "source_record_id": "PER-AP-0003",
        },
    )
    page.reload(wait_until="domcontentloaded")
    survived = "candidate link" in page.locator('[data-testid="feedback-message"]').inner_text()
    results.append(
        {
            "action_id": "registry.propose",
            "outcome": outcome,
            "survives_reload": survived,
            "ok": bool(outcome) and survived,
        }
    )
    return results


def submit(page: Page, action_id: str, fields: dict[str, str]) -> str:
    """Perform one explicit action of the interface and return its outcome."""
    details = page.locator(f'details[data-action-id="{action_id}"]').first
    form = details.locator("form.action-form")
    if not form.is_visible():
        details.locator("summary").click()
    for name, value in fields.items():
        control = form.locator(f'[name="{name}"]')
        if control.evaluate("element => element.type") == "hidden":
            continue
        control.fill(value)
    with page.expect_response(
        lambda response: "/ui/actions/" in response.url
        and response.request.method == "POST"
    ) as answered:
        form.locator('button[type="submit"]').click()
    payload = answered.value.json()
    page.wait_for_function(
        "(expected) => {"
        " const region = document.querySelector('[data-testid=feedback-message]');"
        " return region !== null && region.textContent.trim() === expected;"
        "}",
        arg=str(payload.get("message", "")).strip(),
    )
    return str(payload.get("message", ""))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Return the parsed command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        required=True,
        help="The loopback URL of a running demonstration, for example http://127.0.0.1:8266.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="The JSON manifest the walkthrough writes.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the walkthrough and write the manifest."""
    args = parse_args(argv)
    base_url = args.base_url.rstrip("/")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    collecting = {"value": True}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--no-sandbox"])
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.on(
            "pageerror",
            lambda error: errors.append(f"pageerror: {error}")
            if collecting["value"]
            else None,
        )
        page.on(
            "console",
            lambda message: errors.append(f"console: {message.text}")
            if message.type == "error" and collecting["value"]
            else None,
        )
        try:
            sign_in(page, base_url, ADMINISTRATOR)
            routes = check_routes(page, base_url, output)
            viewports = check_viewports(page, base_url)
            scope = check_scope(page, base_url, collecting)
            actions = check_actions(page, base_url)
        finally:
            context.close()
            browser.close()

    manifest = {
        "base_url": base_url,
        "screens": [path for path, _title in SCREENS],
        "routes": routes,
        "viewports": viewports,
        "scope": scope,
        "actions": actions,
        "page_errors": errors,
        "summary": {
            "routes_ok": sum(1 for item in routes if item["ok"]),
            "routes_total": len(routes),
            "viewports_ok": sum(1 for item in viewports if item["ok"]),
            "viewports_total": len(viewports),
            "scope_ok": sum(1 for item in scope if item["ok"]),
            "scope_total": len(scope),
            "actions_ok": sum(1 for item in actions if item["ok"]),
            "actions_total": len(actions),
            "page_errors": len(errors),
        },
    }
    manifest["ok"] = (
        manifest["summary"]["routes_ok"] == manifest["summary"]["routes_total"]
        and manifest["summary"]["viewports_ok"] == manifest["summary"]["viewports_total"]
        and manifest["summary"]["scope_ok"] == manifest["summary"]["scope_total"]
        and manifest["summary"]["actions_ok"] == manifest["summary"]["actions_total"]
        and not errors
    )
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    summary = manifest["summary"]
    print(f"manifest: {output}")
    print(
        f"routes {summary['routes_ok']}/{summary['routes_total']}, "
        f"viewports {summary['viewports_ok']}/{summary['viewports_total']}, "
        f"scope {summary['scope_ok']}/{summary['scope_total']}, "
        f"actions {summary['actions_ok']}/{summary['actions_total']}, "
        f"page errors {summary['page_errors']}"
    )
    return 0 if manifest["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
