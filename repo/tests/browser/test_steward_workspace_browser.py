"""The workspace of the Data Steward in a browser.

The queue reads its search and its filters from the address of the request.
On a desktop it is a table with its columns; on a phone it is one card per
task, and the bar of the phone keeps the four work screens and the demo
switcher reachable.

Fictional ACME City data only.
"""
# REQUIRES: UX-01, UX-02, UX-04

from __future__ import annotations

import pytest
from conftest import BrowserServer, assert_no_horizontal_overflow, assert_not_covered
from sqlalchemy import select

from acme_city.fixtures.steward_demo import seed_cedarline
from acme_city.persistence.models import permit
from acme_city.persistence.session import SessionFactory, transaction


@pytest.fixture()
def cedarline(server: BrowserServer) -> list[str]:
    """Add the Cedarline proposals to the database of the browser server."""
    factory = SessionFactory(server.settings.database_url)
    try:
        with transaction(factory) as session:
            return seed_cedarline(session)
    finally:
        factory.dispose()


@pytest.fixture()
def waiting_case(server: BrowserServer) -> str:
    """Put one demonstration case into early resolution with a recorded finding."""
    factory = SessionFactory(server.settings.database_url)
    try:
        with transaction(factory) as session:
            application = session.execute(
                select(permit.Application).where(
                    permit.Application.source_application_number == "SYN-APP-007"
                )
            ).scalar_one()
            application.status = "needs_information"
            session.add(
                permit.ApplicationFinding(
                    id="finding_browser_early_resolution",
                    correlation_id="correlation_browser_early_resolution",
                    application_id=application.id,
                    finding_type="missing_document",
                    message="The site plan carries no signature.",
                    rule="A site plan needs a signature.",
                    applicant_must="Send a signed site plan.",
                    severity="block",
                    state="current",
                    revision_number=application.revision,
                )
            )
            return application.source_application_number
    finally:
        factory.dispose()


def test_the_queue_with_the_filters_open_fits_a_phone(
    viewport_390, server: BrowserServer, login
) -> None:
    """The queue, the search and the open filters fit a 390 pixel screen."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="load")
    assert page.viewport_size == {"width": 390, "height": 844}
    filters = page.locator('[data-testid="queue-filters"]')
    assert filters.count() == 1
    filters.locator("summary").click()
    assert filters.locator("select").count() == 2
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator("main h1").first)
    assert_not_covered(page, page.locator('[data-testid="queue-filter-submit"]'))
    assert page.recorded_errors == []


def test_the_search_reads_the_address_and_the_queue_answers(
    page, server: BrowserServer, login
) -> None:
    """The search travels in the address, and the queue answers with the rows."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="domcontentloaded")
    # The search sits behind the disclosure of the filters.
    page.locator('[data-testid="queue-filters"] > summary').click()
    search = page.locator('[data-testid="queue-search"]')
    assert search.count() == 1
    search.locator('input[name="q"]').fill("notarecord")
    search.locator('[data-testid="queue-search-submit"]').click()
    page.wait_for_url("**/steward?q=notarecord")
    assert page.locator('[data-testid="queue-empty"]').count() == 1
    assert page.locator("[data-issue-row]").count() == 0


def test_the_filters_keep_the_queue_readable_at_a_phone(
    viewport_390, server: BrowserServer, login
) -> None:
    """A filtered queue stays inside the screen and keeps its rows."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward?record_type=match", wait_until="load")
    filters = page.locator('[data-testid="queue-filters"]')
    assert filters.locator("summary").inner_text().strip().lower() == "more filters"
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator("main h1").first)
    assert page.recorded_errors == []


def test_the_queue_reads_as_one_card_per_task_on_a_phone(
    viewport_390, server: BrowserServer, login, cedarline
) -> None:
    """At 390 pixels the table becomes one card per task, and every card fits."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="load")
    assert not page.locator('[data-testid="issue-table"] thead').is_visible()
    rows = page.locator("[data-issue-row]")
    assert rows.count() == 4
    assert rows.first.evaluate("element => getComputedStyle(element).display") == "block"
    for index in range(rows.count()):
        box = rows.nth(index).bounding_box()
        assert box is not None
        assert box["x"] >= 0, box
        assert box["x"] + box["width"] <= 390, box
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator("main h1").first)
    assert page.recorded_errors == []


