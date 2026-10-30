"""Operator-lane settings: safe defaults and env overrides."""

from __future__ import annotations

from pathlib import Path

import pytest

from acme_city.core.config import Settings
from acme_city.core.config_operator import (
    DEFAULT_MUSE_DAILY_CALL_CAP,
    operator_env_overrides,
)
from acme_city.agents.worker import worker_enabled

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
    assert operator_env_overrides({"ACME_MUSE_LIVE_CALLS_ALLOWED": "true"}) == {
        "muse_live_calls_allowed": True
    }


def test_the_daily_call_cap_has_a_default_and_an_override(tmp_path: Path) -> None:
    settings = _load(tmp_path)
    assert settings.muse_daily_call_cap == DEFAULT_MUSE_DAILY_CALL_CAP
    assert Settings(secret_key=SECRET_VALUE).muse_daily_call_cap == (
        DEFAULT_MUSE_DAILY_CALL_CAP
    )
    settings = _load(tmp_path, ACME_MUSE_DAILY_CALL_CAP="3")
    assert settings.muse_daily_call_cap == 3
    assert operator_env_overrides({"ACME_MUSE_DAILY_CALL_CAP": "0"}) == {
        "muse_daily_call_cap": 0
    }


def test_a_daily_call_cap_that_is_not_a_whole_number_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _load(tmp_path, ACME_MUSE_DAILY_CALL_CAP="many")
    with pytest.raises(ValueError):
        _load(tmp_path, ACME_MUSE_DAILY_CALL_CAP="-1")


def test_the_background_worker_needs_the_deployment_to_ask_for_it(
    tmp_path: Path,
) -> None:
    """The worker stays off unless the deployment allows it."""
    settings = _load(tmp_path)
    assert settings.agent_worker_enabled is False
    assert worker_enabled(settings) is False
    settings = _load(tmp_path, ACME_AGENT_WORKER_ENABLED="true")
    assert settings.agent_worker_enabled is True
    assert worker_enabled(settings) is True
