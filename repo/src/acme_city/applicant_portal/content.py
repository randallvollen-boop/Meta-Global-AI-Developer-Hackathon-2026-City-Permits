"""The wording of the applicant screens, read from ``config/applicant_portal.json``.

Nothing here is a rule, a fee or a timing.  Limits are filled in from the
published rule versions and timings from the permit type, so a sentence can
never state a number the configuration does not hold.
"""
# REQUIRES: PORTAL-01, UX-01

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from acme_city.fixtures.loader import REPO_ROOT

CONTENT_PATH = REPO_ROOT / "config" / "applicant_portal.json"


@lru_cache(maxsize=1)
def content() -> dict[str, Any]:
    """Return the validated applicant wording."""
    return json.loads(Path(CONTENT_PATH).read_text(encoding="utf-8"))


def reload_content() -> None:
    """Drop the cached wording (used by tests and by a config edit)."""
    content.cache_clear()


def document_purpose(document_type: str) -> str:
    """Return the one-line purpose of a document type, or an empty string."""
    return str(content().get("document_purposes", {}).get(document_type, ""))


def next_step(status: str, *, target_days: int | None = None) -> str:
    """Return the one sentence "What happens next" for an application status."""
    text = str(content().get("next_step", {}).get(status, ""))
    if text and target_days and status in {"submitted", "ready_for_review", "under_review"}:
        text += " " + str(content().get("target_sentence", "")).format(days=target_days)
    return text


__all__ = ["CONTENT_PATH", "content", "document_purpose", "next_step", "reload_content"]
