"""Display-only City view hierarchy preserves the counted records."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from acme_city.insight.city_view import city_view, parse_filters
from acme_city.persistence.session import SessionFactory, transaction

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integration"))
from insight_support import build_environment  # noqa: E402


def test_filter_contract_keeps_uncopied_scope_explicit() -> None:
    filters = parse_filters(
        type="shed",
        outcome="approved",
        period="30d",
        category="restaurant",
        exceptions="1",
        synthetic="exclude",
    )
    assert filters == {
        "type": "shed",
        "outcome": "approved",
        "period": "30d",
        "category": ["restaurant"],
        "exceptions": True,
        "synthetic": "exclude",
    }

@pytest.fixture()
def city_settings(tmp_path: Path):
    return build_environment(tmp_path, synthetic=True, name="admin-city-regression.db")


def city_result(settings, **filters):
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            return city_view(session, **filters)
    finally:
        factory.dispose()


def test_city_view_filters_name_scope_and_preserve_record_counts(city_settings) -> None:
    result = city_result(city_settings, type="shed", outcome="approved")
    assert result["filter_summary"] == "Type: Shed or accessory building; Outcome: Approved"
    assert result["total"] <= result["total_before_filters"]
    assert result["rows_shown"] == min(result["total"], 60)
    assert sum(row["permits"] for row in result["map"]["district_table"]) <= result["total"]
    assert result["whatif_scope_note"] == (
        "Copies permit type and business category only. Outcome filters are not copied."
    )


def test_city_view_all_filters_keep_counts_and_name_only_uncopied_scope(city_settings) -> None:
    result = city_result(
        city_settings, type="shed", outcome="approved", period="30d",
        category="restaurant", exceptions="1", synthetic="exclude",
    )
    assert result["filter_summary"] == (
        "Type: Shed or accessory building; Outcome: Approved; Period: Last 30 days; "
        "Category: Restaurant; Exceptions only; Generated sample excluded"
    )
    assert result["total"] <= result["total_before_filters"]
    assert result["rows_shown"] == min(result["total"], 60)
    assert result["whatif_scope_note"] == (
        "Copies permit type and business category only. "
        "Outcome, period, exceptions, generated sample filters are not copied."
    )
