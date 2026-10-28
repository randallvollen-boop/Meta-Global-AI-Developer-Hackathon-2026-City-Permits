"""The what-if screens: scenarios, immutable runs, results and the briefing.

Covers the grants (every read and write, direct-id access), CSRF and the
mandatory expected version on every write, audit records, soft delete with the
runs kept, the immutability and the content hash of a run, the unsupported
response, the wording rules of the results, the deterministic briefing and its
escaped downloads, and the City view control.
"""
# REQUIRES: PER-02, PER-04, SEC-01, SEC-03, UX-01
# The what-if screens enforce dedicated grants, CSRF and a mandatory version, keep
# runs immutable and state only what a run measured.

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from insight_support import ADMIN, build_environment, open_factory
from sqlalchemy import select

from acme_city.app import create_app
from acme_city.audit.service import AuditService  # noqa: F401  (documents the audit dependency)
from acme_city.auth.context import ActorContext
from acme_city.auth.permissions import PermissionResolver
from acme_city.core.errors import ConflictError, PermissionDeniedError, ValidationError
from acme_city.persistence.base import Base
from acme_city.persistence.models import audit as audit_models
from acme_city.persistence.models import policy as models
from acme_city.persistence.session import transaction
from acme_city.policy import briefing as briefing_module
from acme_city.policy import runs as runs_module
from acme_city.policy.service import PolicyService
from acme_city.ui.router import router as ui_router

STEWARD = "persona_data_steward"
REVIEWER = "persona_permit_reviewer"
APPLICANT = "persona_applicant"
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)

#: Words the results and the briefing never use (the brief's wording rules).
FORBIDDEN_CLAIMS = ("revenue", "staff-day", "staff day", "time saved", "time-saved", "throughput")


@pytest.fixture(scope="module")
def settings(tmp_path_factory):
    return build_environment(tmp_path_factory.mktemp("policy"), synthetic=False, name="policy.db")


@pytest.fixture()
def client(settings):
    app = create_app(settings)
    app.include_router(ui_router)
    with TestClient(app) as test_client:
        yield test_client


def choose(client: TestClient, actor_id: str) -> TestClient:
    assert client.post("/api/session/select", json={"actor_id": actor_id}).status_code == 200
    return client


