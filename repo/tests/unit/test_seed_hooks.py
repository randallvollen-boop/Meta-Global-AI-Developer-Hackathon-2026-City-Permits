"""Seed-hook registry tests: a registered hook runs once per reset, in name order."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import (
    ENVIRONMENT_ID,
    register_seed,
    registered_seeds,
    reset_demo,
    seeded_row_counts,
    unregister_seed,
)
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction


@pytest.fixture(scope="module")
def bundle() -> FixtureBundle:
    return FixtureBundle.load()


@pytest.fixture()
def factory(tmp_path: Path):
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'seed.db'}",
            "ACME_SECRET_KEY": "seed-hook-test-secret-value",
        },
        key_file=tmp_path / "missing.env",
    )
    initialize_database(settings)
    factory = SessionFactory(settings.database_url)
    with transaction(factory) as session:
        session.add(
            DemoEnvironment(
                id="demo_environment_local",
                environment_id=ENVIRONMENT_ID,
                fictional_demo=True,
                fixture_version=None,
                label="local fictional demonstration",
            )
        )
    try:
        yield factory
    finally:
        factory.dispose()


def reset(factory: SessionFactory, bundle: FixtureBundle) -> tuple[dict[str, int], dict[str, int]]:
    phrase = str(bundle.demo.reset["confirmation_phrase"])
    with transaction(factory) as session:
        result = reset_demo(session, bundle, confirmation=phrase)
    with factory() as session:
        return result.counts, seeded_row_counts(session)


#: The only modules that may register reset hooks (see :mod:`acme_city.fixtures.seed_plugins`).
LANE_SEED_MODULES = ("acme_city.agents.seed", "acme_city.registry.automation_seed")


def test_every_registered_hook_comes_from_a_lane_seed_module() -> None:
    from acme_city.fixtures import seed_plugins  # noqa: F401
    from acme_city.fixtures.reset import _SEED_HOOKS

    for name in registered_seeds():
        assert _SEED_HOOKS[name].__module__ in LANE_SEED_MODULES, name


def test_hook_counts_may_not_overwrite_reported_counts(
    factory: SessionFactory, bundle: FixtureBundle
) -> None:
    def clashing_seed(session: Session, seeded_bundle: FixtureBundle) -> dict[str, int]:
        return {"applications": 0}

    register_seed(clashing_seed, name="zz_clashing_seed")
    try:
        with pytest.raises(ValueError, match="applications"):
            reset(factory, bundle)
    finally:
        unregister_seed("zz_clashing_seed")


def test_registered_hook_runs_once_and_unregisters(
    factory: SessionFactory, bundle: FixtureBundle
) -> None:
    baseline_counts, baseline_rows = reset(factory, bundle)
    calls: list[tuple[Session, FixtureBundle]] = []

    def dummy_seed(session: Session, seeded_bundle: FixtureBundle) -> dict[str, int]:
        calls.append((session, seeded_bundle))
        return {"dummy_seed": 0}

    register_seed(dummy_seed, name="zz_dummy_seed")
    try:
        assert "zz_dummy_seed" in registered_seeds()
        counts, rows = reset(factory, bundle)
    finally:
        unregister_seed("zz_dummy_seed")

    assert len(calls) == 1
    assert calls[0][1] is bundle
    assert counts == {**baseline_counts, "dummy_seed": 0}
    assert rows == baseline_rows
    assert "zz_dummy_seed" not in registered_seeds()

    after_counts, after_rows = reset(factory, bundle)
    assert len(calls) == 1
    assert after_counts == baseline_counts
    assert after_rows == baseline_rows


def test_hooks_run_in_name_order_and_names_are_not_reused(
    factory: SessionFactory, bundle: FixtureBundle
) -> None:
    order: list[str] = []

    def second(session: Session, seeded_bundle: FixtureBundle) -> None:
        order.append("second")

    def first(session: Session, seeded_bundle: FixtureBundle) -> None:
        order.append("first")

    register_seed(second, name="zz_b")
    register_seed(first, name="zz_a")
    try:
        register_seed(first, name="zz_a")  # the same function again is a no-op
        with pytest.raises(ValueError):
            register_seed(second, name="zz_a")
        reset(factory, bundle)
    finally:
        unregister_seed("zz_a")
        unregister_seed("zz_b")
    assert order == ["first", "second"]
