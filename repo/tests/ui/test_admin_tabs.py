"""The administration tab registry and the lane route modules.

A lane adds an administration tab and a part of the Users tab through
``admin_tabs`` without editing it, and both render.  The five tabs keep their
labels, every interface action id survives the move to the lane modules, the
queue handlers moved to the steward routes, and ``administration`` is still
importable from ``agent_views``.
"""
# REQUIRES: UX-01

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest
from jinja2 import ChoiceLoader, DictLoader

from acme_city.ui import admin_tabs
from acme_city.ui import router as ui_router_module

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support.client import choose, client, settings  # noqa: E402,F401

REPO_ROOT = Path(__file__).resolve().parents[2]
ADMIN = "persona_city_administrator"

#: The interface action ids before the lane modules existed (W0-5).
ACTION_IDS_BEFORE_W0_5 = frozenset({
    "agent.run.adjudication", "agent.run.intake", "agent.toggle", "change.dispatch",
    "change.request", "change.transition", "config.permit_type.create",
    "config.permit_type.document", "config.reason_code.add", "config.reason_code.retire",
    "config.user.add", "extraction.decide", "fee.approve", "fee.draft", "fee.publish",
    "fee.retire", "fee.submit", "finance.allocate", "finance.assess", "finance.import",
    "finance.reassess", "finance.reconcile", "governance.authority_preview",
    "governance.authority_publish", "governance.escalate", "governance.publish_dataset",
    "governance.reassign", "governance.register", "intake.simulate", "ops.checks.run",
    "parcel.candidate.choose", "parcel.confirm", "parcel.find", "parcel.link.decide",
    "permit.case.advance", "permit.case.archive", "permit.case.assign",
    "permit.case.comment", "permit.case.priority", "permit.case.request_revisions",
    "permit.case.restore", "permit.case.return", "permit.decide", "permit.evaluate",
    "permit.finding.waive", "permit.icon.generate", "permit.icon.save",
    "permit.intake.process_selected", "permit.issue", "permit.reconfirm", "permit.revise",
    "recommendation.confirm", "recommendation.revert", "registry.decide", "registry.defer",
    "registry.propose", "rule.approve", "rule.draft", "rule.publish", "rule.retire",
    "rule.submit", "source.write", "support.case.record", "support.help_request.answer",
})


def test_the_five_tabs_keep_their_order_and_labels() -> None:
    tabs = sorted(admin_tabs.ADMIN_TABS.values(), key=lambda tab: tab.order)
    # Changed deliberately (admin-a ADA-4): the labels are the plain names of
    # the five sections, in sentence case.
    assert [(tab.key, tab.label) for tab in tabs[:5]] == [
        ("permit-types", "Permit types"),
        ("appearance", "Appearance"),
        ("users", "Users and roles"),
        ("reason-codes", "Reason codes"),
        ("log", "Configuration log"),
    ]
    for tab in tabs[:5]:
        assert (REPO_ROOT / "src" / "acme_city" / "templates" / tab.template).is_file()


def test_a_registered_tab_and_users_extra_render_and_unregister(client) -> None:  # noqa: F811
    env = ui_router_module.templates.env
    original = env.loader
    env.loader = ChoiceLoader([
        DictLoader({
            "test/_dummy_tab.html": (
                '<details data-testid="admin-section" data-section="dummy">'
                "{{ dummy_tab_text }}</details>"
            ),
            "test/_dummy_users_extra.html": (
                '<p data-testid="dummy-users-extra">{{ dummy_extra_text }}</p>'
            ),
        }),
        original,
    ])
    admin_tabs.register_admin_tab(
        "dummy", "Dummy Tab", "test/_dummy_tab.html",
        context_fn=lambda session, actor: {"dummy_tab_text": f"tab for {actor.actor_id}"},
        order=999,
    )
    admin_tabs.register_users_extra(
        "test/_dummy_users_extra.html",
        context_fn=lambda session, actor: {"dummy_extra_text": "users extra"},
    )
    try:
        body = choose(client, ADMIN).get("/admin?tab=dummy").text
        assert 'data-tab="dummy">Dummy Tab</a>' in body
        assert f"tab for {ADMIN}" in body
        # Changed deliberately (admin-a ADA-4): one section renders at a time,
        # so the part of the Users tab is asked for on the Users tab.
        users_body = choose(client, ADMIN).get("/admin?tab=users").text
        assert '<p data-testid="dummy-users-extra">users extra</p>' in users_body
        # The extra sits inside the Users tab.
        users = users_body.split('data-section="users"', 1)[1].split("</details>", 1)[0]
        assert "dummy-users-extra" in users
        # The section that is not selected is not rendered at all.
        assert 'data-section="permit-types"' not in body
    finally:
        admin_tabs.unregister_admin_tab("dummy")
        admin_tabs.unregister_users_extra("test/_dummy_users_extra.html")
        env.loader = original
    body = client.get("/admin?tab=dummy").text
    assert "Dummy Tab" not in body and "dummy-users-extra" not in body
    # An unknown tab falls back to the first one.
    assert 'aria-selected="true" data-testid="admin-tab" data-tab="permit-types"' in body


