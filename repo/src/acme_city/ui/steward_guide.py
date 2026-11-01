"""The deterministic guide of the Data Steward.

The guide explains the screen a steward is on and the task in front of it.
Its words come from ``config/steward_guide.json``; the facts it repeats come
from the recorded state the caller has already filtered by the permissions of
the persona.  The guide reads nothing else and decides nothing.

The guide never reaches a model.  It has no write tool, it names no action
that the context does not hold, and it does not import the Muse package.  The
label it returns is exact: "Saved guidance."
"""
# REQUIRES: UX-01, UX-02
# The guide answers from saved words and recorded state.  It cannot call a
# model, submit an action, or name an action the caller did not pass in.

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

#: ``repo/`` (the Python project) and the folder above it.
REPO_DIR = Path(__file__).resolve().parents[3]
GUIDE_PATH = REPO_DIR / "config" / "steward_guide.json"

#: The key of the offline mode of the guide.
GUIDE_MODE = "saved_guidance"

#: The exact label the guide shows while no model is called.
OFFLINE_LABEL = "Saved guidance."

#: The order in which the guide offers its next actions: address invalid or
#: stale evidence, resolve blocking identity questions, review eligible
#: proposals, then inspect completed work.
NEXT_ACTION_ORDER: tuple[str, ...] = (
    "stale_evidence",
    "blocking_identity",
    "eligible_proposal",
    "completed_work",
)

#: The prompt the guide answers when the caller names none.
DEFAULT_PROMPT = "explain_screen"


@dataclass(frozen=True)
class GuideAction:
    """One action of the screen, or one the persona may not take."""

    label: str
    href: str = ""
    detail: str = ""
    category: str = "eligible_proposal"
    allowed: bool = True
    reason: str = ""


@dataclass(frozen=True)
class GuideContext:
    """What the guide knows about the screen, already filtered by permission.

    The caller builds this from the view model of the screen.  Every value
    here is a fact the persona may already see, so the guide can repeat it
    without widening the scope.
    """

    screen: str
    task: str = ""
    state: str = ""
    candidate: str = ""
    evidence: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    actions: tuple[GuideAction, ...] = ()
    dependencies: str = ""
    source_state: str = ""


@dataclass(frozen=True)
class GuideLink:
    """A link to the section or the action an explanation points at."""

    label: str
    href: str = ""
    detail: str = ""


@dataclass(frozen=True)
class GuideResponse:
    """One answer of the guide: an explanation, its evidence and its links."""

    prompt: str
    prompt_label: str
    mode: str
    mode_label: str
    explanation: str
    state: str
    candidate: str
    evidence: tuple[str, ...]
    #: ``True`` when the screen passed recorded evidence.  A screen with no
    #: evidence says nothing about it, so the guide never claims evidence the
    #: page does not show.
    evidence_recorded: bool
    conflicts: tuple[str, ...]
    missing: tuple[str, ...]
    links: tuple[GuideLink, ...]
    next_actions: tuple[GuideLink, ...]
    refusals: tuple[GuideLink, ...]
    dependencies: str
    source_state: str


@lru_cache(maxsize=1)
def _content() -> dict[str, Any]:
    return dict(json.loads(GUIDE_PATH.read_text(encoding="utf-8")))


def reload() -> None:
    """Drop the cached configuration (used by tests)."""
    _content.cache_clear()


def version() -> str:
    """Return the version of the saved guidance."""
    return str(_content().get("version", ""))


def screens() -> tuple[tuple[str, str], ...]:
    """Return the screens the guide knows, with their labels."""
    return tuple(
        (key, str(value.get("label", key)))
        for key, value in sorted(_content().get("screens", {}).items())
    )


def prompts() -> tuple[tuple[str, str], ...]:
    """Return the prompts the guide offers, with their labels."""
    return tuple((key, str(label)) for key, label in _content().get("prompts", {}).items())


def guidance(screen: str) -> str:
    """Return the saved guidance of one screen."""
    entry = _content().get("screens", {}).get(screen) or {}
    return str(entry.get("guidance") or _content().get("no_guidance", ""))


def _rank(category: str) -> int:
    """Return the place of a category in the order of the next actions."""
    if category in NEXT_ACTION_ORDER:
        return NEXT_ACTION_ORDER.index(category)
    return len(NEXT_ACTION_ORDER)


def build(context: GuideContext, prompt: str = DEFAULT_PROMPT) -> GuideResponse:
    """Return the answer of the guide for one screen and one prompt.

    The answer holds a short explanation, the recorded state that supports
    it, the evidence, the links to the section or the permitted action, and
    the actions the persona may not take with the reason for each.
    """
    content = _content()
    prompts = content.get("prompts", {})
    key = prompt if prompt in prompts else DEFAULT_PROMPT
    entry = content.get("screens", {}).get(context.screen) or {}
    texts = entry.get("prompts") or {}
    explanation = str(
        texts.get(key) or entry.get("guidance") or content.get("no_guidance", "")
    )
    recorded = tuple(context.evidence)
    evidence = recorded or (str(content.get("no_evidence", "")),)
    allowed = [item for item in context.actions if item.allowed]
    refused = [item for item in context.actions if not item.allowed]
    return GuideResponse(
        prompt=key,
        prompt_label=str(prompts.get(key, prompts.get(DEFAULT_PROMPT, ""))),
        mode=str(content.get("mode", {}).get("key", GUIDE_MODE)),
        mode_label=str(content.get("mode", {}).get("label", OFFLINE_LABEL)),
        explanation=explanation,
        state=context.state,
        candidate=context.candidate,
        evidence=evidence,
        evidence_recorded=bool(recorded),
        conflicts=tuple(context.conflicts),
        missing=tuple(context.missing),
        links=tuple(
            GuideLink(label=str(item.get("label", "")), href=str(item.get("href", "")))
            for item in entry.get("links") or []
        ),
        next_actions=tuple(
            GuideLink(label=item.label, href=item.href, detail=item.detail)
            for item in sorted(allowed, key=lambda item: (_rank(item.category), item.label))
        ),
        refusals=tuple(
            GuideLink(label=item.label, href=item.href, detail=item.reason or item.detail)
            for item in refused
        ),
        dependencies=context.dependencies,
        source_state=context.source_state,
    )


__all__ = [
    "DEFAULT_PROMPT",
    "GUIDE_MODE",
    "GUIDE_PATH",
    "NEXT_ACTION_ORDER",
    "OFFLINE_LABEL",
    "GuideAction",
    "GuideContext",
    "GuideLink",
    "GuideResponse",
    "build",
    "guidance",
    "prompts",
    "reload",
    "screens",
    "version",
]
