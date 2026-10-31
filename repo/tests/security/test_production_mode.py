"""Production mode: nothing from the demonstration is reachable, and demo mode is unchanged.

The production tests hit the direct URLs and APIs, not just the hidden buttons.
The demo tests pin what must not change: the four personas, the demo switch and
the persona APIs still work in the default mode.
"""
# REQUIRES: SEC-01, SEC-02
# Production mode mounts no persona selector, no simulator and no replay; demo mode keeps them.

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from acme_city.app import ProductionStartupError, create_app
from acme_city.core.clock import scenario_moment, set_scenario_clock
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction

SECRET = "production-mode-test-secret-value"
PROD_ENV = {"ACME_DEPLOYMENT_MODE": "production", "ACME_SECRET_KEY": SECRET}


def make_settings(tmp_path: Path, name: str, **env: str) -> Settings:
    return Settings.load(
        environ={"ACME_DATABASE_URL": f"sqlite:///{tmp_path / name}", **env},
        key_file=tmp_path / "missing.env",
    )


def seed_demo(settings: Settings) -> None:
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
    finally:
        factory.dispose()


@pytest.fixture()
def prod(tmp_path: Path):
    settings = make_settings(tmp_path, "prod.db", **PROD_ENV)
    initialize_database(settings)
    with TestClient(create_app(settings), base_url="https://testserver") as client:
        yield client


@pytest.fixture()
def demo(tmp_path: Path):
    settings = make_settings(tmp_path, "demo.db", ACME_SECRET_KEY=SECRET)
    initialize_database(settings)
    seed_demo(settings)
    with TestClient(create_app(settings)) as client:
        yield client


# ------------------------------------------------------------ startup refusal


def test_production_refuses_a_database_marked_as_the_demo(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, "marked.db", **PROD_ENV)
    initialize_database(settings)
    seed_demo(settings)
    with pytest.raises(ProductionStartupError, match="fictional demonstration"):
        create_app(settings)


def test_production_starts_against_an_unmarked_database(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, "clean.db", **PROD_ENV)
    initialize_database(settings)
    create_app(settings).state.session_factory.dispose()


# ----------------------------------------------------- direct URLs and APIs


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("GET", "/api/session/actors", {}),
        ("POST", "/api/session/select", {"json": {"actor_id": "persona_permit_reviewer"}}),
        ("POST", "/ui/actor", {"data": {"actor_id": "persona_city_administrator"}}),
        ("POST", "/api/intake/simulate", {"json": {"scenario": "random"}}),
        ("GET", "/api/intake/scenarios", {}),
        ("GET", "/sim/arcgis/rest/services/ACME", {}),
        ("GET", "/sim/arcgis/rest/services/ACME/Parcels/FeatureServer", {}),
        ("POST", "/ui/actions/intake.simulate", {"data": {"scenario": "random"}}),
        ("POST", "/ui/actions/intake.generate", {"data": {"count": "3"}}),
        ("GET", "/docs", {}),
        ("GET", "/openapi.json", {}),
        ("GET", "/lifecycle", {}),
        ("GET", "/walkthrough", {}),
    ],
)
def test_demo_only_endpoints_do_not_exist_in_production(prod, method, path, kwargs) -> None:
    response = prod.request(method, path, follow_redirects=False, **kwargs)
    assert response.status_code in {404, 405}, (path, response.status_code)
    assert "acme_session" not in response.headers.get("set-cookie", "")


def test_no_persona_can_be_selected_so_no_session_exists(prod) -> None:
    prod.post("/api/session/select", json={"actor_id": "persona_permit_reviewer"})
    prod.post("/ui/actor", data={"actor_id": "persona_permit_reviewer"})
    assert prod.get("/api/session").status_code == 401
    assert "acme_session" not in prod.cookies