def test_the_queue_keeps_its_columns_on_a_desktop(
    page, server: BrowserServer, login, cedarline
) -> None:
    """On a desktop the queue keeps its columns, its reason and its action."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="load")
    assert page.locator('[data-testid="issue-table"] thead').is_visible()
    assert page.locator("[data-issue-row]").first.evaluate(
        "element => getComputedStyle(element).display"
    ) == "table-row"
    assert page.locator('[data-testid="issue-reason"]').count() == 4
    assert page.locator('[data-testid="issue-action"]').count() == 4
    assert page.locator('[data-testid="issue-reference"]').count() == 4
    assert page.recorded_errors == []


def test_the_bar_and_the_demo_switch_stay_reachable(
    viewport_390, server: BrowserServer, login, cedarline
) -> None:
    """The four work screens and the demo switcher stay reachable on a phone."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="load")
    entries = page.locator(".mobile-nav > a")
    assert entries.count() == 4
    assert page.locator('[data-testid="demo-switch"]').is_visible()
    assert_not_covered(page, page.locator('[data-testid="demo-switch"] > summary'))
    assert_not_covered(page, page.locator("main h1").first)
    assert page.recorded_errors == []


def test_the_case_opens_with_a_compact_summary_of_the_task(
    page, server: BrowserServer, login, cedarline
) -> None:
    """The case names the task, the record, the source, the status and the next step."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="load")
    page.locator("[data-issue-row]", has_text="ERP-BL-00413").locator(
        '[data-testid="issue-link"]'
    ).click()
    page.wait_for_selector('[data-testid="case-summary"]')
    summary = page.locator('[data-testid="case-summary"]')
    summary_text = summary.inner_text()
    assert summary.locator("h1").inner_text().strip() == "Check the business identity"
    assert "Cedarline Coffee Works" in summary_text
    assert "ERP-BL-00413" in summary_text
    assert summary.locator('[data-testid="case-status"]').inner_text().strip() == "Needs review"
    assert summary.locator('[data-testid="case-summary-source"]').inner_text().strip()
    assert summary.locator('[data-testid="case-summary-next"]').inner_text().strip()
    # The summary reads before the comparison and repeats none of its text.
    page_html = page.content()
    assert page_html.index("case-summary") < page_html.index('data-question="3"')
    assert "Source record ERP-BL-00413" not in summary_text
    assert "Check the business identity" not in page_html.split('data-question="1"')[1]
    assert page.recorded_errors == []


def test_the_case_summary_fits_a_phone(
    viewport_390, server: BrowserServer, login, cedarline
) -> None:
    """The summary of the case and the questions below it fit a 390 pixel screen."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="load")
    page.locator("[data-issue-row]", has_text="ERP-BL-00413").locator(
        '[data-testid="issue-link"]'
    ).click()
    page.wait_for_selector('[data-testid="case-summary"]')
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator("main h1").first)
    assert_not_covered(page, page.locator('[data-testid="case-summary-next"]'))
    assert page.locator('[data-testid="case-q6"]').count() == 1
    assert page.recorded_errors == []


def test_the_comparison_fits_a_phone(
    viewport_390, server: BrowserServer, login, cedarline
) -> None:
    """The comparison of the case fits a 390 pixel screen, with every value labelled."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="load")
    page.locator("[data-issue-row]", has_text="ERP-BL-00413").locator(
        '[data-testid="issue-link"]'
    ).click()
    page.wait_for_selector('[data-testid="compare-table"]')
    table = page.locator('[data-testid="compare-table"]').first
    # On a phone the table becomes one card per field, and the column heads
    # become the labels of the values.
    assert not table.locator("thead").is_visible()
    assert table.locator('[data-label="Source record"]').count() >= 1
    assert table.locator('[data-label="Master record"]').count() >= 1
    for row in table.locator("tbody tr").all():
        box = row.bounding_box()
        assert box is not None
        assert box["x"] >= 0, box
        assert box["x"] + box["width"] <= 390, box
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator("main h1").first)
    assert page.recorded_errors == []


def test_the_intake_queue_reads_as_one_card_per_case_on_a_phone(
    viewport_390, server: BrowserServer, login
) -> None:
    """At 390 pixels the incoming cases read as cards, and every card fits."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/queue/intake", wait_until="load")
    assert page.viewport_size == {"width": 390, "height": 844}
    table = page.locator('[data-testid="intake-table"]')
    assert table.count() == 1
    assert not table.locator("thead").is_visible()
    rows = page.locator('[data-testid="intake-row"]')
    assert rows.count() >= 1
    # Every case names what happens next.
    assert page.locator('[data-testid="intake-next-step"]').count() == rows.count()
    for index in range(rows.count()):
        box = rows.nth(index).bounding_box()
        assert box is not None
        assert box["x"] >= 0, box
        assert box["x"] + box["width"] <= 390, box
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator("main h1").first)
    assert page.recorded_errors == []


