# UI Layer Split Implementation Plan (OPTIONAL)

> **OPTIONAL. Start only when every lane is merged and nobody else is editing
> `repo/src/acme_city/ui/`.** Randall asked for this plan on 2026-10-29 and
> marked it optional for when the lanes are clear. If anything for the
> submission is still open, finish that first and skip this plan. It is worth
> doing, but not at the risk of a working demo.

> **For agentic workers:** Implement this plan task-by-task. Randall chose
> ultracode (2026-10-29): run it as a Workflow with one fresh agent per task, and
> a parent gate between tasks that runs the task's acceptance checks and the
> snapshot comparison before the next task starts. A runner never starts the
> next task itself. Steps use checkbox (`- [ ]`) syntax.

## Models

Randall: "If a better model is needed, we need to allow that" (2026-10-29).
The cheap local model is the default, and each task steps up when the work needs
judgment or when a runner fails.

| Task | Starting model | Why |
|---|---|---|
| 1 Snapshot harness and move script | The cheap local model | The code is given in full below. |
| 2 to 5 `router.py` routes and actions | A stronger local model | For about 60 handlers, the runner decides which private helpers move with each one and which stay shared. |
| 6 to 9 section moves by marker | The cheap local model | The script moves the code. The runner writes imports and re-export lists from ruff's output. |
| 0 and 10, and every gate | Parent (the strongest model) | Preconditions, independent acceptance and the hand-off. |

**Stepping up.** A task moves to the next model (the cheap local model, then a
stronger local model, then the strongest)
when either of these happens:
- its acceptance checks fail after two corrections on the same model;
- the runner reports that the task needs a judgment the plan does not settle.

Start the stronger model fresh, with the task text, the failing output and the
`git diff` of the attempt. Reset the attempt with `git checkout -- repo/src`, or
keep it if the diff is sound. Record each step-up and its reason in the
hand-off note.

The parent never accepts a task on a runner's word. The gate reruns the checks.

**Goal:** Split the four oversized UI modules into one module per area. No
behaviour changes: every route, action, rendered page and import path stays the
same.

**Architecture:** This continues the pattern the newer screens already use:
`ops_routes.py`, `steward_routes.py`, `steward_automation_routes.py`,
`agent_routes.py` and `policy_routes.py` each hold one area's routes and a
`HANDLERS` (or `ACTIONS`) dict that `router.py` merges into `ACTION_HANDLERS`.
Each move cuts a section into a new module word for word. The old module then
re-exports the moved names, so the 79 files that import from these modules keep
working. A snapshot of every route, action, importable name and rendered screen
is taken before the first move and compared after every task.

**Tech Stack:** Python 3, FastAPI, Jinja2, SQLAlchemy, pytest with xdist,
Playwright browser tests.

**Spec:** Randall's request in session DemoVideo (2026-10-29): "Plan it out and
mark it as optional when the lanes are clear." The analysis is in the same
session. Four files hold about 12,200 lines, 14% of the app, and parallel lanes
kept colliding in `router.py`.

**Parent plan:** none.

## Global Constraints

- No behaviour change. The snapshot comparison in Task 1 must report zero
  differences after every task.
- Move code word for word. No renames, no refactors, and no fixes on the way.
  A bug found while moving goes into the hand-off note, not into the code.
- Every name importable from `acme_city.ui.view_models`, `acme_city.ui.router`,
  `acme_city.ui.admin_views` or `acme_city.ui.steward_views` before the split
  stays importable from the same path afterwards.
- Names that tests monkeypatch stay defined in their current module, together
  with every function that reads them: `view_models.PermissionResolver`,
  `view_models.SCREEN_PERMISSIONS`, `view_models.SCREEN_DOMAIN`
  (`tests/ui/test_admin_tabs.py`, `tests/ui/test_nav_plugins.py`). A function
  that reads one of them does not move.
- Unit tests run with `PYTHONPATH=src`, because the shared venv points at the
  main checkout. Use `-n 6` for the full suite.
- One branch, `refactor/ui-split`, in its own worktree. No push and no deploy;
  HackathonMuse reviews and merges.
- `tests/regression/data/owned_hunks.json` records every moved function under
  `moved`, the way Wave 0 recorded `ui_intake_queue`.

## The recipe every move task follows

Every task from 2 to 9 uses these steps. Each task repeats the parts it needs,
so a runner can read one task on its own.

