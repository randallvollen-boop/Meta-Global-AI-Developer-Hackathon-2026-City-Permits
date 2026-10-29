"""Display-only City view hierarchy preserves the counted records."""

from __future__ import annotations

from acme_city.insight.city_view import parse_filters


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