def test_the_intake_queue_keeps_its_filters_on_a_phone(
    viewport_390, server: BrowserServer, login
) -> None:
    """The search and the open filters of the incoming queue fit a phone."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/queue/intake", wait_until="load")
    filters = page.locator('[data-testid="intake-filters"]')
    assert filters.count() == 1
    filters.locator("summary").click()
    assert filters.locator("select").count() == 5
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator("main h1").first)
    assert page.recorded_errors == []


def test_the_early_resolution_board_fits_a_phone(
    viewport_390, server: BrowserServer, login, waiting_case
) -> None:
    """The cases that wait for a person fit a 390 pixel screen."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/queue/early-resolution", wait_until="load")
    groups = page.locator('[data-testid="early-resolution-group"]')
    assert groups.count() == 1
    table = page.locator('[data-testid="group-table"]')
    assert not table.locator("thead").is_visible()
    rows = page.locator('[data-testid="early-resolution-case"]')
    assert rows.count() == 1
    assert waiting_case in rows.first.inner_text()
    for index in range(rows.count()):
        box = rows.nth(index).bounding_box()
        assert box is not None
        assert box["x"] >= 0, box
        assert box["x"] + box["width"] <= 390, box
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator("main h1").first)
    assert page.recorded_errors == []


def test_the_source_catalogue_fits_a_phone(
    viewport_390, server: BrowserServer, login, cedarline
) -> None:
    """The catalogue of the source records fits a 390 pixel screen."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/source-records", wait_until="load")
    table = page.locator('[data-testid="source-record-table"]')
    assert table.count() == 1
    assert not table.locator("thead").is_visible()
    rows = table.locator("tbody tr")
    assert rows.count() >= 1
    for index in range(rows.count()):
        box = rows.nth(index).bounding_box()
        assert box is not None
        assert box["x"] >= 0, box
        assert box["x"] + box["width"] <= 390, box
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator("main h1").first)
    assert page.recorded_errors == []


def test_the_source_catalogue_names_the_record_and_its_action(
    page, server: BrowserServer, login, cedarline
) -> None:
    """A source record names the record, its state and the action that state asks for."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/source-records?system=erp_finance", wait_until="load")
    body = page.locator('[data-testid="source-record-table"]')
    assert "Cedarline Coffee Works" in body.inner_text()
    assert "ERP-BL-00413" in body.inner_text()
    states = body.locator('[data-testid="source-link-state"]')
    assert states.count() >= 1
    assert "Match proposed" in states.first.inner_text()
    # The row offers the review of the match.
    action = body.locator('[data-testid="source-action"]').first
    assert action.inner_text().strip() == "Review match"
    assert "/steward/issues/link/" in (action.get_attribute("href") or "")
    # The link state filter narrows the catalogue.
    page.goto(f"{server.base_url}/source-records?link_state=proposed", wait_until="load")
    proposed = page.locator('[data-testid="source-record-table"]')
    assert "Match proposed" in proposed.inner_text()
    assert "Cedarline Coffee Works" in proposed.inner_text()
    page.goto(f"{server.base_url}/source-records?link_state=linked", wait_until="load")
    assert "No source record matches" in page.locator(
        '[data-testid="source-record-table"]'
    ).inner_text()
    assert page.recorded_errors == []


