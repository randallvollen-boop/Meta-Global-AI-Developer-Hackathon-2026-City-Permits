"""The browser navigation tests of the agent operator lane.

The agent operator lane adds its navigation browser tests here; ``test_navigation.py``
is frozen.
"""
# REQUIRES: UX-01

from __future__ import annotations

import pytest

from conftest import assert_no_horizontal_overflow, assert_not_covered


OPERATOR_SCREENS = (
    ("/agent/intake", "Intake agent"),
    ("/agent/adjudication", "Adjudication agent"),
)

#: The operational home of the operator and the runs it opens.
AGENT_OPERATIONS_SCREENS = (
    ("/agents", "Agents"),
    ("/agents/runs", "Agent runs"),
)

OUTSIDE = (
    "persona_data_steward",
    "persona_permit_reviewer",
    "persona_city_administrator",
)


def test_operator_navigation_has_four_visible_destinations_at_390(viewport_390, login) -> None:
    page = viewport_390
    login("persona_agent_operator")
    links = page.locator(".mobile-nav > a")
    assert links.count() == 4
    assert [links.nth(index).get_attribute("href") for index in range(4)] == [
        "/agents", "/agent/intake", "/agent/adjudication", "/agents/runs",
    ]
    # The intake queue is the fifth screen: the operator holds the grant that
    # runs a selected batch, so the queue that lists the cases is reachable.
    more = page.locator('.mobile-nav [data-testid="nav-more-mobile"] a')
    assert [more.nth(index).get_attribute("href") for index in range(more.count())] == [
        "/queue/intake",
    ]
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator(".mobile-nav"))


def test_operator_agent_screens_render_at_390_without_covered_controls(
    viewport_390, server, login
) -> None:
    page = viewport_390
    login("persona_agent_operator")
    for path, title in OPERATOR_SCREENS:
        response = page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        assert response is not None
        assert response.status == 200, path
        assert page.title().startswith(title), path
        assert_no_horizontal_overflow(page)
        assert_not_covered(page, page.locator("main h1"))
    assert page.recorded_errors == []


def test_the_agents_home_and_run_history_fit_at_390(viewport_390, server, login) -> None:
    page = viewport_390
    login("persona_agent_operator")
    for path, title in AGENT_OPERATIONS_SCREENS:
        response = page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        assert response is not None
        assert response.status == 200, path
        assert page.title().startswith(title), path
        assert_no_horizontal_overflow(page)
        assert_not_covered(page, page.locator("main h1"))
    assert page.recorded_errors == []


@pytest.mark.parametrize("actor_id", OUTSIDE)
def test_agent_screens_are_forbidden_to_other_personas(page, server, login, actor_id) -> None:
    login(actor_id)
    for path, _title in OPERATOR_SCREENS:
        response = page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        assert response is not None
        assert response.status == 403, (actor_id, path)


def test_an_agent_screen_links_back_to_the_agents_home(page, server, login) -> None:
    """The agent screens link back to the Agents home, which the operator may open."""
    login("persona_agent_operator")
    for path, _title in OPERATOR_SCREENS:
        page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
        page.click("a:has-text('Back to agents')")
        page.wait_for_url(f"{server.base_url}/agents")
        assert page.locator("main h1").inner_text().strip() == "Agents"


def test_the_agents_home_has_no_process_selected_link_and_the_queue_still_opens(
    page, server, login
) -> None:
    """The Agents home lists the agents only; the intake queue keeps its bulk button."""
    login("persona_agent_operator")
    page.goto(f"{server.base_url}/agents", wait_until="domcontentloaded")
    assert page.locator("[data-testid='opr-process-selected']").count() == 0
    page.goto(f"{server.base_url}/queue/intake", wait_until="domcontentloaded")
    assert page.locator("[data-testid='intake-bulk-submit']").is_visible()
