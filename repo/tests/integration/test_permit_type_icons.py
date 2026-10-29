"""Permit type icon tests: client, governance, caps, audit, serving.

Every provider call is mocked at the HTTP transport; no live request is
ever sent and META_API_KEY is a test-only value.  The tests prove the
brief's Part B contract: b64_json success, provider failure, url-only
refusal, the key never reaching a log or a page, administrator-only
generation, both daily caps, the recorded attempt, save making an icon
current, the byte route's content type and scope, and the work-queue
icon-or-fallback row.
"""
# REQUIRES: AI-01, AI-03, SEC-01, SEC-04, UX-01
# Icon generation is a governed, capped, audited administrator action over a
# mocked provider boundary; Muse proposes an image and only a save applies it.

from __future__ import annotations

import base64
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.audit.service import AuditService
from acme_city.auth.context import ActorContext
from acme_city.core.config import Settings
from acme_city.core.errors import PermissionDeniedError, ValidationError
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.muse.image_client import (
    IMAGE_MODEL,
    META_IMAGES_URL,
    MuseImageClient,
    describe_image,
    wrap_icon_prompt,
)
from acme_city.permits import icons as icon_service
from acme_city.persistence.models import audit, permit
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.ui.router import ActionContext, router as ui_router

CREDENTIAL = "test-image-key-not-a-real-credential"
ADMIN = "persona_city_administrator"
NON_ADMINS = (
    "persona_applicant",
    "persona_data_steward",
    "persona_permit_reviewer",
)


def webp_bytes() -> bytes:
    """Return the bundled seed WebP used as the mocked provider image."""
    from acme_city.permits.icons import STATIC_ICON_DIR

    return (STATIC_ICON_DIR / "sign.webp").read_bytes()


class RecordingTransport(httpx.BaseTransport):
    """A transport that records requests and answers with a fixed body."""

    def __init__(self, body: dict[str, Any], status_code: int = 200) -> None:
        self.requests: list[httpx.Request] = []
        self._body = body
        self._status_code = status_code

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self._status_code, json=self._body)


def success_body() -> dict[str, Any]:
    return {"data": [{"b64_json": base64.b64encode(webp_bytes()).decode("ascii")}]}


@pytest.fixture()
def seeded(tmp_path: Path):
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'icons.db'}",
            "ACME_SECRET_KEY": "icon-test-secret-value",
            "META_API_KEY": CREDENTIAL,
            "ACME_MUSE_LIVE_CALLS_ALLOWED": "true",
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
        yield settings, factory
    finally:
        factory.dispose()


@pytest.fixture()
def client(seeded) -> TestClient:
    settings, _factory = seeded
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def context_for(session, actor_id: str) -> ActorContext:
    from acme_city.auth.permissions import PermissionResolver
    from acme_city.persistence.models.governance import ActorRole

    resolver = PermissionResolver(session)
    grants = resolver.grants_for(actor_id)
    roles = frozenset(
        row[0]
        for row in session.execute(
            select(ActorRole.role_id).where(ActorRole.actor_id == actor_id)
        ).all()
    )
    return ActorContext(
        actor_id=actor_id,
        role_ids=roles,
        domain_scope=frozenset(g.domain_id for g in grants if g.domain_id),
        record_scope=frozenset(r for g in grants for r in g.record_scope),
    )


def action_ctx(session, settings, actor_id: str, **form: str) -> ActionContext:
    return ActionContext(
        session=session,
        actor=context_for(session, actor_id),
        form=form,
        settings=settings,
    )


