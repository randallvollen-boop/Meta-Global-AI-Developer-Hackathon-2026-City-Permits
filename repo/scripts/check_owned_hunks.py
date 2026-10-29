#!/usr/bin/env python3
"""Check that a lane's diff stays inside the functions it owns.

``tests/regression/data/owned_hunks.json`` maps the functions of the shared
files (``ui/router.py`` and ``ui/admin_views.py``) to the lane that owns each
one, and marks the acceptance tests as actor-only.  Given a lane and a base
ref, the script reads ``git diff base...head`` and fails when

- a changed line of a shared file lies outside a function that lane owns
  (a removed line is located in the base version, an added line in the head
  version, and a line outside every function belongs to no lane), or
- a hunk of an actor-only file changes anything other than an actor-id
  literal.

With ``--actor-only`` it checks only the actor-only files and needs no lane.
The integrator runs it on every merge.  It exits 0 when the diff complies and
1 with one line per violation when it does not.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OWNERSHIP = REPO_ROOT / "tests" / "regression" / "data" / "owned_hunks.json"

#: An actor-id string literal, such as ``"persona_data_steward"``.
ACTOR_LITERAL = re.compile(r"""(["'])(?:persona|service)_[a-z0-9_]+\1""")

HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class Hunk:
    """One hunk of a zero-context diff."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    removed: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)

    @property
    def old_lines(self) -> range:
        return range(self.old_start, self.old_start + self.old_count)

    @property
    def new_lines(self) -> range:
        return range(self.new_start, self.new_start + self.new_count)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def changed_files(repo: Path, base: str, head: str) -> list[str]:
    output = git(repo, "diff", "--name-only", "--relative", "--no-renames", f"{base}...{head}")
    return [line for line in output.splitlines() if line]


def parse_hunks(diff: str) -> list[Hunk]:
    """Return the hunks of a ``git diff -U0`` output for one file."""
    hunks: list[Hunk] = []
    for line in diff.splitlines():
        match = HUNK_HEADER.match(line)
        if match:
            old_start, old_count, new_start, new_count = match.groups()
            hunks.append(
                Hunk(
                    int(old_start),
                    1 if old_count is None else int(old_count),
                    int(new_start),
                    1 if new_count is None else int(new_count),
                )
            )
        elif hunks and line.startswith("-") and not line.startswith("---"):
            hunks[-1].removed.append(line[1:])
        elif hunks and line.startswith("+") and not line.startswith("+++"):
            hunks[-1].added.append(line[1:])
    return hunks


def file_hunks(repo: Path, base: str, head: str, path: str) -> list[Hunk]:
    diff = git(
        repo, "diff", "-U0", "--no-color", "--no-ext-diff", "--relative", "--no-renames",
        f"{base}...{head}", "--", path,
    )
    return parse_hunks(diff)


def source_at(repo: Path, ref: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repo), "show", f"{ref}:./{path}"],
        capture_output=True, text=True, check=False,
    )
    return result.stdout if result.returncode == 0 else None


def function_spans(source: str | None) -> list[tuple[int, int, str]]:
    """Return ``(first, last, name)`` of every top-level function and method.

    A function starts at its first decorator.  A method is named
    ``Class.method``.
    """
    if source is None:
        return []
    spans: list[tuple[int, int, str]] = []

    def add(node: ast.AST, name: str) -> None:
        first = min([node.lineno, *(item.lineno for item in node.decorator_list)])
        spans.append((first, node.end_lineno or node.lineno, name))

    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            add(node, node.name)
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    add(item, f"{node.name}.{item.name}")
    return spans


def enclosing(spans: list[tuple[int, int, str]], line: int) -> str | None:
    for first, last, name in spans:
        if first <= line <= last:
            return name
    return None


def check_functions(
    path: str, hunks: list[Hunk], owners: dict[str, str], lane: str,
    old_spans: list[tuple[int, int, str]], new_spans: list[tuple[int, int, str]],
) -> list[str]:
    violations: list[str] = []
    for hunk in hunks:
        located = [("base", line, enclosing(old_spans, line)) for line in hunk.old_lines]
        located += [("head", line, enclosing(new_spans, line)) for line in hunk.new_lines]
        for side, line, name in located:
            if name is None:
                violations.append(f"{path}:{line} ({side}) changes a line outside every function")
            elif owners.get(name) != lane:
                owner = owners.get(name, "no lane")
                violations.append(
                    f"{path}:{line} ({side}) changes {name}, owned by {owner}, not {lane}"
                )
    return violations


def check_actor_only(path: str, hunks: list[Hunk]) -> list[str]:
    violations: list[str] = []
    for hunk in hunks:
        if len(hunk.removed) != len(hunk.added):
            violations.append(
                f"{path}:{hunk.new_start} adds or removes lines; only actor ids may change"
            )
            continue
        for offset, (before, after) in enumerate(zip(hunk.removed, hunk.added, strict=True)):
            if ACTOR_LITERAL.sub('"<actor>"', before) != ACTOR_LITERAL.sub('"<actor>"', after):
                violations.append(
                    f"{path}:{hunk.new_start + offset} changes more than an actor-id literal"
                )
    return violations


def check(
    repo: Path, ownership: dict, lane: str | None, base: str, head: str
) -> list[str]:
    """Return the violations of ``lane`` in ``git diff base...head``.

    With ``lane`` None only the actor-only files are checked.
    """
    if lane is not None and lane not in ownership["lanes"]:
        raise SystemExit(f"unknown lane {lane!r}; expected one of {ownership['lanes']}")
    violations: list[str] = []
    for path in changed_files(repo, base, head):
        owners = ownership["functions"].get(path) if lane is not None else None
        actor_only = any(fnmatch.fnmatch(path, pattern) for pattern in ownership["actor_only"])
        if owners is None and not actor_only:
            continue
        hunks = file_hunks(repo, base, head, path)
        if owners is not None:
            merge_base = git(repo, "merge-base", base, head).strip()
            violations += check_functions(
                path, hunks, owners, lane,
                function_spans(source_at(repo, merge_base, path)),
                function_spans(source_at(repo, head, path)),
            )
        if actor_only:
            violations += check_actor_only(path, hunks)
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--lane", help="the lane whose diff is checked")
    scope.add_argument(
        "--actor-only", action="store_true", help="check only the actor-only files"
    )
    parser.add_argument("--base", required=True, help="the base ref, normally main")
    parser.add_argument("--head", default="HEAD", help="the head ref (default HEAD)")
    parser.add_argument("--repo", type=Path, default=REPO_ROOT, help="the repository directory")
    parser.add_argument("--ownership", type=Path, default=DEFAULT_OWNERSHIP)
    args = parser.parse_args(argv)
    ownership = json.loads(args.ownership.read_text(encoding="utf-8"))
    violations = check(args.repo, ownership, args.lane, args.base, args.head)
    for violation in violations:
        print(violation)
    subject = args.lane or "actor-only files"
    if violations:
        print(f"{len(violations)} violation(s) for {subject}")
        return 1
    if args.lane:
        print(f"{args.lane}: every hunk is inside the lane's own functions")
    else:
        print("actor-only files: only actor-id literals change")
    return 0


if __name__ == "__main__":
    sys.exit(main())