@pytest.mark.parametrize(
    ("persona", "path"),
    (
        ("persona_data_steward", "/masters/party_cedarline"),
        ("persona_permit_reviewer", "/applicants/party_cedarline"),
    ),
)
def test_the_profile_puts_selected_values_before_statuses_on_a_phone(
    viewport_390, server: BrowserServer, login, persona: str, path: str
) -> None:
    """A profile leads with selected values and keeps its three statuses separate.

    The selected values open on the record of the steward and on the record of
    the applicant the reviewer opens, so both are checked at 390 pixels.
    """
    page = viewport_390
    login(persona)
    page.goto(f"{server.base_url}{path}", wait_until="load")
    selected = page.locator('[data-testid="trusted-values-overview"]')
    identity = page.locator('[data-testid="profile-overview"]')
    assert selected.count() == identity.count() == 1
    body = page.content()
    assert body.index('data-testid="trusted-values-overview"') < body.index(
        'data-testid="profile-overview"'
    )
    # The status section that repeated the header is gone.  The identity list
    # holds the identity and the credentials as two separate rows.
    assert page.locator('[data-testid="profile-status-overview"]').count() == 0
    assert page.locator('[data-testid="identity-status"]').inner_text().strip() in (
        "Identity linked",
        "Authority needs review",
    )
    assert page.locator('[data-testid="credential-status-summary"]').inner_text().strip()
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, selected)
    assert_not_covered(page, page.locator("main h1").first)
    assert page.recorded_errors == []


def test_master_collections_explain_identities_and_credentials_on_a_phone(
    viewport_390, server: BrowserServer, login
) -> None:
    """Master records keep identities, properties, and credentials distinct at 390 pixels."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/masters", wait_until="load")
    assert "canonical identities" in page.locator("main").inner_text()
    tabs = page.locator('[data-testid="master-tabs"]')
    assert tabs.locator('[data-tab="people"]').count() == 1
    assert tabs.locator('[data-tab="properties"]').count() == 1
    page.goto(f"{server.base_url}/masters?tab=licenses", wait_until="load")
    assert "A credential belongs to an identity" in page.locator("main").inner_text()
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, page.locator("main h1").first)
    assert page.recorded_errors == []


def test_the_saved_guide_opens_without_overflow_on_a_phone(
    viewport_390, server: BrowserServer, login
) -> None:
    """The queue guide is visibly offline and usable above the fixed controls."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="load")
    guide = page.locator('[data-testid="steward-guide"]')
    guide.locator("summary").click()
    assert "Saved guidance. Live Muse is off." in guide.inner_text()
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, guide)
    assert_not_covered(page, page.locator("main h1").first)
    assert page.recorded_errors == []


def test_the_queue_guide_holds_no_link_back_to_the_queue(
    viewport_390, server: BrowserServer, login
) -> None:
    """The guide of the queue holds no link back to the queue."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="load")
    guide = page.locator('[data-testid="steward-guide"]')
    guide.locator("summary").click()
    assert guide.locator("a").count() == 0
    assert page.recorded_errors == []


def test_the_case_guide_link_opens_the_section_it_names(
    viewport_390, server: BrowserServer, login, cedarline
) -> None:
    """A link of the case guide lands on the question it names."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="load")
    page.locator("[data-issue-row]", has_text="ERP-BL-00413").locator(
        '[data-testid="issue-link"]'
    ).click()
    page.wait_for_selector('[data-testid="steward-guide"]')
    guide = page.locator('[data-testid="steward-guide"]')
    guide.locator("summary").click()
    link = guide.locator("a", has_text="See the comparison")
    assert link.count() == 1
    assert link.get_attribute("href") == "#q3"
    link.click()
    assert page.url.endswith("#q3")
    assert page.locator("#q3").is_visible()
    assert page.recorded_errors == []


def test_the_profile_guide_link_opens_the_section_it_names(
    viewport_390, server: BrowserServer, login
) -> None:
    """A link of the profile guide lands on the section it names."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/masters/party_cedarline", wait_until="load")
    guide = page.locator('[data-testid="steward-guide"]')
    guide.locator("summary").click()
    link = guide.locator("a", has_text="See the identity")
    assert link.count() == 1
    assert link.get_attribute("href") == "#identity-heading"
    link.click()
    assert page.url.endswith("#identity-heading")
    assert page.locator("#identity-heading").is_visible()
    assert page.recorded_errors == []


def test_the_profile_guide_off_the_overview_links_nowhere(
    viewport_390, server: BrowserServer, login
) -> None:
    """The profile guide holds no link to a section the other views do not have."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/masters/party_cedarline?view=sources", wait_until="load")
    guide = page.locator('[data-testid="steward-guide"]')
    guide.locator("summary").click()
    assert guide.locator("a").count() == 0
    assert page.recorded_errors == []


