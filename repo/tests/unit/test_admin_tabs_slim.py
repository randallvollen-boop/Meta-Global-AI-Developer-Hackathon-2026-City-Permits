"""The administration screen after the slim-down: the tabs and what they keep.

The administration screen shows what a person needs to decide.  The tabs are
the screen, the configuration log keeps the value before a change and the
value after it in visible columns, the add-user form is a closed disclosure,
the appearance section is collapsed and the agent-processing tab keeps the
story sentence and its three fields.  Every button of the screen has a click
test here.
"""
# REQUIRES: UX-01, UX-02, UX-03
# The tabs show only what a decision needs, and every action of the screen is
# exercised through the interface it is offered on.

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "integration"))
from insight_support import build_environment  # noqa: E402

from acme_city.app import create_app  # noqa: E402
from acme_city.ui.router import router as ui_router  # noqa: E402

ADMIN = "persona_city_administrator"

#: The tabs of the administration screen and the section each one opens.
TABS: tuple[tuple[str, str], ...] = (
    ("permit-types", "permit-types"),
    ("appearance", "permit-type-icons"),
    ("users", "users"),
    ("reason-codes", "reason-codes"),
    ("log", "log"),
)


def csrf_of(body: str) -> str:
    """Return the CSRF token of the session from a rendered page."""
    match = re.search(r'name="csrf_token" value="([^"]+)"', body)
    assert match is not None, "the page carries a form token"
    return match.group(1)


def words_of(body: str) -> str:
    """Return the words of a rendered page, with the line breaks removed."""
    return re.sub(r"\s+", " ", body)


def choose(client: TestClient, actor_id: str) -> None:
    """Establish a server-held session for a persona."""
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """A demonstration database of its own, so a test leaves no trace."""
    settings = build_environment(tmp_path, synthetic=False, name="admin-tabs.db")
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


# ----------------------------------------------------------------- the shell


def test_the_administration_screen_shows_only_its_tabs(client: TestClient) -> None:
    """The screen is the tabs and the section the selected tab names."""
    choose(client, ADMIN)
    body = client.get("/admin").text
    assert "<h1>Administration</h1>" in body
    # The introduction, the evidence panel, the history panel and the back
    # link are gone: the configuration log is the history of this screen.
    assert "Every change here is a governed, audited action" not in body
    assert 'data-testid="evidence-panel"' not in body
    assert 'data-testid="history-panel"' not in body
    assert "Back to the work queue" not in body
    for tab, _section in TABS:
        assert f'data-testid="admin-tab" data-tab="{tab}"' in body, tab


@pytest.mark.parametrize("tab,section", TABS)
def test_every_tab_opens_its_own_section(client: TestClient, tab: str, section: str) -> None:
    """A tab opens the section it names, and only that section."""
    choose(client, ADMIN)
    body = client.get(f"/admin?tab={tab}").text
    assert f'data-testid="admin-section" data-section="{section}"' in body
    for other, other_section in TABS:
        if other == tab:
            continue
        assert f'data-section="{other_section}"' not in body, other


def test_the_agent_processing_tab_opens_its_section(client: TestClient) -> None:
    """The agent processing tab is a tab of the same screen."""
    choose(client, ADMIN)
    body = client.get("/admin?tab=agent_processing").text
    assert 'data-testid="admin-tab" data-tab="agent_processing"' in body
    assert 'data-testid="admin-agent-processing"' in body
    assert 'aria-current="page" aria-selected="true" data-testid="admin-tab" data-tab="agent_processing"' in body


# ------------------------------------------------------------------- the log


def test_the_configuration_log_shows_the_value_before_and_the_value_after(
    client: TestClient,
) -> None:
    """The before and the after are columns of the row, not a hidden list."""
    choose(client, ADMIN)
    page = client.get("/admin?tab=reason-codes")
    retired = client.post(
        "/ui/actions/config.reason_code.retire",
        data={
            "csrf_token": csrf_of(page.text),
            "action_id": "config.reason_code.retire",
            "next": "/admin?tab=reason-codes",
            "code": "INCOMPLETE_APPLICATION",
        },
        headers={"Accept": "application/json"},
    )
    assert retired.status_code == 200, retired.text
    body = client.get("/admin?tab=log").text
    assert '<th scope="col">Before</th>' in body
    assert '<th scope="col">After</th>' in body
    assert 'data-testid="admin-log-before"' in body
    assert 'data-testid="admin-log-after"' in body
    row = re.search(
        r'<tr data-testid="admin-log-row" data-action="config.reason_code.retire".*?</tr>',
        body,
        re.S,
    )
    assert row is not None, "the log holds the change"
    # The two values sit in the row itself.
    assert "active" in row.group(0)
    assert "retired" in row.group(0)
    # The technical key is the only part that is behind a disclosure.
    assert "View values" not in body
    assert "More details" in row.group(0)
    assert "Raw action" in row.group(0)
    assert "config.reason_code.retire" in row.group(0)


