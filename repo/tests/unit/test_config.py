"""Tests for settings loading, identifiers, clock, results and the app factory."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acme_city.app import create_app
from acme_city.core.clock import ensure_utc, isoformat, utc_now
from acme_city.core.config import Settings, parse_key_file
from acme_city.core.ids import id_prefix, is_generated_id, new_id, uuid_from_id
from acme_city.core.results import ConflictResult, VersionedResult

SECRET_VALUE = "unit-test-secret-value-not-a-real-key"


def write_key_file(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_settings_read_environment_values(tmp_path: Path) -> None:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": "sqlite:///var/unit.db",
            "ACME_DEMO_TIMEZONE": "UTC",
            "ACME_MUSE_MODEL_ALLOWLIST": "muse-spark-1.3, muse-spark-1.4",
            "ACME_MUSE_LIVE_CALL_CAP": "3",
            "ACME_EVIDENCE_ROOT": "evidence/unit",
            "ACME_SECRET_KEY": SECRET_VALUE,
        },
        key_file=tmp_path / "missing.env",
    )
    assert settings.database_url == "sqlite:///var/unit.db"
    assert settings.demo_timezone == "UTC"
    assert settings.muse_model_allowlist == ("muse-spark-1.3", "muse-spark-1.4")
    assert settings.muse_live_call_cap == 3
    assert settings.evidence_root == Path("evidence/unit")


def test_environment_takes_precedence_over_key_file(tmp_path: Path) -> None:
    key_file = write_key_file(
        tmp_path / "ai-keys.env",
        f"ACME_SECRET_KEY={SECRET_VALUE}\nMETA_API_KEY=file-meta-key\n",
    )
    from_file = Settings.load(environ={}, key_file=key_file)
    assert from_file.secret_key.get_secret_value() == SECRET_VALUE
    assert from_file.meta_api_key is not None
    assert from_file.meta_api_key.get_secret_value() == "file-meta-key"

    from_env = Settings.load(
        environ={"ACME_SECRET_KEY": "environment-secret-value", "META_API_KEY": "env-meta-key"},
        key_file=key_file,
    )
    assert from_env.secret_key.get_secret_value() == "environment-secret-value"
    assert from_env.meta_api_key is not None
    assert from_env.meta_api_key.get_secret_value() == "env-meta-key"


def test_key_file_parser_ignores_unlisted_names_and_executes_nothing() -> None:
    parsed = parse_key_file(
        """
        # comment
        export ACME_SECRET_KEY="quoted-secret"
        META_API_KEY='single-quoted'
        OTHER_PERSONAL_SECRET=do-not-read
        not an assignment
        ACME_SECRET_KEY_EXTRA=ignored
        """
    )
    assert parsed == {"ACME_SECRET_KEY": "quoted-secret", "META_API_KEY": "single-quoted"}


def test_secret_values_never_appear_in_representations(tmp_path: Path) -> None:
    settings = Settings.load(
        environ={
            "ACME_SECRET_KEY": SECRET_VALUE,
            "META_API_KEY": "meta-secret-value",
        },
        key_file=tmp_path / "missing.env",
    )
    representations = [
        repr(settings),
        str(settings),
        settings.model_dump_json(),
        json.dumps(settings.safe_summary()),
    ]
    for representation in representations:
        assert SECRET_VALUE not in representation
        assert "meta-secret-value" not in representation


def test_safe_summary_has_no_secret_and_no_local_path(tmp_path: Path) -> None:
    settings = Settings.load(
        environ={"ACME_SECRET_KEY": SECRET_VALUE, "ACME_DATABASE_URL": "sqlite:////srv/acme/secret.db"},
        key_file=tmp_path / "missing.env",
    )
    summary = settings.safe_summary()
    assert summary["database_scheme"] == "sqlite"
    assert "secret" not in summary
    assert "/srv/acme" not in json.dumps(summary)


def test_contributor_models_are_rejected() -> None:
    with pytest.raises(ValueError):
        Settings(
            secret_key=SECRET_VALUE,
            muse_model_allowlist=("muse-spark-1.3-contributor",),
        )
    settings = Settings(secret_key=SECRET_VALUE, muse_model_allowlist=("muse-spark-1.3",))
    assert settings.model_is_allowed("muse-spark-1.3")
    assert not settings.model_is_allowed("muse-spark-1.3-contributor")
    assert not settings.model_is_allowed("some-other-model")


def test_ephemeral_secret_is_generated_when_unset(tmp_path: Path) -> None:
    settings = Settings.load(environ={}, key_file=tmp_path / "missing.env")
    assert settings.secret_is_ephemeral is True
    assert len(settings.secret_key.get_secret_value()) >= 16


def test_new_id_is_prefixed_and_uuid_compatible() -> None:
    identifier = new_id("party")
    assert identifier.startswith("party_")
    assert is_generated_id(identifier)
    assert id_prefix(identifier) == "party"
    assert uuid_from_id(identifier).version == 4
    assert isinstance(uuid.UUID(identifier.split("_", 1)[1]), uuid.UUID)
    assert new_id("party") != identifier
    with pytest.raises(ValueError):
        new_id("Party With Spaces")


def test_utc_now_is_timezone_aware() -> None:
    moment = utc_now()
    assert moment.tzinfo is not None
    assert moment.utcoffset().total_seconds() == 0
    assert isoformat(moment).endswith("+00:00")
    assert ensure_utc(moment) == moment
    with pytest.raises(ValueError):
        ensure_utc(moment.replace(tzinfo=None))


def test_conflict_result_serializes() -> None:
    conflict = ConflictResult(
        code="version_conflict",
        expected_version=4,
        current_version=5,
        differences=({"field": "valuation", "expected": 1, "current": 2},),
    )
    payload = conflict.to_dict()
    assert payload["code"] == "version_conflict"
    assert payload["expected_version"] == 4
    assert payload["current_version"] == 5
    assert payload["differences"][0]["field"] == "valuation"


def test_versioned_result_serializes() -> None:
    result = VersionedResult(value={"status": "submitted"}, version=3, audit_event_id="audit_1")
    payload = result.to_dict()
    assert payload == {"value": {"status": "submitted"}, "version": 3, "audit_event_id": "audit_1"}


def test_healthz_reports_uninitialized_database(tmp_path: Path) -> None:
    settings = Settings.load(
        environ={
            "ACME_SECRET_KEY": SECRET_VALUE,
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'uninitialized.db'}",
        },
        key_file=tmp_path / "missing.env",
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["database"] == "uninitialized"
    assert SECRET_VALUE not in response.text
    assert settings.database_url not in response.text
