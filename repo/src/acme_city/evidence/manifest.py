"""The evidence recorder and the run manifest.

The recorder writes the manifest of one run.  It writes through a temporary
file and an atomic rename, so a manifest is never half written, and it
refuses to record a secret, a cookie or an authorization header.
"""
# REQUIRES: EVAL-03
# The evidence recorder writes a reproducible manifest through a temporary file and an atomic
# rename, hashes every artifact, and refuses to record a secret, a cookie or an authorization
# header.

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from acme_city.evidence.schemas import (
    ArtifactRef,
    CheckResult,
    EvidenceError,
    MetricGroup,
    RunManifest,
)

#: The name of the manifest file inside an evidence directory.
MANIFEST_NAME = "manifest.json"

#: The names that may never appear as a key of a recorded value.
FORBIDDEN_KEY_MARKERS: tuple[str, ...] = (
    "authorization",
    "cookie",
    "set-cookie",
    "api_key",
    "apikey",
    "secret",
    "password",
    "passwd",
    "credential",
    "bearer",
    "x-api-key",
    "session_token",
    "private_key",
)

#: The value patterns that look like a credential rather than like data.
FORBIDDEN_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsk-[A-Za-z0-9]{12,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"META_API_KEY\s*="),
    re.compile(r"\bACME_SECRET_KEY\s*="),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)

#: The directories that never take part in a tree hash.
EXCLUDED_DIRECTORY_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "evidence",
        "node_modules",
        "var",
    }
)

#: The file suffixes that never take part in a tree hash.
EXCLUDED_SUFFIXES: frozenset[str] = frozenset({".pyc", ".pyo", ".so", ".db", ".sqlite3"})


def sha256_bytes(payload: bytes) -> str:
    """Return the SHA-256 hash of the given bytes."""
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hash of the bytes of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def hash_tree(root: Path, *, relative_to: Path | None = None) -> str:
    """Return one hash for a whole directory tree.

    The hash covers the relative path and the content hash of every file that
    is not excluded, so a changed byte, a renamed file and an added file all
    change the result.  The order is the sorted order, so the hash is
    reproducible on any machine.
    """
    base = relative_to or root
    entries: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if EXCLUDED_DIRECTORY_NAMES.intersection(path.relative_to(root).parts):
            continue
        if path.suffix in EXCLUDED_SUFFIXES:
            continue
        relative = path.relative_to(base).as_posix()
        entries.append(f"{relative}:{sha256_file(path)}")
    return sha256_bytes("\n".join(entries).encode("utf-8"))


def build_hash(root: Path) -> str:
    """Return the hash of the application build.

    The build hash covers the application source, its configuration and its
    fixtures: the parts that decide what the application does.
    """
    parts = [
        hash_tree(root / "src"),
        hash_tree(root / "config"),
        hash_tree(root / "fixtures"),
    ]
    return sha256_bytes(":".join(parts).encode("utf-8"))


def find_secret_keys(payload: Any, path: str = "") -> list[str]:
    """Return the paths of every key that names a credential."""
    found: list[str] = []
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            lowered = str(key).lower()
            names_a_credential = any(marker in lowered for marker in FORBIDDEN_KEY_MARKERS)
            # A key that reports the presence of a credential names no
            # credential value, so it may be recorded.
            reports_presence = lowered.endswith("_present") or lowered.endswith("_configured")
            if names_a_credential and not reports_presence:
                found.append(f"{path}/{key}")
            found.extend(find_secret_keys(value, f"{path}/{key}"))
    elif isinstance(payload, (list, tuple)):
        for index, item in enumerate(payload):
            found.extend(find_secret_keys(item, f"{path}[{index}]"))
    return found


def find_secret_values(payload: Any) -> list[str]:
    """Return every string value that looks like a credential."""
    found: list[str] = []
    if isinstance(payload, Mapping):
        for value in payload.values():
            found.extend(find_secret_values(value))
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            found.extend(find_secret_values(item))
    elif isinstance(payload, str):
        for pattern in FORBIDDEN_VALUE_PATTERNS:
            if pattern.search(payload):
                found.append(payload[:40])
                break
    return found


def assert_no_secrets(payload: Any) -> None:
    """Refuse a record that carries a credential, a cookie or a header.

    The evidence of a run is local, but it is still evidence: a recorded
    session cookie or an authorization header would make the run
    unreproducible and would put a credential in a file that is meant to be
    read by other people.
    """
    secret_keys = find_secret_keys(payload)
    if secret_keys:
        raise EvidenceError(
            "the record names a credential at: " + ", ".join(sorted(secret_keys)[:5])
        )
    secret_values = find_secret_values(payload)
    if secret_values:
        raise EvidenceError("the record carries a value that looks like a credential")


