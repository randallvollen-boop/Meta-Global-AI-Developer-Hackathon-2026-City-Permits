"""WEB-003: the detail drawer close link cannot leave the site."""
# REQUIRES: SEC-01, SEC-02
# A backslash or control character in a return path falls back to a local path.

from __future__ import annotations

import pytest

from acme_city.ui.router import safe_next


@pytest.mark.parametrize(
    "value",
    ["/\\evil.example", "/\\\\evil.example", "//evil.example", "/ok\r\nLocation: x", "/a\tb", "https://evil.example"],
)
def test_unsafe_return_paths_fall_back(value: str) -> None:
    assert safe_next(value, "/fallback") == "/fallback"


def test_a_local_return_path_is_kept() -> None:
    assert safe_next("/queue?x=1", "/fallback") == "/queue?x=1"


def test_the_drawer_close_link_is_local(audit_client, pick) -> None:
    pick(audit_client, "persona_data_steward")
    response = audit_client.get("/detail/help/queue", params={"from": "/\\evil.example"})
    assert "evil.example" not in response.text
