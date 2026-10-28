#!/usr/bin/env python3
"""Rebuild, check, and optionally replace the private AVA architecture article."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent
PAGE_DIR = WORKSPACE / "page"
STATUS_PATH = WORKSPACE / "STATUS.json"
FACTS_PATH = WORKSPACE / "facts.md"
DATA_PATH = PAGE_DIR / "data.json"
BODY_SOURCE_PATH = PAGE_DIR / "body.src.html"
PAGE_CONFIG_PATH = PAGE_DIR / "page.json"
BUILD_REPORT_PATH = WORKSPACE / "BUILD_REPORT.md"
PROJECT_NOTE_PATH = WORKSPACE / "PROJECT_NOTE.md"
RECEIPT_PATH = WORKSPACE / "status-updates.jsonl"

KIT = Path.home() / "Documents/Vollen Data Analytics/Solution_Architecture_Kit"
SKILL = Path.home() / ".claude/skills/solution-architecture-page"
VOLLENCOMS = Path.home() / ".claude/skills/vollencoms"
AVA_ROOT = Path.home() / "reference-architecture"
ARTICLE_ID = "acme-city-permits-architecture"
PERSONAS = ["Applicant", "Data Steward", "Permit Reviewer", "City Administrator"]
PHASE_STATES = {"planned", "in_progress", "verified", "blocked", "failed"}
OVERALL_STATES = {"planned", "in_implementation", "blocked", "verified"}
ARCHITECTURE_STATES = {"planned", "as_built"}


def load_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return data


def atomic_json(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_status(status: dict) -> None:
    if status.get("schema_version") != 1 or status.get("solution_id") != "acme-city-permits":
        raise ValueError("unsupported status schema or solution id")
    datetime.fromisoformat(str(status["as_of"]))
    if status.get("overall_status") not in OVERALL_STATES:
        raise ValueError("invalid overall_status")
    if status.get("architecture_status") not in ARCHITECTURE_STATES:
        raise ValueError("invalid architecture_status")

    requirements = status["requirements"]
    total = int(requirements["total"])
    outlined = int(requirements["outlined"])
    implemented = int(requirements["implemented"])
    verified = int(requirements["verified"])
    if not 0 <= verified <= implemented <= outlined <= total or total != 57:
        raise ValueError("requirement counts must satisfy 0 <= verified <= implemented <= outlined <= 57")

    execution = status["execution"]
    tasks_total = int(execution["tasks_total"])
    tasks_verified = int(execution["tasks_verified"])
    if tasks_total != 22 or not 0 <= tasks_verified <= tasks_total:
        raise ValueError("task counts must satisfy 0 <= verified <= 22")
    if not isinstance(execution.get("current_phase"), str) or not execution["current_phase"].strip():
        raise ValueError("current_phase must be a nonempty string")
    if not isinstance(execution.get("current_tasks"), list):
        raise ValueError("current_tasks must be a list")

    verification = status["verification"]
    expected_totals = {
        "acceptance_total": 20,
        "supplementary_total": 8,
        "scenarios_total": 11,
    }
    for key, expected in expected_totals.items():
        if int(verification[key]) != expected:
            raise ValueError(f"{key} must remain {expected}")
    if not 0 <= int(verification["acceptance_passed"]) <= 20:
        raise ValueError("acceptance_passed is outside 0..20")
    if not 0 <= int(verification["supplementary_passed"]) <= 8:
        raise ValueError("supplementary_passed is outside 0..8")
    if not 0 <= int(verification["scenarios_recorded"]) <= 11:
        raise ValueError("scenarios_recorded is outside 0..11")

    phases = status.get("phases")
    if not isinstance(phases, list) or len(phases) != 6:
        raise ValueError("exactly six phases are required")
    if len({phase["id"] for phase in phases}) != 6:
        raise ValueError("phase ids must be unique")
    for phase in phases:
        if phase.get("status") not in PHASE_STATES:
            raise ValueError(f"invalid phase state for {phase.get('id')}")

    personas = status.get("personas")
    if not isinstance(personas, list) or [item.get("label") for item in personas] != PERSONAS:
        raise ValueError("status must contain exactly the four approved personas in order")
    if any(item.get("selectable") is not True for item in personas):
        raise ValueError("all four approved personas must be selectable")

    library = status.get("library")
    if not isinstance(library, dict) or library.get("article_id") != ARTICLE_ID:
        raise ValueError("library article id must remain stable")


def replace_marked(text: str, begin: str, end: str, replacement: str) -> str:
    start = text.find(begin)
    finish = text.find(end)
    if start < 0 or finish < 0 or finish < start:
        raise ValueError(f"missing or misordered markers {begin!r} and {end!r}")
    finish += len(end)
    return text[:start] + replacement + text[finish:]


def display_state(value: str) -> str:
    return value.replace("_", " ").title()


def status_block(status: dict) -> str:
    req = status["requirements"]
    run = status["execution"]
    ver = status["verification"]
    as_of = datetime.fromisoformat(status["as_of"])
    current_tasks = ", ".join(html.escape(str(task)) for task in run["current_tasks"]) or "none"
    phase_rows = []
    chip = {"verified": "ga", "in_progress": "pv", "planned": "ex", "blocked": "ex", "failed": "ex"}
    for phase in status["phases"]:
        phase_rows.append(
            f'        <tr><td>{html.escape(phase["label"])}</td><td><span class="chip {chip[phase["status"]]}">{display_state(phase["status"])}</span></td></tr>'
        )
    overall = display_state(status["overall_status"]).upper()
    architecture = display_state(status["architecture_status"]).upper()
    muse = display_state(str(ver["live_muse_primary_chain"]))
    return f'''<!-- ARCH_STATUS_BEGIN -->
<section id="status" class="alt"><div class="wrap">
  <h2>Current status</h2>
  <p class="lede">This panel is generated from the workspace status record. Values change only when stored evidence changes.</p>
  <div class="status-grid">
    <div class="status-card accent" id="status-overall" data-status="{html.escape(status["overall_status"])}" data-architecture="{html.escape(status["architecture_status"])}" data-as-of="{html.escape(status["as_of"])}">
      <p class="kicker">Overall</p>
      <p class="status-value">{overall}</p>
      <p class="status-note">Architecture status: <b>{architecture}</b>. The status record was written at {as_of.strftime("%H:%M")} Eastern on {as_of.date().isoformat()}.</p>
    </div>
    <div class="status-card" id="status-requirements" data-total="{req["total"]}" data-outlined="{req["outlined"]}" data-implemented="{req["implemented"]}" data-verified="{req["verified"]}">
      <p class="kicker">Requirements</p>
      <p class="status-value">{req["outlined"]} outlined</p>
      <p class="status-note"><b>{req["implemented"]} implemented</b>, <b>{req["verified"]} verified</b>. All {req["total"]} identifiers are represented in the outline.</p>
    </div>
    <div class="status-card" id="status-tasks" data-total="{run["tasks_total"]}" data-verified="{run["tasks_verified"]}" data-phase="{html.escape(run["current_phase"])}" data-current-tasks="{current_tasks}">
      <p class="kicker">Execution tasks</p>
      <p class="status-value">{run["tasks_total"]} tasks</p>
      <p class="status-note"><b>{run["tasks_verified"]} verified</b>. {html.escape(run["current_phase"])}. Current tasks: {current_tasks}.</p>
    </div>
    <div class="status-card" id="status-phase" data-phase="{html.escape(run["current_phase"])}" data-phase-state="in_progress">
      <p class="kicker">Phase</p>
      <p class="status-value">{html.escape(run["current_phase"])}</p>
      <p class="status-note">Phase states below come from accepted evidence in the status record.</p>
    </div>
    <div class="status-card" id="status-verification" data-acceptance-total="{ver["acceptance_total"]}" data-acceptance-passed="{ver["acceptance_passed"]}" data-supplementary-total="{ver["supplementary_total"]}" data-supplementary-passed="{ver["supplementary_passed"]}" data-scenarios-total="{ver["scenarios_total"]}" data-scenarios-recorded="{ver["scenarios_recorded"]}">
      <p class="kicker">Verification</p>
      <p class="status-value">{ver["acceptance_total"]} acceptance, {ver["supplementary_total"]} supplementary, {ver["scenarios_total"]} scenarios</p>
      <p class="status-note"><b>{ver["acceptance_passed"]} acceptance</b>, <b>{ver["supplementary_passed"]} supplementary</b>, and <b>{ver["scenarios_recorded"]} scenarios</b> passed or recorded.</p>
    </div>
    <div class="status-card" id="status-muse" data-live-muse-primary-chain="{html.escape(str(ver["live_muse_primary_chain"]))}">
      <p class="kicker">Live model chain</p>
      <p class="status-value">{muse}</p>
      <p class="status-note">Replay never counts as live evidence.</p>
    </div>
  </div>
  <div class="sub">
    <h3>Phases</h3>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Phase</th><th>State</th></tr></thead>
      <tbody>
{chr(10).join(phase_rows)}
      </tbody>
    </table></div>
  </div>
  <p class="mock-note">Source: the workspace status record. Counts are recorded facts, not projections.</p>
</div></section>
<!-- ARCH_STATUS_END -->'''


def component_status_block(status: dict) -> str:
    """Return the evidence-backed built/planned table body."""
    req = status["requirements"]
    run = status["execution"]
    ver = status["verification"]
    chip = {"verified": "ga", "in_progress": "pv", "planned": "ex", "blocked": "ex", "failed": "ex"}
    task_ranges = {
        "foundation": "F1 to F4",
        "registry": "R1 to R4",
        "permits": "P1 to P5",
        "muse_ui": "M1 to M4",
        "acceptance": "A1 to A5",
    }
    rows = [
        '<tr><td>Requirements outline</td><td><span class="chip ga">Exists</span></td><td>57 of 57 requirement identifiers are represented and coverage checked.</td></tr>',
        '<tr><td>Executable plan</td><td><span class="chip ga">Exists</span></td><td>22 implementation tasks across one parent plan and five child plans.</td></tr>',
        '<tr><td>Fact sheet and status record</td><td><span class="chip ga">Exist</span></td><td>They supply the claims and current progress values used on this page.</td></tr>',
    ]
    for phase in status["phases"]:
        if phase["id"] == "planning":
            continue
        state = phase["status"]
        label = display_state(state)
        task_range = task_ranges[phase["id"]]
        if state == "verified":
            detail = f"Tasks {task_range} are verified."
        elif state == "in_progress":
            current = ", ".join(str(item) for item in run["current_tasks"])
            detail = f"Current tasks: {current}."
        elif state == "blocked":
            detail = f"Tasks {task_range} are blocked. The current status record names the active phase."
        elif state == "failed":
            detail = f"Tasks {task_range} have a failed gate."
        else:
            detail = f"Tasks {task_range} are planned."
        rows.append(
            f'<tr><td>{html.escape(phase["label"])}</td><td><span class="chip {chip[state]}">{label}</span></td><td>{html.escape(detail)}</td></tr>'
        )
    remaining = int(req["total"]) - int(req["implemented"])
    rows.extend(
        [
            f'<tr><td>Implemented requirements</td><td><span class="chip pv">{req["implemented"]} of {req["total"]}</span></td><td>{remaining} requirement identifiers remain for later phases.</td></tr>',
            f'<tr><td>Acceptance and scenario evidence</td><td><span class="chip ex">In progress</span></td><td>{ver["acceptance_passed"]} of {ver["acceptance_total"]} acceptance tests, {ver["supplementary_passed"]} of {ver["supplementary_total"]} supplementary checks and {ver["scenarios_recorded"]} of {ver["scenarios_total"]} scenarios are recorded in the integrated manifest.</td></tr>',
            f'<tr><td>Live model evidence</td><td><span class="chip ex">{display_state(str(ver["live_muse_primary_chain"]))}</span></td><td>Replay never counts as a completed live primary-chain run.</td></tr>',
            '<tr><td>Release gates</td><td><span class="chip ex">Open</span></td><td>Brand, delivery owner and security review remain open, so the internal banner stays.</td></tr>',
        ]
    )
    return "<!-- ARCH_COMPONENT_STATUS_BEGIN -->\n    <tbody>\n      " + "\n      ".join(rows) + "\n    </tbody>\n    <!-- ARCH_COMPONENT_STATUS_END -->"


def facts_status_block(status: dict) -> str:
    req = status["requirements"]
    run = status["execution"]
    ver = status["verification"]
    as_of = datetime.fromisoformat(status["as_of"])
    return f'''<!-- FACT_STATUS_BEGIN -->
`STATUS.json` is the one architecture-status record. Current state at {as_of.strftime("%Y-%m-%d %H:%M")} Eastern:

- Overall: {display_state(status["overall_status"]).upper()}.
- Architecture: {display_state(status["architecture_status"]).upper()}.
- Requirements: {req["total"]} total, {req["outlined"]} outlined, {req["implemented"]} implemented, {req["verified"]} verified through integrated mapped checks.
- Execution tasks: {run["tasks_total"]} total, {run["tasks_verified"]} verified; {run["current_phase"]}.
- Verification inventory: {ver["acceptance_total"]} acceptance tests with {ver["acceptance_passed"]} passed, {ver["supplementary_total"]} supplementary checks with {ver["supplementary_passed"]} passed, and {ver["scenarios_total"]} scenarios with {ver["scenarios_recorded"]} recorded.
- Live Muse primary-chain evidence: {display_state(str(ver["live_muse_primary_chain"])).upper()}.
<!-- FACT_STATUS_END -->'''


def update_sources(status: dict) -> None:
    body = BODY_SOURCE_PATH.read_text(encoding="utf-8")
    body = replace_marked(body, "<!-- ARCH_STATUS_BEGIN -->", "<!-- ARCH_STATUS_END -->", status_block(status))
    body = replace_marked(
        body,
        "<!-- ARCH_COMPONENT_STATUS_BEGIN -->",
        "<!-- ARCH_COMPONENT_STATUS_END -->",
        component_status_block(status),
    )
    BODY_SOURCE_PATH.write_text(body, encoding="utf-8")

    facts = FACTS_PATH.read_text(encoding="utf-8")
    facts = replace_marked(facts, "<!-- FACT_STATUS_BEGIN -->", "<!-- FACT_STATUS_END -->", facts_status_block(status))
    FACTS_PATH.write_text(facts, encoding="utf-8")

    data = load_json(DATA_PATH)
    req = status["requirements"]
    run = status["execution"]
    ver = status["verification"]
    data["nodes"]["status"]["s"] = f'{display_state(status["architecture_status"])}, {display_state(status["overall_status"])}'
    data["views"]["status"]["note"] = (
        f'The status record holds {req["outlined"]} outlined requirements, {req["implemented"]} implemented, '
        f'{req["verified"]} verified, {run["tasks_total"]} tasks, and {run["tasks_verified"]} verified tasks.'
    )
    data["info"]["status"]["f"] = [
        f'{req["outlined"]} requirements outlined, {req["implemented"]} implemented, {req["verified"]} verified.',
        f'{run["tasks_total"]} tasks, {run["tasks_verified"]} verified. {run["current_phase"]}.',
        f'{ver["acceptance_total"]} acceptance tests with {ver["acceptance_passed"]} passed, '
        f'{ver["supplementary_total"]} supplementary checks with {ver["supplementary_passed"]} passed, '
        f'and {ver["scenarios_total"]} scenarios with {ver["scenarios_recorded"]} recorded.',
        f'Live Muse primary chain {display_state(str(ver["live_muse_primary_chain"])).lower()}.',
    ]
    data["info"]["status"]["status"] = "ga" if status["architecture_status"] == "as_built" else "pv"
    data["info"]["status"]["sl"] = display_state(status["overall_status"])
    atomic_json(DATA_PATH, data)


def run_checked(command: list[str], cwd: Path = WORKSPACE) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}")
    return result


def build_and_check() -> tuple[Path, str]:
    # page.json is tracked with a workspace-relative output; the kit needs an absolute
    # path, so it is set only for the build and restored afterwards.
    page_config = load_json(PAGE_CONFIG_PATH)
    relative_output = page_config["output"]
    output = WORKSPACE / relative_output if not Path(relative_output).is_absolute() else Path(relative_output)
    atomic_json(PAGE_CONFIG_PATH, {**page_config, "output": str(output)})
    try:
        return _build_and_check(output)
    finally:
        atomic_json(PAGE_CONFIG_PATH, page_config)


def _build_and_check(output: Path) -> tuple[Path, str]:
    check_dir = WORKSPACE / "check" / "status-current"
    if check_dir.exists():
        shutil.rmtree(check_dir)

    run_checked([sys.executable, "-I", str(SKILL / "scripts/inline_assets.py"), str(PAGE_DIR)])
    run_checked([sys.executable, "-I", str(KIT / "build_page.py"), str(PAGE_DIR)])
    run_checked([str(SKILL / "scripts/check_linux.sh"), str(output), str(check_dir)])
    run_checked([sys.executable, "-I", str(WORKSPACE / "check/verify_page.py"), str(output), str(STATUS_PATH), str(PAGE_CONFIG_PATH)])
    lint_copy_split(check_dir)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return output, digest


def update_current_metadata(output: Path, digest: str) -> None:
    """Keep the current-output fields in the project note and build report accurate."""
    size = output.stat().st_size
    note = PROJECT_NOTE_PATH.read_text(encoding="utf-8")
    note, note_count = re.subn(
        r"One self-contained HTML file\. \d+ bytes\. SHA-256 `[0-9a-f]{64}`\.",
        f"One self-contained HTML file. {size} bytes. SHA-256 `{digest}`.",
        note,
        count=1,
    )
    if note_count != 1:
        raise ValueError("PROJECT_NOTE.md current-output metadata was not found exactly once")
    PROJECT_NOTE_PATH.write_text(note, encoding="utf-8")

    report = BUILD_REPORT_PATH.read_text(encoding="utf-8")
    report, byte_count = re.subn(
        r"\| Bytes \| \d+ \|",
        f"| Bytes | {size} |",
        report,
        count=1,
    )
    report, hash_count = re.subn(
        r"\| SHA-256 \| `[0-9a-f]{64}` \|",
        f"| SHA-256 | `{digest}` |",
        report,
        count=1,
    )
    if byte_count != 1 or hash_count != 1:
        raise ValueError("BUILD_REPORT.md current-output metadata was not found exactly once")
    BUILD_REPORT_PATH.write_text(report, encoding="utf-8")


NARRATION_BEGIN = '<div class="stack" data-narration>'


def lint_copy_split(check_dir: Path) -> None:
    """Lint page copy, with the quoted video narration linted under the narration exemption.

    Narration is spoken by the presenter, so the copy standard lets it address the viewer
    directly; the rest of the page keeps every rule.
    """
    body = BODY_SOURCE_PATH.read_text(encoding="utf-8")
    start = body.find(NARRATION_BEGIN)
    if start < 0:
        run_checked([sys.executable, str(VOLLENCOMS / "scripts/lint_copy.py"), str(BODY_SOURCE_PATH)])
        return
    end = body.index("\n  </div>", start)
    check_dir.mkdir(parents=True, exist_ok=True)
    page_part = check_dir / "lint-page.html"
    narration_part = check_dir / "lint-narration.html"
    page_part.write_text(body[:start] + body[end:], encoding="utf-8")
    narration_part.write_text(body[start:end], encoding="utf-8")
    run_checked([sys.executable, str(VOLLENCOMS / "scripts/lint_copy.py"), str(page_part)])
    run_checked([sys.executable, str(VOLLENCOMS / "scripts/lint_copy.py"), "--allow-second-person", str(narration_part)])


def publish_ava(output: Path, status: dict, digest: str) -> dict:
    source_path = "Meta-Global-AI-Developer-Hackathon-2026-City-Permits/docs/solution-architecture/acme-city-permits/"
    command = [
        sys.executable,
        "-B",
        str(AVA_ROOT / "library_add.py"),
        "add",
        str(output),
        "--root",
        str(AVA_ROOT),
        "--id",
        ARTICLE_ID,
        "--title",
        "ACME City Permits Architecture",
        "--date",
        "2026-10-26",
        "--area",
        "Hackathon",
        "--kind",
        "architecture",
        "--summary",
        "Registry MDM permit application with four personas, Muse Spark agents that propose and people who decide, built during the hackathon week.",
        "--tag",
        "ACME City",
        "--tag",
        "Permitting",
        "--tag",
        "MDM",
        "--tag",
        "Muse",
        "--tag",
        "In implementation",
        "--source-path",
        source_path,
        "--replace",
    ]
    result = run_checked(command)
    entry = json.loads(result.stdout)
    if entry.get("id") != ARTICLE_ID:
        raise RuntimeError("AVA returned an unexpected article id")
    status["library"]["published"] = True
    status["library"]["last_published_at"] = datetime.now(timezone.utc).isoformat()
    status["library"]["last_page_sha256"] = digest
    atomic_json(STATUS_PATH, status)
    return entry


def append_receipt(receipt: dict) -> None:
    with RECEIPT_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, ensure_ascii=False) + "\n")
    with BUILD_REPORT_PATH.open("a", encoding="utf-8") as handle:
        handle.write(
            "\n## Status update " + receipt["completed_at"] + "\n\n"
            + f"- Page SHA-256: `{receipt['page_sha256']}`\n"
            + f"- Status as of: `{receipt['status_as_of']}`\n"
            + f"- Checker and independent status verification: PASS\n"
            + f"- Private AVA Library replacement: {'PASS' if receipt['published_to_ava'] else 'not requested'}\n"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish-ava", action="store_true", help="Replace the private AVA Library article after all checks pass")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    status = load_json(STATUS_PATH)
    validate_status(status)
    update_sources(status)
    output, digest = build_and_check()
    update_current_metadata(output, digest)
    library_entry = None
    if args.publish_ava:
        library_entry = publish_ava(output, status, digest)
    receipt = {
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "status_as_of": status["as_of"],
        "page": str(output),
        "page_sha256": digest,
        "published_to_ava": bool(args.publish_ava),
        "library_id": library_entry.get("id") if library_entry else None,
    }
    append_receipt(receipt)
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
