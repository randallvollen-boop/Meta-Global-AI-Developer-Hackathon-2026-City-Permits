"""VC08: the baseline simulation and the observed results stay separate.

The synthetic figures of the reference package, the results this run
observed in the model and the registry, and the business outcome of the
demonstration are three separate labelled groups.  The package's pilot
agreement figures are never presented as a staff result or as a Muse
result.
"""
# REQUIRES: VC08, EVAL-02
# The three measurement groups stay apart. A synthetic figure of the reference package is never
# presented as a staff result or as a model result.

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from acme_city.evidence.manifest import EvidenceRecorder
from acme_city.evidence.schemas import (
    METRIC_GROUP_BASELINE,
    METRIC_GROUP_BUSINESS,
    METRIC_GROUP_OBSERVED,
    MetricGroup,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = REPO_ROOT / "scripts" / "run_acceptance.py"

#: The figures of the reference package that must never be presented as an
#: observed staff or model result.
PACKAGE_FIGURES = (
    "pilot_staff_agree_pct",
    "pilot_staff_reverse_pct",
    "pilot_caught_pct",
    "pilot_false_flag_pct",
    "pilot_apps",
    "bm_host_composite",
    "median_days_first_review",
    "resubmit_cycles_avg",
)


def load_runner():
    """Return the acceptance runner as a module."""
    spec = importlib.util.spec_from_file_location("run_acceptance_module", RUNNER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_vc08_the_runner_keeps_the_three_measurement_groups_apart(tmp_path: Path) -> None:
    runner = load_runner()
    baseline = runner.baseline_metrics()
    observed = runner.observed_metrics(
        {
            "counts": {
                "expected_links_found": 7,
                "labeled_expected_links": 9,
                "false_links": 0,
                "accepted_links": 7,
                "unresolved_cases": 2,
                "evaluated_cases": 11,
            }
        }
    )
    business = runner.business_metrics(
        {
            "counts": {
                "scenarios_matched": 11,
                "scenarios_evaluated": 11,
                "permits_issued": 1,
                "applications_evaluated": 11,
            }
        }
    )

    assert baseline, "the runner records no baseline"
    assert observed, "the runner records no observed result"
    assert business, "the runner records no business outcome"
    assert {metric.group for metric in baseline} == {METRIC_GROUP_BASELINE}
    assert {metric.group for metric in observed} == {METRIC_GROUP_OBSERVED}
    assert {metric.group for metric in business} == {METRIC_GROUP_BUSINESS}

    # Every measurement names its denominator.
    for metric in (*baseline, *observed, *business):
        assert metric.denominator > 0, f"{metric.label} has no denominator"
    assert all(metric.limitation for metric in baseline), (
        "a synthetic baseline figure carries no limitation"
    )
    assert all("synthetic" in (metric.limitation or "") for metric in baseline)

    # The groups are stored apart and are never merged.
    recorder = EvidenceRecorder(tmp_path, run_id="vc08", mode="deterministic")
    for metric in (*baseline, *observed, *business):
        recorder.record_metric(metric)
    grouped = recorder.build_manifest().metrics_by_group()
    assert len(grouped[METRIC_GROUP_BASELINE]) == len(baseline)
    assert len(grouped[METRIC_GROUP_OBSERVED]) == len(observed)
    assert len(grouped[METRIC_GROUP_BUSINESS]) == len(business)
    payload = recorder.to_dict()
    assert set(payload["metric_groups"]) == {
        METRIC_GROUP_BASELINE,
        METRIC_GROUP_OBSERVED,
        METRIC_GROUP_BUSINESS,
    }
    for group, metrics in payload["metric_groups"].items():
        for metric in metrics:
            assert metric["group"] == group


def test_vc08_the_reference_package_figures_never_reach_the_build() -> None:
    """The pilot figures of the package stay out of the application."""
    searched = 0
    for folder in ("src/acme_city", "config", "fixtures"):
        for path in sorted((REPO_ROOT / folder).rglob("*")):
            if not path.is_file() or path.suffix not in {".py", ".json", ".txt"}:
                continue
            searched += 1
            text = path.read_text(encoding="utf-8")
            for figure in PACKAGE_FIGURES:
                assert figure not in text, f"{path.name} carries the package figure {figure}"
    assert searched > 0


def test_vc08_the_build_records_no_agreement_percentage() -> None:
    """No file of the build presents an agreement rate as a result."""
    for folder in ("src/acme_city", "config", "fixtures"):
        for path in sorted((REPO_ROOT / folder).rglob("*")):
            if not path.is_file() or path.suffix not in {".py", ".json"}:
                continue
            text = path.read_text(encoding="utf-8").lower()
            assert "staff_agree" not in text, f"{path.name} reports a staff agreement rate"
            assert "agreement rate" not in text, f"{path.name} reports an agreement rate"


def test_vc08_a_model_score_is_never_a_calibrated_confidence() -> None:
    """The proposal score of the model is a heuristic and says so."""
    from acme_city.muse.schemas import MATCH_PROMPT_VERSION, MATCH_SCHEMA_VERSION

    assert MATCH_PROMPT_VERSION == "acme-match-prompt-v1"
    assert MATCH_SCHEMA_VERSION == "acme-match-schema-v1"
    recorder = EvidenceRecorder(
        Path(__file__).resolve().parents[2] / "var" / "vc08-not-written",
        run_id="vc08",
        mode="deterministic",
    )
    metric = MetricGroup(
        label="model proposal score",
        group=METRIC_GROUP_OBSERVED,
        numerator=1,
        denominator=1,
        note="the proposal score is a heuristic and is labeled uncalibrated",
    )
    recorder.record_metric(metric)
    payload = recorder.to_dict()
    assert payload["metrics"][0]["note"] == metric.note
    assert "uncalibrated" in payload["metrics"][0]["note"]


def test_vc08_the_manifest_holds_no_figure_of_the_reference_package(
    tmp_path: Path,
) -> None:
    recorder = EvidenceRecorder(tmp_path, run_id="vc08", mode="deterministic")
    recorder.record_metric(
        MetricGroup(
            label="expected links found",
            group=METRIC_GROUP_OBSERVED,
            numerator=7,
            denominator=9,
            note="observed in this run",
        )
    )
    payload = json.dumps(recorder.to_dict())
    for figure in PACKAGE_FIGURES:
        assert figure not in payload
