"""Deployment mode, cookie, proxy, provider-switch and error-envelope settings.

Demo mode (the default) must behave exactly as before; production mode is
opt-in.  These tests pin both sides.
"""
# REQUIRES: SEC-01, AI-01
# The deployment mode only ever removes demonstration behaviour; the global provider
# switch is enforced at the one place that talks to the provider.

from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest

from acme_city.core.config import Settings
from acme_city.core.errors import (
    AuthenticationRequiredError,
    ConflictError,
    PermissionDeniedError,
    ValidationError,
)
from acme_city.muse.client import PROVIDER_DISABLED_ERROR, MuseClient
from acme_city.muse.image_client import MuseImageClient
from acme_city.muse.service import MuseRunCommand

SECRET = "deployment-mode-test-secret-value"


def load(tmp_path: Path, **env: str) -> Settings:
    return Settings.load(environ=dict(env), key_file=tmp_path / "missing.env")


def test_default_is_demo_with_todays_behaviour(tmp_path: Path) -> None:
    settings = load(tmp_path, ACME_SECRET_KEY=SECRET)
    assert settings.deployment_mode == "demo"
    assert settings.is_production is False
    assert settings.effective_cookie_secure is False
    assert settings.trust_proxy_headers is False
    assert settings.provider_enabled is True


def test_ephemeral_secret_is_allowed_in_demo(tmp_path: Path) -> None:
    settings = load(tmp_path)
    assert settings.secret_is_ephemeral is True
    assert settings.deployment_mode == "demo"


def test_production_refuses_to_load_without_a_secret(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ACME_SECRET_KEY is required"):
        load(tmp_path, ACME_DEPLOYMENT_MODE="production")


def test_production_accepts_a_secret_from_the_key_file(tmp_path: Path) -> None:
    key_file = tmp_path / "keys.env"
    key_file.write_text(f"ACME_SECRET_KEY={SECRET}\n", encoding="utf-8")
    settings = Settings.load(environ={"ACME_DEPLOYMENT_MODE": "production"}, key_file=key_file)
    assert settings.is_production


def test_production_defaults(tmp_path: Path) -> None:
    settings = load(tmp_path, ACME_DEPLOYMENT_MODE="production", ACME_SECRET_KEY=SECRET)
    assert settings.effective_cookie_secure is True
    assert settings.provider_enabled is False
    assert settings.trust_proxy_headers is False


def test_explicit_cookie_and_provider_settings_win_in_both_modes(tmp_path: Path) -> None:
    demo = load(
        tmp_path,
        ACME_SECRET_KEY=SECRET,
        ACME_COOKIE_SECURE="true",
        ACME_MUSE_PROVIDER_ENABLED="false",
        ACME_TRUST_PROXY_HEADERS="1",
    )
    assert demo.effective_cookie_secure is True
    assert demo.provider_enabled is False
    assert demo.trust_proxy_headers is True
    prod = load(
        tmp_path,
        ACME_DEPLOYMENT_MODE="production",
        ACME_SECRET_KEY=SECRET,
        ACME_COOKIE_SECURE="false",
        ACME_MUSE_PROVIDER_ENABLED="yes",
    )
    assert prod.effective_cookie_secure is False
    assert prod.provider_enabled is True


def test_invalid_mode_and_invalid_boolean_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ACME_DEPLOYMENT_MODE"):
        load(tmp_path, ACME_DEPLOYMENT_MODE="staging", ACME_SECRET_KEY=SECRET)
    with pytest.raises(ValueError, match="ACME_COOKIE_SECURE"):
        load(tmp_path, ACME_SECRET_KEY=SECRET, ACME_COOKIE_SECURE="maybe")


def test_safe_summary_reports_the_mode_without_secrets(tmp_path: Path) -> None:
    summary = load(tmp_path, ACME_SECRET_KEY=SECRET).safe_summary()
    assert summary["deployment_mode"] == "demo"
    assert SECRET not in str(summary)


# ------------------------------------------------------------ provider switch


def _payload() -> dict:
    return {
        "model": "muse-spark-1.3",
        "input": "x",
        "max_output_tokens": 100,
        "text": {"format": {"type": "json_schema", "strict": True, "name": "n", "schema": {}}},
    }


def _spy_transport(calls: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"id": "r1", "status": "completed", "output_text": "{}"})

    return httpx.MockTransport(handler)


def test_provider_switch_blocks_text_dispatch_before_any_network_call(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    settings = load(tmp_path, ACME_DEPLOYMENT_MODE="production", ACME_SECRET_KEY=SECRET, META_API_KEY="k")
    response = MuseClient(settings, transport=_spy_transport(calls)).create_response(_payload())
    assert calls == []
    assert response.error == PROVIDER_DISABLED_ERROR
    assert response.ok is False


def test_provider_switch_blocks_image_dispatch(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    settings = load(tmp_path, ACME_DEPLOYMENT_MODE="production", ACME_SECRET_KEY=SECRET, META_API_KEY="k")
    result = MuseImageClient(settings, transport=_spy_transport(calls)).generate("a drawing")
    assert calls == []
    assert result.ok is False
    assert "disabled" in (result.error or "")


def test_demo_dispatch_is_unchanged_and_production_can_opt_in(tmp_path: Path) -> None:
    for env in (
        {},
        {"ACME_DEPLOYMENT_MODE": "production", "ACME_MUSE_PROVIDER_ENABLED": "true"},
    ):
        calls: list[httpx.Request] = []
        settings = load(tmp_path, ACME_SECRET_KEY=SECRET, META_API_KEY="k", **env)
        response = MuseClient(settings, transport=_spy_transport(calls)).create_response(_payload())
        assert len(calls) == 1
        assert response.ok


def test_general_command_never_defaults_to_live() -> None:
    command = MuseRunCommand(task="extraction", application_id="app_1")
    assert command.mode == "replay"


# ----------------------------------------------------------------- envelopes


def test_public_envelope_drops_supplied_detail() -> None:
    denied = PermissionDeniedError("actor persona_x may not read secret thing 42", actor_id="persona_x")
    assert denied.to_dict()["message"].startswith("actor persona_x")
    public = denied.to_public_dict()
    assert public == {"code": "permission_denied", "message": "this action is outside your granted scope"}
    assert AuthenticationRequiredError("cookie bad").to_public_dict()["message"] == "authentication is required"
    conflict = ConflictError("version 3 of record A differs", current_version=3, differences=["x"])
    assert conflict.to_public_dict() == {
        "code": "version_conflict",
        "message": "the request conflicts with the current state of the record",
        "current_version": 3,
    }
    assert ValidationError("count must be at least 1").to_public_dict()["message"] == "count must be at least 1"


def test_demo_warning_for_ephemeral_secret_is_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    from acme_city.app import create_app

    settings = load(tmp_path, ACME_DATABASE_URL=f"sqlite:///{tmp_path / 'w.db'}")
    with caplog.at_level(logging.WARNING, logger="acme_city"):
        create_app(settings).state.session_factory.dispose()
    assert any("ACME_SECRET_KEY is not set" in record.message for record in caplog.records)
