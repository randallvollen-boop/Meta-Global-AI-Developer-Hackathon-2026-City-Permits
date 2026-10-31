"""Container entrypoint: apply the migrations once, optionally seed, then serve.

Environment:
    ACME_RUN_MIGRATIONS     "false" skips the upgrade (a separate job ran it).
    PORT                    Listen port set by the host (Render).  Wins when set.
    ACME_BIND_PORT          Listen port when PORT is not set (default 8000).
    ACME_FORWARDED_ALLOW_IPS  Proxy addresses uvicorn trusts (default 127.0.0.1).
    ACME_DEMO_SEED_ON_START "1" rebuilds the fictional demonstration data before
                            serving (demo image only; refused in production mode).
    ACME_DEMO_GENERATED_COUNT  How many sample intake cases the seed adds (default 0,
                            none).
    ACME_SEED_PORT          Loopback port of the short-lived server the seeding
                            walkthrough uses (default 18266).

The service refuses to start in production mode without ACME_SECRET_KEY or
against a database marked as the fictional demo.

With seeding, the demonstration database file is deleted first and rebuilt (the
reset step creates, migrates and marks it); the upgrade to head then runs as a
check.  Seeding prepares the same state as the local demonstration: the
"ready-for-review" case, the synthetic year (seed 20261028, 600 permits) and the
steward demo.  A fourth step adds the sample intake cases when
ACME_DEMO_GENERATED_COUNT asks for them; without it the seed is exactly the
three steps it always was.  Each start therefore begins from one labelled
fictional dataset.  A failed step stops the start with a non-zero exit, so the
host keeps the previous deploy running.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

#: /app in the image; ACME_APP_ROOT lets a test point elsewhere.
APP_ROOT = Path(os.environ.get("ACME_APP_ROOT") or Path(__file__).resolve().parent)
SCRIPTS = APP_ROOT / "scripts"
DEFAULT_DATABASE = "sqlite:////app/var/acme_city.db"
SYNTHETIC_SEED = "20261028"
SYNTHETIC_COUNT = "600"
#: The seed the sample intake cases are built from.
GENERATED_SEED = "20261031"
_TRUE = frozenset({"1", "true", "yes", "on"})

#: Settings the seeding steps must not inherit: they start a short-lived server on
#: loopback and call it over plain HTTP, so Secure cookies, request limits and any
#: live provider credential would break or endanger the run.
_SEED_ENV_UNSET = ("META_API_KEY", "ACME_MUSE_PROVIDER_ENABLED", "ACME_TRUST_PROXY_HEADERS")
_SEED_ENV_OVERRIDES = {
    "ACME_COOKIE_SECURE": "0",
    "ACME_RATE_LIMIT_ALL_PER_MINUTE": "0",
    "ACME_RATE_LIMIT_WRITE_PER_MINUTE": "0",
    "ACME_RATE_LIMIT_SESSION_PER_MINUTE": "0",
    "ACME_RATE_LIMIT_UPLOAD_PER_MINUTE": "0",
    "ACME_SCENARIO_CLOCK": "auto",
}


def listen_port(environ: dict[str, str] | None = None) -> str:
    """Return the port to listen on: PORT, then ACME_BIND_PORT, then 8000."""
    env = os.environ if environ is None else environ
    for name in ("PORT", "ACME_BIND_PORT"):
        value = env.get(name, "").strip()
        if value:
            return value
    return "8000"


def seed_requested(environ: dict[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return env.get("ACME_DEMO_SEED_ON_START", "").strip().lower() in _TRUE


def generated_count(environ: dict[str, str] | None = None) -> int:
    """Return how many sample intake cases the seed adds.

    The demonstration asks for none unless ``ACME_DEMO_GENERATED_COUNT`` says
    so, so the seed stays the three commands it always was.
    """
    env = os.environ if environ is None else environ
    raw = env.get("ACME_DEMO_GENERATED_COUNT", "").strip()
    if not raw:
        return 0
    try:
        count = int(raw)
    except ValueError as error:
        raise ValueError(
            "ACME_DEMO_GENERATED_COUNT must be a whole number"
        ) from error
    if count < 0:
        raise ValueError("ACME_DEMO_GENERATED_COUNT cannot be negative")
    return count


def seed_commands(
    database: str, seed_port: str, generated: int = 0
) -> list[list[str]]:
    """Return the seeding commands, in order.

    The first three commands prepare the demonstration as it always was.  A
    fourth command adds the sample intake cases when the demonstration asks
    for them; it only adds them, so the steps before it keep their work.
    """
    python = sys.executable
    commands = [
        [
            python, str(SCRIPTS / "prepare_user_test.py"),
            "--mode", "ready-for-review",
            "--database", database,
            "--port", seed_port,
        ],
        [
            python, str(SCRIPTS / "load_synthetic_year.py"),
            "--database", database,
            "--seed", SYNTHETIC_SEED,
            "--count", SYNTHETIC_COUNT,
            "--confirm-fictional-demo",
        ],
        [
            python, str(SCRIPTS / "load_steward_demo.py"),
            "--database", database,
            "--confirm-fictional-demo",
        ],
    ]
    if generated:
        commands.append(
            [
                python, str(SCRIPTS / "reset_demo.py"),
                "--database", database,
                "--generated", str(generated),
                "--generated-seed", GENERATED_SEED,
                "--add-generated",
                "--confirm-fictional-demo",
            ]
        )
    return commands


def clear_database(database: str) -> None:
    """Delete a SQLite demonstration database file so the seed starts from nothing.

    The reset script accepts an empty database or one it marked itself, never a
    migrated but unmarked one, so the seed creates, migrates and marks the file.
    """
    from sqlalchemy.engine import make_url

    url = make_url(database)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return
    for suffix in ("", "-wal", "-shm", "-journal"):
        Path(url.database + suffix).unlink(missing_ok=True)


def seed_demo(environ: dict[str, str] | None = None) -> int:
    """Rebuild the fictional demonstration data; return a process exit code."""
    env = dict(os.environ if environ is None else environ)
    if env.get("ACME_DEPLOYMENT_MODE", "demo").strip().lower() == "production":
        print("entrypoint: ACME_DEMO_SEED_ON_START is refused in production mode", file=sys.stderr)
        return 2
    if not SCRIPTS.is_dir():
        print("entrypoint: this image has no demonstration scripts; use the demo target", file=sys.stderr)
        return 2
    database = env.setdefault("ACME_DATABASE_URL", DEFAULT_DATABASE)
    try:
        generated = generated_count(env)
    except ValueError as error:
        print(f"entrypoint: {error}", file=sys.stderr)
        return 2
    clear_database(database)
    for name in _SEED_ENV_UNSET:
        env.pop(name, None)
    env.update(_SEED_ENV_OVERRIDES)
    commands = seed_commands(
        database, env.get("ACME_SEED_PORT", "18266"), generated
    )
    for command in commands:
        print(f"entrypoint: seeding step {Path(command[1]).name}", flush=True)
        result = subprocess.run(command, cwd=APP_ROOT, env=env, check=False)
        if result.returncode != 0:
            print(f"entrypoint: {Path(command[1]).name} failed with exit {result.returncode}", file=sys.stderr)
            return result.returncode
    print("entrypoint: fictional demonstration data is ready", flush=True)
    return 0


def migrate() -> int:
    if os.environ.get("ACME_RUN_MIGRATIONS", "true").lower() != "true":
        return 0
    return subprocess.run(["alembic", "upgrade", "head"], check=False).returncode


def main() -> int:
    if seed_requested():
        # The seed creates and migrates a fresh database itself; the upgrade below
        # then confirms it is at the head.
        seeded = seed_demo()
        if seeded != 0:
            return seeded
    upgraded = migrate()
    if upgraded != 0:
        return upgraded
    os.execvp(
        "uvicorn",
        [
            "uvicorn",
            "acme_city.app:create_app",
            "--factory",
            "--host",
            "0.0.0.0",
            "--port",
            listen_port(),
            "--no-access-log",
            "--proxy-headers",
            "--forwarded-allow-ips",
            os.environ.get("ACME_FORWARDED_ALLOW_IPS", "127.0.0.1"),
        ],
    )
    return 1  # pragma: no cover - execvp does not return


if __name__ == "__main__":
    sys.exit(main())