# ------------------------------------------------------------------ the users


def test_the_add_user_form_is_closed_and_the_administrator_adds_a_user(
    client: TestClient,
) -> None:
    """The form that adds a user is a disclosure, and it still adds one."""
    choose(client, ADMIN)
    body = client.get("/admin?tab=users").text
    assert 'data-testid="admin-add-user-panel"' in body
    panel = re.search(
        r'<details class="adm-disclosure" data-testid="admin-add-user-panel".*?</details>',
        body,
        re.S,
    )
    assert panel is not None, "the add-user form sits in a disclosure"
    assert "open" not in panel.group(0).split(">")[0], "the disclosure starts closed"
    assert 'data-testid="admin-add-user"' in panel.group(0)

    added = client.post(
        "/ui/actions/config.user.add",
        data={
            "csrf_token": csrf_of(body),
            "action_id": "config.user.add",
            "next": "/admin?tab=users",
            "name": "Rosa Reviewer",
            "department": "Permit Reviewing",
            "persona_role": "Permit Reviewer",
        },
        headers={"Accept": "application/json"},
    )
    assert added.status_code == 200, added.text
    assert added.json()["status"] == "accepted", added.json()
    after = client.get("/admin?tab=users").text
    assert "Rosa Reviewer" in after


def test_the_department_of_a_person_is_behind_more_details(client: TestClient) -> None:
    """The people table holds the name, the role and the access."""
    choose(client, ADMIN)
    body = client.get("/admin?tab=users").text
    assert '<th scope="col">Name</th>' in body
    assert '<th scope="col">Role</th>' in body
    assert '<th scope="col">Demo access</th>' in body
    assert '<th scope="col">Department</th>' not in body
    details = re.search(
        r'<details class="adm-disclosure" data-testid="admin-people-departments".*?</details>',
        body,
        re.S,
    )
    assert details is not None, "the department sits in a disclosure"
    assert "More details" in details.group(0)
    assert "open" not in details.group(0).split(">")[0], "the disclosure starts closed"
    # A user added with a department shows it there.
    added = client.post(
        "/ui/actions/config.user.add",
        data={
            "csrf_token": csrf_of(body),
            "action_id": "config.user.add",
            "next": "/admin?tab=users",
            "name": "Rosa Reviewer",
            "department": "Permit Reviewing",
            "persona_role": "Permit Reviewer",
        },
        headers={"Accept": "application/json"},
    )
    assert added.status_code == 200, added.text
    after = client.get("/admin?tab=users").text
    details = re.search(
        r'<details class="adm-disclosure" data-testid="admin-people-departments".*?</details>',
        after,
        re.S,
    )
    assert details is not None
    assert 'data-testid="admin-person-department"' in details.group(0)
    assert "Permit Reviewing" in details.group(0)


# ------------------------------------------------------------ the permit types


def test_the_administrator_requires_and_stops_requiring_a_document(
    client: TestClient,
) -> None:
    """The toggles of a permit type change the type and are accepted."""
    choose(client, ADMIN)
    body = client.get("/admin?tab=permit-types").text
    required = client.post(
        "/ui/actions/config.permit_type.document",
        data={
            "csrf_token": csrf_of(body),
            "action_id": "config.permit_type.document",
            "next": "/admin?tab=permit-types",
            "permit_type_id": "permit_type_shed",
            "document_type": "construction_plans",
            "required": "yes",
            "expected_version": "1",
        },
        headers={"Accept": "application/json"},
    )
    assert required.status_code == 200, required.text
    assert required.json()["status"] == "accepted", required.json()
    after = client.get("/admin?tab=permit-types").text
    assert "construction plans" in after

    stopped = client.post(
        "/ui/actions/config.permit_type.document",
        data={
            "csrf_token": csrf_of(after),
            "action_id": "config.permit_type.document",
            "next": "/admin?tab=permit-types",
            "permit_type_id": "permit_type_shed",
            "document_type": "construction_plans",
            "required": "no",
            "expected_version": "2",
        },
        headers={"Accept": "application/json"},
    )
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["status"] == "accepted", stopped.json()


