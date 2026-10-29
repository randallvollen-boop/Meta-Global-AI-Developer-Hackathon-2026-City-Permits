"""Auto-link-lane settings: safe defaults and env overrides."""

from __future__ import annotations

from pathlib import Path

from acme_city.core.config import Settings
from acme_city.core.config_autolink import autolink_env_overrides

SECRET_VALUE = "unit-test-secret-value-not-a-real-key"


def _load(tmp_path: Path, **env: str) -> Settings:
    return Settings.load(environ=env, key_file=tmp_path / "missing.env", secret_key=SECRET_VALUE)


def test_registry_automation_defaults_to_paused(tmp_path: Path) -> None:
    assert _load(tmp_path).registry_automation_mode == "paused"
    assert Settings(secret_key=SECRET_VALUE).registry_automation_mode == "paused"


def test_registry_automation_env_override_takes_effect(tmp_path: Path) -> None:
    settings = _load(tmp_path, ACME_REGISTRY_AUTOMATION_MODE="Active")
    assert settings.registry_automation_mode == "active"


def test_autolink_overrides_only_contain_set_names() -> None:
    assert autolink_env_overrides({}) == {}