@pytest.mark.parametrize("path", ["/queue", "/", "/select", "/governance", "/review/queue", "/admin", "/apply"])
def test_staff_and_applicant_routes_say_sign_in_is_not_configured(prod, path) -> None:
    response = prod.get(path, follow_redirects=True)
    assert response.status_code in {503, 404}, (path, response.status_code)
    if path != "/review/queue":
        assert "Sign-in is not configured" in response.text, path
    # No persona picker and no demo switch are rendered, anywhere.
    assert "data-demo-persona" not in response.text
    assert "Demo controls" not in response.text
    assert "persona-list" not in response.text


def test_select_page_is_the_sign_in_not_configured_page(prod) -> None:
    response = prod.get("/select")
    assert response.status_code == 503
    assert "Sign-in is not configured" in response.text
    assert "data-persona=" not in response.text


def test_authenticated_apis_answer_401_with_a_sanitized_envelope(prod) -> None:
    response = prod.get("/api/session")
    assert response.status_code == 401
    assert response.json() == {"code": "authentication_required", "message": "authentication is required"}
    assert prod.post("/api/muse/run", json={"task": "extraction", "application_id": "x"}).status_code == 401
    assert prod.post("/api/intake/records", json={}).status_code in {401, 422}


def test_forged_session_cookie_does_not_authenticate(prod) -> None:
    prod.cookies.set("acme_session", "forged.deadbeef")
    assert prod.get("/api/session").status_code == 401


def test_scenario_clock_is_disabled_in_production(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, "clock.db", ACME_SCENARIO_CLOCK="2026-10-14", **PROD_ENV)
    initialize_database(settings)
    set_scenario_clock(None)
    with TestClient(create_app(settings)):
        assert scenario_moment() is None


# ----------------------------------------------------------- demo unchanged


def test_demo_mode_still_offers_the_five_personas_and_the_switch(demo) -> None:
    actors = demo.get("/api/session/actors").json()["actors"]
    assert {a["label"] for a in actors} == {
        "Applicant",
        "Data Steward",
        "Permit Reviewer",
        "City Administrator",
        "Agent Operator",
    }
    page = demo.get("/select")
    assert page.status_code == 200
    assert "Choose a persona" in page.text
    selected = demo.post("/api/session/select", json={"actor_id": "persona_permit_reviewer"})
    assert selected.status_code == 200
    # The cookie is not Secure by default in demo mode.
    assert "secure" not in selected.headers["set-cookie"].lower()
    queue = demo.get("/queue")
    assert queue.status_code == 200
    assert "Demo controls" in queue.text


def test_demo_mode_still_mounts_the_simulators(demo) -> None:
    demo.post("/api/session/select", json={"actor_id": "persona_city_administrator"})
    assert demo.get("/api/intake/scenarios").status_code == 200
    assert demo.get("/docs").status_code == 200


def test_demo_error_messages_are_unchanged(demo) -> None:
    body = demo.get("/api/session").json()
    assert body["message"] == "no session cookie was presented"


# -------------------------------------------------------------- cookies


def test_cookie_secure_follows_the_setting(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, "cookie.db", ACME_SECRET_KEY=SECRET, ACME_COOKIE_SECURE="true")
    initialize_database(settings)
    seed_demo(settings)
    with TestClient(create_app(settings), base_url="https://testserver") as client:
        response = client.post("/api/session/select", json={"actor_id": "persona_permit_reviewer"})
        assert "secure" in response.headers["set-cookie"].lower()
        assert response.json()["cookie"]["secure"] is True


def test_trusted_proxy_header_is_ignored_unless_enabled(tmp_path: Path) -> None:
    for enabled, expected in (("", "http"), ("true", "https")):
        env = {"ACME_SECRET_KEY": SECRET}
        if enabled:
            env["ACME_TRUST_PROXY_HEADERS"] = enabled
        settings = make_settings(tmp_path, f"proxy{enabled}.db", **env)
        initialize_database(settings)
        app = create_app(settings)

        @app.get("/__scheme")
        def scheme(request: Request) -> dict:
            return {"scheme": request.url.scheme}

        with TestClient(app) as client:
            got = client.get("/__scheme", headers={"X-Forwarded-Proto": "https"}).json()["scheme"]
            assert got == expected