def test_the_permit_type_register_has_no_icon_thumbnail(client: TestClient) -> None:
    """The register names the type; the icons live in the appearance section."""
    choose(client, ADMIN)
    body = client.get("/admin?tab=permit-types").text
    assert body.count('data-testid="admin-permit-type-row"') == 17
    assert "<img" not in body.split('data-testid="admin-permit-types"', 1)[1]


def test_the_administrator_adds_a_permit_type(client: TestClient) -> None:
    """The button that adds a permit type creates one."""
    choose(client, ADMIN)
    body = client.get("/admin?tab=permit-types").text
    created = client.post(
        "/ui/actions/config.permit_type.create",
        data={
            "csrf_token": csrf_of(body),
            "action_id": "config.permit_type.create",
            "next": "/admin?tab=permit-types",
            "key": "greenhouse",
            "label": "Greenhouse",
            "description": "A small residential greenhouse.",
            "review_area": "Building",
            "process_category": "simple",
            "discretionary": "no",
            "required_fields": "parcel_number project_description",
            "required_documents": "site_plan",
            "fee_schedule_key": "fee_commercial_demo",
        },
        headers={"Accept": "application/json"},
    )
    assert created.status_code == 200, created.text
    assert created.json()["status"] == "accepted", created.json()
    after = client.get("/admin?tab=permit-types").text
    assert "Greenhouse" in after


# -------------------------------------------------------------- the appearance


def test_the_appearance_section_is_collapsed(client: TestClient) -> None:
    """The appearance section is closed until it is asked for."""
    choose(client, ADMIN)
    body = client.get("/admin?tab=appearance").text
    section = re.search(
        r'<details class="panel card" data-testid="admin-section" data-section="permit-type-icons".*?>',
        body,
        re.S,
    )
    assert section is not None, "the appearance section is on the page"
    assert "open" not in section.group(0), "the section starts closed"
    # The icons and their limits are still there for anyone who opens it.
    assert 'data-testid="permit-type-icon-row"' in body
    assert 'data-testid="icon-cost"' in body
    assert 'data-testid="icon-per-type-cap"' in body
    assert 'data-testid="icon-global-cap"' in body
    assert 'data-testid="icon-provenance"' in body


# ------------------------------------------------------- the agent processing


def test_the_agent_processing_tab_keeps_the_story_sentence_and_saves(
    client: TestClient,
) -> None:
    """The story sentence, the three fields and the save are the tab."""
    choose(client, ADMIN)
    body = client.get("/admin?tab=agent_processing").text
    assert (
        "The policy says when the agents work. People still review the "
        "recommendations and make the permit decisions."
    ) in words_of(body)
    assert 'data-testid="admin-processing-mode"' in body
    assert 'id="opr-runs-per-hour"' in body
    assert 'name="keep_awake"' in body
    assert 'id="opr-processing-reason"' in body
    # The provider allowance, the engine, the notes and the waiting count sit
    # behind More details.
    details = re.search(
        r'<details class="adm-disclosure" data-testid="admin-agent-processing-more".*?</details>',
        body,
        re.S,
    )
    assert details is not None, "the notes sit in a disclosure"
    assert "open" not in details.group(0).split(">")[0], "the disclosure starts closed"
    for testid in (
        "admin-muse-cap",
        "admin-engine",
        "admin-muse-note",
        "admin-worker-note",
        "admin-eligible-count",
    ):
        assert f'data-testid="{testid}"' in details.group(0), testid

    version = re.search(r'name="expected_version" value="([^"]+)"', body)
    assert version is not None
    saved = client.post(
        "/ui/actions/admin.agent.processing",
        data={
            "csrf_token": csrf_of(body),
            "action_id": "admin.agent.processing",
            "next": "/admin?tab=agent_processing",
            "keep_awake": "true",
            "runs_per_hour": "42",
            "reason": "A fictional demonstration step",
            "expected_version": version.group(1),
        },
        headers={"Accept": "application/json"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["status"] == "accepted", saved.json()
    after = client.get("/admin?tab=agent_processing").text
    assert 'value="42"' in after
    assert "checked" in after
