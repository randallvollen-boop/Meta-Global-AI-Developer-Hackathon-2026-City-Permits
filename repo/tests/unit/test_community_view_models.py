"""The presentation helpers of the two public community pages.

The helpers turn one public value into the words a resident reads or into a
local link.  They never widen the public record and they never build a link
that leaves this site.
"""
# REQUIRES: UX-01

from __future__ import annotations

import json
from pathlib import Path

from acme_city.fixtures.loader import REPO_ROOT
from acme_city.insight.public import PUBLIC_STATUS
from acme_city.ui.community_view_models import (
    MAX_QUERY_LENGTH,
    NOT_RECORDED,
    STATUS_EXPLANATIONS,
    UNKNOWN_STATUS,
    community_url,
    display_date,
    normalize_query,
    normalize_type,
    permit_type_keys,
    public_record_url,
    status_explanation,
)


def test_a_public_date_is_shown_as_a_resident_reads_it() -> None:
    assert display_date("2026-10-12") == "Oct 12, 2026"
    assert display_date("2026-01-05") == "Jan 5, 2026"
    assert display_date("2026-12-31") == "Dec 31, 2026"


def test_a_missing_or_broken_date_is_never_guessed() -> None:
    assert display_date("") == NOT_RECORDED
    assert display_date("   ") == NOT_RECORDED
    assert display_date("not a date") == NOT_RECORDED
    assert display_date("2026-13-45") == NOT_RECORDED


def test_every_public_status_has_a_fixed_explanation() -> None:
    assert set(STATUS_EXPLANATIONS) == set(PUBLIC_STATUS.values())
    assert status_explanation("Received") == "The application has been received."
    assert status_explanation("In review") == "The application is in review."
    assert status_explanation("Denied") == "The application was denied."
    assert status_explanation("Permit issued") == "A permit has been issued."
    approved = status_explanation("Approved")
    assert approved.startswith("The application is approved.")
    assert "permit has not necessarily been issued" in approved


def test_an_unknown_status_gets_neutral_wording() -> None:
    assert status_explanation("") == UNKNOWN_STATUS
    assert status_explanation("Archived") == UNKNOWN_STATUS
    assert status_explanation("not a status") == UNKNOWN_STATUS


def test_the_search_text_is_collapsed_and_clipped() -> None:
    assert normalize_query("  Example   Lane  ") == "Example Lane"
    assert normalize_query("") == ""
    assert len(normalize_query("x" * 500)) == MAX_QUERY_LENGTH


def test_only_a_known_permit_type_is_accepted() -> None:
    assert normalize_type("rezoning") == "rezoning"
    assert normalize_type("  rezoning  ") == "rezoning"
    assert normalize_type("not-a-type") == ""
    assert normalize_type("") == ""
    assert normalize_type("../../etc/passwd") == ""


def test_the_type_whitelist_matches_the_fictional_catalog() -> None:
    payload = json.loads(
        (REPO_ROOT / "config" / "rules_and_fees.json").read_text(encoding="utf-8")
    )
    keys = {str(item["key"]) for item in payload["permit_types"]}
    assert permit_type_keys() == keys
    assert "rezoning" in permit_type_keys()


def test_the_community_url_is_local_and_bounded() -> None:
    assert community_url() == "/city/community"
    assert community_url("", "") == "/city/community"
    assert community_url("Example Lane") == "/city/community?q=Example+Lane"
    assert community_url("Example Lane", "rezoning") == (
        "/city/community?q=Example+Lane&type=rezoning"
    )
    assert community_url("Lane", "not-a-type") == "/city/community?q=Lane"


def test_the_record_url_encodes_the_reference() -> None:
    assert public_record_url("ACME-2026-000731") == "/city/community/permit/ACME-2026-000731"
    assert public_record_url("a/b") == "/city/community/permit/a%2Fb"
    assert public_record_url("a b") == "/city/community/permit/a%20b"
    assert public_record_url("ACME-2026-000731", "Lane", "rezoning") == (
        "/city/community/permit/ACME-2026-000731?q=Lane&type=rezoning"
    )


def test_no_helper_builds_a_remote_or_absolute_url() -> None:
    urls = [
        community_url("Example Lane", "rezoning"),
        community_url("../../etc", "not-a-type"),
        public_record_url("ACME-2026-000731", "Example Lane"),
        public_record_url("../../secret"),
    ]
    for url in urls:
        assert url.startswith("/city/community"), url
        assert "://" not in url, url
        assert url.count("?") <= 1, url
        path = url.split("?")[0]
        assert "//" not in path, url
        if "/permit/" in path:
            # The reference stays one path segment, so it cannot walk out.
            assert "/" not in path.split("/permit/", 1)[1], url


def test_the_return_context_stays_inside_the_community_pages() -> None:
    url = public_record_url("ACME-2026-000731", "Example Lane", "rezoning")
    assert url.startswith("/city/community/permit/")
    assert "q=Example+Lane" in url
    assert "type=rezoning" in url
    assert Path(url.split("?")[0]).name == "ACME-2026-000731"
