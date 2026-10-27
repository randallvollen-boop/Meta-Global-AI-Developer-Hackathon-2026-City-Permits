"""The isolated browser server of the acceptance walkthrough.

The fixture owns its own database, its own loopback server and its own
process identifier.  It never touches another running service: the database
lives in a temporary directory, the port is chosen by the operating system and
the process is stopped when the fixture ends.
"""
# REQUIRES: UX-01, UX-02, UX-03, UX-04, GOV-04, EDIT-01, EDIT-02, EDIT-03, SEC-01, SEC-02
# The browser walks the eight screens of an isolated demonstration server: the
# server, its database and its process identifier belong to the fixture and
# are cleaned up with it.

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import finance
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)

#: The repository root of the demonstration.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: The bootstrap of the isolated server.  The server reads the UI router from
#: the package and binds to the loopback interface only.
BOOTSTRAP = """
import os

import uvicorn

from acme_city.app import create_app
from acme_city.ui.router import router as ui_router

app = create_app()
app.include_router(ui_router)
uvicorn.run(
    app,
    host="127.0.0.1",
    port=int(os.environ["ACME_PORT"]),
    log_level="warning",
    access_log=False,
)
"""


@dataclass(frozen=True)
class BrowserServer:
    """The isolated server the browser walks."""

    base_url: str
    pid: int
    pid_file: Path
    database: Path
    settings: Settings

    def terminate(self) -> None:
        """Stop the server and remove the files it owned."""
        try:
            os.kill(self.pid, 15)
        except ProcessLookupError:
            return
        for _ in range(50):
            try:
                os.kill(self.pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.1)
        try:
            os.kill(self.pid, 9)
        except ProcessLookupError:
            return


def free_port() -> int:
    """Return a free loopback port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def wait_for(base_url: str, process: subprocess.Popen[bytes], timeout: float = 30.0) -> None:
    """Wait until the isolated server answers its health check."""
    import urllib.error
    import urllib.request

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("the isolated server stopped before it became ready")
        try:
            with urllib.request.urlopen(f"{base_url}/healthz", timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            time.sleep(0.2)
    raise RuntimeError("the isolated server did not become ready in time")


@pytest.fixture()
def server(tmp_path: Path) -> BrowserServer:
    """Start an isolated server with its own seeded database."""
    database = tmp_path / "browser-demo.db"
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{database}",
            "ACME_SECRET_KEY": "browser-acceptance-secret-value",
        },
        key_file=tmp_path / "missing.env",
    )
    initialize_database(settings)
    bundle = FixtureBundle.load()
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            session.add(
                DemoEnvironment(
                    id="demo_environment_local",
                    environment_id=ENVIRONMENT_ID,
                    fictional_demo=True,
                    fixture_version=bundle.fixture_version,
                    label="local fictional demonstration",
                )
            )
        with transaction(factory) as session:
            reset_demo(session, bundle, confirmation="--confirm-fictional-demo")
        with transaction(factory) as session:
            _approve_payer_link(session)
    finally:
        factory.dispose()

    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    pid_file = tmp_path / "browser-demo.pid"
    environment = {
        **os.environ,
        "ACME_DATABASE_URL": settings.database_url,
        "ACME_SECRET_KEY": "browser-acceptance-secret-value",
        "ACME_KEY_FILE": str(tmp_path / "missing.env"),
        "ACME_PORT": str(port),
        "PYTHONPATH": str(REPO_ROOT / "src"),
    }
    process = subprocess.Popen(
        [sys.executable, "-c", BOOTSTRAP],
        cwd=str(REPO_ROOT),
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pid_file.write_text(str(process.pid), encoding="utf-8")
    handle = BrowserServer(
        base_url=base_url,
        pid=process.pid,
        pid_file=pid_file,
        database=database,
        settings=settings,
    )
    try:
        wait_for(base_url, process)
        yield handle
    finally:
        handle.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive cleanup
            process.kill()
        pid_file.unlink(missing_ok=True)


def _approve_payer_link(session) -> None:
    """Record the approved finance account link the primary chain needs.

    The registry records an approved account link on the account row with the
    state ``linked``, while the finance service accepts the state
    ``approved`` or a recorded link row.  No service writes that row yet, so
    the browser fixture arranges it exactly as the acceptance tests do.  The
    gap is reported to the parent as a missing service interface.
    """
    session.add(
        finance.FinanceAccountLink(
            id="faclink_legacy",
            account_id="facct_cedarline_legacy",
            party_id="party_cedarline",
            link_status="approved",
            decided_by_actor_id="persona_data_steward",
            decided_at=datetime(2026, 9, 14, 15, 20, tzinfo=UTC),
        )
    )
    session.flush()


@pytest.fixture()
def browser():
    """Return a Chromium browser for the walkthrough."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(args=["--no-sandbox"])
        try:
            yield instance
        finally:
            instance.close()


@pytest.fixture()
def page(browser):
    """Return a page with a 1280 pixel viewport and its recorded errors."""
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
    page.on(
        "console",
        lambda message: errors.append(f"console: {message.text}")
        if message.type == "error"
        else None,
    )
    page.recorded_errors = errors  # type: ignore[attr-defined]
    try:
        yield page
    finally:
        context.close()


@pytest.fixture()
def login(page, server: BrowserServer):
    """Return a callable that signs the browser in as one persona."""

    def sign_in(actor_id: str) -> None:
        page.goto(f"{server.base_url}/select", wait_until="domcontentloaded")
        page.locator(f'button[data-persona="{actor_id}"]').click()
        page.wait_for_url(f"{server.base_url}/queue")

    return sign_in


@pytest.fixture()
def submit_action(page, server: BrowserServer):
    """Return a callable that performs one explicit action of the interface."""

    def perform(action_id: str, fields: dict[str, str] | None = None) -> str:
        details = page.locator(f'details[data-action-id="{action_id}"]').first
        form = details.locator("form.action-form")
        if not form.is_visible():
            details.locator("summary").click()
        for name, value in (fields or {}).items():
            control = form.locator(f'[name="{name}"]')
            if control.evaluate("element => element.type") == "hidden":
                continue
            if control.evaluate("element => element.tagName") == "SELECT":
                control.select_option(value)
            else:
                control.fill(value)
        with page.expect_response(
            lambda response: "/ui/actions/" in response.url
            and response.request.method == "POST"
        ) as answered:
            form.locator('button[type="submit"]').click()
        response = answered.value
        payload = response.json()
        page.wait_for_function(
            "(expected) => {"
            " const region = document.querySelector('[data-testid=feedback-message]');"
            " return region !== null && region.textContent.trim() === expected;"
            "}",
            arg=str(payload.get("message", "")).strip(),
        )
        return str(payload.get("message", ""))

    return perform


@pytest.fixture()
def screenshot_dir(tmp_path: Path) -> Path:
    """Return the directory that holds the captured screenshots."""
    target = tmp_path / "screenshots"
    target.mkdir(parents=True, exist_ok=True)
    return target


def write_manifest(path: Path, payload: dict[str, object]) -> None:
    """Write one browser manifest as JSON."""
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
