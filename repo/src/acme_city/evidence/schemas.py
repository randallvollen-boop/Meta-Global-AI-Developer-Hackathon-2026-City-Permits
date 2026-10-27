"""The schemas of one acceptance run.

Every value here describes what was expected, what was observed and which
requirement the check belongs to.  Nothing in this module writes to the
database, reads the evaluator truth or talks to a provider: it is a record of
what a run did.
"""
# REQUIRES: EVAL-01, EVAL-02, EVAL-03
# The evidence schemas carry the expected outcome, the observed outcome, the requirement
# identifiers, the artifact references and the failures of every check, and they separate
# the baseline synthetic measurements from the observed results and the business outcomes.

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

#: The three outcomes a check may have.  A blocked check is never a passed
#: check: a check that could not run is reported as blocked and stays blocked.
CHECK_STATUS_PASSED: str = "passed"
CHECK_STATUS_FAILED: str = "failed"
CHECK_STATUS_BLOCKED: str = "blocked"
CHECK_STATUSES: tuple[str, ...] = (CHECK_STATUS_PASSED, CHECK_STATUS_FAILED, CHECK_STATUS_BLOCKED)

#: The measurement groups.  They never mix: the synthetic baseline of the
#: demonstration, the observed model and registry results, and the business
#: outcomes are three separate labelled groups.
METRIC_GROUP_BASELINE: str = "baseline_synthetic"
METRIC_GROUP_OBSERVED: str = "observed_model_registry"
METRIC_GROUP_BUSINESS: str = "business_outcome"
METRIC_GROUPS: tuple[str, ...] = (
    METRIC_GROUP_BASELINE,
    METRIC_GROUP_OBSERVED,
    METRIC_GROUP_BUSINESS,
)

#: The kinds of check the inventory holds.
CHECK_KIND_ACCEPTANCE: str = "acceptance"
CHECK_KIND_SUPPLEMENTARY: str = "supplementary"
CHECK_KIND_SCENARIO: str = "scenario"
CHECK_KINDS: tuple[str, ...] = (
    CHECK_KIND_ACCEPTANCE,
    CHECK_KIND_SUPPLEMENTARY,
    CHECK_KIND_SCENARIO,
)


class EvidenceError(ValueError):
    """Raised when a run record would be dishonest or unusable."""


