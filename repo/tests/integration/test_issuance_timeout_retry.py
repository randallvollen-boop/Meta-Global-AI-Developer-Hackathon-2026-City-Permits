"""A caller retry after an issuance response loss returns one stored permit."""
# REQUIRES: PER-05, CHG-05, EVAL-01

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

from sqlalchemy import select

from acme_city.persistence.models import permit
from acme_city.persistence.session import SessionFactory

REPO_ROOT = Path(__file__).resolve().parents[2]
PREPARE = REPO_ROOT / "scripts" / "prepare_user_test.py"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_response_loss_retry_keeps_the_original_permit(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'retry.db'}"
    evidence_dir = tmp_path / "evidence"
    environment = os.environ.copy()
    environment["ACME_SECRET_KEY"] = "issuance-retry-secret-value"
    result = subprocess.run(
        [
            sys.executable,
            str(PREPARE),
            "--mode",
            "completed-reference",
            "--database",
            database_url,
            "--port",
            str(free_port()),
            "--record",
            str(tmp_path / "process.json"),
            "--state-file",
            str(tmp_path / "state.json"),
            "--evidence-dir",
            str(evidence_dir),
        ],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    evidence = json.loads(
        (evidence_dir / "demo-walkthrough.json").read_text(encoding="utf-8")
    )
    assert evidence["status"] == "passed"
    assert evidence["mode"] == "replay"
    step_names = [step["step"] for step in evidence["steps"]]
    assert "issue simulated permit" in step_names
    assert "retry issuance after simulated response loss" in step_names

    factory = SessionFactory(database_url)
    try:
        with factory() as session:
            rows = session.execute(
                select(permit.Permit).where(
                    permit.Permit.application_id == "app_synth_001"
                )
            ).scalars().all()
            assert len(rows) == 1
            issued = rows[0]
            assert issued.id == evidence["records"]["permit_id"]
            assert issued.permit_number == evidence["records"]["permit_number"]
            assert issued.artifact_hash == evidence["records"]["artifact_hash"]
            assert issued.issuance_command_key == "issue:walkthrough:d01"
    finally:
        factory.dispose()
