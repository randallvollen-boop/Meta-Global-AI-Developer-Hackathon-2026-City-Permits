"""The other reviewer screens show only what a worker needs to decide.

The review queue, early resolution, life cycle, town map and planning
overview keep the decision content in view. Area, owner, findings, counts,
the parcel table and the overview tables sit behind More details.
"""

from __future__ import annotations

import re
import sys
from html import unescape
from pathlib import Path
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "integration"))
from insight_support import build_environment  # noqa: E402

from acme_city.app import create_app  # noqa: E402
from acme_city.auth.context import ActorContext  # noqa: E402
from acme_city.auth.permissions import PermissionResolver  # noqa: E402
from acme_city.core.config import Settings  # noqa: E402
from acme_city.persistence.models import permit  # noqa: E402
from acme_city.persistence.models.governance import ActorRole  # noqa: E402
from acme_city.persistence.session import SessionFactory, transaction  # noqa: E402
from acme_city.permits.schemas import SubmitApplicationCommand  # noqa: E402
from acme_city.permits.service import PermitService  # noqa: E402
from acme_city.ui.router import router as ui_router  # noqa: E402

REVIEWER = "persona_permit_reviewer"
STEWARD = "persona_data_steward"
ADMIN = "persona_city_administrator"

FACTS = {
    "valuation": "50000.00",
    "valuation_cents": 5000000,
    "project_description": "A fictional fence",
    "contractor_license": "ACME-LIC-1042",
    "submitted_parcel": "ACME-P-1001",
    "channel": "portal",
    "applicant_name": "Cedar Line Coffee Roasters",
}


def choose(client: TestClient, actor_id: str) -> None:
    """Establish a server-held session for a persona."""
    response = client.post("/api/session/select", json={"actor_id": actor_id})
    assert response.status_code == 200, response.text


def inside_details(page: str, marker: str) -> bool:
    """Return whether the first marker sits inside a details element."""
    index = page.index(marker)
    opens = len(re.findall(r"<details\b", page[:index]))
    closes = len(re.findall(r"</details>", page[:index]))
    return opens > closes


def assert_closed(page: str, testid: str) -> None:
    """The named disclosures are present and closed."""
    tags = re.findall(rf'<details\b[^>]*data-testid="{testid}"[^>]*>', page)
    assert tags, testid
    for tag in tags:
        assert not re.search(r"(?:^|\s)open(?:\s|=|>|$)", tag), tag


def hrefs(page: str, pattern: str) -> list[str]:
    """Return the unescaped hrefs a pattern names."""
    return [unescape(href) for href in re.findall(pattern, page)]


def assert_disabled_buttons_say_why(page: str) -> None:
    """A disabled button on the screen names the reason beside it."""
    main = page.split('<div class="main">', 1)[-1]
    for match in re.finditer(r"<button\b([^>]*)>", main):
        if not re.search(r"\bdisabled\b", match.group(1)):
            continue
        after = main[match.end(): match.end() + 500]
        assert re.search(r'class="hint"|data-reason=|reason', after, re.I), match.group(0)


def _context_for(session, actor_id: str) -> ActorContext:
    resolver = PermissionResolver(session)
    grants = resolver.grants_for(actor_id)
    roles = frozenset(
        row[0]
        for row in session.execute(
            select(ActorRole.role_id).where(ActorRole.actor_id == actor_id)
        ).all()
    )
    return ActorContext(
        actor_id=actor_id,
        role_ids=roles,
        domain_scope=frozenset(grant.domain_id for grant in grants if grant.domain_id),
        record_scope=frozenset(
            record_id for grant in grants for record_id in grant.record_scope
        ),
    )


def _submit(session, site: str) -> permit.Application:
    service = PermitService(session)
    view = service.submit(
        SubmitApplicationCommand(
            permit_type_key="com_ti",
            facts={**FACTS, "submitted_site_text": site},
            applicant_party_id="party_cedarline",
        ),
        _context_for(session, STEWARD),
    )
    application = service.load_application(view.application_id)
    session.flush()
    return application


