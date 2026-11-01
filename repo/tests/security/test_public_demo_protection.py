"""Public-demo protection: rate limits, client address, request size, notice.

The hosted demonstration lets anyone act as any persona, so the service limits
each client address.  These tests pin every limit, the way the client address is
found behind a proxy, the bounded request size, the demonstration notice, and
that the four personas and the user switch keep working.
"""
# REQUIRES: SEC-01, SEC-02

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.core.protection import (
    TokenBucketLimiter,
    classify,
    resolve_client_ip,
)
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction

SECRET = "public-demo-protection-test-secret"
REPO = Path(__file__).resolve().parents[2]
PERSONAS = [
    "persona_applicant",
    "persona_data_steward",
    "persona_permit_reviewer",
    "persona_city_administrator",
]


def make_settings(tmp_path: Path, **env: str) -> Settings:
    return Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'demo.db'}",
            "ACME_SECRET_KEY": SECRET,
            **env,
        },
        key_file=tmp_path / "missing.env",
    )


def seed(settings: Settings) -> None:
    bundle = FixtureBundle.load()
    initialize_database(settings)
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
def make_client(tmp_path: Path):
    clients: list[TestClient] = []

    def build(client_address: tuple[str, int] = ("203.0.113.10", 50000), **env: str) -> TestClient:
        settings = make_settings(tmp_path, **env)
        if not (tmp_path / "demo.db").exists():
            seed(settings)
        client = TestClient(create_app(settings), client=client_address)
        client.__enter__()
        clients.append(client)
        return client

    yield build
    for client in clients:
        client.__exit__(None, None, None)


def statuses(client: TestClient, count: int, method: str, path: str, **kwargs) -> list[int]:
    return [client.request(method, path, follow_redirects=False, **kwargs).status_code for _ in range(count)]


# --------------------------------------------------------------- defaults


def test_every_limit_is_off_by_default(make_client) -> None:
    client = make_client()
    assert set(statuses(client, 40, "GET", "/select")) == {200}
    assert 429 not in statuses(client, 40, "POST", "/ui/actor", data={"actor_id": PERSONAS[0]})


def test_settings_default_to_off_and_parse_from_the_environment(tmp_path: Path) -> None:
    default = make_settings(tmp_path)
    assert (
        default.rate_limit_all_per_minute,
        default.rate_limit_write_per_minute,
        default.rate_limit_session_per_minute,
        default.rate_limit_upload_per_minute,
    ) == (0, 0, 0, 0)
    assert default.public_demo is False and default.max_request_bytes == 32 * 1024 * 1024
    tuned = make_settings(
        tmp_path,
        ACME_RATE_LIMIT_ALL_PER_MINUTE="300",
        ACME_RATE_LIMIT_WRITE_PER_MINUTE="60",
        ACME_RATE_LIMIT_SESSION_PER_MINUTE="20",
        ACME_RATE_LIMIT_UPLOAD_PER_MINUTE="10",
        ACME_TRUSTED_PROXY_HOPS="1",
        ACME_PUBLIC_DEMO="1",
    )
    assert (
        tuned.rate_limit_all_per_minute,
        tuned.rate_limit_write_per_minute,
        tuned.rate_limit_session_per_minute,
        tuned.rate_limit_upload_per_minute,
        tuned.trusted_proxy_hops,
        tuned.public_demo,
    ) == (300, 60, 20, 10, 1, True)
    with pytest.raises(ValueError):
        make_settings(tmp_path, ACME_RATE_LIMIT_ALL_PER_MINUTE="-1")


# ------------------------------------------------------------ token bucket


def test_token_bucket_spends_then_refills() -> None:
    now = [0.0]
    limiter = TokenBucketLimiter(6, clock=lambda: now[0])  # one token every 10 seconds
    for _ in range(6):
        assert limiter.retry_after("a") == 0
        limiter.take("a")
    assert limiter.retry_after("a") == pytest.approx(10.0)
    assert limiter.retry_after("b") == 0
    now[0] = 10.0
    assert limiter.retry_after("a") == 0
    limiter.take("a")
    assert limiter.retry_after("a") > 0
    now[0] = 1000.0
    assert limiter.retry_after("a") == 0  # refill is capped at the burst size


