"""Every Muse request leaves room for the answer after the reasoning.

A live call to Check my application came back "incomplete": 743 of its 800
output tokens went to reasoning, so the JSON answer never arrived.  The
budget of every payload is now the shared ceiling.
"""

from __future__ import annotations

import inspect

from acme_city.muse import presubmit
from acme_city.muse.client import MAX_OUTPUT_TOKENS
from acme_city.triage import summary


def test_the_ceiling_leaves_room_for_reasoning_and_an_answer() -> None:
    assert MAX_OUTPUT_TOKENS >= 2000


def test_presubmit_and_triage_use_the_shared_ceiling() -> None:
    for module in (presubmit, summary):
        source = inspect.getsource(module)
        assert '"max_output_tokens": 800' not in source, module.__name__
        assert '"max_output_tokens": MAX_OUTPUT_TOKENS' in source, module.__name__
