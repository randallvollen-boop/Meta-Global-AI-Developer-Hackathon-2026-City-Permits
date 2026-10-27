#!/usr/bin/env python3
"""Check that every family of tests collects something.

The script reads the collection pytest produced, counts the nodes of every
family and reports the families that are empty or missing.  A family that
collects nothing is a hole in the evidence, not a pass.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The families the demonstration promises.
DEFAULT_FAMILIES: tuple[str, ...] = (
    "unit",
    "api",
    "security",
    "acceptance",
    "supplementary",
    "scenarios",
    "evaluator",
    "integration",
    "regression",
    "browser",
)


def parse_collection(path: Path) -> list[str]:
    """Return the collected node identifiers of a pytest collection file."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SystemExit(f"the collection file is missing: {path}")
    return [
        line.strip()
        for line in text.splitlines()
        if "::" in line and not line.startswith(" ")
    ]


def family_of(node: str) -> str:
    """Return the family a collected node belongs to."""
    parts = node.split("::")[0].split("/")
    if len(parts) < 2 or parts[0] != "tests":
        return "other"
    return parts[1]


def parse_report(path: Path) -> dict[str, str]:
    """Return the outcome of every executed node of a JUnit report."""
    outcomes: dict[str, str] = {}
    if not path.is_file():
        return outcomes
    tree = ElementTree.parse(path)
    for case in tree.iter("testcase"):
        key = f"{case.get('classname', '')}::{case.get('name', '')}"
        if case.find("failure") is not None or case.find("error") is not None:
            outcomes[key] = "failed"
        elif case.find("skipped") is not None:
            outcomes[key] = "skipped"
        else:
            outcomes[key] = "passed"
    return outcomes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("collection", type=Path, help="the pytest collection file")
    parser.add_argument(
        "--families",
        default=",".join(DEFAULT_FAMILIES),
        help="the families that must collect something",
    )
    parser.add_argument(
        "--reports",
        type=Path,
        default=None,
        help="the directory that holds the JUnit reports of the families",
    )
    args = parser.parse_args(argv)

    families = tuple(
        family.strip() for family in args.families.split(",") if family.strip()
    )
    nodes = parse_collection(args.collection)
    counts: dict[str, int] = {family: 0 for family in families}
    counts["other"] = 0
    for node in nodes:
        family = family_of(node)
        counts[family] = counts.get(family, 0) + 1

    problems: list[str] = []
    for family in families:
        collected = counts.get(family, 0)
        print(f"  {family:<14} {collected} collected")
        if collected == 0:
            problems.append(f"the family {family} collected no test")

    if args.reports is not None:
        for family in families:
            report = args.reports / f"{family}.junit.xml"
            outcomes = parse_report(report)
            if not outcomes:
                problems.append(f"the family {family} produced no report")
                continue
            skipped = sum(1 for value in outcomes.values() if value == "skipped")
            failed = sum(1 for value in outcomes.values() if value == "failed")
            print(
                f"  {family:<14} {len(outcomes)} executed, {skipped} skipped, {failed} failed"
            )
            if skipped == len(outcomes):
                problems.append(f"every test of the family {family} was skipped")

    print(f"  total            {len(nodes)} collected")
    if problems:
        print("test collection check FAILED", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("test collection check OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