def _seed(settings: Settings) -> None:
    """Add review and early-resolution cases without touching the seeded corpus."""
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            building = _submit(session, "410 Lantern Row, ACME City")
            building.status = "ready_for_review"
            building.review_area = "Building"
            fire = _submit(session, "420 Lantern Row, ACME City")
            fire.status = "ready_for_review"
            fire.review_area = "Fire"
            waiting = _submit(session, "430 Lantern Row, ACME City")
            waiting.status = "needs_information"
            session.add(
                permit.ApplicationFinding(
                    id="finding_r3_waiting",
                    correlation_id="corr_r3_waiting",
                    application_id=waiting.id,
                    finding_type="missing_document",
                    message="The site plan is missing.",
                    applicant_must="Send a signed site plan.",
                    severity="block",
                    state="current",
                    revision_number=waiting.revision,
                    version=1,
                )
            )
    finally:
        factory.dispose()


@pytest.fixture(scope="module")
def client(tmp_path_factory) -> TestClient:
    directory = tmp_path_factory.mktemp("reviewer-screens")
    settings = build_environment(directory, synthetic=False, name="screens.db")
    _seed(settings)
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def test_the_review_queue_keeps_the_decision_and_collapses_the_rest(
    client: TestClient,
) -> None:
    choose(client, REVIEWER)
    response = client.get("/queue/review")
    assert response.status_code == 200, response.text[:400]
    page = response.text
    assert "Cases with the Permit Reviewer, by review area." in page
    assert "and the decisions that were recorded recently" not in page
    assert "What these figures mean" not in page
    assert '<th scope="col">Decided by</th>' not in page
    assert 'data-testid="review-areas"' in page
    assert 'data-testid="review-row"' in page
    assert 'data-testid="review-recommendation-none"' in page
    assert "The adjudication agent has not run on this case." in page
    assert not inside_details(page, 'data-testid="review-recommendation-none"')
    assert inside_details(page, 'data-testid="review-row-area"')
    assert inside_details(page, 'data-testid="review-row-owner"')
    assert_closed(page, "review-row-more")
    assert inside_details(page, 'data-testid="recent-decisions"')
    assert inside_details(page, 'data-testid="review-definitions"')
    assert inside_details(page, 'data-testid="review-recent-definitions"')
    assert_closed(page, "review-more")
    table = re.search(r'data-testid="review-table".*?</table>', page, re.S)
    assert table is not None
    headers = re.findall(r'<th scope="col">([^<]+)</th>', table.group(0))
    assert headers == ["Reference", "Type", "Stage", "Next action", "Recommendation", "Age"]
    assert 'data-testid="next-action-filters"' in page
    assert 'data-testid="review-stage"' in page
    assert 'data-testid="review-next-action"' in page
    assert "Checks (3 of 6)" in page
    assert not inside_details(page, 'data-testid="review-stage"')
    assert not inside_details(page, 'data-testid="review-next-action"')
    recent = re.search(r'data-testid="recent-decisions".*?</table>', page, re.S)
    assert recent is not None
    assert REVIEWER not in recent.group(0)
    recent_headers = re.findall(r'<th scope="col">([^<]+)</th>', recent.group(0))
    assert recent_headers == ["Reference", "Type", "Outcome", "Conditions", "When"]
    source = (ROOT / "src/acme_city/templates/review_queue.html").read_text(encoding="utf-8")
    stale_at = source.index('data-testid="review-recommendation-stale"')
    details_at = source.index('data-testid="review-row-more"')
    assert stale_at < details_at
    assert_disabled_buttons_say_why(page)


def test_every_review_area_tab_opens(client: TestClient) -> None:
    choose(client, REVIEWER)
    page = client.get("/queue/review").text
    tabs = re.findall(
        r'<a href="([^"]+)" data-testid="review-area" data-area="([^"]*)" aria-selected="(true|false)">',
        page,
    )
    areas = {area for _href, area, _selected in tabs}
    assert "" in areas and "Building" in areas and "Fire" in areas
    for href, area, _selected in tabs:
        opened = client.get(unescape(href))
        assert opened.status_code == 200, href
        selected = re.findall(
            r'data-testid="review-area" data-area="([^"]*)" aria-selected="true"',
            opened.text,
        )
        assert selected == [area], (href, selected)


