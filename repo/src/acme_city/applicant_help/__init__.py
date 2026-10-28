"""The applicant help assistant.

The assistant answers an applicant's questions about the ACME permit process,
the rules that apply to their project and their own application.  It is
deliberately small and honest:

* it answers **only** from a source bundle the server builds — the City's
  published rule versions, the stored permit-type configuration, the fixed
  applicant-facing passages and, when the applicant asks about their own
  case, the facts of that case;
* the answer is either **deterministic** — the matching is a stable ranking
  over that bundle, and the answer quotes the matching passages — or
  **written by the assistant**: the model path of this package, whose prose
  is validated against the very bundle it was given before the applicant
  reads it;
* it **never decides**: it explains, it cites, and it hands the applicant to
  a person when it cannot answer;
* the conversation is **private**: it belongs to the applicant who opened it,
  and a member of the City sees it only when the applicant asks one.
"""
# REQUIRES: PER-04, PER-05, SEC-02, SEC-03, UX-02
# The assistant answers only from a server-built source bundle, quotes that
# bundle, keeps the conversation private to its owner, and hands the applicant
# to a person when it cannot answer.

from __future__ import annotations

__all__ = [
    "assist",
    "assist_validation",
    "config",
    "matching",
    "service",
    "sources",
    "views",
]