def write_json_atomically(path: Path, payload: Any) -> Path:
    """Write JSON through a temporary file and an atomic rename.

    A reader either sees the previous file or the complete new one.  The
    temporary file carries the identifier of the process, so two runs never
    write over each other.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    text = json.dumps(payload, indent=2, sort_keys=True, default=str)
    temporary.write_text(f"{text}\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


class EvidenceRecorder:
    """Collects the results of one run and writes its manifest.

    The recorder holds the run facts that do not change while the run runs,
    the checks it is told about and the artifacts it is given.  It writes the
    manifest only when :meth:`finalize` is called, and the written manifest is
    free of secrets, cookies and authorization headers.
    """

    def __init__(
        self,
        directory: Path | str,
        *,
        run_id: str,
        mode: str,
        started_at: datetime | None = None,
        build_hash_value: str = "",
        tree_hash_value: str = "",
        fixture_version: str = "",
        database_schema_revision: str = "",
        source_snapshots: Mapping[str, str] | None = None,
        model: Mapping[str, str] | None = None,
        prompt_versions: Mapping[str, str] | None = None,
        schema_versions: Mapping[str, str] | None = None,
        rule_versions: Mapping[str, str] | None = None,
        actors: Iterable[str] = (),
        environment: Mapping[str, str] | None = None,
    ) -> None:
        """Prepare a recorder for one run.

        Args:
            directory: The evidence directory that receives the manifest.
            run_id: The identifier of the run.
            mode: The mode of the run, for example ``deterministic``.
            started_at: When the run started.  Defaults to now.
            build_hash_value: The hash of the application build.
            tree_hash_value: The hash of the whole tree.
            fixture_version: The version of the fixture bundle.
            database_schema_revision: The migration revision of the database.
            source_snapshots: The hash of every source snapshot that was read.
            model: The provider, the model and the mode of the model run.
            prompt_versions: The prompt version of every model task.
            schema_versions: The schema version of every model task.
            rule_versions: The rule version of every applied rule set.
            actors: The actors that acted during the run.
            environment: The non-sensitive facts about the environment.
        """
        self.directory = Path(directory)
        self.run_id = run_id
        self.mode = mode
        self.started_at = started_at or datetime.now(UTC)
        self.build_hash = build_hash_value
        self.tree_hash = tree_hash_value
        self.fixture_version = fixture_version
        self.database_schema_revision = database_schema_revision
        self.source_snapshots = dict(source_snapshots or {})
        self.model = dict(model or {})
        self.prompt_versions = dict(prompt_versions or {})
        self.schema_versions = dict(schema_versions or {})
        self.rule_versions = dict(rule_versions or {})
        self.actors = tuple(actors)
        self.environment = dict(environment or {})
        self._checks: list[CheckResult] = []
        self._artifacts: list[ArtifactRef] = []
        self._metrics: list[MetricGroup] = []
        self._failures: list[str] = []
        self._commands: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ record

    def record_check(self, result: CheckResult) -> None:
        """Record the result of one check."""
        self._checks.append(result)
        if result.status != "passed" and result.failure:
            self._failures.append(f"{result.check_id}: {result.failure}")

    def record_artifact(
        self, path: Path | str, *, name: str | None = None, kind: str = "artifact"
    ) -> ArtifactRef:
        """Record one artifact and the hash of its bytes."""
        target = Path(path)
        if not target.is_file():
            raise EvidenceError(f"the artifact {target.name} does not exist")
        artifact = ArtifactRef(
            name=name or target.name,
            sha256=sha256_file(target),
            size_bytes=target.stat().st_size,
            kind=kind,
        )
        self._artifacts.append(artifact)
        return artifact

    def record_metric(self, metric: MetricGroup) -> None:
        """Record one measurement in its own labelled group."""
        self._metrics.append(metric)

    def record_command(
        self,
        *,
        command: str,
        exit_code: int,
        collected: int = 0,
        passed: int = 0,
        failed: int = 0,
        skipped: int = 0,
        duration_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Record one child command and its exit code."""
        entry = {
            "command": command,
            "exit_code": exit_code,
            "collected": collected,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "duration_seconds": duration_seconds,
        }
        self._commands.append(entry)
        return entry

    def record_failure(self, reason: str) -> None:
        """Record a failure of the run that belongs to no single check."""
        if reason:
            self._failures.append(reason)

    # ----------------------------------------------------------------- finalize

    def build_manifest(self) -> RunManifest:
        """Return the manifest of the run without writing it."""
        return RunManifest(
            run_id=self.run_id,
            mode=self.mode,
            started_at=self.started_at,
            finished_at=datetime.now(UTC),
            build_hash=self.build_hash,
            tree_hash=self.tree_hash,
            fixture_version=self.fixture_version,
            database_schema_revision=self.database_schema_revision,
            source_snapshots=self.source_snapshots,
            model=self.model,
            prompt_versions=self.prompt_versions,
            schema_versions=self.schema_versions,
            rule_versions=self.rule_versions,
            actors=self.actors,
            checks=tuple(self._checks),
            artifacts=tuple(self._artifacts),
            metrics=tuple(self._metrics),
            failures=tuple(self._failures),
            commands=tuple(self._commands),
            environment=self.environment,
        )

    def finalize(self) -> Path:
        """Write the manifest and return the path of the written file."""
        manifest = self.build_manifest()
        payload = manifest.to_dict()
        assert_no_secrets(payload)
        return write_json_atomically(self.directory / MANIFEST_NAME, payload)

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-ready form of the manifest without writing it."""
        return self.build_manifest().to_dict()


__all__ = [
    "EXCLUDED_DIRECTORY_NAMES",
    "FORBIDDEN_KEY_MARKERS",
    "MANIFEST_NAME",
    "EvidenceRecorder",
    "assert_no_secrets",
    "build_hash",
    "find_secret_keys",
    "find_secret_values",
    "hash_tree",
    "sha256_bytes",
    "sha256_file",
    "write_json_atomically",
]
