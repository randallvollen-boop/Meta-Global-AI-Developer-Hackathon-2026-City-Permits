"""The display models of the admin-b screens.

The screens show what the permit engine stored and counted.  A model may
explain a run or propose a change, but it never supplies a figure, a label or
a decision, so the display models are plain functions of the frozen baseline
and of the stored rows.

This file starts as the skeleton of the lane.  The later slices add their own
cases: ADB-7 the deterministic run summary and ADB-10 the governance screen.
"""
# REQUIRES: UX-01, PER-02

from __future__ import annotations

import sys
from pathlib import Path

from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.persistence.models import governance
from acme_city.persistence.session import SessionFactory, transaction
from acme_city.policy import views
from acme_city.ui import admin_b_labels, admin_views

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integration"))
from insight_support import build_environment  # noqa: E402


def test_the_display_models_are_plain_functions_of_the_stored_rows() -> None:
    """Every display model of the lane is a plain function, with no model call."""
    for name in ("describe_change", "check_changes", "editor_options", "run_view"):
        assert callable(getattr(views, name)), name


def test_governance_labels_and_attention_are_derived_from_seeded_rows(tmp_path: Path) -> None:
    assert admin_b_labels.identifier_label("applications_and_permits") == "Applications and permits"
    settings = build_environment(tmp_path, synthetic=False, name="admin-display-models.db")
    factory = SessionFactory(settings.database_url)
    try:
        with transaction(factory) as session:
            resolver = PermissionResolver(session)
            grants = resolver.grants_for("persona_city_administrator")
            actor = ActorContext(
                actor_id="persona_city_administrator", role_ids=frozenset(),
                domain_scope=frozenset(g.domain_id for g in grants if g.domain_id),
                record_scope=frozenset(r for g in grants for r in g.record_scope),
            )
            unowned = session.query(governance.SourceContract).filter_by(
                dataset_key="business_licensing_register"
            ).one()
            unowned.accountable_owner_actor_id = None
            unowned.steward_queue_id = None
            unowned.system_custodian_actor_id = None
            session.flush()
            screen = admin_views.governance_screen(session, actor)
            assert screen["attention"] == {
                "staged_records": len(screen["staged"]),
                "quarantine_errors": len(screen["quarantined"]),
            }
            by_dataset = {row["dataset_key"]: row for row in screen["registrations"]}
            assert by_dataset["business_licensing_register"]["source_label"] == "ERP/Finance"
            assert by_dataset["business_licensing_register"]["source_system_id"] == "erp_finance"
            assert by_dataset["business_licensing_register"]["owner_label"] == "No owner assigned"
            assert by_dataset["business_licensing_register"]["custodian_label"] == "No custodian assigned"
            assert by_dataset["applications_and_permits"]["dataset_label"] == "Applications and permits"
            assert by_dataset["applications_and_permits"]["dataset_key"] == "applications_and_permits"
    finally:
        factory.dispose()
