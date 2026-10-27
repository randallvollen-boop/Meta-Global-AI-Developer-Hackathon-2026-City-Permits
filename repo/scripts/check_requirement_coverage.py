#!/usr/bin/env python3
"""Check the committed requirement contract.

The contract in ``config/requirements.json`` records identifiers, titles and
planned verification identifiers.  This script proves that the contract is
internally consistent and, unless ``--planning-only`` is given, that every
requirement identifier is referenced by at least one implementation symbol.

A planned check identifier is a verification target.  This script never claims
that a requirement is implemented or that a check passed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = REPO_ROOT / "config" / "requirements.json"
DEFAULT_SOURCE_ROOT = REPO_ROOT / "src" / "acme_city"

EXPECTED_REQUIREMENT_COUNT = 57
EXPECTED_ACCEPTANCE_TESTS = 20
EXPECTED_SUPPLEMENTARY_CHECKS = 8
EXPECTED_SCENARIOS = 11

REQUIREMENT_ID = re.compile(r"^[A-Z]{2,5}-\d{2}$")
ACCEPTANCE_ID = re.compile(r"^AT\d{2}$")
SUPPLEMENTARY_ID = re.compile(r"^VC\d{2}$")
SCENARIO_ID = re.compile(r"^D\d{2}$")

#: A source file declares the requirements it implements with a marker line:
#: ``REQUIRES: GOV-01, SEC-01``.  Only explicit markers count, so an
#: incidental identifier inside a string never registers as implementation.
REQUIRES_MARKER = re.compile(r"^\s*#?\s*REQUIRES:\s*(?P<ids>[A-Z]{2,5}-\d{2}(?:\s*,\s*[A-Z]{2,5}-\d{2})*)\s*$")


def load_contract(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"requirement contract not found: {path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"requirement contract is not valid JSON: {exc}")
    if not isinstance(data, dict):
        raise SystemExit("requirement contract must be a JSON object")
    return data


def check_contract(contract: dict) -> tuple[list[str], dict[str, list[str]]]:
    """Validate the contract and return ``(problems, requirement_to_checks)``."""
    problems: list[str] = []

    requirements = contract.get("requirements") or []
    acceptance_tests = contract.get("acceptance_tests") or []
    supplementary_checks = contract.get("supplementary_checks") or []
    scenarios = contract.get("scenarios") or []

    seen_requirement_ids: set[str] = set()
    requirement_to_checks: dict[str, list[str]] = defaultdict(list)
    for entry in requirements:
        rid = entry.get("requirement_id", "")
        if not REQUIREMENT_ID.match(str(rid)):
            problems.append(f"malformed requirement identifier: {rid!r}")
        if rid in seen_requirement_ids:
            problems.append(f"duplicate requirement identifier: {rid}")
        seen_requirement_ids.add(rid)
        if not entry.get("title"):
            problems.append(f"requirement {rid} has no title")
        checks = list(entry.get("acceptance_test_ids") or []) + list(
            entry.get("supplementary_check_ids") or []
        )
        if not checks:
            problems.append(f"requirement {rid} has no planned verification identifier")
        for check in checks:
            if not (ACCEPTANCE_ID.match(str(check)) or SUPPLEMENTARY_ID.match(str(check))):
                problems.append(f"requirement {rid} references unknown check {check!r}")
            if check in requirement_to_checks[rid]:
                problems.append(f"requirement {rid} references check {check} twice")
            requirement_to_checks[rid].append(check)

    known_at = {entry.get("test_id") for entry in acceptance_tests}
    known_vc = {entry.get("check_id") for entry in supplementary_checks}
    known_d = {entry.get("scenario_id") for entry in scenarios}

    if len(seen_requirement_ids) != EXPECTED_REQUIREMENT_COUNT:
        problems.append(
            f"expected {EXPECTED_REQUIREMENT_COUNT} distinct requirement identifiers, "
            f"found {len(seen_requirement_ids)}"
        )

    expected_at = {f"AT{index:02d}" for index in range(1, EXPECTED_ACCEPTANCE_TESTS + 1)}
    if known_at != expected_at:
        problems.append(
            f"acceptance test identifiers differ from AT01-AT{EXPECTED_ACCEPTANCE_TESTS:02d}: "
            f"missing {sorted(expected_at - known_at)}, unexpected {sorted(known_at - expected_at)}"
        )
    if len(acceptance_tests) != len(known_at):
        problems.append("duplicate acceptance test identifier")

    expected_vc = {f"VC{index:02d}" for index in range(1, EXPECTED_SUPPLEMENTARY_CHECKS + 1)}
    if known_vc != expected_vc:
        problems.append(
            f"supplementary check identifiers differ from VC01-VC{EXPECTED_SUPPLEMENTARY_CHECKS:02d}: "
            f"missing {sorted(expected_vc - known_vc)}, unexpected {sorted(known_vc - expected_vc)}"
        )
    if len(supplementary_checks) != len(known_vc):
        problems.append("duplicate supplementary check identifier")

    expected_d = {f"D{index:02d}" for index in range(1, EXPECTED_SCENARIOS + 1)}
    if known_d != expected_d:
        problems.append(
            f"scenario identifiers differ from D01-D{EXPECTED_SCENARIOS:02d}: "
            f"missing {sorted(expected_d - known_d)}, unexpected {sorted(known_d - expected_d)}"
        )
    if len(scenarios) != len(known_d):
        problems.append("duplicate scenario identifier")

    referenced_at = {check for checks in requirement_to_checks.values() for check in checks if ACCEPTANCE_ID.match(str(check))}
    referenced_vc = {check for checks in requirement_to_checks.values() for check in checks if SUPPLEMENTARY_ID.match(str(check))}
    for check in sorted(referenced_at - known_at):
        problems.append(f"requirement contract references unknown acceptance test {check}")
    for check in sorted(referenced_vc - known_vc):
        problems.append(f"requirement contract references unknown supplementary check {check}")

    for entry in acceptance_tests:
        if not entry.get("title"):
            problems.append(f"acceptance test {entry.get('test_id')} has no title")
    for entry in supplementary_checks:
        if not entry.get("title"):
            problems.append(f"supplementary check {entry.get('check_id')} has no title")
    for entry in scenarios:
        if not entry.get("title"):
            problems.append(f"scenario {entry.get('scenario_id')} has no title")

    return problems, dict(requirement_to_checks)


def scan_implementation(source_root: Path) -> dict[str, list[str]]:
    """Return requirement identifier -> implementing source files."""
    implemented: dict[str, list[str]] = defaultdict(list)
    if not source_root.exists():
        return {}
    for path in sorted(source_root.rglob("*.py")):
        relative = path.relative_to(REPO_ROOT).as_posix()
        for line in path.read_text(encoding="utf-8").splitlines():
            match = REQUIRES_MARKER.match(line)
            if match is None:
                continue
            for identifier in (part.strip() for part in match.group("ids").split(",")):
                if identifier and relative not in implemented[identifier]:
                    implemented[identifier].append(relative)
    return dict(implemented)


# --------------------------------------------------------------------------
# The requirement-linked executable check inventory
# --------------------------------------------------------------------------

DEFAULT_INVENTORY = REPO_ROOT / "config" / "check_inventory.json"
DEFAULT_COLLECTION = REPO_ROOT / "var" / "collection.txt"

#: A symbol reference names a file and, optionally, the name it defines.
SYMBOL_REFERENCE = re.compile(
    r"^(?P<path>[A-Za-z0-9_./-]+\.py)"
    r"(?::(?P<name>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?))?$"
)

#: A definition of a name inside a source file.
DEFINITION = re.compile(
    r"^\s*(?:class|def|async def)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE
)
#: An assignment of a name inside a source file.
ASSIGNMENT = re.compile(r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?::[^=]+)?=", re.MULTILINE)


def load_inventory(path: Path) -> dict:
    """Return the requirement-linked executable check inventory."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"the check inventory is missing: {path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"the check inventory is not valid JSON: {exc}")
    if not isinstance(data, dict):
        raise SystemExit("the check inventory must be a JSON object")
    return data