1. Move the code with the script from Task 1, never by retyping it:
   `python3 scripts/ui_split_move.py src/acme_city/ui/<old>.py src/acme_city/ui/<new>.py "<start marker>" "<end marker>"`.
   It cuts the lines from the start marker up to (not including) the end marker
   and appends them to the new module unchanged. It prints the SHA-256 of the
   moved text, which it reads back from both files.
   Marker strings are unique substrings of the section comment lines, for
   example `# ---- work queue` written as it appears in the file. An empty end
   marker means end of file.
   For moves that are not a whole section (Tasks 2 to 5), call the script once
   per contiguous block, using the first line of the function after the block
   as the end marker.
2. Put the new module's header above the moved text: a docstring that names the
   area, `from __future__ import annotations`, and the imports.
3. Find the undefined names with
   `uvx ruff check --select F821,F811,F401 --no-cache src/acme_city/ui/<new>.py src/acme_city/ui/<old>.py`
   (ruff 0.17.3 is cached for uvx on this host), and import each one from where
   it is defined. Shared helpers stay in the old module and are imported from
   it.
4. At the end of the old module, add one re-export block that lists every moved
   name explicitly, private names included:
   `from acme_city.ui.<new> import (a, b, _c)  # noqa: E402,F401 - moved, re-exported`.
   The block goes at the end because the new module imports helpers from the
   old one.
5. Add each moved name to the old module's `__all__` if it was there before.
6. Run the task's acceptance checks and the snapshot comparison.

---

### Task 0: Preconditions (parent only, no runner)

**Requirement:** the plan starts only when it is safe to start.

**Acceptance checks:**
- `git branch --no-merged main | grep -E "lane/|feature/|fix/|design/"` lists
  no live branch that touches `repo/src/acme_city/ui/`. Check each listed
  branch with `git diff --stat main...<branch> -- repo/src/acme_city/ui`.
- HackathonMuse confirms in writing that no lane is still writing to
  `repo/src/acme_city/ui/`.
- `PYTHONPATH=src python -m pytest -q -n 6` on main reports no failure. The one
  known environmental failure, `tests/unit/test_reset.py::test_reset_script_initializes_an_empty_alembic_shell`,
  is fixed or explained first.

- [ ] **Step 1: Ask HackathonMuse for the all-clear and record the reply in the hand-off note.**
- [ ] **Step 2: Create the worktree.**

Run: `git worktree add -b refactor/ui-split ~/Projects/Personal/acme-permits-ui-split-wt main`

---

### Task 1: Snapshot harness

**Requirement:** the proof that nothing changed.

**Files:**
- Create: `repo/scripts/ui_split_snapshot.py`
- Create: `repo/scripts/ui_split_move.py`
- Snapshots are written to `repo/var/ui-split/` (git-ignored, because `var/` is
  in `.gitignore`).

**Interfaces:**
- Produces:
  - `python3 scripts/ui_split_snapshot.py capture <label>` writes `var/ui-split/<label>.json`.
  - `python3 scripts/ui_split_snapshot.py compare <a> <b>` prints each
    difference and exits 1 if there is any.

**Acceptance checks:**
- Two captures of unchanged code compare equal:
  `capture base && capture base2 && compare base base2` exits 0.
- `base.json` holds at least 60 routes, every `ACTION_HANDLERS` key, the
  public and private names of the four modules, and one page per persona and
  screen.

- [ ] **Step 1: Write the harness.**

