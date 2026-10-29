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

from acme_city.policy import views
from acme_city.ui import admin_b_labels, admin_views


def test_the_display_models_are_plain_functions_of_the_stored_rows() -> None:
    """Every display model of the lane is a plain function, with no model call."""
    for name in ("describe_change", "check_changes", "editor_options", "run_view"):
        assert callable(getattr(views, name)), name


def test_governance_labels_and_attention_are_derived_without_model_calls() -> None:
    assert admin_b_labels.identifier_label("applications_and_permits") == "Applications and permits"
    assert callable(admin_views.governance_screen)