def test_classification_of_requests() -> None:
    assert classify("GET", "/queue", "") == ["all"]
    assert classify("POST", "/ui/x", "application/x-www-form-urlencoded") == ["all", "write"]
    assert classify("POST", "/ui/actor", "") == ["all", "write", "session"]
    assert classify("POST", "/api/session/select", "application/json") == ["all", "write", "session"]
    assert classify("DELETE", "/api/session", "") == ["all", "write", "session"]
    assert classify("POST", "/apply/x", "multipart/form-data; boundary=x") == ["all", "write", "upload"]
    for exempt in ("/readyz", "/healthz", "/ui/static/app.css"):
        assert classify("GET", exempt, "") == []


def test_the_form_background_check_counts_as_a_read() -> None:
    # The applicant form checks itself after every pause in typing and the
    # server writes nothing, so the check is a read: it must not spend the
    # upload allowance that the real submission needs.
    assert classify("POST", "/apply/fence/check", "multipart/form-data; boundary=x") == ["all"]
    assert classify("POST", "/apply/deck_fence/check", "multipart/form-data; boundary=x") == ["all"]
    assert classify("POST", "/apply/fence/check/", "multipart/form-data; boundary=x") == ["all"]
    submitted = classify("POST", "/apply/fence", "multipart/form-data; boundary=x")
    assert "upload" in submitted and "write" in submitted
    # Only the check path is a read; a real submission and every near miss
    # still count as a change and as an upload.
    assert classify("POST", "/apply/fence/checklist", "multipart/form-data; boundary=x") == [
        "all", "write", "upload",
    ]
    assert classify("POST", "/apply/fence/check/extra", "multipart/form-data; boundary=x") == [
        "all", "write", "upload",
    ]


# ------------------------------------------------------- the four limits


def test_all_requests_limit_answers_429_with_the_application_page(make_client) -> None:
    client = make_client(ACME_RATE_LIMIT_ALL_PER_MINUTE="5")
    assert statuses(client, 5, "GET", "/select") == [200] * 5
    blocked = client.get("/select")
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) >= 1
    assert 'data-testid="rate-limited"' in blocked.text and "Too many requests" in blocked.text
    assert "/ui/static/app.css" in blocked.text
    assert blocked.headers["content-security-policy"]  # the security headers still apply
    assert re.search(r"Wait \d+ seconds?", blocked.text)


def test_api_callers_get_a_json_429(make_client) -> None:
    client = make_client(ACME_RATE_LIMIT_ALL_PER_MINUTE="2")
    statuses(client, 2, "GET", "/api/session/actors")
    blocked = client.get("/api/session/actors")
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "rate_limited"
    assert "retry-after" in blocked.headers


def test_health_checks_and_static_files_are_never_counted(make_client) -> None:
    client = make_client(ACME_RATE_LIMIT_ALL_PER_MINUTE="3")
    assert set(statuses(client, 30, "GET", "/readyz")) == {200}
    assert set(statuses(client, 30, "GET", "/healthz")) == {200}
    assert set(statuses(client, 30, "GET", "/ui/static/app.css")) == {200}
    assert statuses(client, 4, "GET", "/select") == [200, 200, 200, 429]


def test_state_changing_limit_leaves_reads_alone(make_client) -> None:
    client = make_client(ACME_RATE_LIMIT_WRITE_PER_MINUTE="3")
    results = statuses(client, 4, "POST", "/ui/actions/no.such.action", data={})
    assert 429 not in results[:3] and results[3] == 429
    assert set(statuses(client, 20, "GET", "/select")) == {200}


def test_session_switch_limit_counts_only_switches(make_client) -> None:
    client = make_client(ACME_RATE_LIMIT_SESSION_PER_MINUTE="3")
    first = statuses(client, 3, "POST", "/ui/actor", data={"actor_id": PERSONAS[1]})
    assert 429 not in first
    assert client.post("/ui/actor", data={"actor_id": PERSONAS[2]}, follow_redirects=False).status_code == 429
    select = client.post("/api/session/select", json={"actor_id": PERSONAS[2]})
    assert select.status_code == 429 and select.json()["code"] == "rate_limited"
    # Other changes and reads are not session switches.
    assert 429 not in statuses(client, 5, "POST", "/ui/actions/no.such.action", data={})
    assert client.get("/select").status_code == 200


