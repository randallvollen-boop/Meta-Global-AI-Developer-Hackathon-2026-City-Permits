"""Operator-lane settings: safe defaults and env overrides."""

from __future__ import annotations

from pathlib import Path

from acme_city.core.config import Settings
from acme_city.core.config_operator import operator_env_overrides

SECRET_VALUE = "unit-test-secret-value-not-a-real-key"


def _load(tmp_path: Path, **env: str) -> Settings:
    return Settings.load(environ=env, key_file=tmp_path / "missing.env", secret_key=SECRET_VALUE)


def test_operator_defaults_are_off(tmp_path: Path) -> None:
    settings = _load(tmp_path)
    assert settings.agent_worker_enabled is False
    assert settings.muse_live_calls_allowed is False
    assert Settings(secret_key=SECRET_VALUE).agent_worker_enabled is False
    assert Settings(secret_key=SECRET_VALUE).muse_live_calls_allowed is False


def test_operator_env_override_takes_effect(tmp_path: Path) -> None:
    settings = _load(tmp_path, ACME_AGENT_WORKER_ENABLED="true")
    assert settings.agent_worker_enabled is True
    assert settings.muse_live_calls_allowed is False
    settings = _load(tmp_path, ACME_MUSE_LIVE_CALLS_ALLOWED="1")
    assert settings.muse_live_calls_allowed is True
    assert settings.agent_worker_enabled is False


def test_operator_overrides_only_contain_set_names() -> None:
    assert operator_env_overrides({}) == {}
    assert operator_env_overrides({"ACME_AGENT_WORKER_ENABLED": "off"}) == {
        "agent_worker_enabled": False
    }
