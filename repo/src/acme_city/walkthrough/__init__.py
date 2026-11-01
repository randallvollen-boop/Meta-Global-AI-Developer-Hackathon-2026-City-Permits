"""The demonstration walkthrough: the paths, their tours and the judge's copy."""

from __future__ import annotations

from acme_city.walkthrough.judge_copy import (
    JUDGE_REFERENCE_PREFIX,
    MAX_JUDGE_COPIES,
    JudgeCopy,
    create_judge_copy,
    judge_copy_count,
    room_for_copies,
)

__all__ = [
    "JUDGE_REFERENCE_PREFIX",
    "MAX_JUDGE_COPIES",
    "JudgeCopy",
    "create_judge_copy",
    "judge_copy_count",
    "room_for_copies",
]
