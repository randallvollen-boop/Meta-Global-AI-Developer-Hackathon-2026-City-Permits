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
    assert [(tab.key, tab.label) for tab in tabs[:5]] == [
        ("permit-types", "Permit Types"),
        ("appearance", "Appearance"),
        ("users", "Users"),
        ("reason-codes", "Reason Codes"),
        ("log", "Log"),
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
        assert '<p data-testid="dummy-users-extra">users extra</p>' in body
        # The extra sits inside the Users tab.
        users = body.split('data-section="users"', 1)[1].split("</details>", 1)[0]
        assert "dummy-users-extra" in users
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