def symbol_is_defined(reference: str) -> tuple[bool, str]:
    """Return whether a symbol reference names a definition that exists."""
    match = SYMBOL_REFERENCE.match(reference)
    if match is None:
        return False, f"the symbol reference {reference!r} is malformed"
    path = match.group("path")
    name = match.group("name")
    target = REPO_ROOT / path
    if not target.is_file():
        return False, f"the file {path} does not exist"
    if not name:
        return True, ""
    head, _, member = name.partition(".")
    text = target.read_text(encoding="utf-8")
    defined = {item.group("name") for item in DEFINITION.finditer(text)}
    defined |= {item.group("name") for item in ASSIGNMENT.finditer(text)}
    if head not in defined:
        return False, f"the symbol {head} is not defined in {path}"
    if member:
        members = {
            item.group("name")
            for item in DEFINITION.finditer(text)
            if item.group("name") == member
        }
        if member not in members:
            return False, f"the member {name} is not defined in {path}"
    return True, ""


def collected_nodes(collection: Path | None) -> list[str]:
    """Return the test nodes pytest collects."""
    if collection is not None and collection.is_file():
        text = collection.read_text(encoding="utf-8")
    else:
        import subprocess
        import sys

        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        text = completed.stdout
    return [
        line.strip()
        for line in text.splitlines()
        if "::" in line and not line.startswith(" ")
    ]