@dataclass(frozen=True)
class CheckResult:
    """The result of one requirement-linked check.

    Attributes:
        check_id: The identifier of the check, for example ``AT02``.
        status: ``passed``, ``failed`` or ``blocked``.
        requirement_ids: The requirements the check belongs to.
        expected: What the check was supposed to show.
        observed: What the run actually showed.
        evidence_refs: The record identifiers, versions or artifact hashes that
            back the observation.
        failure: Why the check failed or was blocked.  A passed check has
            none, and a failed or blocked check always has one.
        kind: The family of the check.
        node_ids: The collected test nodes that produced the observation.
        duration_seconds: How long the check took, when it was measured.
        live_required: Whether the check needs a live provider run.
    """

    check_id: str
    status: str
    requirement_ids: tuple[str, ...] = ()
    expected: str = ""
    observed: str = ""
    evidence_refs: tuple[str, ...] = ()
    failure: str | None = None
    kind: str = CHECK_KIND_ACCEPTANCE
    node_ids: tuple[str, ...] = ()
    duration_seconds: float | None = None
    live_required: bool = False

    def __post_init__(self) -> None:
        """Refuse a result that would overstate what happened."""
        if not self.check_id:
            raise EvidenceError("a check result needs a check identifier")
        if self.status not in CHECK_STATUSES:
            raise EvidenceError(
                f"the status {self.status!r} of {self.check_id} is not one of {CHECK_STATUSES}"
            )
        if self.kind not in CHECK_KINDS:
            raise EvidenceError(f"the kind {self.kind!r} of {self.check_id} is unknown")
        if self.status == CHECK_STATUS_PASSED and self.failure:
            raise EvidenceError(f"the passed check {self.check_id} may not carry a failure")
        if self.status in {CHECK_STATUS_FAILED, CHECK_STATUS_BLOCKED} and not self.failure:
            raise EvidenceError(
                f"the {self.status} check {self.check_id} needs a reason"
            )

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-ready form of the result."""
        return {
            "check_id": self.check_id,
            "kind": self.kind,
            "status": self.status,
            "requirement_ids": list(self.requirement_ids),
            "expected": self.expected,
            "observed": self.observed,
            "evidence_refs": list(self.evidence_refs),
            "failure": self.failure,
            "node_ids": list(self.node_ids),
            "duration_seconds": self.duration_seconds,
            "live_required": self.live_required,
        }


@dataclass(frozen=True)
class ArtifactRef:
    """One artifact of a run and the hash of its bytes."""

    name: str
    sha256: str
    size_bytes: int
    kind: str = "artifact"

    def __post_init__(self) -> None:
        """Refuse an artifact without a name or a hash."""
        if not self.name:
            raise EvidenceError("an artifact needs a name")
        if len(self.sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.sha256
        ):
            raise EvidenceError(f"the artifact {self.name} has no valid SHA-256 hash")

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-ready form of the artifact."""
        return {
            "name": self.name,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class MetricGroup:
    """One measurement with an explicit denominator.

    The denominator is always stated.  A measurement over a small fictional
    fixture is a demonstration check, not an estimate of real-world accuracy,
    and the limitation says so.
    """

    label: str
    group: str
    numerator: float
    denominator: float
    unit: str = "count"
    limitation: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        """Refuse a measurement without a denominator or an unknown group."""
        if not self.label:
            raise EvidenceError("a metric needs a label")
        if self.group not in METRIC_GROUPS:
            raise EvidenceError(f"the metric group {self.group!r} is unknown")
        if self.denominator < 0:
            raise EvidenceError("a metric denominator may not be negative")
        if self.numerator < 0:
            raise EvidenceError("a metric numerator may not be negative")

    @property
    def ratio(self) -> float | None:
        """Return the ratio, or ``None`` when the denominator is zero."""
        if self.denominator == 0:
            return None
        return self.numerator / self.denominator

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-ready form of the measurement."""
        return {
            "label": self.label,
            "group": self.group,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "unit": self.unit,
            "ratio": self.ratio,
            "limitation": self.limitation,
            "note": self.note,
        }


@dataclass(frozen=True)
class RunManifest:
    """The manifest of one acceptance run.

    The manifest names the build it ran against, the versions of the fixture,
    the schema, the sources, the model, the prompts, the schemas and the rules
    it used, the actors that acted, the checks it ran with their expected and
    actual outcomes, the failures it hit and the hashes of its artifacts.
    """

    run_id: str
    mode: str
    started_at: datetime
    finished_at: datetime
    build_hash: str
    tree_hash: str
    fixture_version: str
    database_schema_revision: str
    source_snapshots: dict[str, str] = field(default_factory=dict)
    model: dict[str, str] = field(default_factory=dict)
    prompt_versions: dict[str, str] = field(default_factory=dict)
    schema_versions: dict[str, str] = field(default_factory=dict)
    rule_versions: dict[str, str] = field(default_factory=dict)
    actors: tuple[str, ...] = ()
    checks: tuple[CheckResult, ...] = ()
    artifacts: tuple[ArtifactRef, ...] = ()
    metrics: tuple[MetricGroup, ...] = ()
    failures: tuple[str, ...] = ()
    commands: tuple[dict[str, Any], ...] = ()
    environment: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Refuse a manifest that is not internally coherent."""
        if not self.run_id:
            raise EvidenceError("a run manifest needs a run identifier")
        if self.finished_at < self.started_at:
            raise EvidenceError("a run cannot finish before it starts")
        seen: set[str] = set()
        for check in self.checks:
            if check.check_id in seen:
                raise EvidenceError(f"the check {check.check_id} appears twice in the manifest")
            seen.add(check.check_id)

    def checks_by_kind(self, kind: str) -> tuple[CheckResult, ...]:
        """Return the checks of one family."""
        return tuple(check for check in self.checks if check.kind == kind)

    def status_counts(self) -> dict[str, int]:
        """Return the number of checks in every status."""
        counts = {status: 0 for status in CHECK_STATUSES}
        for check in self.checks:
            counts[check.status] += 1
        return counts

    def metrics_by_group(self) -> dict[str, list[MetricGroup]]:
        """Return the measurements of every group, kept apart."""
        grouped: dict[str, list[MetricGroup]] = {group: [] for group in METRIC_GROUPS}
        for metric in self.metrics:
            grouped[metric.group].append(metric)
        return grouped

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-ready form of the manifest."""
        return {
            "run_id": self.run_id,
            "mode": self.mode,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "build_hash": self.build_hash,
            "tree_hash": self.tree_hash,
            "fixture_version": self.fixture_version,
            "database_schema_revision": self.database_schema_revision,
            "source_snapshots": dict(self.source_snapshots),
            "model": dict(self.model),
            "prompt_versions": dict(self.prompt_versions),
            "schema_versions": dict(self.schema_versions),
            "rule_versions": dict(self.rule_versions),
            "actors": list(self.actors),
            "checks": [check.to_dict() for check in self.checks],
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "metrics": [metric.to_dict() for metric in self.metrics],
            "metric_groups": {
                group: [metric.to_dict() for metric in metrics]
                for group, metrics in self.metrics_by_group().items()
            },
            "failures": list(self.failures),
            "commands": [dict(command) for command in self.commands],
            "environment": dict(self.environment),
            "status_counts": self.status_counts(),
        }


__all__ = [
    "CHECK_KIND_ACCEPTANCE",
    "CHECK_KIND_SCENARIO",
    "CHECK_KIND_SUPPLEMENTARY",
    "CHECK_KINDS",
    "CHECK_STATUS_BLOCKED",
    "CHECK_STATUS_FAILED",
    "CHECK_STATUS_PASSED",
    "CHECK_STATUSES",
    "METRIC_GROUP_BASELINE",
    "METRIC_GROUP_BUSINESS",
    "METRIC_GROUP_OBSERVED",
    "METRIC_GROUPS",
    "ArtifactRef",
    "CheckResult",
    "EvidenceError",
    "MetricGroup",
    "RunManifest",
]
