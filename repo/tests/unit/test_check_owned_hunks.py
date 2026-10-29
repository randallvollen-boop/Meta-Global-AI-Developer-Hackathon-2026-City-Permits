"""The hunk checker keeps each lane inside the functions it owns.

A no-op diff passes; a synthetic diff in a scratch repository that touches a
function another lane owns, a line outside every function, or more than an
actor id of an acceptance test fails.
"""
# REQUIRES: W0-7

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_owned_hunks import DEFAULT_OWNERSHIP, check, function_spans, main  # noqa: E402

ROUTER = "src/acme_city/ui/router.py"
ADMIN_VIEWS = "src/acme_city/ui/admin_views.py"
AT01 = "tests/acceptance/test_at01.py"


def _ownership() -> dict:
    return json.loads(DEFAULT_OWNERSHIP.read_text(encoding="utf-8"))


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        [
            "git", "-C", str(repo),
            "-c", "user.name=Scratch", "-c", "user.email=scratch@example.invalid",
            "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
            *args,
        ],
        check=True, capture_output=True,
    )


@pytest.fixture()
def scratch(tmp_path: Path) -> Path:
    """A scratch repository holding copies of the shared files, on a base commit."""
    for relative in (ROUTER, ADMIN_VIEWS, AT01):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_ROOT / relative, target)
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def _commit_change(repo: Path, relative: str, old: str, new: str) -> None:
    path = repo / relative
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    path.write_text(text.replace(old, new), encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "lane change")


def _inside(relative: str, function: str) -> str:
    """Return one line from the body of ``function`` that occurs once in the file."""
    source = (REPO_ROOT / relative).read_text(encoding="utf-8")
    lines = source.splitlines()
    (first, last) = next((a, b) for a, b, name in function_spans(source) if name == function)
    for line in lines[first:last]:
        stripped = line.strip()
        if stripped and not stripped.startswith(("#", "@", '"')) and source.count(line) == 1:
            return line
    raise AssertionError(f"no unique body line in {function}")


def test_every_owned_function_exists_and_every_owner_is_a_lane() -> None:
    ownership = _ownership()
    for relative, owners in ownership["functions"].items():
        names = {name for _a, _b, name in function_spans((REPO_ROOT / relative).read_text())}
        assert set(owners) <= names, (relative, sorted(set(owners) - names))
        assert set(owners.values()) <= set(ownership["lanes"]), relative
    assert list((REPO_ROOT / "tests" / "acceptance").glob("test_at*.py"))


def test_a_no_op_diff_passes(capsys) -> None:
    assert main(["--lane", "agent-operator", "--base", "HEAD", "--head", "HEAD"]) == 0
    assert "every hunk is inside" in capsys.readouterr().out


def test_a_change_inside_the_lane_function_passes(scratch: Path) -> None:
    line = _inside(ROUTER, "_agent_toggle")
    _commit_change(scratch, ROUTER, line, line + "  # lane note")
    assert check(scratch, _ownership(), "agent-operator", "main~1", "HEAD") == []


def test_a_change_to_a_function_another_lane_owns_fails(scratch: Path) -> None:
    line = _inside(ROUTER, "_agent_toggle")
    _commit_change(scratch, ROUTER, line, line + "  # lane note")
    violations = check(scratch, _ownership(), "steward-queue-guide", "main~1", "HEAD")
    assert violations and all("_agent_toggle, owned by agent-operator" in v for v in violations)
    assert main([
        "--lane", "steward-queue-guide", "--base", "main~1", "--repo", str(scratch),
    ]) == 1


def test_a_change_to_an_unowned_function_or_outside_every_function_fails(scratch: Path) -> None:
    line = _inside(ADMIN_VIEWS, "_lifecycle_next")
    _commit_change(scratch, ADMIN_VIEWS, line, line + "  # lane note")
    _commit_change(
        scratch, ROUTER, "from __future__ import annotations\n",
        "from __future__ import annotations\n\nimport os  # noqa: F401\n",
    )
    violations = check(scratch, _ownership(), "admin-b", "main~2", "HEAD")
    assert any("_lifecycle_next, owned by no lane" in v for v in violations)
    assert any(v.startswith(ROUTER) and "outside every function" in v for v in violations)


def test_an_acceptance_test_may_change_only_actor_ids(scratch: Path) -> None:
    source = (scratch / AT01).read_text(encoding="utf-8")
    actor = next(a for a in ('"persona_permit_reviewer"', '"persona_data_steward"') if a in source)
    swapped = source.replace(actor, '"persona_agent_operator"')
    (scratch / AT01).write_text(swapped, encoding="utf-8")
    _git(scratch, "commit", "-q", "-am", "actor ids")
    assert check(scratch, _ownership(), "agent-operator", "main~1", "HEAD") == []

    (scratch / AT01).write_text(swapped.replace("assert ", "assert  ", 1), encoding="utf-8")
    _git(scratch, "commit", "-q", "-am", "more than actor ids")
    violations = check(scratch, _ownership(), "agent-operator", "main~1", "HEAD")
    assert violations and all("more than an actor-id literal" in v for v in violations)


def test_an_unknown_lane_is_refused() -> None:
    with pytest.raises(SystemExit):
        check(REPO_ROOT, _ownership(), "nobody", "HEAD", "HEAD")
