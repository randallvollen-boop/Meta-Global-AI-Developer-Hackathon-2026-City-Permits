"""The local demo launcher owns only its recorded loopback process."""
# REQUIRES: GOV-04, UX-04

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parents[2]
START = REPO_ROOT / "scripts" / "start_demo.py"
STOP = REPO_ROOT / "scripts" / "stop_demo.py"
RESET = REPO_ROOT / "scripts" / "reset_demo.py"


def run_script(path: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(path), *args],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_start_refuses_non_loopback(tmp_path: Path) -> None:
    result = run_script(
        START,
        "--host",
        "0.0.0.0",
        "--record",
        str(tmp_path / "process.json"),
        "--log",
        str(tmp_path / "server.log"),
    )
    assert result.returncode == 2
    assert "outside loopback" in result.stderr


def test_start_refuses_an_occupied_port_without_touching_its_owner(tmp_path: Path) -> None:
    record = tmp_path / "process.json"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = int(listener.getsockname()[1])
        result = run_script(
            START,
            "--port",
            str(port),
            "--record",
            str(record),
            "--log",
            str(tmp_path / "server.log"),
        )
        assert result.returncode == 4
        assert "occupied" in result.stderr
        assert listener.fileno() >= 0
    assert not record.exists()


def test_start_health_stop_preserves_unrelated_process(tmp_path: Path) -> None:
    database = f"sqlite:///{tmp_path / 'demo.db'}"
    record = tmp_path / "process.json"
    log = tmp_path / "server.log"
    port = free_port()
    environment = os.environ.copy()
    environment["ACME_SECRET_KEY"] = "process-test-secret-value"
    environment["ACME_DATABASE_URL"] = database

    reset = run_script(
        RESET,
        "--database",
        database,
        "--confirm-fictional-demo",
        env=environment,
    )
    assert reset.returncode == 0, reset.stderr

    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        start = run_script(
            START,
            "--port",
            str(port),
            "--database",
            database,
            "--record",
            str(record),
            "--log",
            str(log),
            env=environment,
        )
        assert start.returncode == 0, start.stderr
        metadata = json.loads(record.read_text(encoding="utf-8"))
        owned_pid = int(metadata["pid"])
        assert owned_pid != unrelated.pid

        with urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as response:
            health = json.loads(response.read().decode("utf-8"))
        assert response.status == 200
        assert health["status"] == "ok"

        stop = run_script(STOP, "--record", str(record), env=environment)
        assert stop.returncode == 0, stop.stderr
        assert unrelated.poll() is None
        assert not record.exists()
        deadline = time.monotonic() + 3
        while Path(f"/proc/{owned_pid}").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        if Path(f"/proc/{owned_pid}/stat").exists():
            state = Path(f"/proc/{owned_pid}/stat").read_text(encoding="utf-8").split()[2]
            assert state == "Z"
    finally:
        if record.exists():
            run_script(STOP, "--record", str(record), env=environment)
        unrelated.terminate()
        unrelated.wait(timeout=5)
