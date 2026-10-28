"""The shared interface patterns: info popover, help and the detail drawer."""
# REQUIRES: UX-01, UX-02, SEC-01

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from markupsafe import escape

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui import patterns
from acme_city.ui.router import router as ui_router

REPO = Path(__file__).resolve().parents[2]
TEMPLATES = REPO / "src" / "acme_city" / "templates"
APPLICATION = "app_synth_001"


RUN_ID = "run_ui_patterns_001"


def seed_muse_run(settings: Settings) -> None:
    """Record one fictional Muse run for the seeded application."""
    from datetime import UTC, datetime

    from acme_city.persistence.models import model_run

    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            session.add(
                model_run.ModelRun(
                    id=RUN_ID,
                    correlation_id="corr_ui_patterns",
                    mode="replay",
                    provider="meta",
                    model="muse-spark-test",
                    prompt_version="extraction-prompt-v1",
                    schema_version="extraction-schema-v1",
                    input_refs={
                        "application_id": APPLICATION,
                        "documents": [
                            {
                                "document_id": "doc_ui_patterns",
                                "version": 1,
                                "content_hash": "ab12" * 16,
                                "document_type": "site_plan",
                            }
                        ],
                    },
                    output={},
                    validation_result={"checked": ["fields_present"], "issues": []},
                    usage={"input_tokens": 120, "output_tokens": 45},
                    latency_ms=830,
                    started_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
                    completed_at=datetime(2026, 10, 1, 12, 0, 1, tzinfo=UTC),
                    actor_id="persona_data_steward",
                )
            )
    finally:
        factory.dispose()


