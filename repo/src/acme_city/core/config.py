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
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, SecretStr, field_validator, model_validator

from acme_city.core.config_autolink import AutolinkSettings, autolink_env_overrides
from acme_city.core.config_operator import OperatorSettings, operator_env_overrides

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
#: ``auto`` (derive the demo date from the seeded data), an ISO date
#: (``2026-10-14``) or empty (the real clock, the default).
ENV_SCENARIO_CLOCK: Final = "ACME_SCENARIO_CLOCK"
ENV_KEY_FILE: Final = "ACME_KEY_FILE"
ENV_GIS_BASE_URL: Final = "ACME_GIS_BASE_URL"
ENV_GIS_AUTO_PROPOSE_SCORE: Final = "ACME_GIS_AUTO_PROPOSE_SCORE"
ENV_APPLICANT_ASSIST_LIVE: Final = "ACME_APPLICANT_ASSIST_LIVE_ENABLED"
ENV_POLICY_ASSIST_LIVE: Final = "ACME_POLICY_ASSIST_LIVE_ENABLED"
#: Pre-submit feedback on Check my application.  Off by default.  A credential
#: alone never turns it on.
ENV_PRESUBMIT_REVIEW_LIVE: Final = "ACME_PRESUBMIT_REVIEW_LIVE_ENABLED"
#: ``demo`` (the default; the fictional demonstration, unchanged) or ``production``.
ENV_DEPLOYMENT_MODE: Final = "ACME_DEPLOYMENT_MODE"
#: Whether the session cookie carries the ``Secure`` attribute.  Unset means on
#: in production and off in demo.
ENV_COOKIE_SECURE: Final = "ACME_COOKIE_SECURE"
#: Whether ``X-Forwarded-Proto`` from a reverse proxy is trusted.  Off by default.
ENV_TRUST_PROXY_HEADERS: Final = "ACME_TRUST_PROXY_HEADERS"
#: The global switch for every call to the external AI provider.  Unset means
#: allowed in demo and denied in production.
ENV_MUSE_PROVIDER_ENABLED: Final = "ACME_MUSE_PROVIDER_ENABLED"

#: Public-demo protection.  Each limit is requests per minute per client address;
#: ``0`` switches that limit off (the default, so tests and the local demo are
#: unaffected).  ``render.yaml`` turns them on.
ENV_RATE_LIMIT_ALL: Final = "ACME_RATE_LIMIT_ALL_PER_MINUTE"
ENV_RATE_LIMIT_WRITE: Final = "ACME_RATE_LIMIT_WRITE_PER_MINUTE"
ENV_RATE_LIMIT_SESSION: Final = "ACME_RATE_LIMIT_SESSION_PER_MINUTE"
ENV_RATE_LIMIT_UPLOAD: Final = "ACME_RATE_LIMIT_UPLOAD_PER_MINUTE"
#: Extra trusted proxy hops on the right of ``X-Forwarded-For`` (see core/ratelimit.py).
ENV_TRUSTED_PROXY_HOPS: Final = "ACME_TRUSTED_PROXY_HOPS"
#: Largest accepted request body in bytes; ``0`` switches the check off.
ENV_MAX_REQUEST_BYTES: Final = "ACME_MAX_REQUEST_BYTES"
DEFAULT_MAX_REQUEST_BYTES: Final = 32 * 1024 * 1024
#: Show the public-demonstration notice on the persona chooser and the City home.
ENV_PUBLIC_DEMO: Final = "ACME_PUBLIC_DEMO"

DEPLOYMENT_MODES: Final = ("demo", "production")
_TRUE_VALUES: Final = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES: Final = frozenset({"0", "false", "no", "off"})


def _optional_bool(raw: str | None, name: str) -> bool | None:
    """Parse an optional boolean setting; unset stays ``None``."""
    if raw is None or not raw.strip():
        return None
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise ValueError(f"{name} must be one of 1, true, yes, on, 0, false, no, off")

#: The locator score at or above which the intake agent auto-proposes a parcel
#: link (it never auto-approves one).
DEFAULT_GIS_AUTO_PROPOSE_SCORE: Final = 90
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


