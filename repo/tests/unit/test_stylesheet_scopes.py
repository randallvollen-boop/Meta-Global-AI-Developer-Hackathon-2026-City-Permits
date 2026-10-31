"""Per-area stylesheets: prefix scoping, the insight.css move, and the head links."""
# REQUIRES: W0-1

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "acme_city" / "static"
APP_CSS = "./src/acme_city/static/app.css"

sys.path.insert(0, str(ROOT / "tests" / "integration"))
from insight_support import ADMIN, build_environment  # noqa: E402

from acme_city.app import create_app  # noqa: E402
from acme_city.ui.router import router as ui_router  # noqa: E402

PREFIXES = {
    "steward.css": (".stw-", "body[data-screen="),
    "steward-auto.css": (".stwa-",),
    "admin-a.css": (".adm-",),
    "admin-b.css": (".admin-b",),
    "operator.css": (".opr-", "body[data-screen="),
    "nav-more.css": (".nav-more",),
    "demo-video.css": (".demo-video",),
    "guide.css": (".guide-",),
    "city-community.css": (".community-page", ".community-record-page"),
}

#: The selectors the staff frame (slice S1) removed on purpose: the demo
#: banner, the side foot and the build label that stood in it.
STAFF_FRAME_REMOVED = (".demo-banner", ".side-foot", ".mock-tag")

#: The selectors the staff frame (slice S1) added on purpose: the disclosure
#: that holds the detail list of the last action.
STAFF_FRAME_ADDED = (
    ".feedback-more",
    ".feedback-more > summary",
    ".feedback-more > summary:hover",
)

#: The selectors the persona menu (slice S4) added on purpose: the chip in the
#: top bar and the list of personas that opens under it.
#: The agents' Incoming list (slice D4) added these on purpose.
AGENT_INBOX_ADDED = (
    ".agent-inbox .card-b > .lock",
    ".agent-inbox .action-form",
)

PERSONA_MENU_ADDED = (
    ".account-trigger::after",
    ".account-switch-label",
    ".account-personas",
    ".account-personas form",
    ".account-persona",
    ".account-persona span",
    ".account-persona:hover",
    '.account-persona[aria-current="true"]',
    ".account-persona:focus-visible",
)


#: The reviewer screens (R1-R3) dropped the sticky right rail on purpose; the
#: workspace is one column now (".ws" lost its narrow-screen rule).  No selector was added.
REVIEWER_SLIM_REMOVED = (".rail > *", ".rail", ".ws")
REVIEWER_SLIM_ADDED: tuple[str, ...] = ()


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _rules(text: str) -> list[str]:
    """Top-level rules (an at-rule counts as one), whitespace-normalised, in order."""
    text = _strip_comments(text)
    rules, depth, start = [], 0, 0
    for index, char in enumerate(text):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                rules.append(" ".join(text[start:index + 1].split()))
                start = index + 1
        elif char == ";" and depth == 0:
            rules.append(" ".join(text[start:index + 1].split()))
            start = index + 1
    assert depth == 0, "balanced braces"
    return rules


def _selectors(text: str) -> list[str]:
    found: list[str] = []
    for rule in _rules(text):
        head, _, body = rule.partition("{")
        if head.strip().startswith("@"):
            if head.strip().startswith(("@media", "@supports")):
                found.extend(_selectors(body.rsplit("}", 1)[0]))
            continue
        found.extend(part.strip() for part in head.split(","))
    return found


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout


def _old_app_css() -> str:
    """app.css as it was just before the insight block moved out."""
    # Before the move is committed the old file is HEAD; afterwards it is the parent of the removal.
    head = _git("show", f"HEAD:{APP_CSS}")
    if ".insight-shade-0" in head:
        return head
    movers = _git("log", "-1", "--format=%H", "-S.insight-shade-0", "--", APP_CSS).split()
    if not movers:
        pytest.skip("the insight move is not in this checkout's history")
    return _git("show", f"{movers[0]}^:{APP_CSS}")


def _old_insight_block(old: str) -> str:
    lines = old.splitlines()
    start = next(i for i, line in enumerate(lines) if "Community permit insight" in line)
    end = next(i for i, line in enumerate(lines) if line.startswith(".insight-def"))
    return "\n".join(lines[start:end + 1])


@pytest.mark.parametrize("name", sorted(PREFIXES))
def test_each_area_file_only_uses_its_own_prefix(name) -> None:
    path = STATIC / name
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert text.lstrip().startswith("/*"), "header comment"
    for selector in _selectors(text):
        assert selector.startswith(PREFIXES[name]), f"{name}: {selector}"


def test_insight_css_keeps_the_old_selectors_in_order() -> None:
    new = (STATIC / "insight.css").read_text(encoding="utf-8")
    assert _selectors(new) == _selectors(_old_insight_block(_old_app_css()))


def test_app_css_plus_insight_css_keeps_the_old_selector_list() -> None:
    old = _selectors(_old_app_css())
    new = _selectors((STATIC / "app.css").read_text(encoding="utf-8"))
    insight = _selectors((STATIC / "insight.css").read_text(encoding="utf-8"))
    assert insight, "insight.css holds selectors"
    # The staff frame (slice S1) dropped the banner and the side foot and added
    # the rule for the "More details" disclosure.  Those selectors changed on
    # purpose and are compared apart; every other selector must still be
    # exactly what it was before the insight move.
    old = [
        selector
        for selector in old
        if selector not in STAFF_FRAME_REMOVED
        and selector not in REVIEWER_SLIM_REMOVED
    ]
    new = [
        selector
        for selector in new
        if selector not in STAFF_FRAME_REMOVED
        and selector not in REVIEWER_SLIM_REMOVED
        and selector not in STAFF_FRAME_ADDED
        and selector not in PERSONA_MENU_ADDED
        and selector not in AGENT_INBOX_ADDED
        and selector not in REVIEWER_SLIM_ADDED
    ]
    # The block sat in one contiguous run: app.css before it, insight.css, then app.css after.
    first = old.index(insight[0])
    assert old == new[:first] + insight + new[first:]


def test_base_and_city_layout_link_the_new_files_in_order() -> None:
    base = (ROOT / "src/acme_city/templates/base.html").read_text(encoding="utf-8")
    links = re.findall(r'href="/ui/static/([\w-]+\.css)"', base)
    assert links[links.index("reviewer.css") + 1:] == [
        "insight.css", "nav-more.css", "steward.css", "steward-auto.css",
        "admin-a.css", "admin-b.css", "operator.css", "demo-video.css", "guide.css",
    ]
    assert base.index("{% block extra_css %}") > base.index("operator.css")
    assert base.index("{% block extra_js %}") < base.index("</body>")
    city = (ROOT / "src/acme_city/templates/city/layout.html").read_text(encoding="utf-8")
    links = re.findall(r'href="/ui/static/([\w-]+\.css)"', city)
    assert links == [
        "app.css", "city.css", "ui-patterns.css",
        "insight.css", "city-community.css",
    ]
    assert city.index("{% block page_css %}") > city.index("city-community.css")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    settings = build_environment(tmp_path_factory.mktemp("sheets"), synthetic=True, name="s.db")
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def test_pages_link_insight_css(client) -> None:
    assert client.post("/api/session/select", json={"actor_id": ADMIN}).status_code == 200
    staff = client.get("/insight/city")
    link = re.search(r'<a href="(/city/community/permit/[^"]+)"', staff.text)
    assert link
    for path in ("/city/community", link.group(1), "/insight/city", "/queue"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "/ui/static/insight.css" in response.text, path
