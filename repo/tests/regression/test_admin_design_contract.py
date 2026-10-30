"""The selector and form contract of the admin-b screens (ADB-1).

The redesign may move a control, group it in a disclosure or rename a heading.
It may not drop a test hook, change the destination of a form or rename a field
that a form sends.  The inventory in ``data/admin_b_hooks.json`` was taken
before the first slice, so the contract is the state the screens started from.

The test also fixes the boundary of the lane: five personas are selectable and
the admin-b screens belong to the City Administrator alone.
"""
# REQUIRES: UX-01, UX-02, PER-04

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acme_city.app import create_app
from acme_city.ui.router import router as ui_router

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.client import build_settings  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT = REPO_ROOT / "tests" / "regression" / "data" / "admin_b_hooks.json"

#: The nine screens of the admin-b redesign.
SCREENS = (
    "policy_scenarios",
    "policy_scenario",
    "policy_proposal",
    "policy_run",
    "policy_briefing",
    "governance_sources",
    "rules_fees",
    "insight_city",
    "early_resolution",
)

#: The five personas of the demonstration.
PERSONAS = (
    "persona_applicant",
    "persona_data_steward",
    "persona_permit_reviewer",
    "persona_city_administrator",
    "persona_agent_operator",
)

ADMIN = "persona_city_administrator"

#: The admin-b screens and the address that opens them.
ADMIN_SCREENS = (
    "/policy/scenarios",
    "/governance",
    "/rules-fees",
    "/insight/city",
)

#: The screens only the City Administrator may open.  The rules and fees
#: register is shared with the Data Steward, who holds a rule grant.
ADMIN_ONLY_SCREENS = (
    "/policy/scenarios",
    "/governance",
    "/insight/city",
)


def _contract() -> dict:
    return json.loads(CONTRACT.read_text(encoding="utf-8"))


def _text(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


@pytest.fixture()
def client(tmp_path: Path):
    """Return a client with its own seeded database."""
    settings = build_settings(tmp_path, "admin-b-contract.db")
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


# ------------------------------------------------------------- the inventory


def test_the_inventory_covers_the_nine_screens_and_the_shared_components() -> None:
    contract = _contract()
    assert set(contract["screens"]) == set(SCREENS)
    assert contract["includes"], "the shared components are inventoried"
    assert contract["generated"], "the hooks a builder writes are inventoried"


@pytest.mark.parametrize("screen", SCREENS)
def test_every_hook_of_a_screen_survives(screen: str) -> None:
    entry = _contract()["screens"][screen]
    text = _text(entry["template"])
    missing = [hook for hook in entry["hooks"] if f'data-testid="{hook}"' not in text]
    assert not missing, f"{screen} lost the hooks {missing}"


@pytest.mark.parametrize("screen", SCREENS)
def test_every_form_keeps_its_destination_and_its_field_names(screen: str) -> None:
    entry = _contract()["screens"][screen]
    text = _text(entry["template"])
    for form in entry["forms"]:
        assert f'action="{form["action"]}"' in text, (screen, form["action"])
        for field in form["fields"]:
            assert f'name="{field}"' in text, (screen, field)


@pytest.mark.parametrize("component", sorted(_contract()["includes"]))
def test_every_hook_of_a_shared_component_survives(component: str) -> None:
    entry = _contract()["includes"][component]
    text = _text(entry["template"])
    missing = [hook for hook in entry["hooks"] if f'data-testid="{hook}"' not in text]
    assert not missing, f"{component} lost the hooks {missing}"


@pytest.mark.parametrize("builder", sorted(_contract()["generated"]))
def test_every_hook_a_builder_writes_is_still_written(builder: str) -> None:
    hooks = _contract()["generated"][builder]
    text = _text(builder)
    missing = [hook for hook in hooks if f'data-testid="{hook}"' not in text]
    assert not missing, f"{builder} no longer writes {missing}"


# ----------------------------------------------------------------- the lane


def test_five_personas_are_selectable(client: TestClient) -> None:
    page = client.get("/select")
    assert page.status_code == 200
    cards = page.text.count('data-testid="persona-card"')
    assert cards == len(PERSONAS), cards
    for actor_id in PERSONAS:
        response = client.post(
            "/ui/actor", data={"actor_id": actor_id, "next": "/queue"}, follow_redirects=False
        )
        assert response.status_code == 303, actor_id


def test_governance_rules_and_city_copy_is_plain_and_fictional(client: TestClient) -> None:
    """The final admin-b copy states scope without implying real authority."""
    assert client.post(
        "/api/session/select", json={"actor_id": ADMIN}
    ).status_code == 200

    governance = client.get("/governance?tab=sources").text
    assert "Data sources and ownership" in governance
    assert "See each dataset owner, source, correction route and unowned record." in governance
    assert "Records needing attention" in governance

    rules = client.get("/rules?tab=rules&view=published").text
    assert "Fictional ACME rules and fees. They do not govern a real jurisdiction." in rules
    assert "what-if" not in rules
    assert "append-only" not in rules

    city = client.get("/insight/city").text
    assert "Fictional ACME City permit records by district, type, outcome and business category." in city
    assert 'data-testid="filter-apply">Apply</button>' in city
    assert "Business categories" in city
    assert "Permit records" in city
    assert "Where restaurants and bars are opening" not in city


@pytest.mark.parametrize("path", ADMIN_SCREENS)
def test_the_city_administrator_opens_every_admin_b_screen(client: TestClient, path: str) -> None:
    assert client.post(
        "/api/session/select", json={"actor_id": ADMIN}
    ).status_code == 200
    assert client.get(path).status_code == 200, path


@pytest.mark.parametrize("path", ADMIN_ONLY_SCREENS)
def test_the_admin_b_screens_belong_to_the_city_administrator(
    client: TestClient, path: str
) -> None:
    for actor_id in PERSONAS:
        assert client.post(
            "/api/session/select", json={"actor_id": actor_id}
        ).status_code == 200
        response = client.get(path)
        if actor_id == ADMIN:
            assert response.status_code == 200, (actor_id, path)
        else:
            assert response.status_code == 403, (actor_id, path)
