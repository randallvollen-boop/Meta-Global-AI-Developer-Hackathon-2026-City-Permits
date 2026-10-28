"""The evaluation kernels are side-effect free by construction.

Two checks that cannot pass vacuously: a fresh interpreter that imports every
pure module must not have loaded the database layer, and the source of those
modules must not reach for a session, the clock, randomness, the network or a
file.  A control module that does is shown to be caught.
"""
# REQUIRES: PER-02
# The pure kernels import no persistence, clock, randomness or network module.

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "acme_city"

PURE_MODULES = (
    "kernel/__init__.py",
    "kernel/findings.py",
    "kernel/inputs.py",
    "kernel/intake.py",
    "kernel/adjudication.py",
    "kernel/selection.py",
    "rules/evaluator.py",
    "finance/calculator.py",
    "policy/__init__.py",
    "policy/config.py",
    "policy/changes.py",
    "policy/population.py",
    "policy/kernel.py",
    "policy/fees.py",
    "policy/impact.py",
)

FORBIDDEN_IMPORTS = (
    "sqlalchemy",
    "acme_city.persistence",
    "acme_city.core.clock",
    "acme_city.core.ids",
    "acme_city.audit",
    "acme_city.auth",
    "random",
    "secrets",
    "socket",
    "http",
    "httpx",
    "requests",
    "urllib",
    "subprocess",
    "os",
    "pathlib",
    "shutil",
    "acme_city.muse",
    "acme_city.agents",
    "acme_city.permits",
    "acme_city.policy.baseline",
    "acme_city.policy.loader",
)

FORBIDDEN_CALLS = ("open", "now", "utcnow", "today", "random", "uuid4", "new_id", "utc_now")

#: Methods that only matter on a database session (a set also has ``add``).
SESSION_CALLS = ("add", "add_all", "flush", "commit", "execute", "delete", "merge", "refresh")


def violations(source: str) -> list[str]:
    tree = ast.parse(source)
    found: list[str] = []
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for name in names:
            for banned in FORBIDDEN_IMPORTS:
                if name == banned or name.startswith(banned + "."):
                    found.append(f"import {name}")
        if isinstance(node, ast.Call):
            func = node.func
            called = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if called in FORBIDDEN_CALLS:
                found.append(f"call {called}()")
            if (
                called in SESSION_CALLS
                and isinstance(func, ast.Attribute)
                and "session" in ast.unparse(func.value).lower()
            ):
                found.append(f"call {called}()")
    return found


@pytest.mark.parametrize("relative", PURE_MODULES)
def test_pure_modules_reach_for_no_session_clock_randomness_network_or_file(relative: str) -> None:
    source = (SRC / relative).read_text(encoding="utf-8")
    assert violations(source) == [], relative


def test_the_scan_catches_a_module_that_does_reach_for_them() -> None:
    bad = (
        "from sqlalchemy.orm import Session\n"
        "from acme_city.core.clock import utc_now\n"
        "def f(session):\n    session.add(1)\n    session.flush()\n    return utc_now()\n"
    )
    found = violations(bad)
    assert "import sqlalchemy.orm" in found
    assert "import acme_city.core.clock" in found
    assert "call add()" in found and "call flush()" in found and "call utc_now()" in found


def test_importing_every_pure_module_never_loads_the_database_layer() -> None:
    modules = [relative[:-3].replace("/", ".") for relative in PURE_MODULES if not relative.endswith("__init__.py")]
    program = (
        "import sys\n"
        + "".join(f"import acme_city.{name}\n" for name in modules)
        + "loaded = sorted(m for m in sys.modules if m == 'sqlalchemy' or m.startswith('sqlalchemy.')"
        " or m.startswith('acme_city.persistence') or m.startswith('acme_city.agents')"
        " or m.startswith('acme_city.permits') or m.startswith('acme_city.muse'))\n"
        "print(','.join(loaded))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, check=False,
        env={**__import__("os").environ, "PYTHONPATH": str(SRC.parent)},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "", result.stdout