def test_the_guide_of_the_incoming_work_fits_a_phone(
    viewport_390, server: BrowserServer, login
) -> None:
    """The saved guide of the incoming work opens on a phone and stays readable."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/queue/intake", wait_until="load")
    guide = page.locator('[data-testid="steward-guide"]')
    assert guide.count() == 1
    guide.locator("summary").click()
    assert "Saved guidance. Live Muse is off." in guide.inner_text()
    assert guide.locator('[data-testid="steward-guide-answer"]').inner_text().strip()
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, guide)
    assert_not_covered(page, page.locator("main h1").first)
    assert page.recorded_errors == []


def test_the_guide_of_the_early_resolution_board_fits_a_phone(
    viewport_390, server: BrowserServer, login
) -> None:
    """The saved guide of the early resolution board opens on a phone."""
    page = viewport_390
    login("persona_data_steward")
    page.goto(f"{server.base_url}/queue/early-resolution", wait_until="load")
    guide = page.locator('[data-testid="steward-guide"]')
    assert guide.count() == 1
    guide.locator("summary").click()
    assert "Saved guidance. Live Muse is off." in guide.inner_text()
    assert_no_horizontal_overflow(page)
    assert_not_covered(page, guide)
    assert page.recorded_errors == []


def test_the_queue_is_searched_and_opened_with_the_keyboard(
    page, server: BrowserServer, login, cedarline
) -> None:
    """The queue is searched and a task is opened without a mouse."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="load")
    # The search sits behind the disclosure of the filters.
    page.locator('[data-testid="queue-filters"] > summary').focus()
    page.keyboard.press("Enter")
    search = page.locator('[data-testid="queue-search-input"]')
    search.focus()
    search.fill("ERP-BL-00413")
    search.press("Enter")
    page.wait_for_url("**/steward?q=ERP-BL-00413")
    assert page.locator("[data-issue-row]").count() == 1
    link = page.locator('[data-testid="issue-link"]').first
    link.focus()
    link.press("Enter")
    page.wait_for_selector('[data-testid="compare-table"]')
    assert page.locator('[data-testid="case-q6"]').count() == 1
    assert page.recorded_errors == []


def test_the_guide_opens_with_the_keyboard(
    page, server: BrowserServer, login
) -> None:
    """The saved guide opens from the keyboard."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/steward", wait_until="load")
    summary = page.locator('[data-testid="steward-guide"] > summary')
    summary.focus()
    summary.press("Enter")
    assert page.locator('[data-testid="steward-guide-answer"]').is_visible()
    assert page.recorded_errors == []


def test_the_incoming_queue_is_searched_with_the_keyboard(
    page, server: BrowserServer, login
) -> None:
    """The incoming queue is searched from the keyboard."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/queue/intake", wait_until="load")
    search = page.locator('[data-testid="intake-search-input"]')
    search.focus()
    search.fill("no such case")
    search.press("Enter")
    page.wait_for_url("**/queue/intake?*")
    assert "q=no+such+case" in page.url
    assert page.locator('[data-testid="intake-empty"]').count() == 1
    assert page.recorded_errors == []


def test_the_filters_of_the_incoming_queue_work_with_the_keyboard(
    page, server: BrowserServer, login
) -> None:
    """The filters of the incoming queue are chosen and applied without a mouse."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/queue/intake", wait_until="load")
    page.locator('[data-testid="intake-filters"] > summary').focus()
    page.keyboard.press("Enter")
    priority = page.locator('[data-testid="intake-priority-filter"]')
    priority.select_option("high")
    page.locator('[data-testid="intake-filter-submit"]').focus()
    page.keyboard.press("Enter")
    page.wait_for_url("**/queue/intake?*")
    assert "priority=high" in page.url
    assert page.locator('[data-testid="intake-priority-filter"]').input_value() == "high"
    assert page.recorded_errors == []


def test_the_resolve_button_of_the_board_opens_the_case(
    page, server: BrowserServer, login, waiting_case
) -> None:
    """The Resolve button of the early resolution board opens the case it names."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/queue/early-resolution", wait_until="load")
    resolve = page.locator('[data-testid="resolve-case"]')
    assert resolve.count() == 1
    resolve.click()
    page.wait_for_load_state("domcontentloaded")
    assert "/permits/" in page.url
    assert waiting_case in page.locator("main").inner_text()
    assert page.recorded_errors == []


