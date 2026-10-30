"""The typed comparison of a focused case.

A party, a parcel and an address are compared in their own fields.  The
comparison reads in the order a steward needs it: what disagrees first, then
what is missing on one side, and only then what agrees.  A missing value
stays missing, and the raw value and the value the matcher normalized stay
apart.

Fictional ACME City data only.
"""
# REQUIRES: UX-01, UX-02, MDM-02

from __future__ import annotations

from pathlib import Path

import pytest

from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.persistence.models import registry
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)
from acme_city.ui import steward_views


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    """Return the settings of a seeded demonstration database."""
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'comparison.db'}",
            "ACME_SECRET_KEY": "steward-comparison-secret-value",
        },
        key_file=tmp_path / "missing.env",
    )
    initialize_database(settings)
    bundle = FixtureBundle.load()
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            session.add(
                DemoEnvironment(
                    id="demo_environment_local",
                    environment_id=ENVIRONMENT_ID,
                    fictional_demo=True,
                    fixture_version=bundle.fixture_version,
                    label="local fictional demonstration",
                )
            )
        with transaction(factory) as session:
            reset_demo(session, bundle, confirmation="--confirm-fictional-demo")
    finally:
        factory.dispose()
    return settings


def with_session(settings: Settings, work):
    """Run one piece of work with a session of the seeded database."""
    factory = SessionFactory(settings.database_url)
    try:
        with factory() as session:
            return work(session)
    finally:
        factory.dispose()


def test_the_comparison_reads_what_disagrees_first() -> None:
    """The rows of a comparison come in the order a reader needs them."""
    rows = [
        {"field": "Name", "source": "a", "master": "b", "result": "agrees", "note": ""},
        {"field": "Email", "source": "a", "master": "No value", "result": "no_comparison", "note": ""},
        {"field": "Unit", "source": "a", "master": "b", "result": "conflicts", "note": ""},
    ]
    comparison = steward_views.typed_comparison(rows, family="party")
    assert [row["field"] for row in comparison["rows"]] == ["Unit", "Email", "Name"]
    assert [row["field"] for row in comparison["conflicts"]] == ["Unit"]
    assert [row["field"] for row in comparison["missing"]] == ["Email"]
    assert [row["field"] for row in comparison["agreements"]] == ["Name"]
    assert comparison["has_conflicts"] is True
    assert comparison["has_missing"] is True


def test_the_comparison_keeps_the_order_inside_a_group() -> None:
    """Two rows that agree keep the order they were built in."""
    rows = [
        {"field": "Name", "source": "a", "master": "a", "result": "agrees", "note": ""},
        {"field": "Address", "source": "a", "master": "a", "result": "agrees", "note": ""},
    ]
    comparison = steward_views.typed_comparison(rows)
    assert [row["field"] for row in comparison["rows"]] == ["Name", "Address"]


def test_a_missing_value_stays_missing() -> None:
    """A value that one side does not have is shown as missing, never filled in."""
    comparison = steward_views.typed_comparison(
        [{"field": "Email", "source": "a@example.invalid", "master": "", "result": "no_comparison", "note": ""}]
    )
    row = comparison["rows"][0]
    assert row["master"] == "No value"
    assert row["master_normalized"] == ""


def test_a_party_comparison_keeps_the_raw_and_the_normalized_apart(
    seeded: Settings,
) -> None:
    """A party is compared in its own fields, with both forms of every value."""
    settings = seeded
    rows = with_session(
        settings,
        lambda session: steward_views.compare_with_party(
            session,
            {
                "organization_name": "Cedarline Coffee Works LLC",
                "license_number": "BL-2026-00413",
                "contact_email": "info@cedarline.example.invalid",
            },
            session.get(registry.Party, "party_cedarline"),
        ),
    )
    by_field = {row["field"]: row for row in rows}
    assert by_field["Name"]["source"] == "Cedarline Coffee Works LLC"
    assert by_field["Name"]["source_normalized"]
    assert by_field["Name"]["source_normalized"] != by_field["Name"]["source"]
    assert by_field["Name"]["master"] == "Cedarline Coffee Roasters LLC"
    assert by_field["Name"]["result"] == "conflicts"
    assert by_field["Email"]["result"] in {"conflicts", "agrees"}
    assert by_field["Email"]["source_normalized"]


def test_a_missing_value_of_a_party_stays_missing(seeded: Settings) -> None:
    """A party without a contact has nothing to compare the email with."""
    rows = with_session(
        seeded,
        lambda session: steward_views.compare_with_party(
            session,
            {"organization_name": "Halcyon Build", "contact_email": "info@halcyon.example.invalid"},
            session.get(registry.Party, "party_halcyon"),
        ),
    )
    by_field = {row["field"]: row for row in rows}
    assert by_field["Email"]["result"] == "no_comparison"
    assert by_field["Email"]["master"] == "No value"
    assert by_field["Email"]["master_normalized"] == ""