def test_the_early_resolution_board_keeps_the_case_and_collapses_the_rest(
    client: TestClient,
) -> None:
    choose(client, STEWARD)
    response = client.get("/queue/early-resolution")
    assert response.status_code == 200, response.text[:400]
    page = response.text
    assert 'id="early-resolution-groups"' in page
    assert 'data-testid="early-resolution-kpis"' not in page
    assert 'data-testid="group-findings"' not in page
    assert "Cases to resolve" not in page
    assert 'data-testid="steward-guide-answer"' in page
    assert "Saved guidance." in page
    assert 'data-testid="resolve-case"' in page
    assert "The site plan is missing." in page
    assert "Missing document · Blocking" in page
    assert "Applicant must: Send a signed site plan." in page
    assert not inside_details(page, 'data-testid="case-primary-finding"')
    assert not inside_details(page, 'data-testid="early-resolution-next-step"')
    assert not inside_details(page, 'data-testid="early-resolution-resolve"')
    assert inside_details(page, 'data-testid="case-type"')
    assert inside_details(page, 'data-testid="case-age"')
    assert inside_details(page, 'data-testid="case-findings"')
    assert inside_details(page, "Applicant must: Send a signed site plan.")
    assert_closed(page, "early-resolution-case-more")
    assert inside_details(page, 'data-testid="early-resolution-definitions"')
    assert_closed(page, "early-resolution-more")
    assert_disabled_buttons_say_why(page)


def test_every_resolve_link_opens_the_case(client: TestClient) -> None:
    choose(client, STEWARD)
    page = client.get("/queue/early-resolution").text
    links = hrefs(page, r'<a class="btn sm" href="([^"]+)" data-testid="resolve-case">')
    assert links
    for href in links:
        opened = client.get(href)
        assert opened.status_code == 200, (href, opened.status_code)


def test_the_life_cycle_keeps_the_path_and_collapses_the_counts(
    client: TestClient,
) -> None:
    response = client.get("/lifecycle")
    assert response.status_code == 200, response.text[:400]
    page = response.text
    assert "Every status a case can hold, and who can move it." in page
    assert "The counts are the cases stored in this demonstration." not in page
    assert "<h2" in page and "Statuses and moves" in page
    assert not inside_details(page, 'data-testid="lifecycle-main-path"')
    assert not inside_details(page, 'data-testid="lifecycle-move"')
    assert "By " in page
    assert inside_details(page, 'data-testid="lifecycle-count"')
    assert inside_details(page, 'data-testid="lifecycle-example"')
    if 'data-testid="lifecycle-note"' in page:
        assert inside_details(page, 'data-testid="lifecycle-note"')
    assert_closed(page, "lifecycle-more")
    draft = re.search(
        r'data-status="draft".*?</article>',
        page,
        re.S,
    )
    assert draft is not None
    assert 'data-testid="lifecycle-example"' not in draft.group(0)
    assert 'href="/walkthrough"' in page
    assert_disabled_buttons_say_why(page)


def test_every_open_as_button_opens_the_example(client: TestClient) -> None:
    page = client.get("/lifecycle").text
    forms = re.findall(
        r'<form method="post" action="/ui/actor" class="guide-open-as">'
        r'\s*<input type="hidden" name="actor_id" value="([^"]+)">'
        r'\s*<input type="hidden" name="next" value="([^"]+)">'
        r'\s*<button type="submit"[^>]*data-testid="lifecycle-example"',
        page,
    )
    assert forms
    for actor_id, path in forms:
        switched = client.post(
            "/ui/actor",
            data={"actor_id": actor_id, "next": path},
            follow_redirects=False,
        )
        assert switched.status_code == 303, (path, switched.status_code)
        landed = urlparse(switched.headers["location"]).path
        assert landed == path, (path, switched.headers["location"])
        opened = client.get(path)
        assert opened.status_code == 200, (path, opened.status_code)


def test_the_town_map_keeps_the_search_and_collapses_the_table(
    client: TestClient,
) -> None:
    choose(client, ADMIN)
    response = client.get("/map")
    assert response.status_code == 200, response.text[:400]
    page = response.text
    assert "Search an address and open its parcel." in page
    assert "The fictional town of ACME City, drawn from the simulated parcel" not in page
    assert "This is not a real GIS." not in page
    assert "Without JavaScript this is a static map" not in page
    assert not inside_details(page, 'data-testid="map-search"')
    assert "Find on the map" in page
    assert not inside_details(page, 'data-testid="town-map"')
    tools = re.search(r'<div class="map-tools"[^>]*>', page)
    assert tools is not None and re.search(r"\bhidden\b", tools.group(0))
    assert inside_details(page, 'data-testid="map-legend"')
    assert inside_details(page, 'data-testid="map-parcel-table"')
    assert "The same information as the map, as text." in page
    assert_closed(page, "map-more")
    assert_disabled_buttons_say_why(page)


