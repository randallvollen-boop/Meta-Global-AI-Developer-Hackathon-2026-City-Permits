"""The hooks of the administration screen.

The redesign may change how the administration screen looks, but it may not
rename or drop a hook: the browser tests, the acceptance walkthrough and the
screens of the other lanes all address the screen through them.  This module
holds the baseline of those hooks and checks that every one of them is still
in the template it belongs to.

It also checks the two seams of the screen: the ``admin_users_extras`` slot,
which the other lanes append to, and the ``register_admin_tab`` API, which
they add a tab through.  Neither is edited by a lane, so a lane that removes
one of them would silently drop the parts another lane registered.
"""
# REQUIRES: UX-01

from __future__ import annotations

import json
from pathlib import Path

from acme_city.ui import admin_tabs

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = REPO_ROOT / "src" / "acme_city" / "templates"
BASELINE = Path(__file__).resolve().parent / "admin_testid_baseline.json"

#: The five sections the administration screen is built of.
BUILT_IN_SECTIONS = ("permit-types", "appearance", "users", "reason-codes", "log")


def _baseline() -> dict:
    """Return the recorded baseline of the administration hooks."""
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def _source(name: str) -> str:
    """Return the source of one template of the administration screen."""
    path = TEMPLATES / name
    assert path.is_file(), path
    return path.read_text(encoding="utf-8")


def test_the_baseline_names_the_templates_that_exist() -> None:
    templates = _baseline()["templates"]
    assert "admin.html" in templates
    for name in templates:
        assert (TEMPLATES / name).is_file(), name
    # Every partial of the administration screen is in the baseline.
    partials = {f"admin/{path.name}" for path in (TEMPLATES / "admin").glob("*.html")}
    assert partials == set(templates) - {"admin.html"}


def test_every_recorded_testid_is_still_in_its_template() -> None:
    for name, hooks in _baseline()["templates"].items():
        source = _source(name)
        for testid in hooks["testids"]:
            assert f'data-testid="{testid}"' in source, (name, testid)


def test_every_recorded_behaviour_attribute_is_still_in_its_template() -> None:
    for name, hooks in _baseline()["templates"].items():
        source = _source(name)
        for attribute in hooks["attributes"]:
            assert f"{attribute}=" in source, (name, attribute)


def test_the_users_tab_keeps_the_slot_the_other_lanes_append_to() -> None:
    source = _source("admin/_users.html")
    assert "admin_users_extras" in source
    assert "{% include part %}" in source


def test_the_registry_api_the_other_lanes_register_through_exists() -> None:
    assert callable(admin_tabs.register_admin_tab)
    assert callable(admin_tabs.register_users_extra)
    assert callable(admin_tabs.visible_tabs)
    assert hasattr(admin_tabs, "ADMIN_TABS")
    assert hasattr(admin_tabs, "ADMIN_USERS_EXTRAS_PROVIDERS")


def test_every_registered_tab_renders_a_template_that_exists() -> None:
    for key, tab in admin_tabs.ADMIN_TABS.items():
        assert tab.template, key
        assert (TEMPLATES / tab.template).is_file(), (key, tab.template)
        assert tab.label, key


def test_the_five_sections_keep_their_keys() -> None:
    keys = [tab.key for tab in sorted(admin_tabs.ADMIN_TABS.values(), key=lambda t: t.order)]
    # The five sections keep their keys and their order.  A lane may register
    # a tab of its own between them.
    assert [key for key in keys if key in BUILT_IN_SECTIONS] == list(BUILT_IN_SECTIONS)


def test_the_baseline_covers_the_hook_families_of_the_screen() -> None:
    found = {
        testid
        for hooks in _baseline()["templates"].values()
        for testid in hooks["testids"]
    }
    for family in ("admin-", "permit-type-", "icon-"):
        assert any(testid.startswith(family) for testid in found), family