def test_upload_limit_counts_only_multipart_requests(make_client) -> None:
    client = make_client(ACME_RATE_LIMIT_UPLOAD_PER_MINUTE="2")
    files = {"file": ("sketch.txt", b"fictional site sketch", "text/plain")}
    path = "/api/applications/app_none/documents"
    first = statuses(client, 2, "POST", path, data={"document_type": "site_plan"}, files=files)
    assert 429 not in first
    blocked = client.post(path, data={"document_type": "site_plan"}, files=files)
    assert blocked.status_code == 429 and blocked.json()["code"] == "rate_limited"
    assert 429 not in statuses(client, 5, "POST", "/api/session/select", json={"actor_id": PERSONAS[0]})


def test_the_form_background_check_does_not_spend_the_upload_allowance(make_client) -> None:
    client = make_client(ACME_RATE_LIMIT_UPLOAD_PER_MINUTE="2")
    client.post("/ui/actor", data={"actor_id": PERSONAS[0]}, follow_redirects=False)
    files = {"file__site_plan": ("sketch.txt", b"fictional site sketch", "text/plain")}
    # Three background checks, as the browser sends them while the person types.
    checks = [
        client.post("/apply/deck_fence/check", data={"intent": "update"}, files=files).status_code
        for _ in range(3)
    ]
    assert 429 not in checks
    assert checks == [200, 200, 200], checks
    # The real submission still has its upload to spend, twice over.
    first = client.post("/apply/deck_fence", data={"intent": "submit"}, files=files)
    assert first.status_code != 429
    second = client.post("/apply/deck_fence", data={"intent": "submit"}, files=files)
    assert second.status_code != 429


def test_the_form_background_check_still_counts_against_the_request_limit(make_client) -> None:
    client = make_client(ACME_RATE_LIMIT_ALL_PER_MINUTE="2")
    files = {"file__site_plan": ("sketch.txt", b"fictional site sketch", "text/plain")}
    path = "/apply/deck_fence/check"
    assert client.post(path, data={"intent": "update"}, files=files).status_code != 429
    assert client.post(path, data={"intent": "update"}, files=files).status_code == 429


def test_a_refused_request_spends_no_tokens_from_the_other_limits(make_client) -> None:
    client = make_client(ACME_RATE_LIMIT_ALL_PER_MINUTE="10", ACME_RATE_LIMIT_SESSION_PER_MINUTE="1")
    statuses(client, 1, "POST", "/ui/actor", data={"actor_id": PERSONAS[0]})
    assert statuses(client, 3, "POST", "/ui/actor", data={"actor_id": PERSONAS[0]}) == [429] * 3
    assert statuses(client, 8, "GET", "/select") == [200] * 8  # 9 of 10 left after the first POST


def test_limits_are_per_client_address(make_client) -> None:
    one = make_client(("198.51.100.1", 1), ACME_RATE_LIMIT_ALL_PER_MINUTE="2")
    assert statuses(one, 3, "GET", "/select")[-1] == 429
    two = TestClient(one.app, client=("198.51.100.2", 1))
    assert two.get("/select").status_code == 200


# ------------------------------------------------- client address handling


def scope(peer: str | None, *forwarded: str) -> dict:
    return {
        "type": "http",
        "client": (peer, 1) if peer else None,
        "headers": [(b"x-forwarded-for", value.encode()) for value in forwarded],
    }


def test_forwarded_for_is_ignored_unless_the_proxy_is_trusted() -> None:
    assert resolve_client_ip(scope("10.0.0.5", "8.8.4.4")) == "10.0.0.5"
    assert resolve_client_ip(scope(None)) == "unknown"


def test_right_most_untrusted_hop_is_the_client() -> None:
    trusted = {"trust_proxy_headers": True}
    # The proxy appended the real address on the right; the left side is the client's claim.
    assert resolve_client_ip(scope("10.0.0.5", "6.6.6.6, 8.8.4.4"), **trusted) == "8.8.4.4"
    assert resolve_client_ip(scope("10.0.0.5", "6.6.6.6", "8.8.4.4"), **trusted) == "8.8.4.4"
    # Private and loopback hops are infrastructure and are skipped.
    assert resolve_client_ip(scope("10.0.0.5", "8.8.4.4, 10.1.2.3, 127.0.0.1"), **trusted) == "8.8.4.4"
    # A known extra proxy on the right (a CDN) is skipped by count.
    chain = "8.8.4.4, 9.9.9.9"
    assert resolve_client_ip(scope("10.0.0.5", chain), trust_proxy_headers=True, trusted_hops=1) == "8.8.4.4"
    assert resolve_client_ip(scope("10.0.0.5", chain), **trusted) == "9.9.9.9"


