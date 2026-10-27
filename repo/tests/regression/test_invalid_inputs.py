"""Regression tests for the named invalid source inputs.

The four inputs below are the ones the demonstration must survive: a setback
that is a word, a setback that is not a finite number, a blank fence location
and an unsupported sign type.  Every one of them produces an explicit field
error, and none of them crashes the intake or becomes an accepted value.
"""
# REQUIRES: ING-02, D09
# The regression inputs are rejected with explicit field errors, and no invalid
# record is ever accepted or published.

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo
from acme_city.ingestion.schemas import IngestCommand, SourceRecordCommand
from acme_city.ingestion.service import IngestionService
from acme_city.persistence.models import source
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import (
    SessionFactory,
    initialize_database,
    transaction,
)

BASE_APPLICATION = {
    "application_number": "SYN-APP-REG-01",
    "permit_type": "com_ti",
    "project_description": "A fictional interior tenant improvement.",
    "valuation": 9000.0,
    "valuation_cents": 900000,
    "submitted_site_text": "12 Marrow Creek Road, ACME City",
    "submitted_parcel": "ACME-P-1002",
}

REGRESSION_INPUTS: tuple[tuple[str, dict, str, str], ...] = (
    (
        "a setback that is a word",
        {**BASE_APPLICATION, "permit_type": "deck_fence", "structure_kind": "deck", "setback_ft": "twenty", "height_ft": 3.5},
        "setback_ft",
        "not_a_number",
    ),
    (
        "a setback that is not a finite number",
        {**BASE_APPLICATION, "permit_type": "deck_fence", "structure_kind": "deck", "setback_ft": "nan", "height_ft": 3.5},
        "setback_ft",
        "not_finite",
    ),
    (
        "a blank fence location",
        {**BASE_APPLICATION, "permit_type": "deck_fence", "structure_kind": "fence", "location": "", "height_ft": 4},
        "location",
        "conditional_required_field",
    ),
    (
        "an unsupported sign type",
        {
            **BASE_APPLICATION,
            "permit_type": "sign",
            "sign_type": "billboard",
            "sign_area_sqft": 1000,
            "illuminated": "no",
        },
        "sign_type",
        "unsupported_value",
    ),
)


@pytest.fixture()
def seeded(tmp_path: Path) -> Settings:
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'regression.db'}",
            "ACME_SECRET_KEY": "regression-test-secret-value",
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


@pytest.mark.parametrize(
    ("title", "payload", "field_path", "error_code"),
    REGRESSION_INPUTS,
    ids=[item[0] for item in REGRESSION_INPUTS],
)
def test_an_invalid_source_input_is_quarantined_with_an_explicit_error(
    seeded: Settings,
    title: str,
    payload: dict,
    field_path: str,
    error_code: str,
) -> None:
    del title
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            service = IngestionService(session)
            actor = ActorContext(actor_id="persona_data_steward")
            result = service.ingest(
                IngestCommand(
                    source_system_id="permitting",
                    dataset_key="applications_and_permits",
                    records=[
                        SourceRecordCommand(
                            source_record_id="PER-APP-REG-01",
                            source_record_version="1",
                            payload=dict(payload),
                        )
                    ],
                ),
                actor,
            )
            assert result.quarantined == 1, result.model_dump(mode="json")
            assert result.accepted == 0
            assert result.unchanged == 0
            matching = [
                error for error in result.field_errors if error.field_path == field_path
            ]
            assert matching, [error.model_dump() for error in result.field_errors]
            assert error_code in {error.error_code for error in matching}

            snapshot = session.execute(
                select(source.SourceSnapshot).where(
                    source.SourceSnapshot.source_record_id == "PER-APP-REG-01"
                )
            ).scalar_one()
            assert snapshot.record_status == "quarantined"
            assert snapshot.raw_payload == payload

            errors = session.execute(
                select(source.QuarantineError).where(
                    source.QuarantineError.source_snapshot_id == snapshot.source_snapshot_id
                )
            ).scalars().all()
            assert any(
                error.field_path == field_path and error.error_code == error_code
                for error in errors
            )
    finally:
        factory.dispose()


def test_no_invalid_input_becomes_an_accepted_value(seeded: Settings) -> None:
    factory = SessionFactory(seeded.database_url)
    try:
        with transaction(factory) as session:
            service = IngestionService(session)
            actor = ActorContext(actor_id="persona_data_steward")
            for index, (_title, payload, _field_path, _error_code) in enumerate(
                REGRESSION_INPUTS, start=1
            ):
                service.ingest(
                    IngestCommand(
                        source_system_id="permitting",
                        dataset_key="applications_and_permits",
                        records=[
                            SourceRecordCommand(
                                source_record_id=f"PER-APP-REG-{index:02d}",
                                source_record_version="1",
                                payload=dict(payload),
                            )
                        ],
                    ),
                    actor,
                )
            accepted = session.execute(
                select(source.SourceSnapshot).where(
                    source.SourceSnapshot.source_dataset_id == "applications_and_permits",
                    source.SourceSnapshot.source_record_id.like("PER-APP-REG-%"),
                    source.SourceSnapshot.record_status == "accepted",
                )
            ).scalars().all()
            assert accepted == []
    finally:
        factory.dispose()
