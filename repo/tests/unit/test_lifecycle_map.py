"""The described permit life cycle matches the statuses and moves the code enforces."""
# REQUIRES: PER-03, PER-04, UX-04
# The life cycle page, the architecture record and the walkthrough read one
# table; these checks keep that table equal to the model and the services.

from __future__ import annotations

import json
import re
from collections import deque
from pathlib import Path

from acme_city.kernel.findings import FindingSpec
from acme_city.kernel.intake import route
from acme_city.permits import lifecycle_map as lm
from acme_city.persistence.models import permit

ROOT = Path(__file__).resolve().parents[2]


def _constraint_statuses() -> set[str]:
    for constraint in permit.Application.__table__.constraints:
        if str(getattr(constraint, "name", "")).endswith("status_allowed"):
            return set(re.findall(r"'([a-z_]+)'", str(constraint.sqltext)))
    raise AssertionError("the status_allowed constraint is missing")


def test_the_map_lists_exactly_the_statuses_the_model_allows() -> None:
    keys = [item.key for item in lm.STATUSES]
    assert len(keys) == len(set(keys))
    assert set(keys) == _constraint_statuses()


def test_every_move_starts_and_ends_on_a_known_status() -> None:
    keys = {item.key for item in lm.STATUSES}
    for move in lm.MOVES:
        assert move.sources and set(move.sources) <= keys, move.key
        assert move.target in keys | {lm.PREVIOUS}, move.key
        assert move.target not in move.sources, move.key


def test_only_the_seeded_only_statuses_are_unreachable_from_a_draft() -> None:
    seen, todo = {"draft"}, deque(["draft"])
    while todo:
        here = todo.popleft()
        for move in lm.moves_from(here):
            if move.target != lm.PREVIOUS and move.target not in seen:
                seen.add(move.target)
                todo.append(move.target)
    unreachable = {item.key for item in lm.STATUSES} - seen
    assert unreachable == {item.key for item in lm.STATUSES if item.seeded_only}


def test_end_statuses_leave_only_by_archive_or_a_new_validation() -> None:
    for item in lm.STATUSES:
        leaving = {move.key for move in lm.moves_from(item.key)}
        if item.kind == "end":
            assert leaving <= {"archive", "validate"}, item.key
        elif item.kind == "closed":
            assert leaving == {"restore"}, item.key
        else:
            assert leaving - {"archive"}, f"{item.key} has no way forward"


def test_every_person_move_names_a_permission_a_selectable_persona_holds() -> None:
    permissions = {
        row["permission_id"]
        for row in json.loads((ROOT / "config/permissions.json").read_text(encoding="utf-8"))["permissions"]
    }
    held = {
        grant["permission_id"]
        for persona in json.loads((ROOT / "config/actors.json").read_text(encoding="utf-8"))["personas"]
        if persona["selectable"]
        for grant in persona["grants"]
    }
    for move in lm.MOVES:
        if move.actor.startswith("agent:"):
            continue
        assert move.actor in permissions, move.key
        assert move.actor in held, move.key


def test_the_intake_router_reaches_the_two_statuses_the_map_names() -> None:
    targets = {move.target for move in lm.MOVES if move.actor == "agent:intake"}
    clear = route([], "residential").status
    blocked = route([FindingSpec("missing_field", "No site address", severity="block")], "residential").status
    assert {clear, blocked} == targets