```python
#!/usr/bin/env python3
"""Snapshot the UI surface before and after the UI split, and compare snapshots.

capture <label>   writes var/ui-split/<label>.json
compare <a> <b>   prints every difference and exits 1 if there is any

A snapshot holds the route table, the action handler table, the names each
split module exports, and the rendered HTML of every screen for every persona
on a fixed fixture database.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "integration"))
from insight_support import build_environment  # noqa: E402

from acme_city.app import create_app  # noqa: E402

OUT = ROOT / "var" / "ui-split"
MODULES = ("view_models", "router", "admin_views", "steward_views")
PERSONAS = (
    "persona_applicant",
    "persona_data_steward",
    "persona_permit_reviewer",
    "persona_city_administrator",
    "persona_agent_operator",
)
EXTRA_PATHS = ("/", "/select", "/lifecycle", "/walkthrough", "/map", "/property", "/city/", "/city/community", "/apply", "/apply/track")
#: Spans that change on every run and say nothing about the code.
NOISE = (
    (re.compile(r'name="csrf_token" value="[^"]*"'), 'name="csrf_token" value=""'),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?([+-]\d{2}:?\d{2}|Z)?"), "<time>"),
    (re.compile(r"\bcorr_[0-9a-f]{8,}\b"), "<corr>"),
)


def _normalise(text: str) -> str:
    for pattern, replacement in NOISE:
        text = pattern.sub(replacement, text)
    return text


def _names() -> dict[str, list[str]]:
    result = {}
    for name in MODULES:
        module = importlib.import_module(f"acme_city.ui.{name}")
        result[name] = sorted(key for key in vars(module) if not key.startswith("__"))
    return result


def _paths(client: TestClient) -> list[str]:
    from acme_city.ui import view_models

    paths = {item["href"] for item in view_models.SCREENS if item.get("href")}
    paths.update(EXTRA_PATHS)
    queue = client.get("/queue/review").text
    match = re.search(r'href="(/permits/[^"/?#]+)"', queue)
    if match:
        paths.add(match.group(1))
    found = client.get("/property").text
    match = re.search(r'href="(/property/[^"/?#]+)"', found)
    if match:
        paths.add(match.group(1))
    return sorted(paths)


def capture(label: str) -> None:
    from acme_city.ui.router import ACTION_HANDLERS

    with tempfile.TemporaryDirectory() as directory:
        settings = build_environment(Path(directory), synthetic=True, name="snapshot.db")
        app = create_app(settings)
        routes = sorted(
            f"{','.join(sorted(getattr(route, 'methods', None) or []))} {route.path} {getattr(route, 'name', '')} "
            f"{getattr(route, 'operation_id', '') or ''}"
            for route in app.routes
        )
        pages: dict[str, dict[str, object]] = {}
        with TestClient(app) as client:
            client.post("/api/session/select", json={"actor_id": "persona_city_administrator"})
            paths = _paths(client)
            for actor in ("",) + PERSONAS:
                client.cookies.clear()
                if actor:
                    client.post("/api/session/select", json={"actor_id": actor})
                for path in paths:
                    response = client.get(path, follow_redirects=False)
                    body = _normalise(response.text)
                    pages[f"{actor or 'signed-out'} {path}"] = {
                        "status": response.status_code,
                        "location": response.headers.get("location", ""),
                        "sha256": hashlib.sha256(body.encode()).hexdigest(),
                        "length": len(body),
                    }
    snapshot = {
        "routes": routes,
        "actions": sorted(ACTION_HANDLERS),
        "names": _names(),
        "pages": pages,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{label}.json").write_text(json.dumps(snapshot, indent=1, sort_keys=True), encoding="utf-8")
    print(f"captured {label}: {len(routes)} routes, {len(snapshot['actions'])} actions, {len(pages)} pages")


def compare(first: str, second: str) -> int:
    a = json.loads((OUT / f"{first}.json").read_text(encoding="utf-8"))
    b = json.loads((OUT / f"{second}.json").read_text(encoding="utf-8"))
    problems = []
    for key in ("routes", "actions"):
        for item in sorted(set(a[key]) ^ set(b[key])):
            problems.append(f"{key}: {'only in ' + first if item in a[key] else 'only in ' + second}: {item}")
    for module in MODULES:
        missing = sorted(set(a["names"][module]) - set(b["names"][module]))
        for name in missing:
            problems.append(f"names: {module}.{name} is no longer importable")
    for page in sorted(set(a["pages"]) | set(b["pages"])):
        if a["pages"].get(page) != b["pages"].get(page):
            problems.append(f"page: {page}: {a['pages'].get(page)} -> {b['pages'].get(page)}")
    for line in problems:
        print(line)
    print(f"{len(problems)} difference(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "capture":
        capture(sys.argv[2])
    elif len(sys.argv) == 4 and sys.argv[1] == "compare":
        raise SystemExit(compare(sys.argv[2], sys.argv[3]))
    else:
        raise SystemExit(__doc__)
```

`names` only fails on a name that disappears. New names in a module (the
re-export lines) are expected.

- [ ] **Step 1b: Write the move script `repo/scripts/ui_split_move.py`.**