def test_unusable_forwarded_for_falls_back_to_the_peer() -> None:
    trusted = {"trust_proxy_headers": True}
    assert resolve_client_ip(scope("10.0.0.5"), **trusted) == "10.0.0.5"
    assert resolve_client_ip(scope("10.0.0.5", "not-an-address"), **trusted) == "10.0.0.5"
    assert resolve_client_ip(scope("10.0.0.5", "10.9.9.9"), **trusted) == "10.0.0.5"
    assert resolve_client_ip(scope("10.0.0.5", "8.8.4.4, garbage"), **trusted) == "10.0.0.5"
    assert resolve_client_ip(scope("10.0.0.5", "8.8.4.4"), trust_proxy_headers=True, trusted_hops=5) == "10.0.0.5"


def test_a_client_cannot_dodge_the_limit_by_forging_forwarded_for(make_client) -> None:
    # Behind the proxy, the peer is the proxy and the proxy appends the real address.
    client = make_client(("10.0.0.5", 1), ACME_TRUST_PROXY_HEADERS="1", ACME_RATE_LIMIT_ALL_PER_MINUTE="3")
    for forged in ("1.1.1.1", "2.2.2.2", "3.3.3.3"):
        client.get("/select", headers={"X-Forwarded-For": f"{forged}, 8.8.4.4"})
    blocked = client.get("/select", headers={"X-Forwarded-For": "4.4.4.4, 8.8.4.4"})
    assert blocked.status_code == 429
    other = client.get("/select", headers={"X-Forwarded-For": "4.4.4.4, 8.8.8.8"})
    assert other.status_code == 200


def test_without_trust_forwarded_for_changes_nothing(make_client) -> None:
    client = make_client(("203.0.113.50", 1), ACME_RATE_LIMIT_ALL_PER_MINUTE="2")
    for forged in ("1.1.1.1", "2.2.2.2"):
        client.get("/select", headers={"X-Forwarded-For": forged})
    assert client.get("/select", headers={"X-Forwarded-For": "3.3.3.3"}).status_code == 429


# ---------------------------------------------------------- request size


def test_declared_oversized_body_is_refused_with_413(make_client) -> None:
    client = make_client(ACME_MAX_REQUEST_BYTES="1000")
    response = client.post("/ui/actions/no.such.action", content=b"x" * 2000)
    assert response.status_code == 413
    assert response.json()["code"] == "request_too_large"


def test_streamed_oversized_body_is_cut_off_with_413(make_client) -> None:
    client = make_client(ACME_MAX_REQUEST_BYTES="1000")

    def chunks():
        for _ in range(10):
            yield b"y" * 300

    response = client.post("/api/session/select", content=chunks())
    assert response.status_code == 413


def test_a_body_inside_the_limit_passes(make_client) -> None:
    client = make_client(ACME_MAX_REQUEST_BYTES="1000")
    response = client.post("/api/session/select", json={"actor_id": PERSONAS[0]})
    assert response.status_code == 200


def test_zero_switches_the_size_limit_off(make_client) -> None:
    client = make_client(ACME_MAX_REQUEST_BYTES="0")
    assert client.post("/ui/actions/no.such.action", content=b"x" * 100_000).status_code != 413


# --------------------------------------------- personas, notice, the switch


def test_four_personas_and_the_switch_work_with_every_limit_on(make_client) -> None:
    client = make_client(
        ACME_TRUST_PROXY_HEADERS="1",
        ACME_RATE_LIMIT_ALL_PER_MINUTE="300",
        ACME_RATE_LIMIT_WRITE_PER_MINUTE="60",
        ACME_RATE_LIMIT_SESSION_PER_MINUTE="20",
        ACME_RATE_LIMIT_UPLOAD_PER_MINUTE="10",
        ACME_PUBLIC_DEMO="1",
    )
    listed = client.get("/api/session/actors").json()
    actors = {item["actor_id"] for item in (listed if isinstance(listed, list) else listed.get("actors", listed))}
    assert set(PERSONAS) <= actors
    page = client.get("/select")
    assert page.status_code == 200 and "persona-list" in page.text
    for actor_id in PERSONAS:
        switched = client.post("/ui/actor", data={"actor_id": actor_id}, follow_redirects=False)
        assert switched.status_code in {200, 303}, actor_id
        assert client.get("/api/session").json()["actor_id"] == actor_id