def csrf_of(body: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', body)
    assert match, "the page carries a form token"
    return match.group(1)


def version_of(body: str) -> str:
    match = re.search(r'name="expected_version" value="(\d+)"', body)
    assert match
    return match.group(1)


def create_fence(client: TestClient, name: str = "Raise the side/rear fence height limit from 6 ft to 7 ft") -> str:
    page = choose(client, ADMIN).get("/policy/scenarios")
    response = client.post(
        "/policy/scenarios",
        data={"csrf_token": csrf_of(page.text), "expected_version": "0",
              "suggestion": "fence_height_7ft", "name": name},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return response.headers["location"].split("?")[0]


def run_it(client: TestClient, editor: str, **fields: str) -> str:
    page = client.get(editor)
    payload = {"csrf_token": csrf_of(page.text), "expected_version": version_of(page.text),
               "kind": "synthetic_year", "seed": "20261028", "count": "300"}
    payload.update(fields)
    response = client.post(f"{editor}/run", data=payload, follow_redirects=False)
    assert response.status_code == 303, response.text
    return response.headers["location"]


def add_change(client: TestClient, editor: str, **fields: str):
    page = client.get(editor)
    return client.post(
        f"{editor}/save",
        data={"csrf_token": csrf_of(page.text), "expected_version": version_of(page.text),
              "operation": "add_change", **fields},
        follow_redirects=False,
    )


def actor_context(session, actor_id: str) -> ActorContext:
    grants = PermissionResolver(session).grants_for(actor_id)
    return ActorContext(
        actor_id=actor_id,
        domain_scope=frozenset(g.domain_id for g in grants if g.domain_id),
        record_scope=frozenset(r for g in grants for r in g.record_scope),
    )


BUSINESS_TABLES = (
    "applications", "application_revisions", "documents", "application_findings",
    "decisions", "permits", "permit_types", "rule_versions", "fee_schedule_versions",
    "assessments",
)


def business_snapshot(settings) -> dict[str, str]:
    factory = open_factory(settings)
    try:
        with factory() as session:
            digests = {}
            for table in Base.metadata.sorted_tables:
                if table.name not in BUSINESS_TABLES:
                    continue
                rows = [
                    json.dumps({k: str(v) for k, v in row._mapping.items()}, sort_keys=True)
                    for row in session.execute(table.select()).all()
                ]
                digests[table.name] = hashlib.sha256("\n".join(sorted(rows)).encode()).hexdigest()
            return digests
    finally:
        factory.dispose()


# ---------------------------------------------------------------- the grants


def test_only_the_city_administrator_holds_the_policy_grants(settings) -> None:
    factory = open_factory(settings)
    try:
        with transaction(factory) as session:
            resolver = PermissionResolver(session)
            wanted = {"policy.scenario.manage", "policy.run.execute", "policy.run.view", "policy.brief.view"}
            assert wanted <= resolver.permissions_for(ADMIN)
            for actor in (APPLICANT, STEWARD, REVIEWER):
                assert not (wanted & resolver.permissions_for(actor)), actor
    finally:
        factory.dispose()


@pytest.mark.parametrize("actor", [APPLICANT, STEWARD, REVIEWER])
def test_every_policy_route_refuses_the_other_personas_including_direct_ids(client, actor) -> None:
    editor = create_fence(client)
    run = run_it(client, editor)
    scenario_id = editor.rsplit("/", 1)[1]
    choose(client, actor)
    for path in ("/policy/scenarios", editor, run, f"{run}/briefing", f"{run}/briefing/download?format=md"):
        assert client.get(path).status_code == 403, (actor, path)
    token = "x"
    for path in ("/policy/scenarios", f"{editor}/save", f"{editor}/delete", f"{editor}/run"):
        response = client.post(path, data={"csrf_token": token, "expected_version": "1"})
        assert response.status_code == 403, (actor, path)
    # Nothing was written by the refused attempts, and the run is intact.
    assert choose(client, ADMIN).get(run).status_code == 200
    assert client.get(editor).status_code == 200 and scenario_id in editor


def test_the_service_checks_the_grant_on_every_method(settings) -> None:
    factory = open_factory(settings)
    try:
        with transaction(factory) as session:
            admin = actor_context(session, ADMIN)
            service = PolicyService(session, now=NOW)
            scenario = service.create_scenario(admin, name="Guard test", changes=[
                {"kind": "rule_threshold", "rule_id": "DF-2", "limit_value": "7"}], expected_version=0)
            run = service.run_scenario(admin, scenario.id, expected_version=scenario.version,
                                       spec={"kind": "synthetic_year", "count": "50"})
            for actor_id in (APPLICANT, STEWARD, REVIEWER):
                other = actor_context(session, actor_id)
                calls = (
                    lambda: service.list_scenarios(other),
                    lambda: service.scenario_for(other, scenario.id),
                    lambda: service.revisions(other, scenario),
                    lambda: service.create_scenario(other, name="x", expected_version=0),
                    lambda: service.edit_scenario(other, scenario.id, operation="rename", name="y",
                                                  expected_version=scenario.version),
                    lambda: service.delete_scenario(other, scenario.id, expected_version=scenario.version),
                    lambda: service.run_scenario(other, scenario.id, expected_version=scenario.version, spec={}),
                    lambda: service.run_for(other, run.id),
                    lambda: service.run_for_briefing(other, run.id),
                    lambda: service.recent_runs(other),
                )
                for call in calls:
                    with pytest.raises(PermissionDeniedError):
                        call()
    finally:
        factory.dispose()


def test_a_grant_for_one_policy_action_does_not_open_another(settings) -> None:
    """The four grants are separate: holding the view grant does not allow a run."""
    factory = open_factory(settings)
    try:
        with transaction(factory) as session:
            admin = actor_context(session, ADMIN)
            service = PolicyService(session, now=NOW)
            scenario = service.create_scenario(admin, name="Separate grants", changes=[
                {"kind": "service_target", "permit_type_key": "shed", "service_target_days": 3}], expected_version=0)
            run = service.run_scenario(admin, scenario.id, expected_version=scenario.version, spec={"count": "40"})
            from acme_city.persistence.models import governance
            session.execute(
                governance.ActorGrant.__table__.delete().where(
                    governance.ActorGrant.actor_id == ADMIN,
                    governance.ActorGrant.permission_id == "policy.brief.view",
                )
            )
            session.flush()
            assert service.run_for(admin, run.id).id == run.id
            with pytest.raises(PermissionDeniedError):
                service.run_for_briefing(admin, run.id)
            session.rollback()
    finally:
        factory.dispose()


# ---------------------------------------------- writes: CSRF, version, audit


def test_a_write_needs_the_csrf_token(client) -> None:
    choose(client, ADMIN)
    response = client.post("/policy/scenarios", data={"expected_version": "0", "name": "No token"})
    assert response.status_code == 403
    editor = create_fence(client)
    page = client.get(editor)
    for path, extra in ((f"{editor}/save", {"operation": "rename", "name": "z"}),
                        (f"{editor}/delete", {}), (f"{editor}/run", {"kind": "synthetic_year"})):
        response = client.post(path, data={"csrf_token": "forged", "expected_version": version_of(page.text), **extra})
        assert response.status_code == 403, path


def test_a_missing_expected_version_is_refused_as_firmly_as_a_stale_one(client) -> None:
    editor = create_fence(client)
    page = client.get(editor)
    token = csrf_of(page.text)
    for path, extra in (
        ("/policy/scenarios", {"name": "Missing version"}),
        (f"{editor}/save", {"operation": "rename", "name": "z"}),
        (f"{editor}/delete", {}),
        (f"{editor}/run", {"kind": "synthetic_year", "count": "40"}),
    ):
        missing = client.post(path, data={"csrf_token": token, **extra})
        assert missing.status_code == 422, (path, missing.status_code)
        stale = client.post(path, data={"csrf_token": token, "expected_version": "99", **extra})
        assert stale.status_code in {409}, (path, stale.status_code)
    assert client.get(editor).status_code == 200  # nothing was deleted


def test_every_write_appends_an_audit_record_without_free_text(client, settings) -> None:
    secret_name = "Audit probe name 71f3"
    editor = create_fence(client, name=secret_name)
    scenario_id = editor.rsplit("/", 1)[1]
    run = run_it(client, editor, count="60")
    page = client.get(editor)
    client.post(f"{editor}/save", data={"csrf_token": csrf_of(page.text), "expected_version": version_of(page.text),
                                        "operation": "rename", "name": "Renamed audit probe 55c2"})
    page = client.get(editor)
    client.post(f"{editor}/delete", data={"csrf_token": csrf_of(page.text), "expected_version": version_of(page.text)})
    client.get(f"{run}/briefing/download?format=html")
    factory = open_factory(settings)
    try:
        with factory() as session:
            events = session.execute(
                select(audit_models.AuditEvent).where(audit_models.AuditEvent.action.like("policy.%"))
            ).scalars().all()
            mine = [e for e in events if scenario_id in json.dumps([e.target_id, e.references, e.metadata_json])
                    or e.target_id == run.rsplit("/", 1)[1]]
            actions = {e.action for e in mine}
            assert {"policy.scenario.create", "policy.scenario.edit", "policy.scenario.delete",
                    "policy.run.execute", "policy.brief.download"} <= actions
            blob = json.dumps([(e.reason, e.metadata_json) for e in mine])
            assert "Audit probe" not in blob and "Renamed audit" not in blob
            assert all(e.actor_id == ADMIN for e in mine if e.outcome == "accepted")
    finally:
        factory.dispose()


# --------------------------------------------------- scenarios and revisions


def test_the_list_offers_the_fence_suggestion_first_and_new_what_if(client) -> None:
    body = choose(client, ADMIN).get("/policy/scenarios").text
    assert "New what-if" in body
    first = re.findall(r'data-testid="policy-suggestion" data-suggestion="([^"]+)"', body)[0]
    assert first == "fence_height_7ft"
    assert "Raise the side/rear fence height limit from 6 ft to 7 ft" in body
    assert "unwinding" not in body.lower()


def test_each_edit_saves_a_revision_and_a_delete_is_soft(client, settings) -> None:
    editor = create_fence(client)
    response = add_change(client, editor, kind="service_target", permit_type_key="shed", service_target_days="3")
    assert response.status_code == 303
    page = client.get(editor)
    assert "Revision 2" in page.text and page.text.count('data-testid="policy-change"') == 2
    client.post(f"{editor}/save", data={"csrf_token": csrf_of(page.text), "expected_version": version_of(page.text),
                                        "operation": "remove_change", "change_index": "1"})
    page = client.get(editor)
    assert "Revision 3" in page.text and page.text.count('data-testid="policy-change"') == 1
    run = run_it(client, editor, count="50")
    page = client.get(editor)
    client.post(f"{editor}/delete", data={"csrf_token": csrf_of(page.text), "expected_version": version_of(page.text)})
    assert client.get(editor).status_code == 404
    assert editor.rsplit("/", 1)[1] not in client.get("/policy/scenarios").text.split("Recent runs")[0]
    # The run is kept and still readable after the soft delete.
    result = client.get(run)
    assert result.status_code == 200 and "what-if was deleted" in result.text
    factory = open_factory(settings)
    try:
        with factory() as session:
            row = session.get(models.PolicyScenario, editor.rsplit("/", 1)[1])
            assert row is not None and row.deleted_at is not None
            revisions = session.execute(select(models.PolicyScenarioRevision).where(
                models.PolicyScenarioRevision.scenario_id == row.id)).scalars().all()
            assert [r.revision_number for r in revisions] == [1, 2, 3]
    finally:
        factory.dispose()
    # A deleted scenario cannot be edited or run again.
    assert client.post(f"{editor}/run", data={"csrf_token": csrf_of(client.get("/policy/scenarios").text),
                                              "expected_version": "9"}).status_code == 404


def test_unsupported_kinds_show_the_explicit_response_and_block_the_run(client) -> None:
    editor = create_fence(client)
    for kind in ("no_permit_required", "conditional_plan_review_removal"):
        assert add_change(client, editor, kind=kind).status_code == 303
    page = client.get(editor).text
    assert 'data-testid="policy-unsupported"' in page
    assert "Not supported in this release" in page
    assert "Making a permit not required is not supported in this release" in page
    assert "Removing plan review for some cases only is not supported" in page
    assert "No permit required" in page and "conditional exemptions are not supported" in page
    # The run button is disabled, with the reason beside it.
    assert re.search(r'data-testid="policy-run-submit"[^>]*disabled', page)
    assert 'data-testid="policy-run-unsupported"' in page
    # A forced post is refused with the explicit response, and no run is made.
    response = client.post(f"{editor}/run", data={"csrf_token": csrf_of(page), "expected_version": version_of(page),
                                                  "kind": "synthetic_year", "count": "40"})
    assert response.status_code == 422 and "not supported in this release" in response.text


# ---------------------------------------------------------------- the results


def test_the_fence_run_results_screen(client, settings) -> None:
    before = business_snapshot(settings)
    editor = create_fence(client)
    run = run_it(client, editor, count="300")
    body = client.get(run).text
    assert business_snapshot(settings) == before, "saving and running a what-if writes no live row"
    assert "Synthetic year (sample data)" in body and 'data-testid="synthetic-badge"' in body
    for section in ("policy-outcomes", "policy-flipped", "policy-safety", "policy-holds", "policy-needs",
                    "policy-targets", "policy-fees"):
        assert f'data-testid="{section}"' in body, section
    assert re.search(r"<strong>\d+</strong> of 300 cases get a different result", body)
    assert "Relaxed" in body and 'data-direction="relaxed"' in body
    assert "Hypothetical assessed fees" in body and "changes no fee" in body
    assert body.count('data-testid="ui-info-btn"') >= 8, "every figure carries its definition"
    lowered = body.lower()
    for word in FORBIDDEN_CLAIMS:
        assert word not in lowered, word
    assert "unwinding" not in lowered
    # The identity drawer is the shared pattern and goes through the same grant.
    assert 'data-detail-kind="policy-run"' in body
    assert client.get(f"/policy/runs/{run.rsplit('/', 1)[1]}?detail=policy-run:{run.rsplit('/', 1)[1]}").status_code == 200
    detail = client.get(f"/detail/policy-run/{run.rsplit('/', 1)[1]}")
    assert detail.status_code == 200 and "Content hash" in detail.text
    choose(client, STEWARD)
    assert client.get(f"/detail/policy-run/{run.rsplit('/', 1)[1]}").status_code == 403


def test_retiring_df_2_explains_the_review_hold_in_plain_words(client) -> None:
    editor = create_fence(client, name="Retire the side/rear fence rule")
    page = client.get(editor)
    client.post(f"{editor}/save", data={"csrf_token": csrf_of(page.text), "expected_version": version_of(page.text),
                                        "operation": "remove_change", "change_index": "0"})
    assert add_change(client, editor, kind="rule_retirement", rule_id="DF-2").status_code == 303
    assert 'data-testid="policy-retire-note"' in client.get(editor).text
    run = run_it(client, editor, count="400")
    body = client.get(run).text
    assert 'data-testid="policy-added-holds"' in body and 'data-testid="policy-retire-holds"' in body
    assert "review hold rather than approving them" in body
    assert "do not know that category" in body


def test_a_fee_change_reports_hypothetical_assessed_fees_and_unpriceable_cases_apart(client) -> None:
    editor = create_fence(client, name="Fee change")
    page = client.get(editor)
    client.post(f"{editor}/save", data={"csrf_token": csrf_of(page.text), "expected_version": version_of(page.text),
                                        "operation": "remove_change", "change_index": "0"})
    assert add_change(client, editor, kind="fee", fee_schedule_id="fee_commercial_demo",
                      valuation_multiplier="0.002").status_code == 303
    run = run_it(client, editor, count="300")
    body = client.get(run).text
    assert 'data-testid="policy-fee-totals"' in body and "Hypothetical assessed fees" in body
    assert "not money collected" in body
    assert "Cases that cannot be priced" in body
    lowered = body.lower()
    for word in FORBIDDEN_CLAIMS:
        assert word not in lowered, word


def test_the_other_populations_are_labelled_as_a_retrospective_re_scoring(client) -> None:
    editor = create_fence(client, name="Stored populations")
    current = client.get(run_it(client, editor, kind="current_applications")).text
    assert "Retrospective re-scoring" in current and "Synthetic year (sample data)" not in current
    decided = client.get(run_it(client, editor, kind="decided_range", range_start="2020-01-01",
                                range_end="2030-01-01")).text
    assert "Retrospective re-scoring" in decided and "does not reconstruct the decisions" in decided
    bad = client.post(f"{editor}/run", data={"csrf_token": csrf_of(client.get(editor).text),
                                             "expected_version": version_of(client.get(editor).text),
                                             "kind": "decided_range", "range_start": "tomorrow"})
    assert bad.status_code == 422


# -------------------------------------------- immutable runs and the hashes


def test_a_run_is_immutable_and_its_content_hash_ignores_ids_and_times(settings) -> None:
    factory = open_factory(settings)
    try:
        with transaction(factory) as session:
            admin = actor_context(session, ADMIN)
            spec = {"kind": "synthetic_year", "seed": "31", "count": "80"}
            first_service = PolicyService(session, now=NOW)
            scenario = first_service.create_scenario(admin, name="Hash probe", changes=[
                {"kind": "rule_threshold", "rule_id": "DF-2", "limit_value": "7"}], expected_version=0)
            one = first_service.run_scenario(admin, scenario.id, expected_version=scenario.version, spec=spec)
            two = PolicyService(session, now=NOW).run_scenario(admin, scenario.id,
                                                              expected_version=scenario.version, spec=spec)
            assert one.id != two.id and one.created_at == two.created_at
            assert one.content_hash == two.content_hash and one.result_hash == two.result_hash
            # A different seed, or a different analysis moment, is a different run content.
            three = first_service.run_scenario(admin, scenario.id, expected_version=scenario.version,
                                               spec={**spec, "seed": "32"})
            assert three.content_hash != one.content_hash
            later = PolicyService(session, now=datetime(2026, 10, 29, tzinfo=UTC)).run_scenario(
                admin, scenario.id, expected_version=scenario.version, spec=spec)
            assert later.content_hash != one.content_hash
            # The snapshot holds everything the brief names.
            assert one.scenario_revision_number == 1 and one.scenario_name == "Hash probe"
            assert one.baseline_config["permit_types"] and one.proposed_config["rules"]
            assert len(one.case_inputs) == 80 and one.case_inputs[0]["case_ref"] == "SYNTH-000001"
            assert one.population_definition["synthetic"] is True
            assert one.engine_version and one.generator_version and one.analysis_at == NOW
            # The stored snapshot still hashes to its content hash, and a tampered copy does not.
            assert first_service.verify_run(admin, one) is True
            tampered = dict(one.case_inputs[0], permit_type_key="shed")
            assert runs_module.content_hash_from_snapshot(
                changes=[{"kind": "rule_threshold", "rule_id": "DF-2", "limit_value": "7"}],
                scenario_name=one.scenario_name, baseline_config=one.baseline_config,
                proposed_config=one.proposed_config, case_inputs=[tampered, *one.case_inputs[1:]],
                population_definition=one.population_definition, analysis_at=one.analysis_at.isoformat(),
                engine_version=one.engine_version, generator_version=one.generator_version,
            ) != one.content_hash
            # Immutable: an update or a delete is refused.
            one.population_size = 1
            with pytest.raises(models.ImmutableRunError):
                session.flush()
            session.rollback()
    finally:
        factory.dispose()


def test_a_baseline_run_with_no_change_effect_shows_zero_effects_honestly(client) -> None:
    editor = create_fence(client, name="A change that touches no sampled case")
    page = client.get(editor)
    client.post(f"{editor}/save", data={"csrf_token": csrf_of(page.text), "expected_version": version_of(page.text),
                                        "operation": "remove_change", "change_index": "0"})
    assert add_change(client, editor, kind="service_target", permit_type_key="shed",
                      service_target_days="3").status_code == 303
    body = client.get(run_it(client, editor, count="120")).text
    assert "<strong>0</strong> of 120 cases get a different result" in body
    assert "No case changes direction" in body


# ------------------------------------------------------------- the briefing


def test_the_briefing_is_deterministic_typed_and_labelled(client) -> None:
    editor = create_fence(client)
    run = run_it(client, editor, count="300")
    first = client.get(f"{run}/briefing").text
    second = client.get(f"{run}/briefing").text
    assert _strip_tokens(first) == _strip_tokens(second), "the same run gives the same briefing"
    assert "Deterministic briefing built from the typed facts of this run. No model was used." in first
    assert 'data-testid="policy-briefing-synthetic"' in first and "Synthetic data" in first
    assert "Fictional ACME City data. Impact estimates come from the ACME permit engine. They forecast no staff time and give no legal opinion." in first
    assert 'data-testid="policy-download-html"' in first and "Download (HTML)" in first
    assert "ACME Code §14-306" in first
    lowered = first.lower()
    for word in FORBIDDEN_CLAIMS:
        assert word not in lowered, word


def _strip_tokens(body: str) -> str:
    body = re.sub(r'name="csrf_token" value="[^"]+"', "", body)
    return re.sub(r"ui-info-\d+", "ui-info", body)


def test_every_figure_of_the_briefing_text_comes_from_a_typed_fact(settings) -> None:
    factory = open_factory(settings)
    try:
        with transaction(factory) as session:
            admin = actor_context(session, ADMIN)
            service = PolicyService(session, now=NOW)
            scenario = service.create_scenario(admin, name="Facts probe", changes=[
                {"kind": "rule_threshold", "rule_id": "DF-2", "limit_value": "7"},
                {"kind": "service_target", "permit_type_key": "shed", "service_target_days": 3}],
                expected_version=0)
            run = service.run_scenario(admin, scenario.id, expected_version=scenario.version,
                                       spec={"kind": "synthetic_year", "seed": "9", "count": "200"})
            brief = briefing_module.build_briefing(run)
            facts = {str(f.value) for f in brief.facts}
            for fact in brief.facts:
                assert fact.unit and fact.direction in {"increase", "decrease", "unchanged", "none"}
                assert fact.population == run.population_label
                assert fact.baseline_id.startswith("baseline ") and fact.scenario_id.startswith("scenario ")
            narrative = " ".join(p for s in brief.sections if s.heading in {"What changes", "Holds and missing information"}
                                 for p in s.paragraphs[:2])
            # Keep the counts only (drop rule ids such as DF-2 and section numbers).
            numbers = set(re.findall(r"(?<![\w§.-])\d+(?![\w-])", narrative))
            assert numbers, "the narrative states counts"
            assert numbers <= facts | {str(run.population_size)}, numbers - facts
            for section in brief.sections:
                if section.table:
                    for row in section.table.rows:
                        for cell in row[1:]:
                            if cell.isdigit():
                                assert cell in facts
    finally:
        factory.dispose()


def test_the_muse_seam_is_named_and_empty_in_this_release() -> None:
    assert briefing_module.MUSE_BRIEFING_WRITER is None
    assert hasattr(briefing_module, "BriefingWriter")


def test_downloads_are_attachments_and_every_text_is_escaped(client) -> None:
    hostile = '<script>alert(1)</script> & "quoted" *bold* [link](http://x.invalid)'
    editor = create_fence(client, name=hostile)
    run = run_it(client, editor, count="60")
    html = client.get(f"{run}/briefing/download?format=html")
    assert html.status_code == 200 and html.headers["content-type"].startswith("text/html")
    assert "attachment;" in html.headers["content-disposition"] and html.headers["x-content-type-options"] == "nosniff"
    assert "<script>" not in html.text and "&lt;script&gt;" in html.text
    assert "<script" not in html.text.lower().replace("&lt;script", "")
    assert "src=" not in html.text and "href=" not in html.text, "self-contained: no outside asset or link"
    assert "Synthetic data" in html.text and "Fictional ACME City data." in html.text
    md = client.get(f"{run}/briefing/download?format=md")
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert "<script>" not in md.text and "\\<script\\>" in md.text and "\\[link\\]" in md.text
    assert "\\*bold\\*" in md.text
    assert client.get(f"{run}/briefing/download?format=exe").status_code == 422
    onscreen = client.get(f"{run}/briefing").text
    assert "<script>alert(1)</script>" not in onscreen


# ---------------------------------------------------- the City view control


def test_the_city_view_starts_a_what_if_with_the_current_filter(client) -> None:
    body = choose(client, ADMIN).get("/insight/city?type=deck_fence&category=restaurant,bar").text
    match = re.search(r'href="(/policy/scenarios\?[^"]+)" data-testid="start-whatif"', body)
    assert match
    link = match.group(1).replace("&amp;", "&")
    assert "type=deck_fence" in link and "category=restaurant%2Cbar" in link
    page = client.get(link)
    assert page.status_code == 200 and 'data-testid="policy-starting"' in page.text
    assert "permit type deck_fence" in page.text and "business category restaurant,bar" in page.text
    # The starting population is carried into the saved what-if.
    token = csrf_of(page.text)
    response = client.post("/policy/scenarios", data={
        "csrf_token": token, "expected_version": "0", "suggestion": "fence_height_7ft", "name": "From the City view",
        "start_permit_type": "deck_fence"}, follow_redirects=False)
    editor = client.get(response.headers["location"].split("?")[0]).text
    assert "Starting population from the City view: permit type deck_fence" in editor
    assert 'value="deck_fence" selected' in editor
    narrowed = client.get(run_it(client, response.headers["location"].split("?")[0], count="200", permit_type="deck_fence")).text
    assert "narrowed to type deck_fence" in narrowed


def test_the_navigation_lists_the_what_if_screen_for_the_administrator_only(client) -> None:
    for actor, listed in ((ADMIN, True), (APPLICANT, False), (STEWARD, False), (REVIEWER, False)):
        choose(client, actor)
        page = client.get("/queue", follow_redirects=True) if actor != APPLICANT else client.get("/applicants")
        keys = re.findall(r'data-screen-key="([^"]+)"', page.text)
        assert ("policy_scenarios" in keys) is listed, actor
    body = choose(client, STEWARD).get("/insight/city")
    assert body.status_code == 403
