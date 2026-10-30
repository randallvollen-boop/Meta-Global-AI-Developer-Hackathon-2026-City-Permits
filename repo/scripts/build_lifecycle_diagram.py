#!/usr/bin/env python3
"""Write the permit life cycle diagram and moves table for the architecture page.

Both come from ``acme_city.permits.lifecycle_map`` and ``config/actors.json``,
so the page shows the same life cycle as the app's ``/lifecycle`` screen.

    PYTHONPATH=src python3 scripts/build_lifecycle_diagram.py \
        --svg ../docs/solution-architecture/acme-city-permits/diagram/permit-lifecycle.svg \
        --page ../docs/solution-architecture/acme-city-permits/page/body.src.html

``--page`` replaces the text between the LIFECYCLE_BEGIN and LIFECYCLE_END
markers of the page source.
"""

from __future__ import annotations

import argparse
import json
from html import escape
from pathlib import Path

from acme_city.permits import lifecycle_map as lm

ROOT = Path(__file__).resolve().parents[1]
BOX_W, BOX_H = 190, 56

#: Box positions (left, top): the main path on the second row, revisions above it.
LAYOUT: dict[str, tuple[int, int]] = {
    "revisions_requested": (500, 14),
    "draft": (20, 170),
    "submitted": (340, 170),
    "ready_for_review": (660, 170),
    "approved": (980, 170),
    "issued": (1300, 170),
    "needs_information": (340, 370),
    "under_review": (660, 370),
    "denied": (980, 370),
    "withdrawn": (1300, 370),
    "returned": (340, 560),
}
ARCHIVE_BOX = (660, 560, 510, BOX_H)
WIDTH, HEIGHT = 1510, 636

#: The edges drawn: (move key, source, offset along the normal, label dx, label dy).
#: Every move is in the table under the diagram; the caption names the ones folded away.
EDGES: tuple[tuple[str, str, int, int, int], ...] = (
    ("submit", "draft", 0, 0, -16),
    ("route_review", "submitted", 0, 0, -16),
    ("approve", "ready_for_review", 0, 0, -16),
    ("issue", "approved", 0, 0, -16),
    ("route_early", "submitted", 16, -110, 0),
    ("resubmit", "needs_information", 16, 50, 30),
    ("advance", "needs_information", 0, 22, 12),
    ("return", "needs_information", 0, 0, 0),
    ("revert_recommendation", "ready_for_review", 0, 0, 0),
    ("approve", "under_review", 0, 22, 12),
    ("deny", "under_review", 0, 0, -16),
    ("request_revisions", "ready_for_review", 0, 70, -6),
    ("resubmit", "revisions_requested", 0, -46, -6),
)

SHORT = {
    "submit": "Submit",
    "route_review": "Agent: to review",
    "approve": "Approve",
    "issue": "Issue",
    "route_early": "Agent: early resolution",
    "resubmit": "Resubmit",
    "advance": "Advance",
    "return": "Return",
    "revert_recommendation": "Revert recommendation",
    "deny": "Deny",
    "request_revisions": "Request revisions",
}


def _centre(key: str) -> tuple[float, float]:
    x, y = LAYOUT[key]
    return x + BOX_W / 2, y + BOX_H / 2


def _clip(cx: float, cy: float, dx: float, dy: float) -> tuple[float, float]:
    """Return where the ray from a box centre along (dx, dy) leaves the box."""
    scale = min(
        (BOX_W / 2) / abs(dx) if dx else float("inf"),
        (BOX_H / 2) / abs(dy) if dy else float("inf"),
    )
    return cx + dx * scale, cy + dy * scale


