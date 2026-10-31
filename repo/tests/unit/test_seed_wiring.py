"""The seed wiring: the demonstration keeps what it was and gains samples.

Two things are optional now: the reset script can prepare the sample intake
cases of the demonstration, and the container seed can ask for them.  Without
either of them the demonstration is exactly the one there was, so the tests
pin the default as firmly as they pin the sample cases.

The reset script is run the way the container runs it, and the database it
leaves behind is read back.

Fictional ACME City data only.
"""
# REQUIRES: ING-01, ING-02, PER-01
# The sample cases are created through the governed intake path, and the
# demonstration without them is unchanged.

from __future__ import annotations

import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

from acme_city.auth.context import ActorContext
from acme_city.core.config import Settings
from acme_city.fixtures.loader import FixtureBundle
from acme_city.fixtures.reset import ENVIRONMENT_ID, reset_demo, seeded_row_counts
from acme_city.persistence.models import audit as audit_models
from acme_city.persistence.models import permit, source
from acme_city.persistence.models.governance import DemoEnvironment
from acme_city.persistence.session import SessionFactory, initialize_database, transaction
from acme_city.portal_intake.service import (
    DATASET_KEY,
    SOURCE_SYSTEM_ID,
    IntakeService,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RESET_SCRIPT = REPO_ROOT / "scripts" / "reset_demo.py"
ENTRYPOINT = REPO_ROOT / "docker" / "entrypoint.py"

#: The portal references the sample cases carry.
GENERATED_PREFIX = "PORTAL-2026-GEN"


def container_entrypoint() -> object:
    """Return the module of the container entrypoint."""
    spec = importlib.util.spec_from_file_location(
        "_acme_container_entrypoint", ENTRYPOINT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def entrypoint() -> object:
    """Return the module of the container entrypoint."""
    return container_entrypoint()


@pytest.fixture()
def seeded_database(tmp_path: Path) -> Path:
    """Return a database the demonstration was seeded into."""
    database = tmp_path / "seeded.db"
    settings = Settings.load(
        environ={
            "ACME_DATABASE_URL": database_url(database),
            "ACME_SECRET_KEY": "seed-wiring-secret-value",
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
    return database


def run_reset(arguments: list[str], tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Run the reset script against a scratch database.

    The working directory is the scratch directory, so the documents of the
    sample cases are written there and never into the repository.
    """
    environment = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "ACME_SECRET_KEY": "seed-wiring-secret-value",
        "ACME_KEY_FILE": str(tmp_path / "missing.env"),
    }
    return subprocess.run(
        [sys.executable, str(RESET_SCRIPT), *arguments],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=environment,
        check=False,
    )


def database_url(path: Path) -> str:
    """Return the database URL of a scratch database."""
    return f"sqlite:///{path}"


def row_counts(path: Path) -> dict[str, int]:
    """Return the row count of every table of a scratch database."""
    factory = SessionFactory(database_url(path))
    try:
        with factory() as session:
            return seeded_row_counts(session)
    finally:
        factory.dispose()


def generated_references(path: Path) -> list[str]:
    """Return the portal references of the sample cases of a scratch database."""
    factory = SessionFactory(database_url(path))
    try:
        with factory() as session:
            rows = session.execute(
                select(source.SourceSnapshot.source_record_id).where(
                    source.SourceSnapshot.source_system_id == SOURCE_SYSTEM_ID,
                    source.SourceSnapshot.source_dataset_id == DATASET_KEY,
                )
            ).scalars().all()
    finally:
        factory.dispose()
    return sorted(row for row in rows if row.startswith(GENERATED_PREFIX))


def sample_applications(path: Path) -> list[permit.Application]:
    """Return the cases the sample cases of a scratch database created."""
    references = set(generated_references(path))
    factory = SessionFactory(database_url(path))
    try:
        with factory() as session:
            rows = session.execute(select(permit.Application)).scalars().all()
            return [
                row
                for row in rows
                if str((row.submitted_facts or {}).get("portal_reference") or "")
                in references
            ]
    finally:
        factory.dispose()


def audit_events(path: Path, action: str) -> list[audit_models.AuditEvent]:
    """Return the audit events of one action of a scratch database."""
    factory = SessionFactory(database_url(path))
    try:
        with factory() as session:
            return list(
                session.execute(
                    select(audit_models.AuditEvent).where(
                        audit_models.AuditEvent.action == action
                    )
                ).scalars().all()
            )
    finally:
        factory.dispose()


# ------------------------------------------------------- the container seed


def test_the_container_seed_asks_for_no_sample_cases_by_default(entrypoint) -> None:
    assert entrypoint.generated_count({}) == 0
    assert entrypoint.generated_count({"ACME_DEMO_GENERATED_COUNT": ""}) == 0
    assert entrypoint.generated_count({"ACME_DEMO_GENERATED_COUNT": "6"}) == 6


def test_the_container_seed_is_the_three_steps_it_always_were(entrypoint) -> None:
    steps = entrypoint.seed_commands("sqlite:////app/var/x.db", "18266")
    assert [Path(step[1]).name for step in steps] == [
        "prepare_user_test.py",
        "load_synthetic_year.py",
        "load_steward_demo.py",
    ]


def test_the_container_seed_adds_a_fourth_step_for_the_sample_cases(entrypoint) -> None:
    steps = entrypoint.seed_commands("sqlite:////app/var/x.db", "18266", 6)
    assert [Path(step[1]).name for step in steps] == [
        "prepare_user_test.py",
        "load_synthetic_year.py",
        "load_steward_demo.py",
        "reset_demo.py",
    ]
    fourth = steps[3]
    assert fourth[fourth.index("--generated") + 1] == "6"
    assert fourth[fourth.index("--generated-seed") + 1] == entrypoint.GENERATED_SEED
    # The fourth step only adds the cases: it never resets the demonstration.
    assert "--add-generated" in fourth
    assert "--confirm-fictional-demo" in fourth


def test_the_container_seed_runs_the_fourth_step(
    entrypoint, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "scripts").mkdir()
    monkeypatch.setattr(entrypoint, "SCRIPTS", tmp_path / "scripts")
    monkeypatch.setattr(entrypoint, "APP_ROOT", tmp_path)
    calls: list[list[str]] = []

    class Done:
        returncode = 0

    monkeypatch.setattr(
        entrypoint.subprocess,
        "run",
        lambda cmd, **kw: calls.append(cmd) or Done(),
    )
    environment = {
        "ACME_DATABASE_URL": f"sqlite:///{tmp_path / 'seed.db'}",
        "ACME_DEPLOYMENT_MODE": "demo",
        "ACME_DEMO_GENERATED_COUNT": "4",
    }
    assert entrypoint.seed_demo(environment) == 0
    assert [Path(command[1]).name for command in calls] == [
        "prepare_user_test.py",
        "load_synthetic_year.py",
        "load_steward_demo.py",
        "reset_demo.py",
    ]
    assert calls[3][calls[3].index("--generated") + 1] == "4"


def test_a_sample_count_that_is_not_a_whole_number_is_refused(
    entrypoint, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "scripts").mkdir()
    monkeypatch.setattr(entrypoint, "SCRIPTS", tmp_path / "scripts")
    monkeypatch.setattr(entrypoint, "APP_ROOT", tmp_path)
    database = tmp_path / "seed.db"
    database.write_text("the demonstration")

    class Done:
        returncode = 0

    monkeypatch.setattr(entrypoint.subprocess, "run", lambda cmd, **kw: Done())
    environment = {
        "ACME_DATABASE_URL": f"sqlite:///{database}",
        "ACME_DEPLOYMENT_MODE": "demo",
        "ACME_DEMO_GENERATED_COUNT": "six",
    }
    assert entrypoint.seed_demo(environment) == 2
    # The database is untouched: the count is refused before anything runs.
    assert database.read_text() == "the demonstration"


# ------------------------------------------------------------- the reset


def test_the_reset_without_the_flag_creates_no_sample_cases(tmp_path: Path) -> None:
    database = tmp_path / "plain.db"
    result = run_reset(
        ["--database", database_url(database), "--confirm-fictional-demo"], tmp_path
    )
    assert result.returncode == 0, result.stderr
    assert "generated_applications" not in result.stdout
    assert generated_references(database) == []


def test_the_seeded_row_counts_are_unchanged_with_no_sample_cases(
    tmp_path: Path,
) -> None:
    """The reset without sample cases seeds exactly what it always seeded."""
    plain = tmp_path / "plain.db"
    zero = tmp_path / "zero.db"
    for database in (plain, zero):
        result = run_reset(
            ["--database", database_url(database), "--confirm-fictional-demo"],
            tmp_path,
        )
        assert result.returncode == 0, result.stderr
    assert row_counts(zero) == row_counts(plain)
    assert set(row_counts(zero)) == set(row_counts(plain))


def test_the_reset_creates_the_sample_cases(tmp_path: Path) -> None:
    database = tmp_path / "generated.db"
    result = run_reset(
        [
            "--database",
            database_url(database),
            "--confirm-fictional-demo",
            "--generated",
            "6",
            "--generated-seed",
            "3",
        ],
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "generated_applications: 6" in result.stdout
    assert generated_references(database) == [
        f"{GENERATED_PREFIX}-seed3-{index:02d}" for index in range(1, 7)
    ]


def test_the_same_seed_builds_the_same_sample_cases(tmp_path: Path) -> None:
    """The same seed builds the same references, so the demo is repeatable."""
    first = tmp_path / "first.db"
    second = tmp_path / "second.db"
    for database in (first, second):
        result = run_reset(
            [
                "--database",
                database_url(database),
                "--confirm-fictional-demo",
                "--generated",
                "6",
                "--generated-seed",
                "3",
            ],
            tmp_path,
        )
        assert result.returncode == 0, result.stderr
    assert generated_references(first) == generated_references(second)


def test_the_sample_cases_wait_for_the_intake_agent(tmp_path: Path) -> None:
    database = tmp_path / "generated.db"
    result = run_reset(
        [
            "--database",
            database_url(database),
            "--confirm-fictional-demo",
            "--generated",
            "6",
            "--generated-seed",
            "3",
        ],
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    applications = sample_applications(database)
    assert len(applications) == 6
    assert {row.status for row in applications} == {"submitted"}
    # A sample case waits for a person: it carries no scenario id.
    assert {row.scenario_id for row in applications} == {None}


def test_the_sample_cases_write_their_audit_rows(tmp_path: Path) -> None:
    database = tmp_path / "generated.db"
    result = run_reset(
        [
            "--database",
            database_url(database),
            "--confirm-fictional-demo",
            "--generated",
            "6",
            "--generated-seed",
            "3",
        ],
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    batches = audit_events(database, "intake.generate")
    assert len(batches) == 1
    assert batches[0].actor_id == "persona_city_administrator"
    assert len(batches[0].references) == 6
    submits = audit_events(database, "intake.record.submit")
    assert len(submits) == 6


def test_adding_the_sample_cases_keeps_the_rest_of_the_demonstration(
    tmp_path: Path,
) -> None:
    """The fourth step of the container only adds: it never resets."""
    database = tmp_path / "added.db"
    result = run_reset(
        ["--database", database_url(database), "--confirm-fictional-demo"], tmp_path
    )
    assert result.returncode == 0, result.stderr
    before = row_counts(database)

    result = run_reset(
        [
            "--database",
            database_url(database),
            "--confirm-fictional-demo",
            "--generated",
            "3",
            "--add-generated",
        ],
        tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "generated_applications: 3" in result.stdout
    after = row_counts(database)
    assert after["applications"] == before["applications"] + 3
    assert after["source_snapshots"] == before["source_snapshots"] + 3
    assert after["permit_types"] == before["permit_types"]
    assert after["actors"] == before["actors"]
    assert after["steward_queues"] == before["steward_queues"]


def test_adding_the_sample_cases_twice_adds_nothing(tmp_path: Path) -> None:
    """The same references are already there, so the second run adds nothing."""
    database = tmp_path / "twice.db"
    reset = run_reset(
        ["--database", database_url(database), "--confirm-fictional-demo"], tmp_path
    )
    assert reset.returncode == 0, reset.stderr
    arguments = [
        "--database",
        database_url(database),
        "--confirm-fictional-demo",
        "--generated",
        "3",
        "--add-generated",
    ]
    assert run_reset(arguments, tmp_path).returncode == 0
    result = run_reset(arguments, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "generated_applications: 0" in result.stdout
    assert "generated_duplicates: 3" in result.stdout
    assert len(generated_references(database)) == 3


def test_adding_the_sample_cases_refuses_a_database_that_is_not_the_demo(
    tmp_path: Path,
) -> None:
    database = tmp_path / "other.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE unrelated_record (id INTEGER PRIMARY KEY)")
    result = run_reset(
        [
            "--database",
            database_url(database),
            "--confirm-fictional-demo",
            "--generated",
            "3",
            "--add-generated",
        ],
        tmp_path,
    )
    assert result.returncode == 3
    assert "not a marked demo" in result.stderr
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert tables == {"unrelated_record"}


def test_adding_the_sample_cases_refuses_a_database_that_does_not_exist(
    tmp_path: Path,
) -> None:
    database = tmp_path / "missing.db"
    result = run_reset(
        [
            "--database",
            database_url(database),
            "--confirm-fictional-demo",
            "--generated",
            "3",
            "--add-generated",
        ],
        tmp_path,
    )
    assert result.returncode == 3
    assert "does not exist" in result.stderr
    assert not database.exists()


def test_more_sample_cases_than_the_cap_are_refused(tmp_path: Path) -> None:
    database = tmp_path / "too-many.db"
    result = run_reset(
        [
            "--database",
            database_url(database),
            "--confirm-fictional-demo",
            "--generated",
            "21",
        ],
        tmp_path,
    )
    assert result.returncode == 2
    assert "at most 20" in result.stderr
    assert not database.exists()


def test_the_total_cap_of_the_sample_cases_is_refused(
    seeded_database: Path, tmp_path: Path
) -> None:
    """The seed refuses to pass the total the demonstration already holds."""
    factory = SessionFactory(database_url(seeded_database))
    try:
        with transaction(factory) as session:
            administrator = ActorContext(
                actor_id="persona_city_administrator",
                role_ids=frozenset({"governance_lead"}),
            )
            service = IntakeService(session, document_root=tmp_path / "documents")
            for batch in range(10):
                service.generate_cases(
                    seed=batch, count=20, nonce=f"batch{batch}", actor=administrator
                )
    finally:
        factory.dispose()
    result = run_reset(
        [
            "--database",
            database_url(seeded_database),
            "--confirm-fictional-demo",
            "--generated",
            "1",
            "--add-generated",
        ],
        tmp_path,
    )
    assert result.returncode == 1
    assert "refusing to seed" in result.stderr
    assert "200" in result.stderr
    assert len(generated_references(seeded_database)) == 200


def test_a_negative_number_of_sample_cases_is_refused(tmp_path: Path) -> None:
    database = tmp_path / "negative.db"
    result = run_reset(
        [
            "--database",
            database_url(database),
            "--confirm-fictional-demo",
            "--generated",
            "-1",
        ],
        tmp_path,
    )
    assert result.returncode == 2
    assert "cannot be negative" in result.stderr
    assert not database.exists()