def test_a_tab_with_a_required_grant_is_hidden_without_it(client) -> None:  # noqa: F811
    admin_tabs.register_admin_tab(
        "granted", "Granted Tab", "admin/_log.html", required_grant="no.such.grant", order=999
    )
    try:
        assert "Granted Tab" not in choose(client, ADMIN).get("/admin").text
    finally:
        admin_tabs.unregister_admin_tab("granted")


def _twice_context(session, actor):
    return {"twice_text": "twice"}


def test_loading_the_lane_modules_twice_registers_once(monkeypatch) -> None:
    from acme_city.ui import agent_admin_views, nav_plugins

    def register() -> None:
        admin_tabs.register_admin_tab(
            "twice", "Twice", "admin/_log.html", context_fn=_twice_context, order=999
        )
        admin_tabs.register_users_extra("test/_twice.html", context_fn=_twice_context)

    monkeypatch.setattr(agent_admin_views, "register", register)
    try:
        nav_plugins.load_plugins()
        nav_plugins.load_plugins()
        assert [key for key in admin_tabs.ADMIN_TABS if key == "twice"] == ["twice"]
        assert [
            extra.template
            for extra in admin_tabs.ADMIN_USERS_EXTRAS_PROVIDERS
            if extra.template == "test/_twice.html"
        ] == ["test/_twice.html"]
        # A different definition under the same key or template is refused.
        with pytest.raises(ValueError):
            admin_tabs.register_admin_tab("twice", "Other", "admin/_log.html")
        with pytest.raises(ValueError):
            admin_tabs.register_users_extra("test/_twice.html")
    finally:
        admin_tabs.unregister_admin_tab("twice")
        admin_tabs.unregister_users_extra("test/_twice.html")


def test_a_provider_may_not_replace_a_page_variable(client) -> None:  # noqa: F811
    admin_tabs.register_admin_tab(
        "clash", "Clash", "admin/_log.html",
        context_fn=lambda session, actor: {"admin_tabs": []}, order=999,
    )
    try:
        with pytest.raises(ValueError, match="admin_tabs"):
            choose(client, ADMIN).get("/admin")
    finally:
        admin_tabs.unregister_admin_tab("clash")


def test_a_required_grant_is_checked_against_its_domain(monkeypatch) -> None:
    from acme_city.auth.context import ActorContext
    from acme_city.auth.permissions import Grant
    from acme_city.ui import view_models

    grant = Grant("p1", "agent.run", "domain_a", frozenset(), False)

    class Resolver:
        def __init__(self, session) -> None:
            pass

        def grants_for(self, actor_id):
            return [grant]

    monkeypatch.setattr(view_models, "PermissionResolver", Resolver)
    actor = ActorContext(actor_id="someone")
    for key, required in (
        ("in_domain", ("agent.run", "domain_a")),
        ("other_domain", ("agent.run", "domain_b")),
        ("any_domain", "agent.run"),
    ):
        admin_tabs.register_admin_tab(key, key, "admin/_log.html", required_grant=required)
    try:
        keys = {tab.key for tab in admin_tabs.visible_tabs(None, actor)}
        assert "in_domain" in keys
        # A grant in one domain does not open a tab scoped to another, nor a
        # tab whose grant names no domain.
        assert "other_domain" not in keys and "any_domain" not in keys
    finally:
        for key in ("in_domain", "other_domain", "any_domain"):
            admin_tabs.unregister_admin_tab(key)


def test_every_earlier_action_id_is_still_handled() -> None:
    assert ACTION_IDS_BEFORE_W0_5 <= set(ui_router_module.ACTION_HANDLERS)


def test_administration_is_still_importable_from_agent_views() -> None:
    from acme_city.ui.admin_config_views import administration as moved
    from acme_city.ui.agent_views import administration

    assert administration is moved


def test_the_moved_handlers_left_the_router() -> None:
    ownership = json.loads(
        (REPO_ROOT / "tests" / "regression" / "data" / "owned_hunks.json").read_text()
    )
    for source, functions in ownership["moved"].items():
        names = _function_names(REPO_ROOT / source)
        for name, target in functions.items():
            assert name not in names, (source, name)
            assert name in _function_names(REPO_ROOT / target), (target, name)
            assert name not in ownership["functions"].get(source, {})


def _function_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