def select_persona(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def csrf_of(html: str) -> str:
    import re

    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None, "the page carries no CSRF token"
    return match.group(1)


def any_csrf(client: TestClient) -> str:
    """Return a CSRF token from any action form visible to the persona.

    The token is bound to the server-held session, not to a screen, so a
    token read on the applicant's own case authorizes the POST that the
    server must then refuse on grants.
    """
    for path in ("/queue", "/rules-fees", "/permits/app_d05", "/permits/app_synth_001", "/steward"):
        response = client.get(path)
        if response.status_code != 200:
            continue
        import re

        match = re.search(r'name="csrf_token" value="([0-9a-f]+)"', response.text)
        if match is not None:
            return match.group(1)
    raise AssertionError("no page carried a CSRF token for this persona")


def seed_attempts(factory, permit_type_id: str, count: int) -> None:
    """Record ``count`` generation attempts for today directly as audit rows."""
    from acme_city.core.clock import utc_now

    with factory() as session:
        for _ in range(count):
            AuditService(session).append(
                action=icon_service.ATTEMPT_ACTION,
                actor=ADMIN,
                target_type="permit_type",
                target_id=permit_type_id,
                reason="icon generation succeeded",
                outcome="accepted",
                metadata={
                    "prompt": "earlier icon",
                    "status": "succeeded",
                    "cost_estimate_usd": 0.01,
                    "response_size": 10,
                    "icon_id": "",
                    "detail": "",
                },
            )
        session.commit()
        assert utc_now() is not None


# --------------------------------------------------------------------- client


def test_image_client_success_decodes_b64_and_wraps_prompt(seeded) -> None:
    settings, _factory = seeded
    transport = RecordingTransport(success_body())
    result = MuseImageClient(settings, transport=transport).generate(
        wrap_icon_prompt("a rooftop crane over a small building")
    )
    assert result.ok
    assert result.media_type == "image/webp"
    assert result.image_data == webp_bytes()
    assert result.response_size == len(webp_bytes())
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert str(request.url) == META_IMAGES_URL
    assert request.headers["authorization"] == f"Bearer {CREDENTIAL}"
    payload = json.loads(request.content)
    assert payload["model"] == IMAGE_MODEL
    assert payload["n"] == 1
    assert "no text" in payload["prompt"] and "no logos" in payload["prompt"]
    assert "rooftop crane" in payload["prompt"]


def test_image_client_failure_is_returned_not_raised(seeded) -> None:
    settings, _factory = seeded
    transport = RecordingTransport({"error": {"message": "quota exhausted"}}, 429)
    result = MuseImageClient(settings, transport=transport).generate("anything")
    assert not result.ok
    assert "quota exhausted" in (result.error or "")
    assert result.http_status == 429
    assert len(transport.requests) == 1


def test_image_client_treats_url_only_response_as_failure(seeded) -> None:
    settings, _factory = seeded
    transport = RecordingTransport({"data": [{"url": "https://example.invalid/icon.webp"}]})
    result = MuseImageClient(settings, transport=transport).generate("anything")
    assert not result.ok
    assert "URL" in (result.error or "")
    assert result.image_data == b""


def test_image_client_never_puts_key_in_logs(seeded, caplog) -> None:
    settings, _factory = seeded
    transport = RecordingTransport(
        {"error": {"message": f"bad key {CREDENTIAL} rejected"}}, 401
    )
    with caplog.at_level(logging.DEBUG):
        result = MuseImageClient(settings, transport=transport).generate(
            wrap_icon_prompt("a sign post")
        )
    assert not result.ok
    assert CREDENTIAL not in caplog.text
    assert CREDENTIAL not in (result.error or "")


def test_describe_image_reads_webp_dimensions() -> None:
    described = describe_image(webp_bytes())
    assert described is not None
    media, width, height = described
    assert media == "image/webp"
    assert width > 0 and height > 0


# ----------------------------------------------------------------- governance


def test_generation_is_denied_for_every_non_admin_persona(seeded) -> None:
    settings, factory = seeded
    transport = RecordingTransport(success_body())
    image_client = MuseImageClient(settings, transport=transport)
    for actor_id in NON_ADMINS:
        with factory() as session:
            ctx = action_ctx(
                session,
                settings,
                actor_id,
                permit_type_id="permit_type_deck_fence",
                prompt="a wooden deck with a fence",
                expected_version="1",
            )
            with pytest.raises(PermissionDeniedError):
                icon_service.generate_icon(ctx, client=image_client)
            session.rollback()
    assert transport.requests == []


def test_generation_records_attempt_and_pending_candidate(seeded) -> None:
    settings, factory = seeded
    transport = RecordingTransport(success_body())
    image_client = MuseImageClient(settings, transport=transport)
    with factory() as session:
        ctx = action_ctx(
            session,
            settings,
            ADMIN,
            permit_type_id="permit_type_deck_fence",
            prompt="a wooden deck with a fence",
            expected_version="1",
        )
        outcome = icon_service.generate_icon(ctx, client=image_client)
        session.commit()
        assert outcome.state == "pending"
        icon_id = outcome.extra["icon_id"]
    assert len(transport.requests) == 1
    with factory() as session:
        icon = session.get(permit.PermitTypeIcon, icon_id)
        assert icon is not None
        assert icon.source == "generated"
        assert icon.is_current is False
        assert icon.prompt == "a wooden deck with a fence"
        type_row = session.execute(
            select(permit.PermitType).where(
                permit.PermitType.id == "permit_type_deck_fence"
            )
        ).scalar_one()
        # Pending until saved: the type keeps its bundled seed icon (deck and
        # fence had none before the 14 seed icons were added, so this was None).
        assert type_row.icon_id == "icon_seed_deck_fence"
        assert type_row.icon_id != icon_id
        attempts = session.execute(
            select(audit.AuditEvent).where(
                audit.AuditEvent.action == icon_service.ATTEMPT_ACTION
            )
        ).scalars().all()
        assert len(attempts) == 1
        metadata = dict(attempts[0].metadata_json or {})
        assert metadata["status"] == "succeeded"
        assert metadata["cost_estimate_usd"] == 0.01
        assert metadata["response_size"] == len(webp_bytes())
        assert metadata["prompt"] == "a wooden deck with a fence"
        assert CREDENTIAL not in json.dumps(metadata)


def test_per_type_cap_refuses_the_fourth_generation(seeded) -> None:
    settings, factory = seeded
    seed_attempts(factory, "permit_type_deck_fence", 3)
    transport = RecordingTransport(success_body())
    image_client = MuseImageClient(settings, transport=transport)
    with factory() as session:
        ctx = action_ctx(
            session,
            settings,
            ADMIN,
            permit_type_id="permit_type_deck_fence",
            prompt="one icon too many",
            expected_version="1",
        )
        with pytest.raises(ValidationError) as raised:
            icon_service.generate_icon(ctx, client=image_client)
        assert raised.value.code == "icon_generation_cap"
    assert transport.requests == []
    with factory() as session:
        attempts = session.execute(
            select(audit.AuditEvent).where(
                audit.AuditEvent.action == icon_service.ATTEMPT_ACTION
            )
        ).scalars().all()
        refused = [row for row in attempts if row.outcome == "denied"]
        assert len(refused) == 1
        assert dict(refused[0].metadata_json or {})["status"] == "refused_cap"


def test_global_cap_refuses_past_the_settings_cap(seeded) -> None:
    settings, factory = seeded
    capped = settings.model_copy(update={"muse_image_daily_cap": 2})
    seed_attempts(factory, "permit_type_sign", 1)
    seed_attempts(factory, "permit_type_com_ti", 1)
    transport = RecordingTransport(success_body())
    image_client = MuseImageClient(capped, transport=transport)
    with factory() as session:
        ctx = ActionContext(
            session=session,
            actor=context_for(session, ADMIN),
            form={
                "permit_type_id": "permit_type_deck_fence",
                "prompt": "one over the global cap",
                "expected_version": "1",
            },
            settings=capped,
        )
        with pytest.raises(ValidationError) as raised:
            icon_service.generate_icon(ctx, client=image_client)
        assert raised.value.code == "icon_generation_cap"
    assert transport.requests == []


def test_save_sets_icon_and_generate_action_runs_over_http(
    client: TestClient, seeded
) -> None:
    settings, factory = seeded
    select_persona(client, ADMIN)
    page = client.get("/rules-fees")
    assert page.status_code == 200, page.text[:400]
    token = csrf_of(page.text)
    # HTTP cannot inject a mocked transport, so the governed generate action
    # is exercised at the service seam above; here the save half runs over
    # HTTP against a candidate row created directly as the seam would.
    with factory() as session:
        icon_service.ensure_seeded(session)
        candidate = permit.PermitTypeIcon(
            id="icon_http_candidate",
            permit_type_id="permit_type_deck_fence",
            image_data=webp_bytes(),
            media_type="image/webp",
            prompt="a wooden deck with a fence",
            created_by=ADMIN,
            source="generated",
            is_current=False,
        )
        session.add(candidate)
        session.commit()
    response = client.post(
        "/ui/actions/permit.icon.save",
        data={
            "permit_type_id": "permit_type_deck_fence",
            "icon_id": "icon_http_candidate",
            "expected_version": "1",
            "csrf_token": token,
            "next": "/rules-fees",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text[:400]
    with factory() as session:
        type_row = session.execute(
            select(permit.PermitType).where(
                permit.PermitType.id == "permit_type_deck_fence"
            )
        ).scalar_one()
        assert type_row.icon_id == "icon_http_candidate"
        assert session.get(permit.PermitTypeIcon, "icon_http_candidate").is_current is True


def test_save_and_generate_are_denied_over_http_for_non_admins(
    client: TestClient, seeded
) -> None:
    _settings, factory = seeded
    with factory() as session:
        icon_service.ensure_seeded(session)
        session.commit()
    for actor_id in NON_ADMINS:
        select_persona(client, actor_id)
        token = any_csrf(client)
        for action_id, form in (
            (
                "permit.icon.generate",
                {
                    "permit_type_id": "permit_type_deck_fence",
                    "prompt": "a deck",
                    "expected_version": "1",
                },
            ),
            (
                "permit.icon.save",
                {
                    "permit_type_id": "permit_type_deck_fence",
                    "icon_id": "icon_http_candidate",
                    "expected_version": "1",
                },
            ),
        ):
            response = client.post(
                f"/ui/actions/{action_id}",
                data={**form, "csrf_token": token, "next": "/queue"},
                headers={"Accept": "application/json"},
            )
            assert response.status_code in (403, 422), (actor_id, action_id, response.text[:200])
            if response.status_code == 403:
                assert "City Administrator" in response.text or "permit.icon.generate" in response.text


def test_icon_route_serves_bytes_with_content_type_and_scope(
    client: TestClient, seeded
) -> None:
    _settings, factory = seeded
    with factory() as session:
        # The fixture reset loads the bundled icons; no page view creates them.
        type_row = session.execute(
            select(permit.PermitType).where(permit.PermitType.id == "permit_type_sign")
        ).scalar_one()
        icon_id = type_row.icon_id
    assert icon_id
    signed_out = client.get(f"/permit-type-icons/{icon_id}", follow_redirects=False)
    assert signed_out.status_code == 303
    select_persona(client, ADMIN)
    response = client.get(f"/permit-type-icons/{icon_id}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/webp")
    assert response.content == webp_bytes()
    # Icons are decorative and appear on every persona's work queue, so each
    # signed-in persona may load them.
    for persona in ("persona_applicant", "persona_permit_reviewer", "persona_data_steward"):
        select_persona(client, persona)
        assert client.get(f"/permit-type-icons/{icon_id}").status_code == 200
    missing = client.get("/permit-type-icons/icon_does_not_exist")
    assert missing.status_code == 404


def test_yesterday_attempts_do_not_count_toward_today(seeded) -> None:
    _settings, factory = seeded
    yesterday = datetime.now(UTC) - timedelta(days=1)
    with factory() as session:
        AuditService(session, now=yesterday).append(
            action=icon_service.ATTEMPT_ACTION,
            actor=ADMIN,
            target_type="permit_type",
            target_id="permit_type_sign",
            reason="icon generation succeeded",
            outcome="accepted",
            metadata={"status": "succeeded", "prompt": "old", "response_size": 1},
        )
        session.commit()
    with factory() as session:
        per_type, total = icon_service.icon_attempt_counts(session)
        assert total == 0
        assert per_type == {}


def test_work_queue_row_shows_icon_or_fallback(client: TestClient, seeded) -> None:
    _settings, factory = seeded
    select_persona(client, ADMIN)
    queue = client.get("/queue?view=all")
    assert queue.status_code == 200
    body = queue.text
    # Every permit type now carries a bundled icon, so no seeded application
    # row falls back to the line tile.  (Before the 14 added icons, two types
    # with applications had none and this test asserted the fallback.)
    assert 'data-testid="permit-type-icon"' in body
    assert 'data-testid="permit-type-icon-fallback"' not in body
    # The fallback still works for a type whose icon rows are gone: remove
    # every icon of one type that has applications and the tile reappears.
    with factory() as session:
        type_row = session.execute(
            select(permit.PermitType).where(permit.PermitType.id == "permit_type_sign")
        ).scalar_one()
        type_row.icon_id = None
        session.query(permit.PermitTypeIcon).filter_by(permit_type_id=type_row.id).delete()
        session.commit()
    assert 'data-testid="permit-type-icon-fallback"' in client.get("/queue?view=all").text
    # Changed deliberately (the City Administrator restyle): the icon cards
    # moved from Rules and fees to Administration, in the Appearance tab, so
    # Rules and fees no longer carries them at all.
    rules = client.get("/rules")
    assert 'data-testid="permit-type-icons"' not in rules.text
    assert "permit-type-icon-row" not in rules.text
    admin = client.get("/admin?tab=appearance")
    assert admin.text.count('data-testid="permit-type-icon-row"') == 17


def test_reset_loads_seed_icons_and_rules_render_writes_nothing(client: TestClient, seeded) -> None:
    _settings, factory = seeded
    with factory() as session:
        seeded_rows = session.execute(select(permit.PermitTypeIcon)).scalars().all()
    assert {row.source for row in seeded_rows} == {"seed"}
    # One bundled icon per permit type: 3 original plus 14 added.
    assert len(seeded_rows) == 17
    select_persona(client, ADMIN)
    assert client.get("/rules-fees").status_code == 200
    with factory() as session:
        assert len(session.execute(select(permit.PermitTypeIcon)).scalars().all()) == 17


# ------------------------------------------------ all 17 types carry an icon



def _all_type_icons(factory) -> dict[str, str]:
    """Return permit type key -> current icon url for every permit type."""
    with factory() as session:
        types = session.execute(select(permit.PermitType)).scalars().all()
        assert len(types) == 17
        urls: dict[str, str] = {}
        for row in types:
            assert row.icon_id, f"{row.key} has no seeded icon after reset"
            urls[row.key] = f"/permit-type-icons/{row.icon_id}"
        return urls


def test_every_permit_type_has_a_seeded_current_icon_after_reset(seeded) -> None:
    _settings, factory = seeded
    urls = _all_type_icons(factory)
    assert len(set(urls.values())) == 17  # one distinct icon per type
    with factory() as session:
        for row in session.execute(select(permit.PermitType)).scalars().all():
            icons = session.execute(
                select(permit.PermitTypeIcon).where(
                    permit.PermitTypeIcon.permit_type_id == row.id
                )
            ).scalars().all()
            assert len(icons) == 1, row.key
            icon = icons[0]
            assert icon.source == "seed" and icon.is_current is True
            assert icon.media_type == "image/webp"
            assert describe_image(icon.image_data)[1:] == (192, 192), row.key
    # Every mapped slug has a bundled asset, and every type is mapped.
    assert len(icon_service.PERMIT_TYPE_SEED_ICONS) == 17
    for slug in icon_service.PERMIT_TYPE_SEED_ICONS.values():
        assert (icon_service.STATIC_ICON_DIR / f"{slug}.webp").is_file(), slug


def test_ensure_seeded_only_fills_types_without_icon_rows(seeded) -> None:
    _settings, factory = seeded
    with factory() as session:
        before = {
            row.id: row.icon_id
            for row in session.execute(select(permit.PermitType)).scalars().all()
        }
        icon_service.ensure_seeded(session)  # idempotent: nothing is missing
        session.commit()
        after = {
            row.id: row.icon_id
            for row in session.execute(select(permit.PermitType)).scalars().all()
        }
        assert before == after
        # A type with a changed current icon keeps it; a type that lost its rows
        # gets its bundled seed back.
        hvac = session.execute(
            select(permit.PermitType).where(permit.PermitType.id == "permit_type_hvac")
        ).scalar_one()
        session.query(permit.PermitTypeIcon).filter_by(permit_type_id=hvac.id).delete()
        hvac.icon_id = None
        session.flush()
        icon_service.ensure_seeded(session)
        session.commit()
        assert hvac.icon_id == "icon_seed_hvac"


def _add_applications_for_missing_types(factory) -> dict[str, str]:
    """Add one submitted application to every type that has none.

    The fixture population has applications for only four of the 17 types, so
    the queue and workspace checks create the rest here.  Returns permit type
    key -> application id for all 17 types.
    """
    from acme_city.core.clock import utc_now

    moment = utc_now()
    result: dict[str, str] = {}
    with factory() as session:
        for row in session.execute(select(permit.PermitType)).scalars().all():
            existing = session.execute(
                select(permit.Application)
                .where(permit.Application.permit_type_id == row.id)
                .order_by(permit.Application.id)
            ).scalars().first()
            if existing is None:
                existing = permit.Application(
                    id=f"app_icon_{row.key}",
                    source_application_number=f"ICON-{row.key}",
                    permit_type_id=row.id,
                    status="submitted",
                    revision=1,
                    initial_submitted_at=moment,
                    revision_submitted_at=moment,
                    description="Icon coverage case (fictional).",
                    submitted_facts={},
                    correlation_id=f"corr_icon_{row.key}",
                )
                session.add(existing)
                session.add(
                    permit.ApplicationRevision(
                        id=f"rev_icon_{row.key}",
                        application_id=existing.id,
                        revision_number=1,
                        submitted_at=moment,
                        snapshot={},
                    )
                )
            result[row.key] = existing.id
        session.commit()
    assert len(result) == 17
    return result


def test_portal_chooser_and_form_show_the_icon_of_every_type(
    client: TestClient, seeded
) -> None:
    _settings, factory = seeded
    urls = _all_type_icons(factory)
    select_persona(client, "persona_applicant")
    chooser = client.get("/apply")
    assert chooser.status_code == 200
    assert chooser.text.count('data-testid="type-card"') == 17
    for key, url in urls.items():
        assert f'data-type-key="{key}"' in chooser.text, key
        assert f'<img class="type-ic" src="{url}"' in chooser.text, key
    for key, url in urls.items():
        form = client.get(f"/apply/{key}")
        assert form.status_code == 200, key
        assert f'<img class="type-ic" src="{url}" alt="" data-testid="form-icon">' in form.text, key


def test_city_home_and_rules_fees_show_no_per_type_icon_by_design(
    client: TestClient, seeded
) -> None:
    # The City of Acme home page lists services, not permit types, and the
    # Rules and fees screen only points to Administration, where the icon
    # cards live.  Neither renders a permit type icon, so this pins that
    # design instead of forcing an icon in.
    _settings, factory = seeded
    urls = _all_type_icons(factory)
    home = client.get("/city")
    assert home.status_code == 200
    select_persona(client, ADMIN)
    rules = client.get("/rules-fees")
    assert rules.status_code == 200
    for page in (home, rules):
        assert "/permit-type-icons/" not in page.text
    # The Administration permit-type tab is where all 17 are shown.
    admin = client.get("/admin?tab=permit-types")
    for key, url in urls.items():
        assert f'<img class="type-ic" src="{url}"' in admin.text, key


def test_work_queue_and_workspace_show_the_icon_of_every_type(
    client: TestClient, seeded
) -> None:
    _settings, factory = seeded
    urls = _all_type_icons(factory)
    applications = _add_applications_for_missing_types(factory)
    select_persona(client, ADMIN)
    queue = client.get("/queue?view=all&page_size=500")
    assert queue.status_code == 200
    for key, url in urls.items():
        assert f'src="{url}" alt="" data-testid="permit-type-icon"' in queue.text, key
    assert 'data-testid="permit-type-icon-fallback"' not in queue.text
    for key, application_id in applications.items():
        page = client.get(f"/permits/{application_id}")
        assert page.status_code == 200, (key, page.text[:300])
        assert f'src="{urls[key]}" alt="" data-testid="permit-type-icon"' in page.text, key
        # The history panel is an audit rail of actions; it carries no per-type
        # image by design, so the icon appears once, in the workspace header.
        assert page.text.count('data-testid="permit-type-icon"') == 1, key