```python
#!/usr/bin/env python3
"""Move a block of lines from one module to another, byte for byte.

ui_split_move.py <source.py> <target.py> <start marker> [<end marker>]

The block runs from the first line containing the start marker up to, but not
including, the first later line containing the end marker (end of file when the
end marker is empty or absent). The block is appended to the target and removed
from the source, and the SHA-256 of the block is checked in both places.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) not in (4, 5):
        raise SystemExit(__doc__)
    source, target = Path(sys.argv[1]), Path(sys.argv[2])
    start_marker = sys.argv[3]
    end_marker = sys.argv[4] if len(sys.argv) == 5 else ""
    lines = source.read_text(encoding="utf-8").splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if start_marker in line]
    if len(starts) != 1:
        raise SystemExit(f"start marker found {len(starts)} times, expected once: {start_marker!r}")
    start = starts[0]
    end = len(lines)
    if end_marker:
        ends = [i for i in range(start + 1, len(lines)) if end_marker in lines[i]]
        if not ends:
            raise SystemExit(f"end marker not found after the start: {end_marker!r}")
        end = ends[0]
    block = "".join(lines[start:end])
    digest = hashlib.sha256(block.encode()).hexdigest()
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    separator = "" if not existing or existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
    target.write_text(existing + separator + block, encoding="utf-8")
    source.write_text("".join(lines[:start] + lines[end:]), encoding="utf-8")
    if hashlib.sha256(target.read_text(encoding="utf-8")[-len(block):].encode()).hexdigest() != digest:
        raise SystemExit("the block in the target does not match the source block")
    print(f"moved {end - start} lines, sha256 {digest}")


if __name__ == "__main__":
    main()
```

Check it on a scratch copy before any real move:

Run: `cp src/acme_city/ui/steward_views.py /tmp/sv.py && python3 scripts/ui_split_move.py /tmp/sv.py /tmp/sv_new.py "- activity" "- registration" && wc -l /tmp/sv.py /tmp/sv_new.py && rm /tmp/sv.py /tmp/sv_new.py`
Expected: "moved N lines, sha256 ...", and the two line counts add up to the
original file's count. Use the exact text of the section comment for the
marker, for example `# ------------------------------------------------------------------- activity`
cut down to a unique substring such as `- activity`.

- [ ] **Step 2: Capture twice and compare.**

Run: `cd repo && PYTHONPATH=src python3 scripts/ui_split_snapshot.py capture base && PYTHONPATH=src python3 scripts/ui_split_snapshot.py capture base2 && PYTHONPATH=src python3 scripts/ui_split_snapshot.py compare base base2`
Expected: `0 difference(s)`. If a page differs between the two runs, find the
span that changed. Add a regex for it to `NOISE`, keeping it as narrow as the
span, and repeat until two runs compare equal. Record each added regex in the
hand-off note.

- [ ] **Step 3: Commit the harness and the move script only.**

Run: `git add repo/scripts/ui_split_snapshot.py repo/scripts/ui_split_move.py && git commit -m "UI split: snapshot harness and move script"`

---

### Task 2: `router.py` permit screens and actions to `permit_routes.py`

**Requirement:** the permit workspace and the permit actions live in one module.

**Files:**
- Create: `repo/src/acme_city/ui/permit_routes.py`
- Modify: `repo/src/acme_city/ui/router.py`
  - Moves the route `ui_permit_workspace` (`/permits/{application_id}`).
  - Moves every `_permit_*`, `_recommendation_*`, `_extraction_*` and
    `_intake_*` action handler, plus the private helpers only they use.
  - Moves the keys `permit.*`, `recommendation.*`, `extraction.*` and
    `intake.*` out of the `ACTION_HANDLERS` literal (17 + 2 + 1 + 1 keys today).
- Modify: `repo/tests/regression/data/owned_hunks.json`, adding the moved
  functions under `moved["src/acme_city/ui/router.py"]`.

**Interfaces:**
- Consumes: `ActionContext`, `Outcome`, `page_context`, `render`, `ui_actor`
  and `require_actor`, all from `acme_city.ui.router`.
- Produces:
  - `permit_routes.router: APIRouter`.
  - `permit_routes.HANDLERS: dict[str, Callable[[ActionContext], Outcome]]`.