def test_a_parcel_comparison_reads_the_parcel_number(seeded: Settings) -> None:
    """A parcel is compared in the fields of a parcel, not of a party."""
    settings = seeded
    rows = with_session(
        settings,
        lambda session: steward_views.compare_with_parcel(
            session,
            {"parcel_number": "ACME-P-1002"},
            session.get(registry.Parcel, "parcel_1001"),
        ),
    )
    by_field = {row["field"]: row for row in rows}
    assert by_field["Parcel number"]["result"] == "conflicts"
    assert by_field["Parcel number"]["source"] == "ACME-P-1002"
    assert by_field["Parcel number"]["master"] == "ACME-P-1001"
    assert by_field["Jurisdiction"]["result"] == "no_comparison"
    assert by_field["Jurisdiction"]["master"] != "No value"


def test_an_address_comparison_keeps_the_unit_apart(seeded: Settings) -> None:
    """Two addresses in one building with another unit are not the same place."""
    settings = seeded
    rows = with_session(
        settings,
        lambda session: steward_views.compare_with_address(
            session,
            {"source_string": "400 Lantern Row Unit 5"},
            session.get(registry.Address, "address_400_lantern_unit_2"),
        ),
    )
    by_field = {row["field"]: row for row in rows}
    assert by_field["Address"]["result"] == "conflicts"
    assert by_field["Address"]["source_normalized"]
    assert by_field["Unit"]["result"] == "conflicts"
    assert by_field["Unit"]["source"] == "Unit 5"
    assert by_field["Unit"]["master"] == "Unit 2"


def test_the_families_are_known() -> None:
    """The renderer knows the families of record it can show."""
    assert "party" in steward_views.COMPARISON_FAMILIES
    assert "parcel" in steward_views.COMPARISON_FAMILIES
    assert "address" in steward_views.COMPARISON_FAMILIES


def test_a_candidate_of_every_family_gets_its_own_comparison(
    seeded: Settings,
) -> None:
    """A candidate is compared in the fields of its own family."""
    class _Candidate:
        def __init__(self, entity_type: str, entity_id: str) -> None:
            self.entity_type = entity_type
            self.entity_id = entity_id

    settings = seeded
    party = with_session(
        settings,
        lambda session: steward_views._candidate_comparison(
            session, _Candidate("party", "party_cedarline"), {"organization_name": "Cedarline"}
        ),
    )
    assert party is not None
    assert party["family"] == "party"
    assert party["linkable"] is True
    assert [row["field"] for row in party["rows"]][0] == "Name"

    parcel = with_session(
        settings,
        lambda session: steward_views._candidate_comparison(
            session, _Candidate("parcel", "parcel_1001"), {"parcel_number": "17 Mill Row"}
        ),
    )
    assert parcel is not None
    assert parcel["family"] == "parcel"
    assert parcel["linkable"] is False
    assert "Parcel number" in [row["field"] for row in parcel["rows"]]

    address = with_session(
        settings,
        lambda session: steward_views._candidate_comparison(
            session,
            _Candidate("address", "address_400_lantern_unit_2"),
            {"source_string": "400 Lantern Row Unit 2"},
        ),
    )
    assert address is not None
    assert address["family"] == "address"
    assert address["linkable"] is False
    assert "Address" in [row["field"] for row in address["rows"]]


def test_a_record_that_is_not_in_the_registry_has_no_comparison(
    seeded: Settings,
) -> None:
    """A candidate the registry does not hold is not shown."""

    class _Candidate:
        entity_type = "party"
        entity_id = "party_does_not_exist"

    result = with_session(
        seeded,
        lambda session: steward_views._candidate_comparison(session, _Candidate(), {}),
    )
    assert result is None


def test_the_stored_evidence_is_used_when_the_proposal_holds_it(
    seeded: Settings,
) -> None:
    """The evidence a proposal recorded is read with the proposal."""
    proposal = registry.MatchProposal(
        id="proposal_comparison",
        source_snapshot_id="snapshot_comparison",
        entity_id="party_cedarline",
        supporting_evidence=[
            {
                "field": "organization_name",
                "method": "name_normalized_exact",
                "detail": "the source names the candidate",
            }
        ],
        conflicting_evidence=[],
    )
    stored = steward_views._stored_evidence(proposal, "party_cedarline")
    assert stored is not None
    assert stored[0][0]["field"] == "organization_name"
    assert steward_views._stored_evidence(proposal, "party_other") is None
    assert steward_views._stored_evidence(None, "party_cedarline") is None
