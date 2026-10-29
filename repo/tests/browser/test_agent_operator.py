"""Phone layout checks for the Agent Operator's admin partial."""

from __future__ import annotations

from conftest import assert_no_horizontal_overflow, assert_not_covered


def test_role_permissions_fit_at_390(viewport_390, login) -> None:
    page = viewport_390
    login("persona_city_administrator")
    page.goto(page.url.split("/overview")[0] + "/admin?tab=users", wait_until="domcontentloaded")
    table = page.locator("[data-testid='agent-role-permissions-table']")
    assert table.is_visible()
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, table)