@pytest.fixture()
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("acme_city.applicant_portal.service.DOCUMENT_ROOT", tmp_path / "documents")
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'patterns.db'}",
            "ACME_SECRET_KEY": "ui-patterns-test-secret",
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
    finally:
        factory.dispose()
    seed_muse_run(settings)
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def choose(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def run_id(client: TestClient) -> str:
    """Return the Muse run id the workspace links to (as a steward)."""
    choose(client, "persona_data_steward")
    page = client.get(f"/permits/{APPLICATION}")
    assert page.status_code == 200
    found = re.search(r'data-detail-kind="muse-run" data-detail-id="([^"]+)"', page.text)
    assert found, "the workspace must link its Muse run to the drawer"
    assert found.group(1) == RUN_ID
    return found.group(1)


# ------------------------------------------------------------ P1 markup


def test_info_popover_markup_and_a11y(client: TestClient) -> None:
    run_id(client)
    text = client.get(f"/permits/{APPLICATION}").text
    button = re.search(r'<button[^>]*class="ui-info-btn"[^>]*>', text)
    assert button, "the info button must be a <button>"
    tag = button.group(0)
    assert 'type="button"' in tag and 'aria-expanded="false"' in tag
    controls = re.search(r'aria-controls="([^"]+)"', tag).group(1)
    assert f'id="{controls}"' in text
    assert "aria-label=" in tag
    # No-JavaScript fallback: the same text, inline, in a details element.
    assert '<details class="ui-info-fallback">' in text
    wording = patterns.term("muse_provenance")["text"]
    assert text.count(str(escape(wording))) == 2


def test_info_ids_are_unique_on_a_page(client: TestClient) -> None:
    run_id(client)
    text = client.get(f"/permits/{APPLICATION}").text
    ids = re.findall(r' id="([^"]+)"', text)
    assert len(ids) == len(set(ids))


def test_every_info_and_help_key_used_in_templates_exists() -> None:
    used_terms: set[str] = set()
    used_screens: set[str] = set()
    for path in (p for p in TEMPLATES.rglob("*.html") if p.name != "_ui.html"):
        body = path.read_text(encoding="utf-8")
        used_terms |= set(re.findall(r"\.info\(\s*'([^']+)'", body))
        used_terms |= set(re.findall(r"\binfo\(\s*'([^']+)'", body))
        used_screens |= set(re.findall(r"help_button\(\s*'([^']+)'", body))
    assert "muse_provenance" in used_terms
    assert used_terms <= set(patterns.term_keys()), used_terms - set(patterns.term_keys())
    assert used_screens <= set(patterns.help_screens()), used_screens - set(patterns.help_screens())


def test_glossary_and_help_config_are_complete() -> None:
    data = json.loads((REPO / "config" / "ui_glossary.json").read_text(encoding="utf-8"))
    for key, entry in data["terms"].items():
        assert entry["label"].strip() and entry["text"].strip(), key
    for key, entry in data["screens"].items():
        assert entry["title"] and entry["purpose"] and entry["can_do"] and entry["next"], key


def test_each_staff_screen_has_help() -> None:
    from acme_city.ui import view_models

    for screen in view_models.SCREEN_PERMISSIONS:
        if screen == "queue":
            assert patterns.screen_help(screen)
    for screen in ("queue", "applicants", "masters", "permit", "steward", "rules",
                   "reconciliation", "governance", "agent_intake", "agent_adjudication",
                   "admin", "intake_queue", "early_resolution", "review_queue",
                   "apply", "apply_track"):
        assert patterns.screen_help(screen), screen


# ------------------------------------------------------------ P2 help


def test_help_button_on_a_staff_and_an_applicant_screen(client: TestClient) -> None:
    choose(client, "persona_data_steward")
    staff = client.get("/rules-fees")
    assert staff.status_code == 200
    link = re.search(r'<a class="ui-help"[^>]*>', staff.text)
    assert link and 'aria-label="Help for this screen"' in link.group(0)
    assert "?detail=help:rules" in link.group(0)
    choose(client, "persona_applicant")
    applicant = client.get("/apply/track")
    assert 'data-testid="ui-help"' in applicant.text
    assert "?detail=help:apply_track" in applicant.text


def test_help_flyout_has_three_parts(client: TestClient) -> None:
    choose(client, "persona_applicant")
    response = client.get("/detail/help/apply_track")
    assert response.status_code == 200
    for heading in ("What this screen is for", "What you can do here", "What usually happens next"):
        assert heading in response.text


def test_staff_help_is_refused_to_a_persona_without_the_screen(client: TestClient) -> None:
    choose(client, "persona_applicant")
    response = client.get("/detail/help/admin")
    assert response.status_code == 403
    assert patterns.screen_help("admin")["purpose"] not in response.text


# ------------------------------------------------------------ P3 drawer


def test_no_javascript_render_opens_the_drawer(client: TestClient) -> None:
    rid = run_id(client)
    closed = client.get(f"/permits/{APPLICATION}").text
    assert re.search(r'<aside id="ui-drawer"[^>]* hidden>', closed)
    opened = client.get(f"/permits/{APPLICATION}?detail=muse-run:{rid}")
    assert opened.status_code == 200
    drawer = re.search(r'<aside id="ui-drawer"[^>]*>', opened.text).group(0)
    assert " hidden" not in drawer and "is-open" in drawer
    assert 'role="dialog"' in drawer and 'aria-labelledby="ui-drawer-title"' in drawer
    for expected in ("Muse run details", "Prompt version", "Latency", rid):
        assert expected in opened.text
    assert 'data-testid="ui-drawer-close"' in opened.text
    close = re.search(r'<a class="ui-drawer-close" href="([^"]+)"', opened.text).group(1)
    assert "detail=" not in close


def test_fragment_route_matches_the_page(client: TestClient) -> None:
    rid = run_id(client)
    fragment = client.get(f"/detail/muse-run/{rid}", params={"from": f"/permits/{APPLICATION}"})
    assert fragment.status_code == 200
    assert fragment.headers["cache-control"] == "no-store"
    assert "Muse run details" in fragment.text and rid in fragment.text
    assert f'href="/permits/{APPLICATION}"' in fragment.text


def test_the_page_with_detail_keeps_the_task_on_screen(client: TestClient) -> None:
    rid = run_id(client)
    text = client.get(f"/permits/{APPLICATION}?detail=muse-run:{rid}").text
    assert 'data-testid="muse-mode"' in text
    assert 'data-testid="muse-panel"' in text


def test_applicant_is_refused_muse_run_details_with_no_data(client: TestClient) -> None:
    rid = run_id(client)
    choose(client, "persona_applicant")
    response = client.get(f"/detail/muse-run/{rid}")
    assert response.status_code == 403
    for leak in ("Prompt version", "Latency", "Provider", rid):
        assert leak not in response.text
    page = client.get(f"/queue?detail=muse-run:{rid}")
    assert 'data-detail-status="403"' in page.text
    assert "Prompt version" not in page.text.split('id="ui-drawer"', 1)[1]


def test_unknown_kind_and_unknown_id_are_404(client: TestClient) -> None:
    choose(client, "persona_data_steward")
    assert client.get("/detail/nothing/x").status_code == 404
    assert client.get("/detail/muse-run/run_does_not_exist").status_code == 404
    assert client.get("/detail/muse-run/bad id").status_code == 404


def test_signed_out_fragment_is_401_and_empty_of_data(client: TestClient) -> None:
    response = client.get("/detail/help/queue")
    assert response.status_code == 401
    assert "What you can do here" not in response.text


def test_malformed_detail_parameter_renders_a_closed_page(client: TestClient) -> None:
    choose(client, "persona_data_steward")
    for bad in ("nocolon", "UPPER:1", "muse-run:", "muse-run:a b"):
        text = client.get(f"/permits/{APPLICATION}", params={"detail": bad}).text
        assert re.search(r'<aside id="ui-drawer"[^>]* hidden>', text), bad


def test_record_scope_is_enforced_by_the_registry(client: TestClient) -> None:
    """A persona cannot fetch a restricted detail of a record outside its scope."""
    seen: list[str] = []

    def resolver(ctx, item_id):
        seen.append(item_id)
        if item_id not in ctx.actor.record_scope:
            return None
        return patterns.DetailView(
            title="Scoped",
            sections=(patterns.Section("Secret", lines=(f"scoped-secret-for-{item_id}",)),),
        )

    patterns.register_detail(
        "scoped-test", resolver, label="Scoped", any_grant=(("application.submit", "permits"),)
    )
    try:
        choose(client, "persona_applicant")
        mine = client.get("/detail/scoped-test/SYN-APP-005")
        assert mine.status_code == 200 and "scoped-secret-for-SYN-APP-005" in mine.text
        other = client.get("/detail/scoped-test/SYN-APP-001")
        assert other.status_code == 404
        assert "scoped-secret" not in other.text and "SYN-APP-001" not in other.text
        page = client.get("/apply/track?detail=scoped-test:SYN-APP-001")
        assert 'data-detail-status="404"' in page.text and "scoped-secret" not in page.text
    finally:
        patterns.unregister_detail("scoped-test")


def test_a_persona_without_the_kinds_grant_never_reaches_the_resolver(client: TestClient) -> None:
    called: list[str] = []

    def resolver(ctx, item_id):
        called.append(item_id)
        return patterns.DetailView(title="Decision detail")

    patterns.register_detail(
        "decision-test", resolver, label="Decision", any_grant=(("permit.decide", "permits"),)
    )
    try:
        choose(client, "persona_applicant")
        refused = client.get("/detail/decision-test/x")
        assert refused.status_code == 403 and "Decision detail" not in refused.text
        assert called == []
        choose(client, "persona_permit_reviewer")
        assert client.get("/detail/decision-test/x").status_code == 200
        assert called == ["x"]
    finally:
        patterns.unregister_detail("decision-test")


def test_registering_a_kind_requires_a_permission_decision() -> None:
    with pytest.raises(ValueError):
        patterns.register_detail("no-grant", lambda ctx, item: None, label="x")
    with pytest.raises(ValueError):
        patterns.register_detail("Bad Kind", lambda ctx, item: None, label="x", public=True)


def test_layouts_load_the_assets_and_mount_one_drawer(client: TestClient) -> None:
    choose(client, "persona_applicant")
    for path in ("/apply/track", "/queue"):
        text = client.get(path).text
        assert "/ui/static/ui-patterns.css" in text and "/ui/static/ui-patterns.js" in text
        assert text.count(' id="ui-drawer"') == 1, path