# ------------------------------------------------------- security headers


def test_security_headers_in_demo_mode(demo) -> None:
    response = demo.get("/select")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "same-origin"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "strict-transport-security" not in response.headers


def test_security_headers_in_production_mode(prod) -> None:
    response = prod.get("/select")
    assert response.headers["strict-transport-security"].startswith("max-age=")
    assert response.headers["x-content-type-options"] == "nosniff"


def test_csp_allows_only_local_sources_and_no_inline_script(demo) -> None:
    csp = demo.get("/select").headers["content-security-policy"]
    directives = dict(part.strip().split(" ", 1) for part in csp.split(";"))
    assert directives["script-src"] == "'self'"
    assert directives["style-src"] == "'self'"
    assert directives["object-src"] == "'none'"
    assert "unsafe-inline" not in directives["script-src"]
    assert "http" not in csp


def test_authenticated_html_is_not_cached(demo) -> None:
    demo.post("/api/session/select", json={"actor_id": "persona_permit_reviewer"})
    assert demo.get("/queue").headers["cache-control"] == "no-store"
    assert demo.get("/api/session").headers["cache-control"] == "no-store"
    # Static assets stay cacheable.
    assert demo.get("/ui/static/app.css").headers.get("cache-control") != "no-store"


def test_no_template_carries_an_inline_script_or_handler() -> None:
    """The CSP forbids inline script; keep the templates and static files honest."""
    import re

    root = Path(__file__).resolve().parents[2] / "src" / "acme_city" / "templates"
    inline_script = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>", re.IGNORECASE)
    handler = re.compile(r"\s(on(?:click|change|submit|load|error|input|keydown|keyup))\s*=", re.IGNORECASE)
    for path in root.rglob("*.html"):
        body = path.read_text(encoding="utf-8")
        assert not inline_script.search(body), path
        assert not handler.search(body), path


# -------------------------------------------------------------- readiness


def test_readyz_is_ready_on_a_current_database(demo, prod) -> None:
    for client in (demo, prod):
        response = client.get("/readyz")
        assert response.status_code == 200
        assert response.json()["checks"] == {
            "database_reachable": True,
            "schema_at_head": True,
            "bootstrap_ok": True,
        }


def test_readyz_is_503_for_a_stale_revision(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, "stale.db", ACME_SECRET_KEY=SECRET)
    initialize_database(settings)
    engine = create_engine(settings.database_url)
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = '0012'"))
    engine.dispose()
    with TestClient(create_app(settings)) as client:
        response = client.get("/readyz")
        assert response.status_code == 503
        body = response.json()
        assert body["checks"]["schema_at_head"] is False
        assert body["schema_revision"] == "0012"
        # Liveness is unchanged: it still answers 200.
        assert client.get("/healthz").status_code == 200


def test_readyz_is_503_for_an_uninitialized_database(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, "empty.db", ACME_SECRET_KEY=SECRET)
    with TestClient(create_app(settings)) as client:
        assert client.get("/readyz").status_code == 503


def test_readyz_is_503_in_production_when_the_database_becomes_a_demo(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, "late.db", **PROD_ENV)
    initialize_database(settings)
    with TestClient(create_app(settings)) as client:
        assert client.get("/readyz").status_code == 200
        factory = SessionFactory(settings.database_url)
        with transaction(factory) as session:
            session.add(
                DemoEnvironment(
                    id="demo_environment_local",
                    environment_id=ENVIRONMENT_ID,
                    fictional_demo=True,
                    fixture_version="x",
                    label="late marker",
                )
            )
        factory.dispose()
        response = client.get("/readyz")
        assert response.status_code == 503
        assert response.json()["checks"]["bootstrap_ok"] is False