**Acceptance checks:**
- `PYTHONPATH=src python3 scripts/ui_split_snapshot.py capture t2 && PYTHONPATH=src python3 scripts/ui_split_snapshot.py compare base t2` → `0 difference(s)`.
- `PYTHONPATH=src python -m pytest -q -n 6 tests/ui tests/unit/test_lifecycle_map_probe.py tests/acceptance` → no failure.
- `wc -l src/acme_city/ui/router.py` is smaller than before by roughly the
  moved lines.

- [ ] **Step 1: Create `permit_routes.py` with this header.**

```python
"""The permit workspace screen and the permit actions.

Moved from ``router.py`` word for word (UI split, 2026-10-29 plan). The
handlers are merged into ``ACTION_HANDLERS`` by ``router.py``.
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from acme_city.auth.router import get_session
from acme_city.ui.router import ActionContext, Outcome, page_context, render, require_actor

router = APIRouter(tags=["ui"])
```

- [ ] **Step 2: Cut the route and the handlers from `router.py` into the new
  module.** Change only the route decorator, from `@router.get(` on the main
  router to `@router.get(` on the new module's `router`. The text is identical,
  so in practice nothing changes.
- [ ] **Step 3: Build `HANDLERS` in `permit_routes.py` from the moved keys,
  copied word for word from the `ACTION_HANDLERS` literal, and delete those
  keys from the literal.**
- [ ] **Step 4: Wire it in at the end of `router.py`, next to the other area
  modules.**

```python
from acme_city.ui import permit_routes as _permit_routes  # noqa: E402

router.include_router(_permit_routes.router)
ACTION_HANDLERS.update(_permit_routes.HANDLERS)
```

- [ ] **Step 5: Re-export every moved name that other files import from
  `router`.** Find them with
  `git grep -n "from acme_city.ui.router import" -- repo | grep -E "<moved names>"`,
  and add them to the end-of-file re-export block.
- [ ] **Step 6: Run the ruff check from the recipe, the snapshot comparison and the tests from the
  acceptance checks.**
- [ ] **Step 7: Commit with the message "UI split: permit routes and actions out of router.py".**

---

### Task 3: `router.py` property, map and queue screens to `property_routes.py` and `queue_routes.py`

**Requirement:** the property master, the town map and the work queues each
live in their area module.

**Files:**
- Create: `repo/src/acme_city/ui/property_routes.py`, holding `ui_property_find`,
  `ui_property_suggest`, `ui_property_record` and `ui_town_map`, plus the
  `_parcel_*` action handlers and keys.
- Create: `repo/src/acme_city/ui/queue_routes.py`, holding `ui_root`,
  `ui_work_queue` and `ui_review_queue`.
- Modify: `repo/src/acme_city/ui/router.py` and
  `repo/tests/regression/data/owned_hunks.json`.

**Interfaces:**
- Consumes: the same router helpers as Task 2.
- Produces: `property_routes.router`, `property_routes.HANDLERS` and
  `queue_routes.router`.

**Acceptance checks:**
- `compare base t3` → `0 difference(s)`.
- `PYTHONPATH=src python -m pytest -q -n 6 tests/ui tests/browser/test_map_buildings_browser.py tests/unit/test_map_buildings.py` → no failure.

- [ ] **Step 1: Follow the recipe for `property_routes.py`, with the Task 2 header changed to name the area.**
- [ ] **Step 2: Follow the recipe for `queue_routes.py`.**

A route that moves into an included router is registered later than before, so
any path that two patterns can match may resolve differently. `router.py`
already warns that the `/apply` help routes must come before
`/apply/{type_key}`. The page snapshot catches a changed resolution only for a
path it requests. Before moving a route, look for a second pattern that could
match its paths:

Run: `git grep -n -E '@(router|persona_router)\.(get|post)\("/(permits|property|queue|apply)' -- repo/src/acme_city/ui`
Expected: for every pair where one pattern's literal segment could fill the
other's `{parameter}`, add one concrete path of each to `EXTRA_PATHS`. Capture
a fresh `base` before the move if `EXTRA_PATHS` changed.

- [ ] **Step 3: Snapshot, test and commit with the message "UI split: property, map and queue routes out of router.py".**

---

### Task 4: `router.py` administration screens and configuration actions to `admin_routes.py`

**Requirement:** the City Administrator screens and their actions live in one
module.

