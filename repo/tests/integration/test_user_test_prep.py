"""User-test preparation creates labelled, replay-safe database states."""
# REQUIRES: GOV-04, UX-04

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PREPARE = REPO_ROOT / "scripts" / "prepare_user_test.py"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def run_prepare(tmp_path: Path, mode: str, *extra: str) -> subprocess.CompletedProcess[str]:
    database = f"sqlite:///{tmp_path / f'{mode}.db'}"
    environment = os.environ.copy()
    environment["ACME_SECRET_KEY"] = "user-test-prep-secret-value"
    return subprocess.run(
        [
            sys.executable,
            str(PREPARE),
            "--mode",
            mode,
            "--database",
            database,
            "--port",
            str(free_port()),
            "--record",
            str(tmp_path / f"{mode}-process.json"),
            "--state-file",
            str(tmp_path / f"{mode}-state.json"),
            "--evidence-dir",
            str(tmp_path / f"{mode}-evidence"),
            *extra,
        ],
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )


def test_fresh_mode_resets_without_starting_a_server(tmp_path: Path) -> None:
    result = run_prepare(tmp_path, "fresh")
    assert result.returncode == 0, result.stderr
    state = json.loads((tmp_path / "fresh-state.json").read_text(encoding="utf-8"))
    assert state["mode"] == "fresh"
    assert state["model_mode"] == "none"
    assert state["server_running"] is False
    assert not (tmp_path / "fresh-process.json").exists()
    assert (tmp_path / "fresh.db").exists()


@pytest.mark.parametrize(
    ("mode", "expected_phrase"),
    [
        ("ready-for-review", "approved identity links"),
        ("completed-reference", "issued simulated permit"),
    ],
)
def test_prepared_reference_modes_are_explicit_replays(
    tmp_path: Path, mode: str, expected_phrase: str
) -> None:
    result = run_prepare(tmp_path, mode)
    assert result.returncode == 0, result.stderr
    state = json.loads((tmp_path / f"{mode}-state.json").read_text(encoding="utf-8"))
    assert state["mode"] == mode
    assert state["model_mode"] == "replay"
    assert expected_phrase in state["label"]
    assert state["server_running"] is False
    assert not (tmp_path / f"{mode}-process.json").exists()
    evidence = json.loads(
        (tmp_path / f"{mode}-evidence" / "demo-walkthrough.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["status"] == "passed"
    assert evidence["mode"] == "replay"


def test_fresh_mode_refuses_live_muse(tmp_path: Path) -> None:
    result = run_prepare(tmp_path, "fresh", "--live-muse")
    assert result.returncode == 1
    assert "requires ready-for-review or completed-reference" in result.stderr
