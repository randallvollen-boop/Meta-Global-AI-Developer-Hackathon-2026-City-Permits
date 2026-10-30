"""The container seed leaves the steward assistant a task it is sure of.

The deployment seeds its demonstration with the three commands of
``docker/entrypoint.py``: the ready-for-review case, the synthetic year and
the steward demonstration.  The D01 walkthrough of the first step decides the
two Cedarline links, so the steward must still meet a task the assistant is
sure of once the sequence is over.  One press of **Prepare recommendations**
has to show every level of certainty: High, Review and Held.

The commands are the commands of the container, run against a scratch copy of
the scripts so the test never touches the state of the machine it runs on.

Fictional ACME City data only.
"""
# REQUIRES: MDM-02, UX-01, PER-04

from __future__ import annotations

import importlib.util
import re
import shutil
import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.core.config import Settings
from acme_city.persistence.models import registry
from acme_city.persistence.models.steward_recommendation import StewardRecommendation
from acme_city.persistence.session import SessionFactory
from acme_city.ui.router import router as ui_router

REPO_ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = REPO_ROOT / "docker" / "entrypoint.py"
SOURCE_ROOT = REPO_ROOT / "src"
SECRET = "container-seed-secret-value"


def free_port() -> int:
    """Return a port nothing listens on."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def container_entrypoint() -> object:
    """Return the module of the container entrypoint.

    The module reads the root of the application when it is loaded, so the
    root is set before it is loaded.
    """
    spec = importlib.util.spec_from_file_location(
        "_acme_container_entrypoint", ENTRYPOINT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def seeded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Return the database the container seed built."""
    # The seed keeps the state of the demonstration in the root of the
    # application: the record of the server, the state file and the evidence
    # of the walkthrough.  A scratch root keeps them out of the repository.
    app_root = tmp_path / "app"
    app_root.mkdir()
    shutil.copytree(REPO_ROOT / "scripts", app_root / "scripts")
    (app_root / "fixtures").symlink_to(REPO_ROOT / "fixtures")
    database = tmp_path / "container-seed.db"
    monkeypatch.setenv("ACME_APP_ROOT", str(app_root))
    monkeypatch.setenv("ACME_DATABASE_URL", f"sqlite:///{database}")
    monkeypatch.setenv("ACME_SEED_PORT", str(free_port()))
    monkeypatch.setenv("ACME_SECRET_KEY", SECRET)
    monkeypatch.setenv("ACME_KEY_FILE", str(tmp_path / "missing.env"))
    # The seed runs the scripts of this checkout, not the installed package.
    monkeypatch.setenv("PYTHONPATH", str(SOURCE_ROOT))
    assert container_entrypoint().seed_demo() == 0
    return f"sqlite:///{database}"


def choose(client: TestClient, actor_id: str) -> None:
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def csrf(client: TestClient, path: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', client.get(path).text)
    assert match, path
    return match.group(1)


def post(client: TestClient, action: str, fields: dict[str, str], next_path: str):
    return client.post(
        f"/ui/actions/{action}",
        data={"csrf_token": csrf(client, next_path), "next": next_path, **fields},
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )


def test_the_container_seed_shows_every_level_of_certainty(
    seeded: str, tmp_path: Path
) -> None:
    """One press after the container seed shows High, Review and Held."""
    settings = Settings.load(
        environ={"ACME_DATABASE_URL": seeded, "ACME_SECRET_KEY": SECRET},
        key_file=tmp_path / "missing.env",
    )
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as client:
        # The Agent Operator wakes the steward assistant.
        choose(client, "persona_agent_operator")
        response = client.post(
            "/ui/actions/agent.toggle",
            data={
                "csrf_token": csrf(client, "/agent/steward_assist"),
                "next": "/agent/steward_assist",
                "agent_key": "steward_assist",
                "mode": "awake",
            },
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )
        assert response.status_code == 200, response.text
        # The Data Steward presses Prepare once.
        choose(client, "persona_data_steward")
        prepared = post(client, "steward.assist.prepare", {"next": "/steward"}, "/steward")
        assert prepared.status_code == 200, prepared.text
        body = client.get("/steward?filter=needs_review").text
        pills = set(re.findall(r'data-testid="recommendation-pill">([^<]+)<', body))
        assert pills == {"High", "Review", "Held"}

    # The walkthrough of the first step decided the two Cedarline links, and
    # the record the demonstration offers besides them is the one the
    # assistant is sure of.
    factory = SessionFactory(seeded)
    try:
        with factory() as session:
            links = session.execute(select(registry.Crosswalk)).scalars().all()
            decided = {
                row.source_record_id for row in links if row.link_status == "approved"
            }
            assert {"PER-AP-0003", "ERP-BL-00412"} <= decided
            rows = session.execute(select(StewardRecommendation)).scalars().all()
            sure = {
                str((row.evidence or {}).get("source_record_id") or "")
                for row in rows
                if row.confidence == "high"
            }
            assert sure == {"ERP-BL-00710"}
    finally:
        factory.dispose()
