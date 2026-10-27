"""The evidence package.

The package holds the schemas of one acceptance run and the recorder that
writes its manifest.  It never imports the evaluator truth, it never talks to
a provider and it never writes to the application database.
"""

from __future__ import annotations

from acme_city.evidence.manifest import (
    MANIFEST_NAME,
    EvidenceRecorder,
    assert_no_secrets,
    build_hash,
    hash_tree,
    sha256_file,
    write_json_atomically,
)
from acme_city.evidence.schemas import (
    CHECK_KIND_ACCEPTANCE,
    CHECK_KIND_SCENARIO,
    CHECK_KIND_SUPPLEMENTARY,
    CHECK_KINDS,
    CHECK_STATUS_BLOCKED,
    CHECK_STATUS_FAILED,
    CHECK_STATUS_PASSED,
    CHECK_STATUSES,
    METRIC_GROUP_BASELINE,
    METRIC_GROUP_BUSINESS,
    METRIC_GROUP_OBSERVED,
    METRIC_GROUPS,
    ArtifactRef,
    CheckResult,
    EvidenceError,
    MetricGroup,
    RunManifest,
)

__all__ = [
    "CHECK_KINDS",
    "CHECK_KIND_ACCEPTANCE",
    "CHECK_KIND_SCENARIO",
    "CHECK_KIND_SUPPLEMENTARY",
    "CHECK_STATUSES",
    "CHECK_STATUS_BLOCKED",
    "CHECK_STATUS_FAILED",
    "CHECK_STATUS_PASSED",
    "MANIFEST_NAME",
    "METRIC_GROUPS",
    "METRIC_GROUP_BASELINE",
    "METRIC_GROUP_BUSINESS",
    "METRIC_GROUP_OBSERVED",
    "ArtifactRef",
    "CheckResult",
    "EvidenceError",
    "EvidenceRecorder",
    "MetricGroup",
    "RunManifest",
    "assert_no_secrets",
    "build_hash",
    "hash_tree",
    "sha256_file",
    "write_json_atomically",
]
