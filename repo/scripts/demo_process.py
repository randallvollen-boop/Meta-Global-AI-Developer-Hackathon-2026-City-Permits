"""Owned-process helpers for the local ACME City demonstration server."""

from __future__ import annotations

import json
import os
import signal
import socket
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECORD = REPO_ROOT / "var" / "demo-process.json"
DEFAULT_LOG = REPO_ROOT / "var" / "demo-server.log"
APP_TARGET = "acme_city.app:create_app"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    """Write JSON without exposing a partially written process record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def process_start_ticks(pid: int) -> int | None:
    """Return Linux process start ticks, which distinguishes PID reuse."""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
        return int(fields[21])
    except (OSError, ValueError, IndexError):
        return None


def process_command(pid: int) -> list[str] | None:
    """Return a process command as tokens without shell interpretation."""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return None
    tokens = [part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part]
    return tokens or None


def pid_is_alive(pid: int) -> bool:
    """Return whether a non-zombie process currently exists."""
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
        if len(fields) > 2 and fields[2] == "Z":
            return False
        os.kill(pid, 0)
    except (ProcessLookupError, FileNotFoundError):
        return False
    except (PermissionError, OSError):
        return True
    return True


def port_is_available(host: str, port: int) -> bool:
    """Check whether the requested loopback address can be bound."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def health_is_ready(host: str, port: int, *, timeout: float = 0.5) -> bool:
    """Return true only for the application's healthy JSON response."""
    try:
        with urlopen(f"http://{host}:{port}/healthz", timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
            return response.status == 200 and body.get("status") == "ok"
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return False


def wait_for_health(host: str, port: int, *, timeout: float) -> bool:
    """Wait for a bounded period for the owned server to become healthy."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if health_is_ready(host, port):
            return True
        time.sleep(0.1)
    return False


def read_record(path: Path = DEFAULT_RECORD) -> dict[str, Any]:
    """Read and minimally validate the owned-process record."""
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {"pid", "process_start_ticks", "host", "port", "repository", "app_target"}
    if not required.issubset(data):
        missing = sorted(required - set(data))
        raise ValueError(f"process record is missing fields: {', '.join(missing)}")
    return data


def record_matches_process(record: dict[str, Any]) -> bool:
    """Verify PID identity, repository, app target and command before signaling."""
    try:
        pid = int(record["pid"])
        expected_ticks = int(record["process_start_ticks"])
        port = str(int(record["port"]))
    except (KeyError, TypeError, ValueError):
        return False
    if Path(str(record.get("repository", ""))).resolve() != REPO_ROOT:
        return False
    if record.get("app_target") != APP_TARGET:
        return False
    if process_start_ticks(pid) != expected_ticks:
        return False
    command = process_command(pid)
    if command is None:
        return False
    joined = "\0".join(command)
    return (
        "uvicorn" in joined
        and APP_TARGET in command
        and "--port" in command
        and port in command
    )


def terminate_owned_process(record: dict[str, Any], *, timeout: float = 8.0) -> bool:
    """Terminate only the process whose live identity matches the record."""
    if not record_matches_process(record):
        return False
    pid = int(record["pid"])
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_is_alive(pid) or process_start_ticks(pid) != int(record["process_start_ticks"]):
            return True
        time.sleep(0.1)
    if not record_matches_process(record):
        return not pid_is_alive(pid)
    os.kill(pid, signal.SIGKILL)
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if not pid_is_alive(pid) or process_start_ticks(pid) != int(record["process_start_ticks"]):
            return True
        time.sleep(0.1)
    return False
