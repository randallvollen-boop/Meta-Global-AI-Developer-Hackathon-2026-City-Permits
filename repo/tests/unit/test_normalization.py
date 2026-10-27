"""Normalization tests: the raw value survives and no link is created."""

from __future__ import annotations

from acme_city.ingestion.normalization import (
    address_building_matches,
    address_unit_conflicts,
    address_unit_matches,
    name_token_overlap,
    normalize_address,
    normalize_email,
    normalize_identifier,
    normalize_name,
    normalize_phone,
    normalize_text,
)


def test_the_raw_name_is_preserved_beside_the_comparison_form() -> None:
    raw = "Cedar Line Coffee Roasters"
    normalized = normalize_name(raw)
    assert normalized.raw == raw
    assert normalized.normalized == "cedar line coffee roasters"
    assert normalized.core_tokens == ("cedar", "line", "coffee", "roasters")


def test_the_legal_form_is_separated_and_not_dropped() -> None:
    normalized = normalize_name("Cedarline Coffee Roasters LLC")
    assert normalized.legal_forms == ("llc",)
    assert normalized.core_tokens == ("cedarline", "coffee", "roasters")
    assert "llc" in normalized.tokens


def test_a_similar_name_stays_a_similar_name() -> None:
    cedarline = normalize_name("Cedar Line Coffee Roasters")
    works = normalize_name("Cedarline Coffee Works")
    overlap = name_token_overlap(cedarline, works)
    assert 0.0 < overlap < 1.0
    assert cedarline.core_tokens != works.core_tokens


def test_the_address_keeps_its_unit_distinction() -> None:
    unit_two = normalize_address("400 Lantern Row Unit 2")
    unit_five = normalize_address("400 Lantern Row Unit 5")
    building = normalize_address("400 Lantern Row")
    assert unit_two.building_key == building.building_key
    assert address_building_matches(unit_two, building)
    assert address_unit_conflicts(unit_two, unit_five)
    assert not address_unit_matches(unit_two, unit_five)
    assert unit_two.unit_number == "2"
    assert unit_five.unit_number == "5"


def test_the_word_that_introduces_a_unit_does_not_change_it() -> None:
    suite = normalize_address("400 Lantern Row, Suite 2, ACME City")
    unit = normalize_address("400 Lantern Row Unit 2")
    assert suite.unit_number == "2"
    assert suite.building_key == unit.building_key
    assert not address_unit_conflicts(suite, unit)


def test_the_locality_is_separated_from_the_street() -> None:
    address = normalize_address("12 Marrow Creek Road, ACME City")
    assert address.street_number == "12"
    assert address.street_name == "marrow creek"
    assert address.street_type == "road"
    assert address.municipality == "acme city"
    assert address.building_key == "12 marrow creek road"


def test_identifiers_and_contact_details_keep_a_comparison_form() -> None:
    assert normalize_identifier("CR-2026 00188") == "cr202600188"
    assert normalize_email(" T.ALD@Example.invalid ") == "t.ald@example.invalid"
    assert normalize_phone("+1-555-0141") == "15550141"
    assert normalize_text("  Cedar   Line  ") == "cedar line"


def test_normalization_never_creates_an_identity_link() -> None:
    """A normalized value carries comparison data only.

    The normalizer returns no canonical identifier, no crosswalk and no
    decision: those belong to the registry and to a steward.
    """
    normalized = normalize_name("Cedar Line Coffee Roasters")
    fields = set(normalized.__dataclass_fields__)
    assert "entity_id" not in fields
    assert "crosswalk_id" not in fields
    assert "decision" not in fields
    address = normalize_address("400 Lantern Row Unit 2")
    address_fields = set(address.__dataclass_fields__)
    assert "entity_id" not in address_fields
    assert "link_status" not in address_fields
