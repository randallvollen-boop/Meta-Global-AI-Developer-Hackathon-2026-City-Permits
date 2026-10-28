"""Container entrypoint: apply the migrations once, then serve.

Environment:
    ACME_RUN_MIGRATIONS     "false" skips the upgrade (a separate job ran it).
    ACME_BIND_PORT          Listen port (default 8000).
    ACME_FORWARDED_ALLOW_IPS  Proxy addresses uvicorn trusts (default 127.0.0.1).

The service refuses to start in production mode without ACME_SECRET_KEY or
against a database marked as the fictional demo.
"""

from __future__ import annotations

import os
import subprocess
import sys


def main() -> int:
    if os.environ.get("ACME_RUN_MIGRATIONS", "true").lower() == "true":
        upgrade = subprocess.run(["alembic", "upgrade", "head"], check=False)
        if upgrade.returncode != 0:
            return upgrade.returncode
    os.execvp(
        "uvicorn",
        [
            "uvicorn",
            "acme_city.app:create_app",
            "--factory",
            "--host",
            "0.0.0.0",
            "--port",
            os.environ.get("ACME_BIND_PORT", "8000"),
            "--no-access-log",
            "--proxy-headers",
            "--forwarded-allow-ips",
            os.environ.get("ACME_FORWARDED_ALLOW_IPS", "127.0.0.1"),
        ],
    )
    return 1  # pragma: no cover - execvp does not return


if __name__ == "__main__":
    sys.exit(main())