class Settings(OperatorSettings, AutolinkSettings, BaseModel):
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
    #: The base URL of the ArcGIS REST ``ACME`` folder.  Empty means the
    #: in-app simulator.  Pointing this at a real server needs a field map
    #: (``config/gis_field_map.json``) and nothing else.
    gis_base_url: str = ""
    gis_auto_propose_score: int = DEFAULT_GIS_AUTO_PROPOSE_SCORE
    #: The demo scenario clock: empty for the real clock (the default),
    #: ``auto`` to derive one date at start-up from the seeded demo data, or an
    #: ISO date.  Only a database marked as the fictional demo honours it.
    scenario_clock: str = ""
    #: Whether the applicant help assistant may call the provider.
    #:
    #: The setting is off by default and stays off when a credential is
    #: present: a credential alone never enables a live answer for an
    #: applicant.  The live path of the assistant is delivered with the part
    #: of the work that adds the model; until then this flag is read by the
    #: settings and by nothing else.
    applicant_assist_live_enabled: bool = False
    #: Whether the what-if policy agent (``policy_brief`` and ``policy_propose``)
    #: may call the provider.  Off by default; a credential alone never turns it
    #: on.  The live path shares the call cap and the error-stop of every run.
    policy_assist_live_enabled: bool = False
    #: Whether Check my application may ask the provider for feedback.
    #:
    #: Off by default.  A credential alone never turns it on.  Submit does not
    #: read this flag: it runs the rules layer only.
    presubmit_review_live_enabled: bool = False
    meta_api_key: SecretStr | None = None
    key_file: Path | None = None
    secret_is_ephemeral: bool = False
    #: ``demo`` keeps the fictional demonstration exactly as it is.  ``production``
    #: removes the persona selector, the simulators and replay, refuses a demo
    #: database, switches the scenario clock off and requires a stable secret.
    deployment_mode: Literal["demo", "production"] = "demo"
    #: Explicit cookie ``Secure`` setting; ``None`` follows the deployment mode.
    cookie_secure: bool | None = None
    #: Trust ``X-Forwarded-Proto`` from the reverse proxy in front of the service.
    trust_proxy_headers: bool = False
    #: Explicit global AI provider switch; ``None`` follows the deployment mode.
    muse_provider_enabled: bool | None = None
    #: Requests per minute per client address; ``0`` is off.
    rate_limit_all_per_minute: int = 0
    rate_limit_write_per_minute: int = 0
    rate_limit_session_per_minute: int = 0
    rate_limit_upload_per_minute: int = 0
    #: Trusted proxy addresses to skip, counted from the right of ``X-Forwarded-For``.
    trusted_proxy_hops: int = 0
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES
    public_demo: bool = False

    @field_validator(
        "rate_limit_all_per_minute",
        "rate_limit_write_per_minute",
        "rate_limit_session_per_minute",
        "rate_limit_upload_per_minute",
        "trusted_proxy_hops",
        "max_request_bytes",
    )
    @classmethod
    def _not_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("rate limit, proxy hop and request size settings must not be negative")
        return value

    @model_validator(mode="after")
    def _production_requires_stable_secret(self) -> Settings:
        if self.deployment_mode == "production" and self.secret_is_ephemeral:
            raise ValueError(
                "ACME_SECRET_KEY is required in production mode: a generated "
                "per-process secret would end every session at each restart"
            )
        return self

    @property
    def is_production(self) -> bool:
        """Return whether the service runs in production mode."""
        return self.deployment_mode == "production"

    @property
    def effective_cookie_secure(self) -> bool:
        """Return whether session cookies are marked ``Secure``."""
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.is_production

    @property
    def provider_enabled(self) -> bool:
        """Return whether any call to the external AI provider is allowed."""
        if self.muse_provider_enabled is not None:
            return self.muse_provider_enabled
        return not self.is_production

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

    @field_validator("gis_auto_propose_score")
    @classmethod
    def _gis_score_in_range(cls, value: int) -> int:
        if not 1 <= value <= 100:
            raise ValueError("gis_auto_propose_score must be between 1 and 100")
        return value

    @field_validator("gis_base_url")
    @classmethod
    def _gis_url_is_http(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("gis_base_url must be empty or an http(s) URL")
        return value

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
            "gis_source": "external" if self.gis_base_url else "in-app simulator",
            "meta_api_key_present": self.meta_api_key is not None,
            "applicant_assist_live_enabled": self.applicant_assist_live_enabled,
            "policy_assist_live_enabled": self.policy_assist_live_enabled,
            "presubmit_review_live_enabled": self.presubmit_review_live_enabled,
            "deployment_mode": self.deployment_mode,
            "cookie_secure": self.effective_cookie_secure,
            "trust_proxy_headers": self.trust_proxy_headers,
            "rate_limit_all_per_minute": self.rate_limit_all_per_minute,
            "rate_limit_write_per_minute": self.rate_limit_write_per_minute,
            "rate_limit_session_per_minute": self.rate_limit_session_per_minute,
            "rate_limit_upload_per_minute": self.rate_limit_upload_per_minute,
            "max_request_bytes": self.max_request_bytes,
            "muse_provider_enabled": self.provider_enabled,
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

        gis_base_url = pick(ENV_GIS_BASE_URL, "") or ""
        gis_score_raw = pick(ENV_GIS_AUTO_PROPOSE_SCORE)
        gis_auto_propose_score = (
            DEFAULT_GIS_AUTO_PROPOSE_SCORE if gis_score_raw is None else int(gis_score_raw)
        )

        live_raw = pick(ENV_APPLICANT_ASSIST_LIVE)
        applicant_assist_live_enabled = str(live_raw or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        policy_live_raw = pick(ENV_POLICY_ASSIST_LIVE)
        policy_assist_live_enabled = str(policy_live_raw or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        presubmit_live_raw = pick(ENV_PRESUBMIT_REVIEW_LIVE)
        presubmit_review_live_enabled = str(presubmit_live_raw or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        scenario_clock = (pick(ENV_SCENARIO_CLOCK, "") or "").strip()

        mode = (pick(ENV_DEPLOYMENT_MODE, "demo") or "demo").strip().lower()
        if mode not in DEPLOYMENT_MODES:
            raise ValueError(f"{ENV_DEPLOYMENT_MODE} must be 'demo' or 'production', not {mode!r}")
        cookie_secure = _optional_bool(pick(ENV_COOKIE_SECURE), ENV_COOKIE_SECURE)
        trust_proxy_headers = bool(
            _optional_bool(pick(ENV_TRUST_PROXY_HEADERS), ENV_TRUST_PROXY_HEADERS)
        )
        muse_provider_enabled = _optional_bool(
            pick(ENV_MUSE_PROVIDER_ENABLED), ENV_MUSE_PROVIDER_ENABLED
        )

        def pick_int(name: str, default: int) -> int:
            raw = pick(name)
            return default if raw is None or not raw.strip() else int(raw)

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
            scenario_clock=scenario_clock,
            secret_key=SecretStr(resolved_secret),
            demo_timezone=demo_timezone,
            muse_model_allowlist=muse_model_allowlist,
            muse_live_call_cap=muse_live_call_cap,
            muse_image_daily_cap=muse_image_daily_cap,
            evidence_root=evidence_root,
            gis_base_url=gis_base_url,
            gis_auto_propose_score=gis_auto_propose_score,
            applicant_assist_live_enabled=applicant_assist_live_enabled,
            policy_assist_live_enabled=policy_assist_live_enabled,
            presubmit_review_live_enabled=presubmit_review_live_enabled,
            meta_api_key=meta_api_key,
            key_file=resolved_key_file,
            secret_is_ephemeral=ephemeral,
            deployment_mode=mode,
            cookie_secure=cookie_secure,
            trust_proxy_headers=trust_proxy_headers,
            muse_provider_enabled=muse_provider_enabled,
            rate_limit_all_per_minute=pick_int(ENV_RATE_LIMIT_ALL, 0),
            rate_limit_write_per_minute=pick_int(ENV_RATE_LIMIT_WRITE, 0),
            rate_limit_session_per_minute=pick_int(ENV_RATE_LIMIT_SESSION, 0),
            rate_limit_upload_per_minute=pick_int(ENV_RATE_LIMIT_UPLOAD, 0),
            trusted_proxy_hops=pick_int(ENV_TRUSTED_PROXY_HOPS, 0),
            max_request_bytes=pick_int(ENV_MAX_REQUEST_BYTES, DEFAULT_MAX_REQUEST_BYTES),
            public_demo=bool(_optional_bool(pick(ENV_PUBLIC_DEMO), ENV_PUBLIC_DEMO)),
            **operator_env_overrides(env),
            **autolink_env_overrides(env),
        )


__all__ = [
    "DEFAULT_DATABASE_URL",
    "DEFAULT_DEMO_TIMEZONE",
    "DEFAULT_EVIDENCE_ROOT",
    "DEFAULT_KEY_FILE",
    "DEFAULT_MUSE_LIVE_CALL_CAP",
    "DEFAULT_MUSE_IMAGE_DAILY_CAP",
    "DEFAULT_MUSE_MODEL_ALLOWLIST",
    "DEPLOYMENT_MODES",
    "ENV_APPLICANT_ASSIST_LIVE",
    "ENV_COOKIE_SECURE",
    "ENV_DEPLOYMENT_MODE",
    "ENV_MUSE_PROVIDER_ENABLED",
    "ENV_TRUST_PROXY_HEADERS",
    "ENV_POLICY_ASSIST_LIVE",
    "ENV_PRESUBMIT_REVIEW_LIVE",
    "KEY_FILE_ALLOWED_NAMES",
    "Settings",
    "parse_key_file",
    "read_key_file",
]