def check_inventory(
    inventory: dict,
    contract: dict,
    *,
    nodes: list[str] | None,
) -> list[str]:
    """Validate the inventory against the contract and the collected nodes.

    Args:
        inventory: The loaded check inventory.
        contract: The loaded requirement contract.
        nodes: The collected test nodes, or ``None`` when the collection is
            not checked.
    """
    problems: list[str] = []
    contract_requirements = {
        entry["requirement_id"]: entry for entry in contract.get("requirements") or []
    }
    contract_checks = {
        entry["test_id"] for entry in contract.get("acceptance_tests") or []
    } | {entry["check_id"] for entry in contract.get("supplementary_checks") or []} | {
        entry["scenario_id"] for entry in contract.get("scenarios") or []
    }

    inventory_requirements = inventory.get("requirements") or []
    seen_requirements: set[str] = set()
    for entry in inventory_requirements:
        requirement_id = entry.get("requirement_id", "")
        if requirement_id in seen_requirements:
            problems.append(f"the inventory lists {requirement_id} twice")
        seen_requirements.add(requirement_id)
        if requirement_id not in contract_requirements:
            problems.append(f"the inventory names the unknown requirement {requirement_id}")
            continue
        symbols = list(entry.get("implementation_symbols") or [])
        if not symbols:
            problems.append(f"{requirement_id} names no implementation symbol")
        for reference in symbols:
            ok, reason = symbol_is_defined(reference)
            if not ok:
                problems.append(f"{requirement_id}: {reason}")
        checks = list(entry.get("check_ids") or [])
        if not checks:
            problems.append(f"{requirement_id} names no check")
        for check in checks:
            if check not in contract_checks:
                problems.append(f"{requirement_id} names the unknown check {check}")
        planned = list(
            contract_requirements[requirement_id].get("acceptance_test_ids") or []
        ) + list(contract_requirements[requirement_id].get("supplementary_check_ids") or [])
        if sorted(checks) != sorted(planned):
            problems.append(
                f"{requirement_id} names the checks {sorted(checks)}, the contract names "
                f"{sorted(planned)}"
            )
        if nodes is not None:
            for node in entry.get("node_ids") or []:
                if node not in nodes:
                    problems.append(
                        f"{requirement_id} names the node {node}, which is not collected"
                    )

    missing_requirements = sorted(set(contract_requirements) - seen_requirements)
    for requirement_id in missing_requirements:
        problems.append(f"the inventory names no requirement {requirement_id}")

    inventory_checks = inventory.get("checks") or []
    seen_checks: set[str] = set()
    for entry in inventory_checks:
        check_id = entry.get("check_id", "")
        if check_id in seen_checks:
            problems.append(f"the inventory lists the check {check_id} twice")
        seen_checks.add(check_id)
        if check_id not in contract_checks:
            problems.append(f"the inventory names the unknown check {check_id}")
        node_ids = list(entry.get("node_ids") or [])
        if not node_ids:
            if entry.get("pending"):
                if nodes is not None:
                    problems.append(
                        f"{check_id} is marked pending: the interface task has not written "
                        "its collected node yet"
                    )
            else:
                problems.append(f"{check_id} has no collected node")
        if nodes is not None:
            for node in node_ids:
                if node not in nodes:
                    problems.append(f"{check_id} names the node {node}, which is not collected")
    for check_id in sorted(contract_checks - seen_checks):
        problems.append(f"the inventory names no check {check_id}")

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--planning-only",
        action="store_true",
        help="validate the committed contract only; do not require implementation symbols",
    )
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument(
        "--inventory",
        type=Path,
        default=DEFAULT_INVENTORY,
        help="the requirement-linked executable check inventory",
    )
    parser.add_argument(
        "--collection",
        type=Path,
        default=None,
        help="a pytest collection file; the collection is run when it is absent",
    )
    args = parser.parse_args(argv)

    contract = load_contract(args.contract)
    problems, requirement_to_checks = check_contract(contract)

    implemented: dict[str, list[str]] = {}
    if not args.planning_only:
        implemented = scan_implementation(args.source_root)
        unmapped = sorted(set(requirement_to_checks) - set(implemented))
        if unmapped:
            problems.append(
                f"{len(unmapped)} requirement identifiers have no implementation symbol: "
                + ", ".join(unmapped)
            )

    inventory = load_inventory(args.inventory)
    nodes = None if args.planning_only else collected_nodes(args.collection)
    problems.extend(check_inventory(inventory, contract, nodes=nodes))

    requirement_ids = sorted(requirement_to_checks)
    if problems:
        print("requirement coverage check FAILED", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print("requirement coverage check OK")
    print(f"  contract: {args.contract.relative_to(REPO_ROOT)}")
    print(f"  inventory: {args.inventory.relative_to(REPO_ROOT)}")
    print(f"  requirements: {len(requirement_ids)} distinct identifiers")
    print(f"  acceptance tests: {len(contract.get('acceptance_tests') or [])}")
    print(f"  supplementary checks: {len(contract.get('supplementary_checks') or [])}")
    print(f"  scenarios: {len(contract.get('scenarios') or [])}")
    if args.planning_only:
        print("  mode: planning-only (no implementation symbols required)")
    else:
        print(f"  implementation symbols: {len(implemented)} requirement identifiers referenced")
        mapped = len(inventory.get("requirements") or [])
        print(f"  inventory mapping: {mapped}/{len(requirement_ids)} requirements")
        print(f"  collected nodes: {len(nodes or [])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