def test_public_demo_notice_shows_on_chooser_and_city_home_when_on(make_client) -> None:
    client = make_client(ACME_PUBLIC_DEMO="1")
    for path in ("/select", "/city/"):
        body = client.get(path).text
        assert 'data-testid="public-demo-notice"' in body, path
        # One line, once (city frame, S2).
        assert body.count('data-testid="public-demo-notice"') == 1, path
        assert "Fictional data. Resets nightly." in body
        assert "—" not in body.split('data-testid="public-demo-notice"')[1][:300]


def test_public_demo_notice_is_absent_by_default(make_client) -> None:
    client = make_client()
    for path in ("/select", "/city/"):
        assert "public-demo-notice" not in client.get(path).text, path


# ------------------------------------------------------------- entrypoint


@pytest.fixture()
def entrypoint():
    spec = importlib.util.spec_from_file_location("acme_entrypoint", REPO / "docker" / "entrypoint.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_entrypoint_port_prefers_port_then_acme_bind_port_then_8000(entrypoint) -> None:
    assert entrypoint.listen_port({"PORT": "10000", "ACME_BIND_PORT": "9000"}) == "10000"
    assert entrypoint.listen_port({"ACME_BIND_PORT": "9000"}) == "9000"
    assert entrypoint.listen_port({"PORT": " ", "ACME_BIND_PORT": ""}) == "8000"
    assert entrypoint.listen_port({}) == "8000"


def test_entrypoint_seed_is_opt_in(entrypoint) -> None:
    assert entrypoint.seed_requested({"ACME_DEMO_SEED_ON_START": "1"})
    assert entrypoint.seed_requested({"ACME_DEMO_SEED_ON_START": "true"})
    assert not entrypoint.seed_requested({"ACME_DEMO_SEED_ON_START": "0"})
    assert not entrypoint.seed_requested({})


def test_entrypoint_seed_steps_match_the_local_demo(entrypoint) -> None:
    steps = entrypoint.seed_commands("sqlite:////app/var/x.db", "18266")
    names = [Path(step[1]).name for step in steps]
    assert names == ["prepare_user_test.py", "load_synthetic_year.py", "load_steward_demo.py"]
    assert steps[0][steps[0].index("--mode") + 1] == "ready-for-review"
    assert steps[1][steps[1].index("--seed") + 1] == "20261028"
    assert steps[1][steps[1].index("--count") + 1] == "600"
    assert "--confirm-fictional-demo" in steps[1] and "--confirm-fictional-demo" in steps[2]


def test_entrypoint_seed_runs_in_order_with_a_safe_environment(entrypoint, monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    monkeypatch.setattr(entrypoint, "SCRIPTS", tmp_path / "scripts")
    monkeypatch.setattr(entrypoint, "APP_ROOT", tmp_path)
    calls: list[tuple[list[str], dict]] = []

    class Done:
        returncode = 0

    monkeypatch.setattr(entrypoint.subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw["env"])) or Done())
    stale = tmp_path / "stale.db"
    stale.write_text("old")
    env = {
        "ACME_DATABASE_URL": f"sqlite:///{stale}",
        "ACME_DEPLOYMENT_MODE": "demo",
        "META_API_KEY": "must-not-reach-the-seed",
        "ACME_COOKIE_SECURE": "1",
        "ACME_RATE_LIMIT_WRITE_PER_MINUTE": "60",
        "ACME_MUSE_PROVIDER_ENABLED": "0",
    }
    assert entrypoint.seed_demo(env) == 0
    assert [Path(cmd[1]).name for cmd, _ in calls] == [
        "prepare_user_test.py", "load_synthetic_year.py", "load_steward_demo.py",
    ]
    seen = calls[0][1]
    assert "META_API_KEY" not in seen
    assert seen["ACME_COOKIE_SECURE"] == "0" and seen["ACME_RATE_LIMIT_WRITE_PER_MINUTE"] == "0"
    assert seen["ACME_SCENARIO_CLOCK"] == "auto"
    assert not stale.exists()  # each start rebuilds the database from nothing


