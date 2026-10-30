"""The Help button on the screens that carry it.

Every screen a person works in offers the help of that screen: the drawer
with the topic of the screen, or the general help for a screen that has no
topic of its own.  The button is visible on the screen, it opens the help and
it opens it without a console error.
"""
# REQUIRES: UX-01, UX-02

from __future__ import annotations

import pytest
from conftest import BrowserServer

#: The screens that carry the Help button and the persona that may open them.
HELP_SCREENS = (
    ("persona_agent_operator", "/agents"),
    ("persona_agent_operator", "/agents/runs"),
    ("persona_agent_operator", "/agents/cases/app_synth_001"),
    ("persona_agent_operator", "/agent/intake"),
    ("persona_agent_operator", "/agent/adjudication"),
    ("persona_city_administrator", "/admin"),
    ("persona_city_administrator", "/insight/city"),
    ("persona_permit_reviewer", "/queue/review"),
    ("persona_data_steward", "/steward/automation"),
    ("persona_city_administrator", "/map"),
    ("persona_city_administrator", "/property"),
    ("persona_city_administrator", "/property/ACME-P-1001"),
    ("persona_applicant", "/city/"),
    ("persona_applicant", "/city/permits"),
    ("persona_applicant", "/city/community"),
    ("persona_applicant", "/city/trash-recycling"),
    ("persona_applicant", "/city/community/permit/SYN-APP-012"),
    ("persona_applicant", "/lifecycle"),
    ("persona_applicant", "/walkthrough"),
)


@pytest.mark.parametrize("actor_id,path", HELP_SCREENS)
def test_every_screen_carries_the_help_button(
    page, server: BrowserServer, login, actor_id: str, path: str
) -> None:
    """The Help button is on the screen and it opens the help of the screen."""
    login(actor_id)
    page.goto(f"{server.base_url}{path}", wait_until="domcontentloaded")
    button = page.locator('[data-testid="ui-help"]')
    assert button.count() == 1, path
    assert button.is_visible(), path
    if button.get_attribute("data-ui-detail") is not None:
        # The screen has a topic of its own: the help opens in the drawer.
        button.click()
        drawer = page.locator("#ui-drawer")
        drawer.wait_for(state="visible")
        title = drawer.locator('[data-testid="ui-drawer-title"]').inner_text()
        assert title.startswith("Help:"), path
    else:
        # The screen has no topic of its own: the general help opens.
        button.click()
        page.wait_for_url(lambda url: url.endswith("/help"))
        assert page.locator('[data-testid="help-page"]').count() == 1, path
    assert page.recorded_errors == []
