"""The permit workspace returns the reviewer to the queue they left.

A ``from`` value is kept only when it is one of the local queues or a
persona home. Anything else falls back, and a case link on those pages
carries the page it left.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from acme_city.ui.reviewer_views import accepted_return, page_origin, stamp_case_links


def test_a_queue_path_is_kept_and_labelled_by_its_screen() -> None:
    assert accepted_return("/queue") == ("/queue", "/queue")
    assert accepted_return("/queue/review") == ("/queue/review", "/queue/review")
    assert accepted_return("/queue?view=all") == ("/queue?view=all", "/queue")
    assert accepted_return("/overview") == ("/overview", "/overview")
    assert accepted_return("/city/") == ("/city/", "/city/")


def test_a_foreign_return_is_refused() -> None:
    for value in (
        None,
        "",
        "https://example.com/queue",
        "//example.com/queue",
        "/\\example.com",
        "/admin",
        "/queue/review/extra",
        "/queue/../admin",
        "/queue/%2e%2e/admin",
        "/%0d%0aLocation:%20https://example.com",
    ):
        assert accepted_return(value) is None, value


def test_case_links_on_a_queue_carry_that_queue() -> None:
    page = {
        "rows": [{"href": "/permits/app_synth_001", "reference": "SYN-APP-001"}],
        "elsewhere": {"href": "/steward/issues/link/case_1"},
        "already": {"href": "/permits/app_d07?tab=review"},
    }
    stamp_case_links(page, page_origin("/queue/review", "area=Building"))
    href = page["rows"][0]["href"]
    parsed = urlsplit(href)
    assert parsed.path == "/permits/app_synth_001"
    assert parse_qs(parsed.query)["from"] == ["/queue/review?area=Building"]
    assert page["elsewhere"]["href"] == "/steward/issues/link/case_1"
    assert page["already"]["href"] == "/permits/app_d07?tab=review"
    untouched = {"href": "/permits/app_synth_001"}
    stamp_case_links(untouched, "https://example.com/queue")
    assert untouched["href"] == "/permits/app_synth_001"
