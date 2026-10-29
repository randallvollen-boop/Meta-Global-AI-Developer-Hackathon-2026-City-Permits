"""Every request session commits before its response is sent.

``get_session`` commits after ``yield``.  At FastAPI's default request scope
that commit runs after the response has gone out, so a client that selects a
persona and at once reads its session can arrive before the row exists and
get a 401.  ``scope="function"`` commits first.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "acme_city"
CALL = re.compile(r"Depends\(\s*get_session\s*([,)])([^)]*)")


def test_every_get_session_dependency_uses_function_scope() -> None:
    found, unscoped = 0, []
    for path in sorted(SRC.rglob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in CALL.finditer(line):
                found += 1
                if 'scope="function"' not in match.group(0):
                    unscoped.append(f"{path.relative_to(SRC)}:{number}")
    assert found > 100
    assert unscoped == []
