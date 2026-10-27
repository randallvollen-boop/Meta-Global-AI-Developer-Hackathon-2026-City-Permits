"""Safe settings loading for the ACME City application.

Settings come from the process environment first and, secondarily, from the
local ignored key file (``~/.config/ai-keys.env`` by default).  The environment
always wins.  Secret values are held in :class:`pydantic.SecretStr` fields so
they cannot leak through ``repr``, ``str``, model dumps, logs or API payloads.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, SecretStr, field_validator

DEFAULT_DATABASE_URL: Final = "sqlite:///var/acme_city.db"
DEFAULT_KEY_FILE: Final = Path("~/.config/ai-keys.env")
DEFAULT_DEMO_TIMEZONE: Final = "America/New_York"
DEFAULT_MUSE_MODEL_ALLOWLIST: Final = ("muse-spark-1.3",)
DEFAULT_MUSE_LIVE_CALL_CAP: Final = 2
DEFAULT_EVIDENCE_ROOT: Final = Path("evidence/runs")
DEFAULT_MUSE_IMAGE_DAILY_CAP: Final = 10

#: Names that may be read from the local key file.  Nothing else is consumed
#: from that file, so unrelated personal secrets never enter the process.
KEY_FILE_ALLOWED_NAMES: Final = frozenset({"META_API_KEY", "ACME_SECRET_KEY"})

#: Environment variables that may override a setting.
ENV_DATABASE_URL: Final = "ACME_DATABASE_URL"
ENV_SECRET_KEY: Final = "ACME_SECRET_KEY"
ENV_DEMO_TIMEZONE: Final = "ACME_DEMO_TIMEZONE"
ENV_MUSE_ALLOWLIST: Final = "ACME_MUSE_MODEL_ALLOWLIST"
ENV_MUSE_LIVE_CALL_CAP: Final = "ACME_MUSE_LIVE_CALL_CAP"
ENV_MUSE_IMAGE_DAILY_CAP: Final = "ACME_MUSE_IMAGE_DAILY_CAP"
ENV_EVIDENCE_ROOT: Final = "ACME_EVIDENCE_ROOT"
ENV_KEY_FILE: Final = "ACME_KEY_FILE"
ENV_META_API_KEY: Final = "META_API_KEY"

#: Model suffixes that may never be selected, in any configuration.
FORBIDDEN_MODEL_MARKERS: Final = ("-contributor",)

_KEY_LINE = re.compile(r"^(?:export\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.*)$")
_PREFIX = re.compile(r"^\s*(?:export\s+)?")


def parse_key_file(text: str) -> dict[str, str]:
    """Parse ``KEY=value`` lines from a local key file.

    The parser is deliberately inert: it never executes, expands, or evaluates
    anything, and it ignores every name that is not explicitly allowlisted.
    Quoted values are unwrapped; trailing comments after an unquoted value are
    dropped.  Values are returned to the caller and are never logged.
    """
    parsed: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _KEY_LINE.match(line)
        if match is None:
            continue
        name = match.group("name")
        if name not in KEY_FILE_ALLOWED_NAMES:
            continue
        value = match.group("value").strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        parsed[name] = value
    return parsed


def read_key_file(path: Path) -> dict[str, str]:
    """Read allowlisted values from ``path``; a missing or unreadable file is empty."""
    try:
        text = path.expanduser().read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    return parse_key_file(text)


class Settings(BaseModel):
    """Immutable application settings.

    ``secret_key`` signs server-held session cookies.  ``meta_api_key`` is the
    server-side provider credential; it is never sent to a browser, logged, or
    included in any serialized representation of these settings.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    database_url: str = DEFAULT_DATABASE_URL
    secret_key: SecretStr
    demo_timezone: str = DEFAULT_DEMO_TIMEZONE
    muse_model_allowlist: tuple[str, ...] = DEFAULT_MUSE_MODEL_ALLOWLIST
    muse_live_call_cap: int = DEFAULT_MUSE_LIVE_CALL_CAP
    muse_image_daily_cap: int = DEFAULT_MUSE_IMAGE_DAILY_CAP
    evidence_root: Path = Path(DEFAULT_EVIDENCE_ROOT)
    meta_api_key: SecretStr | None = None
    key_file: Path | None = None
    secret_is_ephemeral: bool = False

    @field_validator("secret_key")
    @classmethod
    def _secret_not_empty(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 16:
            raise ValueError("secret_key must be at least 16 characters")
        return value

    @field_validator("demo_timezone")
    @classmethod
    def _timezone_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("demo_timezone must not be empty")
        return value.strip()

    @field_validator("muse_model_allowlist")
    @classmethod
    def _allowlist_is_safe(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("muse_model_allowlist must not be empty")
        seen: set[str] = set()
        for model in value:
            normalized = model.strip()
            if not normalized:
                raise ValueError("muse_model_allowlist entries must not be blank")
            lowered = normalized.lower()
            if any(marker in lowered for marker in FORBIDDEN_MODEL_MARKERS):
                raise ValueError(
                    f"model {normalized!r} is not permitted: contributor variants are never used"
                )
            if lowered in seen:
                raise ValueError(f"duplicate muse model {normalized!r} in allowlist")
            seen.add(lowered)
        return tuple(model.strip() for model in value)

    @field_validator("muse_live_call_cap")
    @classmethod
    def _cap_is_positive(cls, value: int) -> int:
        if value < 0:
            raise ValueError("muse_live_call_cap must not be negative")
        return value

    @field_validator("muse_image_daily_cap")
    @classmethod
    def _image_cap_is_positive(cls, value: int) -> int:
        if value < 0:
            raise ValueError("muse_image_daily_cap must not be negative")
        return value

    def model_is_allowed(self, model: str) -> bool:
        """Return whether ``model`` may be selected for a live call."""
        normalized = model.strip().lower()
        if any(marker in normalized for marker in FORBIDDEN_MODEL_MARKERS):
            return False
        return normalized in {entry.lower() for entry in self.muse_model_allowlist}

    def safe_summary(self) -> dict[str, Any]:
        """Return a log-safe summary that contains no secret and no local path."""
        return {
            "database_scheme": self.database_url.split(":", 1)[0],
            "demo_timezone": self.demo_timezone,
            "muse_model_allowlist": list(self.muse_model_allowlist),
            "muse_live_call_cap": self.muse_live_call_cap,
            "secret_is_ephemeral": self.secret_is_ephemeral,
            "meta_api_key_present": self.meta_api_key is not None,
        }

    @classmethod
    def load(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        key_file: Path | None = None,
        secret_key: str | None = None,
    ) -> Settings:
        """Load settings from the environment and the local key file.

        Precedence is environment, then key file, then built-in default.  The
        environment always wins over the key file.
        """
        env = os.environ if environ is None else environ

        resolved_key_file = key_file
        if resolved_key_file is None:
            configured = env.get(ENV_KEY_FILE)
            resolved_key_file = Path(configured) if configured else DEFAULT_KEY_FILE
        file_values = read_key_file(resolved_key_file) if resolved_key_file else {}

        def pick(name: str, default: str | None = None) -> str | None:
            value = env.get(name)
            if value is not None:
                return value
            return file_values.get(name, default)

        database_url = pick(ENV_DATABASE_URL, DEFAULT_DATABASE_URL) or DEFAULT_DATABASE_URL
        demo_timezone = pick(ENV_DEMO_TIMEZONE, DEFAULT_DEMO_TIMEZONE) or DEFAULT_DEMO_TIMEZONE
        evidence_root = Path(pick(ENV_EVIDENCE_ROOT, str(DEFAULT_EVIDENCE_ROOT)))

        allowlist_raw = pick(ENV_MUSE_ALLOWLIST)
        if allowlist_raw is None:
            muse_model_allowlist = DEFAULT_MUSE_MODEL_ALLOWLIST
        else:
            muse_model_allowlist = tuple(
                part.strip() for part in allowlist_raw.split(",") if part.strip()
            )

        cap_raw = pick(ENV_MUSE_LIVE_CALL_CAP)
        muse_live_call_cap = (
            DEFAULT_MUSE_LIVE_CALL_CAP if cap_raw is None else int(cap_raw)
        )

        image_cap_raw = pick(ENV_MUSE_IMAGE_DAILY_CAP)
        muse_image_daily_cap = (
            DEFAULT_MUSE_IMAGE_DAILY_CAP if image_cap_raw is None else int(image_cap_raw)
        )

        meta_api_key_raw = pick(ENV_META_API_KEY)
        meta_api_key = SecretStr(meta_api_key_raw) if meta_api_key_raw else None

        resolved_secret = secret_key or pick(ENV_SECRET_KEY)
        ephemeral = False
        if not resolved_secret:
            import secrets as _secrets

            resolved_secret = _secrets.token_urlsafe(48)
            ephemeral = True

        return cls(
            database_url=database_url,
            secret_key=SecretStr(resolved_secret),
            demo_timezone=demo_timezone,
            muse_model_allowlist=muse_model_allowlist,
            muse_live_call_cap=muse_live_call_cap,
            muse_image_daily_cap=muse_image_daily_cap,
            evidence_root=evidence_root,
            meta_api_key=meta_api_key,
            key_file=resolved_key_file,
            secret_is_ephemeral=ephemeral,
        )


__all__ = [
    "DEFAULT_DATABASE_URL",
    "DEFAULT_DEMO_TIMEZONE",
    "DEFAULT_EVIDENCE_ROOT",
    "DEFAULT_KEY_FILE",
    "DEFAULT_MUSE_LIVE_CALL_CAP",
    "DEFAULT_MUSE_IMAGE_DAILY_CAP",
    "DEFAULT_MUSE_MODEL_ALLOWLIST",
    "KEY_FILE_ALLOWED_NAMES",
    "Settings",
    "parse_key_file",
    "read_key_file",
]