**Files:**
- Create: `repo/src/acme_city/ui/admin_routes.py`. It holds the routes
  `ui_insight_city`, `ui_rules_fees_old`, `ui_rules_fees`,
  `ui_planning_overview`, `ui_reconciliation`, `ui_governance_sources`,
  `ui_administration` and `ui_permit_type_icon`. It also holds the
  `governance.*`, `rule.*`, `fee.*`, `config.*` and `finance.*` handlers and
  keys (6 + 5 + 5 + 5 + 5 today).
- Modify: `repo/src/acme_city/ui/router.py` and `owned_hunks.json`.

**Interfaces:**
- Produces: `admin_routes.router` and `admin_routes.HANDLERS`.

**Acceptance checks:**
- `compare base t4` → `0 difference(s)`.
- `PYTHONPATH=src python -m pytest -q -n 6 tests/ui tests/acceptance tests/security` → no failure.

- [ ] **Step 1: Follow the recipe.** `ui_agent_intake` and
  `ui_agent_adjudication` stay where they are unless `agent_routes.py` already
  holds the agent area; in that case move them there in this task.
- [ ] **Step 2: Snapshot, test and commit with the message "UI split: administration routes out of router.py".**

---

### Task 5: `router.py` remaining registry actions to `steward_routes.py`

**Requirement:** the steward actions sit with the steward routes that already
exist.

**Files:**
- Modify: `repo/src/acme_city/ui/steward_routes.py`, adding the `registry.*`,
  `change.*`, `source.*` and `agent.*` handlers. The `agent.*` handlers go to
  `agent_routes.py` instead if it already defines `ACTIONS`.
- Modify: `repo/src/acme_city/ui/router.py` and `owned_hunks.json`.

**Acceptance checks:**
- `compare base t5` → `0 difference(s)`.
- `python3 -c "import re;s=open('src/acme_city/ui/router.py').read();m=re.search(r'ACTION_HANDLERS[^=]*= \{(.*?)\n\}',s,re.S);print(m.group(1).count('\":'))"`
  prints `0`, because the literal is now empty and every key arrives through an
  `update`.
- `wc -l src/acme_city/ui/router.py` is under 900.

- [ ] **Step 1: Follow the recipe and append the moved keys to the existing `HANDLERS` (or `ACTIONS`) dict.**
- [ ] **Step 2: Replace the emptied literal with `ACTION_HANDLERS: dict[str, Callable[[ActionContext], Outcome]] = {}`.**
- [ ] **Step 3: Snapshot, test and commit with the message "UI split: router.py keeps only context, security, rendering, persona and dispatch".**

---

### Task 6: `view_models.py` action catalogue to `action_catalog.py`

**Requirement:** the form definitions for every action live apart from the
navigation core.

**Files:**
- Create: `repo/src/acme_city/ui/action_catalog.py`. It holds the section from
  `# ---- actions` up to `# ---- permit icons` (about 1,300 lines).
- Modify: `repo/src/acme_city/ui/view_models.py` (re-export block at the end),
  `owned_hunks.json`.

**Interfaces:**
- Consumes: the helpers in `view_models.py` above the line `# ---- responsibility`.
- Produces: every moved name, re-exported from `view_models`.

**Acceptance checks:**
- `compare base t6` → `0 difference(s)`.
- `grep -n "PermissionResolver\|SCREEN_PERMISSIONS\|SCREEN_DOMAIN" src/acme_city/ui/action_catalog.py`
  prints nothing. If it prints a line, that function stays in `view_models.py`
  (Global Constraints).
- `PYTHONPATH=src python -m pytest -q -n 6 tests/ui` → no failure.

- [ ] **Step 1: Follow the recipe.**
- [ ] **Step 2: Snapshot, test and commit with the message "UI split: action catalogue out of view_models.py".**

---

### Task 7: `view_models.py` area view models to four modules

**Requirement:** each area's view model lives in its own module.

**Files:**
- Create: `repo/src/acme_city/ui/queue_views.py`, holding the sections
  `work queue` and `responsibility`.
- Create: `repo/src/acme_city/ui/permit_views.py`, holding the sections
  `permit icons`, `permit workspace` and `evidence`.
- Create: `repo/src/acme_city/ui/registry_views.py`, holding the sections
  `applicants`, `masters` and `steward review`.
- Create: `repo/src/acme_city/ui/config_views.py`, holding the sections
  `rules and fees`, `reconciliation` and `governance and sources`.