def _edge(source: str, target: str, offset: int, label: str, ldx: int, ldy: int) -> str:
    (ax, ay), (bx, by) = _centre(source), _centre(target)
    dx, dy = bx - ax, by - ay
    length = (dx * dx + dy * dy) ** 0.5
    nx, ny = -dy / length, dx / length
    ax, ay, bx, by = ax + nx * offset, ay + ny * offset, bx + nx * offset, by + ny * offset
    sx, sy = _clip(ax, ay, dx, dy)
    ex, ey = _clip(bx, by, -dx, -dy)
    mx, my = (sx + ex) / 2 + ldx, (sy + ey) / 2 + ldy
    width = 7 * len(label) + 10
    return (
        f'<line class="lc-edge" x1="{sx:.1f}" y1="{sy:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" marker-end="url(#lc-arrow)"/>'
        f'<rect class="lc-label-bg" x="{mx - width / 2:.1f}" y="{my - 10:.1f}" width="{width}" height="18" rx="4"/>'
        f'<text class="lc-label" x="{mx:.1f}" y="{my + 4:.1f}" text-anchor="middle">{escape(label)}</text>'
    )


def _box(key: str, label: str, kind: str, small: str = "") -> str:
    x, y = LAYOUT[key]
    cls = f"lc-box lc-{kind}" + (" lc-dashed" if small else "")
    text_y = y + BOX_H / 2 + (-2 if small else 5)
    extra = (
        f'<text class="lc-small" x="{x + BOX_W / 2}" y="{y + BOX_H / 2 + 16}" text-anchor="middle">{escape(small)}</text>'
        if small
        else ""
    )
    return (
        f'<g class="{cls}" data-status="{key}"><rect x="{x}" y="{y}" width="{BOX_W}" height="{BOX_H}" rx="10"/>'
        f'<text x="{x + BOX_W / 2}" y="{text_y}" text-anchor="middle">{escape(label)}</text>{extra}</g>'
    )


def build_svg() -> str:
    labels = {item.key: item for item in lm.STATUSES}
    moves = {move.key: move for move in lm.MOVES}
    body = []
    for key, source, offset, ldx, ldy in EDGES:
        move = moves[key]
        assert source in move.sources, (key, source)
        body.append(_edge(source, move.target, offset, SHORT[key], ldx, ldy))
    for key in LAYOUT:
        item = labels[key]
        body.append(_box(key, item.label, item.kind, "seeded history only" if item.seeded_only else ""))
    x, y, w, h = ARCHIVE_BOX
    body.append(
        f'<g class="lc-box lc-closed"><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10"/>'
        f'<text x="{x + w / 2}" y="{y + 24}" text-anchor="middle">Archived</text>'
        f'<text class="lc-small" x="{x + w / 2}" y="{y + 40}" text-anchor="middle">from any status but Issued; Restore returns the case</text></g>'
    )
    style = (
        ".lc-edge{stroke:var(--edge,#7a8794);stroke-width:1.6;fill:none}"
        ".lc-label-bg{fill:var(--bg,#fff);opacity:.92}"
        ".lc-label{font:600 12px var(--font,system-ui,sans-serif);fill:var(--muted,#55616d)}"
        ".lc-box rect{fill:var(--node,#fff);stroke:var(--node-line,#9aa6b2);stroke-width:1.5}"
        ".lc-box text{font:600 14px var(--font,system-ui,sans-serif);fill:var(--ink,#14233f)}"
        ".lc-box .lc-small{font-weight:400;font-size:12px;fill:var(--muted,#55616d)}"
        ".lc-start rect{stroke:#c98a12;stroke-width:2.5}.lc-active rect{stroke:var(--accent,#1d5fa8);stroke-width:2.5}"
        ".lc-end rect{stroke:#2f7d4f;stroke-width:2.5}.lc-closed rect{stroke-dasharray:2 0}"
        ".lc-dashed rect{stroke-dasharray:6 4}#lc-arrow path{fill:var(--edge,#7a8794)}"
        ".lc-svg{display:block;width:100%;min-width:1100px}"
    )
    return (
        f'<svg class="lc-svg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" '
        'aria-labelledby="lc-title lc-desc">'
        '<title id="lc-title">Permit life cycle of ACME City Permits</title>'
        '<desc id="lc-desc">The main path runs Draft, Submitted, Ready for review, Approved, Issued. '
        "The intake agent routes a submitted case to review or to early resolution (Needs information). "
        "From Needs information a person advances the case, returns it, or the applicant resubmits. "
        "A reviewer can request revisions, revert the agent recommendation (Under review), approve or deny. "
        "Any case but an issued one can be archived and restored. Withdrawn exists only in seeded history.</desc>"
        f"<style>{style}</style>"
        '<defs><marker id="lc-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
        '<path d="M0 0 L10 5 L0 10 z"/></marker></defs>'
        + "".join(body)
        + "</svg>"
    )