def test_entrypoint_seed_stops_at_the_first_failure(entrypoint, monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    monkeypatch.setattr(entrypoint, "SCRIPTS", tmp_path / "scripts")
    calls: list[list[str]] = []

    class Failed:
        returncode = 7

    monkeypatch.setattr(entrypoint.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or Failed())
    monkeypatch.setattr(entrypoint, "clear_database", lambda database: None)
    assert entrypoint.seed_demo({}) == 7
    assert len(calls) == 1


def test_entrypoint_refuses_to_seed_in_production_or_without_scripts(entrypoint, monkeypatch, tmp_path: Path) -> None:
    assert entrypoint.seed_demo({"ACME_DEPLOYMENT_MODE": "production"}) == 2
    monkeypatch.setattr(entrypoint, "SCRIPTS", tmp_path / "absent")
    assert entrypoint.seed_demo({"ACME_DEPLOYMENT_MODE": "demo"}) == 2


# ------------------------------------------------------ render blueprint


BLUEPRINT = (REPO.parent / "render.yaml").read_text(encoding="utf-8")


def test_blueprint_declares_the_demo_service_without_secret_values() -> None:
    for expected in (
        "type: web",
        "runtime: docker",
        "dockerfilePath: ./repo/Dockerfile-demo",
        "dockerContext: ./repo",
        "healthCheckPath: /readyz",
        "type: cron",
    ):
        assert expected in BLUEPRINT, expected
    assert not re.search(r"(?m)^\s*disk:", BLUEPRINT)  # the database lives on the container
    assert re.search(r"key: ACME_SECRET_KEY\n\s+generateValue: true", BLUEPRINT)
    assert re.search(r"key: META_API_KEY\n\s+sync: false", BLUEPRINT)
    assert re.search(r"key: ACME_DEPLOY_HOOK_URL\n\s+sync: false", BLUEPRINT)
    assert re.search(r"key: ACME_DEPLOYMENT_MODE\n\s+value: demo", BLUEPRINT)
    # Randall turned live Muse on for judging (2026-10-31), capped per day.
    assert re.search(r"key: ACME_MUSE_PROVIDER_ENABLED\n\s+value: \"?1\"?", BLUEPRINT)
    assert re.search(r"key: ACME_DEMO_SEED_ON_START\n\s+value: \"?1\"?", BLUEPRINT)
    assert 'schedule: "0 2 * * *"' in BLUEPRINT
    assert not re.search(r"(?m)^\s+plan:", BLUEPRINT)  # Randall sets the instance type
    assert not re.search(r"https://api\.render\.com/deploy/\S+key=", BLUEPRINT)
    assert not re.search(r"(?i)\b(?:sk|rnd|nvapi)[-_][A-Za-z0-9]{8,}", BLUEPRINT)


def test_blueprint_limits_match_the_documented_defaults() -> None:
    for key, value in (
        ("ACME_RATE_LIMIT_ALL_PER_MINUTE", "300"),
        ("ACME_RATE_LIMIT_WRITE_PER_MINUTE", "60"),
        ("ACME_RATE_LIMIT_SESSION_PER_MINUTE", "20"),
        ("ACME_RATE_LIMIT_UPLOAD_PER_MINUTE", "20"),
        ("ACME_MUSE_LIVE_CALL_CAP", "100"),
        ("ACME_MUSE_DAILY_CALL_CAP", "100"),
        ("ACME_MUSE_IMAGE_DAILY_CAP", "10"),
        ("ACME_COOKIE_SECURE", "1"),
        ("ACME_TRUST_PROXY_HEADERS", "1"),
        ("ACME_SCENARIO_CLOCK", "auto"),
        ("ACME_PUBLIC_DEMO", "1"),
    ):
        assert re.search(rf"key: {key}\n\s+value: \"?{value}\"?\n", BLUEPRINT), key


def test_demo_dockerfile_shares_the_recipe_and_production_has_no_scripts() -> None:
    main = (REPO / "Dockerfile").read_text(encoding="utf-8")
    demo = (REPO / "Dockerfile-demo").read_text(encoding="utf-8")
    marker = "# ----------------------------------------------------------------- demo\n"
    shared = main.split(marker)[0].split("ARG PYTHON_VERSION")[1]
    assert demo.split("ARG PYTHON_VERSION")[1].split(marker)[0] == shared
    demo_stage = re.split(r"# -+ production\n", main.split(marker)[1])[0]
    assert demo.endswith(marker + demo_stage.rstrip() + "\n")
    assert "COPY scripts" in demo_stage
    production_stage = main.split("AS production")[1]
    assert "scripts" not in production_stage.replace("No reset script, no loaders", "")
    assert "COPY scripts" not in production_stage
    assert "rm -rf /app/fixtures/replay" in production_stage