- Modify: `repo/src/acme_city/ui/view_models.py`, which keeps the constants,
  the navigation, the persona profiles, the helpers and one re-export block.
  Also modify `owned_hunks.json`.

**Acceptance checks:**
- `compare base t7` → `0 difference(s)`.
- `wc -l src/acme_city/ui/view_models.py` is under 1,300.
- The grep check from Task 6 prints nothing for each new file.
- `PYTHONPATH=src python -m pytest -q -n 6 tests/ui tests/unit tests/acceptance` → no failure.

- [ ] **Step 1: Move one new module at a time, and run the snapshot comparison after each one before starting the next.**
- [ ] **Step 2: Commit once all four compare clean, with the message "UI split: view models by area".**

---

### Task 8: `admin_views.py` by screen

**Requirement:** each administration screen's view lives in its own module.

**Files:**
- Create: `repo/src/acme_city/ui/admin_overview_views.py`, holding the section `overview`.
- Create: `repo/src/acme_city/ui/admin_rules_views.py`, holding the section `rules and fees` (about 1,180 lines).
- Create: `repo/src/acme_city/ui/admin_governance_views.py`, holding the section `governance screen`.
- Create: `repo/src/acme_city/ui/admin_reconciliation_views.py`, holding the section `reconciliation screen`.
- Modify: `repo/src/acme_city/ui/admin_views.py`, which keeps `helpers` and
  the re-export block. Also modify `owned_hunks.json`, where `admin_views.py`
  is listed under `functions`. Move its entries to `moved`.

**Acceptance checks:**
- `compare base t8` → `0 difference(s)`.
- `wc -l src/acme_city/ui/admin_views.py` is under 400.
- `PYTHONPATH=src python -m pytest -q -n 6 tests/ui tests/browser/test_admin_ui_browser.py` → no failure.

- [ ] **Step 1: Follow the recipe for each module, running the snapshot comparison after each one.**
- [ ] **Step 2: Commit with the message "UI split: admin views by screen".**

---

### Task 9: `steward_views.py` by part

**Requirement:** the steward views live in three focused modules.

**Files:**
- Create: `repo/src/acme_city/ui/steward_record_views.py`, holding the
  sections `party helpers`, `record profile`, `source / credential`, `parcels`
  and `comparison`.
- Create: `repo/src/acme_city/ui/steward_issue_views.py`, holding the sections
  `Data issues`, `focused case` and `evidence drawer`.
- Create: `repo/src/acme_city/ui/steward_page_views.py`, holding the sections
  `source records page`, `activity` and `registration`.
- Modify: `repo/src/acme_city/ui/steward_views.py`, which keeps
  `small helpers`, `freshness` and the re-export block. Also modify
  `owned_hunks.json`.

**Acceptance checks:**
- `compare base t9` → `0 difference(s)`.
- `wc -l src/acme_city/ui/steward_views.py` is under 400.
- `PYTHONPATH=src python -m pytest -q -n 6 tests/ui tests/browser/test_steward_browser.py` → no failure.

- [ ] **Step 1: Follow the recipe for each module, running the snapshot comparison after each one.**
- [ ] **Step 2: Commit with the message "UI split: steward views by part".**

---

### Task 10: Full verification and hand-off (parent only)

**Requirement:** the split is proven before anyone merges it.

**Acceptance checks:**
- `compare base final` → `0 difference(s)`.
- `PYTHONPATH=src python -m pytest -q -n 6` → the same pass count as the Task 0
  baseline, with no new failure.
- `python3 scripts/check_owned_hunks.py --actor-only --base main` passes.
- `python3 scripts/check_test_collection.py` and
  `python3 scripts/run_all_checks.py` pass, if the project runs them before a
  merge.
- A person follows `/walkthrough` steps 1 to 9 on a local demo started from
  the branch, and every step opens its screen.
- None of the four original files is over 1,300 lines, and no new file is over
  1,300 lines.

- [ ] **Step 1: Run the checks above.**
- [ ] **Step 2: Write the hand-off note for HackathonMuse.** It lists the
  branch SHA, the line counts before and after, the snapshot result, the
  `NOISE` regexes added in Task 1, and any bug seen but not fixed.
- [ ] **Step 3: Leave the merge, the restart of the demo on :8266, and any push to HackathonMuse and Randall.**