def _holders() -> dict[str, list[str]]:
    data = json.loads((ROOT / "config/actors.json").read_text(encoding="utf-8"))
    holders: dict[str, list[str]] = {}
    for persona in data["personas"]:
        if not persona["selectable"]:
            continue
        for grant in persona["grants"]:
            holders.setdefault(grant["permission_id"], []).append(persona["label"])
    return holders


def build_section(svg: str) -> str:
    labels = {item.key: item.label for item in lm.STATUSES}
    holders = _holders()
    rows = []
    for move in lm.MOVES:
        who = (
            "Intake agent (automatic)"
            if move.actor.startswith("agent:")
            else ", ".join(holders.get(move.actor, [])) or "none"
        )
        target = "The status held before" if move.target == lm.PREVIOUS else labels[move.target]
        rows.append(
            "<tr>"
            f"<td><b>{escape(move.action)}</b></td>"
            f"<td>{escape(', '.join(labels[key] for key in move.sources))}</td>"
            f"<td>{escape(target)}</td>"
            f"<td>{escape(who)}</td>"
            f"<td><code>{escape(move.actor)}</code></td>"
            f"<td>{escape(move.note)}</td>"
            "</tr>"
        )
    return (
        '<section id="lifecycle"><div class="wrap">\n'
        "  <h2>Permit life cycle</h2>\n"
        f'  <p class="lede">A permit application holds one of {len(lm.STATUSES)} statuses and changes status through '
        f"{len(lm.MOVES)} moves. The intake agent only routes a submitted case. A person makes every other move. "
        "Each move checks the person's grant and the case version, and writes an audit record.</p>\n"
        f'  <figure class="lc-figure"><div class="lc-scroll" style="overflow-x:auto">{svg}</div><figcaption>The diagram shows the main moves. '
        "Run application checks, Request information, Archive and Restore apply from several statuses. "
        "The table lists them, with Approve and Deny from Submitted and Needs information.</figcaption></figure>\n"
        '  <div class="tbl-wrap"><table>\n'
        "    <thead><tr><th>Move</th><th>From</th><th>To</th><th>Who</th><th>Grant</th><th>Note</th></tr></thead>\n"
        f"    <tbody>{''.join(rows)}</tbody>\n"
        "  </table></div>\n"
        "  <p>The table lives in <code>repo/src/acme_city/permits/lifecycle_map.py</code>. "
        "A generator, <code>repo/scripts/build_lifecycle_diagram.py</code>, draws this diagram and table from it. "
        "A unit test, <code>repo/tests/unit/test_lifecycle_map.py</code>, checks it against the model's status constraint, "
        "the status sets the services enforce, the persona grants and the intake router. "
        "The same table drives the in-app screen <code>/lifecycle</code>. "
        "The guided path for judges is <code>/walkthrough</code>.</p>\n"
        "  <p><b>Known gaps.</b> Withdrawn appears only in seeded history, because the app has no withdraw action yet. "
        "Run application checks reopens any case that is not issued, returned or archived. "
        "That includes an approved or denied case, by design of the evaluation service.</p>\n"
        "</div></section>"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--svg", type=Path, required=True)
    parser.add_argument("--page", type=Path)
    args = parser.parse_args()
    svg = build_svg()
    args.svg.write_text(svg + "\n", encoding="utf-8")
    if args.page:
        text = args.page.read_text(encoding="utf-8")
        begin, end = "<!-- LIFECYCLE_BEGIN -->", "<!-- LIFECYCLE_END -->"
        head, rest = text.split(begin, 1)
        _, tail = rest.split(end, 1)
        args.page.write_text(f"{head}{begin}\n{build_section(svg)}\n{end}{tail}", encoding="utf-8")


if __name__ == "__main__":
    main()
