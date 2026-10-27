"""The evidence manifest of one run.

The manifest names the build, the versions, the actors and the artifacts of
the run, it keeps the three measurement groups apart, it refuses a result
that would overstate what happened, and it never carries a secret.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from acme_city.evidence.manifest import (
    MANIFEST_NAME,
    EvidenceRecorder,
    assert_no_secrets,
    build_hash,
    hash_tree,
    sha256_file,
)
from acme_city.evidence.schemas import (
    CHECK_KIND_ACCEPTANCE,
    CHECK_KIND_SCENARIO,
    CHECK_KIND_SUPPLEMENTARY,
    CHECK_STATUS_BLOCKED,
    CHECK_STATUS_FAILED,
    CHECK_STATUS_PASSED,
    METRIC_GROUP_BASELINE,
    METRIC_GROUP_BUSINESS,
    METRIC_GROUP_OBSERVED,
    ArtifactRef,
    CheckResult,
    EvidenceError,
    MetricGroup,
)


def recorder(directory: Path, **overrides: object) -> EvidenceRecorder:
    """Return a recorder for a run of a fictional demonstration."""
    values: dict[str, object] = {
        "run_id": "run_deterministic_001",
        "mode": "deterministic",
        "started_at": datetime(2026, 10, 26, 12, 0, tzinfo=UTC),
        "build_hash_value": "a" * 64,
        "tree_hash_value": "b" * 64,
        "fixture_version": "2026.10.26-1",
        "database_schema_revision": "0001",
        "source_snapshots": {"fixtures/base_population.json": "c" * 64},
        "model": {"mode": "replay", "provider": "meta", "model": "muse-spark-1.3"},
        "prompt_versions": {"extraction": "acme-extraction-prompt-v1"},
        "schema_versions": {"extraction": "acme-extraction-schema-v1"},
        "rule_versions": {"com_ti": "rule_set_com_ti_v1"},
        "actors": ("persona_data_steward", "persona_permit_reviewer"),
        "environment": {"python_version": "3.12", "fictional_demo": "true"},
    }
    values.update(overrides)
    return EvidenceRecorder(directory, **values)  # type: ignore[arg-type]


def test_the_manifest_names_the_build_the_versions_and_the_actors(tmp_path: Path) -> None:
    record = recorder(tmp_path)
    record.record_check(
        CheckResult(
            check_id="AT02",
            status=CHECK_STATUS_PASSED,
            requirement_ids=("EDIT-01", "EDIT-02", "EDIT-03"),
            expected="each field group names one correction destination",
            observed="the applicant profile names the permitting applicant profile",
            evidence_refs=("contract_permitting_applicant_profiles",),
            kind=CHECK_KIND_ACCEPTANCE,
            node_ids=("tests/acceptance/test_at02.py::test_a",),
        )
    )
    path = record.finalize()
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert path.name == MANIFEST_NAME
    assert payload["run_id"] == "run_deterministic_001"
    assert payload["mode"] == "deterministic"
    assert payload["build_hash"] == "a" * 64
    assert payload["tree_hash"] == "b" * 64
    assert payload["fixture_version"] == "2026.10.26-1"
    assert payload["database_schema_revision"] == "0001"
    assert payload["source_snapshots"]["fixtures/base_population.json"] == "c" * 64
    assert payload["model"]["model"] == "muse-spark-1.3"
    assert payload["prompt_versions"]["extraction"] == "acme-extraction-prompt-v1"
    assert payload["schema_versions"]["extraction"] == "acme-extraction-schema-v1"
    assert payload["rule_versions"]["com_ti"] == "rule_set_com_ti_v1"
    assert payload["actors"] == ["persona_data_steward", "persona_permit_reviewer"]
    assert payload["checks"][0]["requirement_ids"] == ["EDIT-01", "EDIT-02", "EDIT-03"]
    assert payload["checks"][0]["expected"]
    assert payload["checks"][0]["observed"]
    assert payload["checks"][0]["evidence_refs"] == ["contract_permitting_applicant_profiles"]
    assert payload["started_at"] < payload["finished_at"]


def test_a_failed_and_a_blocked_check_carry_their_reason(tmp_path: Path) -> None:
    record = recorder(tmp_path)
    record.record_check(
        CheckResult(
            check_id="AT15",
            status=CHECK_STATUS_BLOCKED,
            requirement_ids=("AI-03", "AI-04"),
            expected="a live call and a recorded replay are two different records",
            observed="no live provider call was made in the deterministic run",
            failure="the live provider call is not part of the deterministic run",
            live_required=True,
        )
    )
    record.record_check(
        CheckResult(
            check_id="AT19",
            status=CHECK_STATUS_FAILED,
            requirement_ids=("PER-05", "CHG-05", "EVAL-03"),
            expected="the complete chain survives a restart",
            observed="the restart never ran",
            failure="the restart step is missing",
        )
    )
    payload = record.to_dict()
    blocked = payload["checks"][0]
    failed = payload["checks"][1]
    assert blocked["status"] == CHECK_STATUS_BLOCKED
    assert blocked["failure"]
    assert blocked["live_required"] is True
    assert failed["status"] == CHECK_STATUS_FAILED
    assert failed["failure"]
    assert payload["failures"] == [
        "AT15: the live provider call is not part of the deterministic run",
        "AT19: the restart step is missing",
    ]


def test_a_passed_check_may_not_carry_a_failure() -> None:
    with pytest.raises(EvidenceError):
        CheckResult(
            check_id="AT02",
            status=CHECK_STATUS_PASSED,
            expected="something",
            observed="something",
            failure="this should not be here",
        )


def test_a_failed_check_without_a_reason_is_refused() -> None:
    with pytest.raises(EvidenceError):
        CheckResult(check_id="AT03", status=CHECK_STATUS_FAILED, expected="a", observed="b")


def test_an_unknown_status_is_refused() -> None:
    with pytest.raises(EvidenceError):
        CheckResult(check_id="AT03", status="skipped", expected="a", observed="b")


def test_the_manifest_is_written_through_a_temporary_file_and_a_rename(
    tmp_path: Path,
) -> None:
    target = tmp_path / "evidence" / "run-001"
    record = recorder(target)
    record.record_check(
        CheckResult(
            check_id="VC07",
            status=CHECK_STATUS_PASSED,
            expected="every denominator is stated",
            observed="every denominator is stated",
            kind=CHECK_KIND_SUPPLEMENTARY,
        )
    )
    path = record.finalize()
    assert path.is_file()
    leftovers = [item.name for item in path.parent.iterdir() if ".tmp-" in item.name]
    assert leftovers == []
    # The written file is complete JSON, not a partial write.
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["checks"][0]["check_id"] == "VC07"


def test_a_record_that_names_a_credential_is_refused(tmp_path: Path) -> None:
    record = recorder(tmp_path, environment={"meta_api_key": "not-a-real-credential"})
    with pytest.raises(EvidenceError):
        record.finalize()


def test_a_record_that_carries_a_credential_value_is_refused(tmp_path: Path) -> None:
    record = recorder(tmp_path, environment={"note": "Bearer abcdefghijklmnop"})
    with pytest.raises(EvidenceError):
        record.finalize()


def test_the_presence_of_a_credential_may_be_recorded(tmp_path: Path) -> None:
    record = recorder(tmp_path, environment={"meta_api_key_present": "false"})
    path = record.finalize()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["environment"]["meta_api_key_present"] == "false"


def test_the_three_measurement_groups_stay_apart(tmp_path: Path) -> None:
    record = recorder(tmp_path)
    record.record_metric(
        MetricGroup(
            label="accepted identity links",
            group=METRIC_GROUP_OBSERVED,
            numerator=4,
            denominator=5,
            note="the links a steward approved in the demonstration run",
        )
    )
    record.record_metric(
        MetricGroup(
            label="package agreement statistic",
            group=METRIC_GROUP_BASELINE,
            numerator=0.92,
            denominator=1.0,
            limitation="a synthetic figure of the reference package, not an observed result",
        )
    )
    record.record_metric(
        MetricGroup(
            label="issued permits",
            group=METRIC_GROUP_BUSINESS,
            numerator=1,
            denominator=1,
        )
    )
    grouped = record.build_manifest().metrics_by_group()
    assert len(grouped[METRIC_GROUP_OBSERVED]) == 1
    assert len(grouped[METRIC_GROUP_BASELINE]) == 1
    assert len(grouped[METRIC_GROUP_BUSINESS]) == 1
    assert grouped[METRIC_GROUP_OBSERVED][0].numerator == 4
    assert grouped[METRIC_GROUP_OBSERVED][0].denominator == 5
    assert grouped[METRIC_GROUP_OBSERVED][0].ratio == pytest.approx(0.8)
    assert grouped[METRIC_GROUP_BASELINE][0].limitation


def test_a_measurement_without_a_denominator_is_refused() -> None:
    metric = MetricGroup(label="a", group=METRIC_GROUP_BUSINESS, numerator=1, denominator=0)
    assert metric.ratio is None
    with pytest.raises(EvidenceError):
        MetricGroup(label="a", group="unknown_group", numerator=1, denominator=2)


def test_the_artifact_hash_matches_the_bytes_on_disk(tmp_path: Path) -> None:
    artifact = tmp_path / "collection.txt"
    artifact.write_text("tests/acceptance/test_at02.py::test_a\n", encoding="utf-8")
    record = recorder(tmp_path / "evidence")
    reference = record.record_artifact(artifact, kind="collection")
    assert reference.sha256 == sha256_file(artifact)
    assert reference.size_bytes == artifact.stat().st_size
    assert record.to_dict()["artifacts"][0]["sha256"] == reference.sha256


def test_an_artifact_without_a_hash_is_refused() -> None:
    with pytest.raises(EvidenceError):
        ArtifactRef(name="a", sha256="not-a-hash", size_bytes=1)


def test_the_tree_hash_changes_when_a_file_changes(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    (tree / "src").mkdir(parents=True)
    (tree / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    first = hash_tree(tree)
    assert first == hash_tree(tree)
    (tree / "src" / "a.py").write_text("x = 2\n", encoding="utf-8")
    assert hash_tree(tree) != first


def test_the_tree_hash_ignores_the_runtime_and_cache_directories(tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    (tree / "src").mkdir(parents=True)
    (tree / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    first = hash_tree(tree)
    (tree / "var").mkdir()
    (tree / "var" / "acme_city.db").write_text("not a database\n", encoding="utf-8")
    (tree / "__pycache__").mkdir()
    (tree / "__pycache__" / "a.cpython-312.pyc").write_bytes(b"\x00")
    assert hash_tree(tree) == first


def test_the_build_hash_covers_the_source_the_configuration_and_the_fixtures(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    for name in ("src", "config", "fixtures"):
        (root / name).mkdir(parents=True)
    (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "config" / "a.json").write_text("{}\n", encoding="utf-8")
    (root / "fixtures" / "a.json").write_text("{}\n", encoding="utf-8")
    first = build_hash(root)
    (root / "config" / "a.json").write_text('{"b": 1}\n', encoding="utf-8")
    assert build_hash(root) != first


def test_the_manifest_records_the_child_commands_and_their_exit_codes(
    tmp_path: Path,
) -> None:
    record = recorder(tmp_path)
    record.record_command(
        command="python -m pytest tests/unit -q",
        exit_code=0,
        collected=12,
        passed=12,
        skipped=0,
    )
    record.record_command(
        command="python -m pytest tests/acceptance -q",
        exit_code=1,
        collected=4,
        passed=3,
        failed=1,
    )
    payload = record.to_dict()
    assert payload["commands"][0]["exit_code"] == 0
    assert payload["commands"][1]["exit_code"] == 1
    assert payload["commands"][1]["failed"] == 1


def test_a_run_may_not_finish_before_it_starts(tmp_path: Path) -> None:
    record = recorder(tmp_path)
    manifest = record.build_manifest()
    assert manifest.finished_at >= manifest.started_at
    later = manifest.started_at + timedelta(seconds=60)
    with pytest.raises(EvidenceError):
        type(manifest)(
            run_id=manifest.run_id,
            mode=manifest.mode,
            started_at=later,
            finished_at=manifest.started_at,
            build_hash=manifest.build_hash,
            tree_hash=manifest.tree_hash,
            fixture_version=manifest.fixture_version,
            database_schema_revision=manifest.database_schema_revision,
        )


def test_the_scenario_checks_keep_their_own_kind(tmp_path: Path) -> None:
    record = recorder(tmp_path)
    record.record_check(
        CheckResult(
            check_id="D01",
            status=CHECK_STATUS_PASSED,
            expected="the alias, the unit and the legacy account reach one party",
            observed="the three links are approved and recorded",
            kind=CHECK_KIND_SCENARIO,
        )
    )
    payload = record.to_dict()
    assert payload["checks"][0]["kind"] == CHECK_KIND_SCENARIO


def test_the_secret_scan_names_the_path_of_the_offending_key() -> None:
    with pytest.raises(EvidenceError) as error:
        assert_no_secrets({"checks": [{"evidence_refs": [{"authorization": "x"}]}]})
    assert "authorization" in str(error.value)