def test_find_on_the_map_opens_the_parcel_and_its_record(client: TestClient) -> None:
    choose(client, ADMIN)
    found = client.get("/map", params={"q": "400 Lantern Row"})
    assert found.status_code == 200, found.text[:400]
    assert 'data-testid="map-candidates"' in found.text
    assert "ACME-P-1001" in found.text
    highlighted = client.get("/map", params={"parcel": "ACME-P-1001"})
    assert highlighted.status_code == 200
    page = highlighted.text
    subject = re.search(r'data-testid="map-subject".*?</section>', page, re.S)
    assert subject is not None
    assert "(synthetic)" not in subject.group(0)
    record = re.search(r'href="(/property/[^"]+)">Open property record</a>', subject.group(0))
    assert record is not None
    opened = client.get(unescape(record.group(1)))
    assert opened.status_code == 200, opened.status_code


def test_the_overview_keeps_the_counts_and_collapses_the_tables(
    client: TestClient,
) -> None:
    choose(client, ADMIN)
    response = client.get("/overview")
    assert response.status_code == 200, response.text[:400]
    page = response.text
    head = re.search(r'<div class="page-head">.*?</p>', page, re.S)
    assert head is not None
    assert "What needs attention, what has been proposed and where the data comes from." in head.group(0)
    assert "Every figure is counted from the stored records." not in head.group(0)
    assert 'data-testid="overview-scope"' not in page
    assert "Sample applications · synthetic" not in page
    for testid in (
        "overview-attention-count",
        "overview-changes-count",
        "overview-property-count",
        "overview-sources-count",
    ):
        assert not inside_details(page, f'data-testid="{testid}"'), testid
    order = [
        page.index(f'data-testid="overview-{key}-count"')
        for key in ("attention", "changes", "property", "sources")
    ]
    assert order == sorted(order)
    assert inside_details(page, 'data-testid="overview-card-definition"')
    for marker in re.finditer(r'data-testid="overview-card-definition"', page):
        prefix = page[: marker.start()]
        tag = prefix[prefix.rfind("<details") :]
        assert tag.startswith("<details>"), tag[:80]
    assert not inside_details(page, 'data-testid="overview-attention-table"')
    assert 'aria-label="Open the case ' in page
    assert not inside_details(page, 'data-testid="overview-approval-policy"')
    assert inside_details(page, 'data-testid="overview-changes-table"')
    assert_closed(page, "overview-changes-more")
    assert inside_details(page, 'data-testid="overview-property-table"')
    assert_closed(page, "overview-property-more")
    assert inside_details(page, 'data-testid="overview-sources-table"')
    assert_closed(page, "overview-sources-more")
    assert inside_details(page, 'data-testid="overview-related"')
    assert_closed(page, "overview-related-more")
    assert inside_details(page, 'data-testid="evidence-panel"')
    assert_closed(page, "overview-evidence-more")
    assert "further applications are counted" in page
    info = re.search(r'<button type="button"[^>]*data-testid="ui-info-btn"[^>]*>', page)
    assert info is not None
    assert "disabled" not in info.group(0)
    assert "Single administrator:" in page
    assert_disabled_buttons_say_why(page)


def test_overview_links_open_the_screens_they_name(client: TestClient) -> None:
    choose(client, ADMIN)
    page = client.get("/overview").text
    cases = hrefs(page, r'href="([^"]+)" aria-label="Open the case [^"]+">')
    assert cases
    for href in cases:
        opened = client.get(href)
        assert opened.status_code == 200, (href, opened.status_code)
    summaries = hrefs(page, r'<a class="adm-summary-link" href="([^"]+)">')
    assert len(summaries) == 4
    for href in summaries:
        opened = client.get(href)
        assert opened.status_code == 200, (href, opened.status_code)
    versions = hrefs(page, r'href="([^"]+)" aria-label="Open the version [^"]+">')
    assert versions
    for href in versions:
        opened = client.get(href)
        assert opened.status_code == 200, (href, opened.status_code)
    contexts = hrefs(
        page,
        r'href="([^"]+)" data-ui-detail data-detail-kind="property-context"',
    )
    assert contexts
    opened = client.get(contexts[0])
    assert opened.status_code == 200, opened.status_code
    assert "property-context" in contexts[0]