def test_the_search_button_of_the_incoming_queue_searches_the_cases(
    page, server: BrowserServer, login
) -> None:
    """The Search button of the incoming queue searches the cases."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/queue/intake", wait_until="load")
    page.locator('[data-testid="intake-search-input"]').fill("no such case")
    page.locator('[data-testid="intake-search-submit"]').click()
    page.wait_for_url("**/queue/intake?*")
    assert "q=no+such+case" in page.url
    assert page.locator('[data-testid="intake-empty"]').count() == 1
    assert page.recorded_errors == []


def test_a_tab_of_the_incoming_queue_opens_the_view_it_names(
    page, server: BrowserServer, login
) -> None:
    """A tab of the incoming queue opens the saved view it names."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/queue/intake", wait_until="load")
    tab = page.locator('[data-testid="intake-tab"][data-tab="archived"]')
    assert tab.count() == 1
    tab.click()
    page.wait_for_url("**/queue/intake?*")
    assert "tab=archived" in page.url
    assert page.locator('[data-testid="intake-count"]').is_visible()
    assert (
        page.locator('[data-testid="intake-tab"][data-tab="archived"]').get_attribute(
            "aria-selected"
        )
        == "true"
    )
    assert page.recorded_errors == []


def test_the_help_link_of_the_incoming_queue_opens_its_help(
    page, server: BrowserServer, login
) -> None:
    """The help link of the incoming queue opens the help of that screen."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/queue/intake", wait_until="load")
    page.locator('[data-testid="ui-help"]').click()
    drawer = page.locator("#ui-drawer")
    drawer.wait_for(state="visible")
    assert (
        drawer.locator('[data-testid="ui-drawer-title"]').inner_text()
        == "Help: Intake queue"
    )
    assert "what this screen is for" in drawer.inner_text().lower()
    assert page.recorded_errors == []


def test_the_help_link_of_the_early_resolution_board_opens_its_help(
    page, server: BrowserServer, login, waiting_case
) -> None:
    """The help link of the early resolution board opens the help of that screen."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/queue/early-resolution", wait_until="load")
    page.locator('[data-testid="ui-help"]').click()
    drawer = page.locator("#ui-drawer")
    drawer.wait_for(state="visible")
    assert (
        drawer.locator('[data-testid="ui-drawer-title"]').inner_text()
        == "Help: Early resolution"
    )
    assert "what this screen is for" in drawer.inner_text().lower()
    assert page.recorded_errors == []


def test_the_guide_link_of_the_early_resolution_board_opens_the_groups(
    page, server: BrowserServer, login, waiting_case
) -> None:
    """The guide link of the early resolution board lands on the groups it names."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/queue/early-resolution", wait_until="load")
    guide = page.locator('[data-testid="steward-guide"]')
    guide.locator("summary").click()
    link = guide.locator("a", has_text="See the groups")
    assert link.count() == 1
    link.click()
    assert page.url.endswith("#early-resolution-groups")
    assert page.locator("#early-resolution-groups").is_visible()
    assert page.recorded_errors == []


def test_the_guide_link_of_the_incoming_queue_opens_the_figures(
    page, server: BrowserServer, login
) -> None:
    """The guide link of the incoming queue lands on the figures it names."""
    login("persona_data_steward")
    page.goto(f"{server.base_url}/queue/intake", wait_until="load")
    guide = page.locator('[data-testid="steward-guide"]')
    guide.locator("summary").click()
    link = guide.locator("a", has_text="See what the figures mean")
    assert link.count() == 1
    link.click()
    assert page.url.endswith("#intake-definitions")
    assert page.locator("#intake-definitions").is_visible()
    assert page.recorded_errors == []
