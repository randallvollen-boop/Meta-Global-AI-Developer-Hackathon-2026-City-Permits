"""A completed D01 chain survives an owned server restart unchanged."""
# REQUIRES: EVAL-01, EVAL-03, GOV-04

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import httpx
from sqlalchemy import select

from acme_city.persistence.models import finance, model_run, permit, registry
from acme_city.persistence.session import SessionFactory

REPO_ROOT = Path(__file__).resolve().parents[2]
PREPARE = REPO_ROOT / "scripts" / "prepare_user_test.py"
START = REPO_ROOT / "scripts" / "start_demo.py"
STOP = REPO_ROOT / "scripts" / "stop_demo.py"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def invoke(script: Path, *args: str, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )


def api_snapshot(port: int) -> dict:
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10) as client:
        selected = client.post(
            "/api/session/select", json={"actor_id": "persona_data_steward"}
        )
        assert selected.status_code == 200, selected.text
        application = client.get("/api/permits/applications/app_synth_001")
        crosswalks = client.get("/api/registry/crosswalks", params={"entity_id": "party_cedarline"})
        runs = client.get("/api/muse/runs", params={"application_id": "app_synth_001"})
        documents = client.get("/api/permits/applications/app_synth_001/documents")
        for response in (application, crosswalks, runs, documents):
            assert response.status_code == 200, response.text
        return {
            "application": application.json(),
            "crosswalk_ids": sorted(
                row["crosswalk_id"] for row in crosswalks.json()["crosswalks"]
            ),
            "model_run_ids": sorted(row["run_id"] for row in runs.json()["runs"]),
            "document_ids": sorted(row["document_id"] for row in documents.json()["documents"]),
        }


def database_snapshot(database_url: str) -> dict:
    factory = SessionFactory(database_url)
    try:
        with factory() as session:
            application = session.get(permit.Application, "app_synth_001")
            return {
                "application_id": application.id,
                "application_version": application.version,
                "application_status": application.status,
                "assessment_ids": sorted(
                    session.execute(
                        select(finance.Assessment.id).where(
                            finance.Assessment.application_id == application.id
                        )
                    ).scalars()
                ),
                "allocation_ids": sorted(session.execute(select(finance.Allocation.id)).scalars()),
                "permit_ids": sorted(
                    session.execute(
                        select(permit.Permit.id).where(
                            permit.Permit.application_id == application.id
                        )
                    ).scalars()
                ),
                "crosswalk_ids": sorted(
                    session.execute(
                        select(registry.Crosswalk.id).where(
                            registry.Crosswalk.entity_id == "party_cedarline",
                            registry.Crosswalk.link_status == "approved",
                        )
                    ).scalars()
                ),
                "model_run_ids": sorted(
                    session.execute(select(model_run.ModelRun.id)).scalars()
                ),
            }
    finally:
        factory.dispose()


def test_completed_chain_survives_stop_and_restart(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'restart.db'}"
    record = tmp_path / "process.json"
    evidence = tmp_path / "evidence"
    state = tmp_path / "state.json"
    port = free_port()
    environment = os.environ.copy()
    environment["ACME_SECRET_KEY"] = "restart-persistence-secret-value"
    environment["ACME_DATABASE_URL"] = database_url

    prepared = invoke(
        PREPARE,
        "--mode",
        "completed-reference",
        "--database",
        database_url,
        "--port",
        str(port),
        "--record",
        str(record),
        "--state-file",
        str(state),
        "--evidence-dir",
        str(evidence),
        environment=environment,
    )
    assert prepared.returncode == 0, prepared.stderr
    assert json.loads(state.read_text(encoding="utf-8"))["model_mode"] == "replay"
    before_database = database_snapshot(database_url)

    try:
        first_start = invoke(
            START,
            "--port",
            str(port),
            "--database",
            database_url,
            "--record",
            str(record),
            "--log",
            str(tmp_path / "server.log"),
            environment=environment,
        )
        assert first_start.returncode == 0, first_start.stderr
        before_api = api_snapshot(port)
        stopped = invoke(STOP, "--record", str(record), environment=environment)
        assert stopped.returncode == 0, stopped.stderr

        second_start = invoke(
            START,
            "--port",
            str(port),
            "--database",
            database_url,
            "--record",
            str(record),
            "--log",
            str(tmp_path / "server.log"),
            environment=environment,
        )
        assert second_start.returncode == 0, second_start.stderr
        after_api = api_snapshot(port)
        after_database = database_snapshot(database_url)

        assert after_api == before_api
        assert after_database == before_database
        assert after_database["application_status"] == "issued"
        assert len(after_database["permit_ids"]) == 1
        assert after_database["assessment_ids"]
        assert after_database["allocation_ids"]
        assert len(after_database["model_run_ids"]) == 1
    finally:
        if record.exists():
            invoke(STOP, "--record", str(record), environment=environment)
