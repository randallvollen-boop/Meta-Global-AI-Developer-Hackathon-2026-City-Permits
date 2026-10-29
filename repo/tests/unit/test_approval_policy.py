"""The approval policy setting: one source of truth, an environment override.

``config/approval_policy.json`` holds the city value and defaults to
``single``.  ``ACME_APPROVAL_POLICY`` overrides it for one process.  An
unknown value falls back to the stricter ``independent`` policy.
"""
# REQUIRES: REF-02, CHG-01

from __future__ import annotations

import json

import pytest

from acme_city.rules import approval_policy


def test_the_city_configuration_defaults_to_single(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ACME_APPROVAL_POLICY", raising=False)
    stored = json.loads(approval_policy.CONFIG_PATH.read_text(encoding="utf-8"))
    assert stored["approval_policy"] == "single"
    assert approval_policy.active_policy() == "single"
    assert approval_policy.is_single()
    assert approval_policy.policy_label() == "single administrator"


@pytest.mark.parametrize("value", ["independent", " Independent ", "INDEPENDENT"])
def test_the_environment_overrides_the_configuration(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("ACME_APPROVAL_POLICY", value)
    assert approval_policy.active_policy() == "independent"
    assert not approval_policy.is_single()


def test_an_unknown_value_falls_back_to_the_stricter_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACME_APPROVAL_POLICY", "anyone")
    assert approval_policy.active_policy() == "independent"


def test_a_missing_configuration_uses_the_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.delenv("ACME_APPROVAL_POLICY", raising=False)
    monkeypatch.setattr(approval_policy, "CONFIG_PATH", tmp_path / "missing.json")
    assert approval_policy.active_policy() == "single"
