"""The governed actions of the steward assistant.

``ui/router.py`` merges ``HANDLERS`` into ``ACTION_HANDLERS``, so the lane
adds its actions here and never in the router body.

Four actions carry the work of the assistant:

* ``steward.assist.prepare``     prepare the recommendations of the tasks of
  the queue, at most twenty of them per press;
* ``steward.assist.recommend``   prepare the recommendation of one task;
* ``steward.assist.clear``       clear a recommendation the steward does not
  want;
* ``steward.assist.accept``      accept a recommendation.

A fifth action, ``steward.assist.batch_accept``, accepts the list of
recommendations the steward confirmed in the preview.  It is a sequence of
the single acceptances and nothing else: every item goes through the same
path, and an item that changed since the preview is skipped and named.  The
confirmation carries the list of the preview with the versions it showed and
the proof of that list, so a confirmation of another list is refused.

The accept does not write on its own: it goes through the existing service
action of the task kind, with the steward as the decider of record, and it
records the recommendation in the audit trail.
"""
# REQUIRES: PER-04, SEC-01, UX-01
# The assistant proposes and the steward decides.  Nothing runs without the
# grant of the Data Steward and an awake assistant, and every write that
# follows an accepted recommendation goes through the existing service.

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from acme_city.agents import steward_assist as assistant
from acme_city.agents.control import AgentControlService
from acme_city.audit.service import AuditService
from acme_city.core.clock import utc_now
from acme_city.core.errors import NotFoundError, ValidationError
from acme_city.persistence.models.steward_recommendation import StewardRecommendation
from acme_city.registry import steward_assist as recommenders
from acme_city.ui import steward_assist_views
from acme_city.ui.router import ActionContext, Outcome


def _tasks_of_the_queue(
    session: Any,
    actor: Any,
    *,
    query: str = "",
    record_type: str = "",
    source: str = "",
) -> list[recommenders.Task]:
    """Return the tasks of the needs-review view the button may prepare."""
    from acme_city.ui import steward_queue_views, steward_views

    issues = steward_views.collect_issues(session, actor)
    chosen = [
        issue
        for issue in issues
        if steward_queue_views.matches(issue, "needs_review", actor.actor_id)
        and steward_queue_views.matches_query(issue, query)
        and steward_queue_views.matches_record_type(issue, record_type)
        and steward_queue_views.matches_source(issue, source)
    ]
    ordered = steward_queue_views.order_tasks(chosen)
    return [recommenders.Task(issue.kind, issue.item_id) for issue in ordered]


def _prepare(ctx: ActionContext) -> Outcome:
    """Prepare the recommendations of the tasks of the queue.

    One press prepares at most twenty tasks: a long queue is worked in
    bounded steps, and the steward presses again for the rest.
    """
    tasks = _tasks_of_the_queue(
        ctx.session,
        ctx.actor,
        query=ctx.text("q"),
        record_type=ctx.text("record_type"),
        source=ctx.text("source"),
    )
    if not tasks:
        return Outcome(
            message="There is no task that needs a recommendation right now.",
            destination="Data issues",
            state="skipped",
            target_type="agent_run",
            target_id="",
        )
    result = assistant.prepare(
        ctx.session, tasks=tasks, actor=ctx.actor, settings=ctx.settings
    )
    message = (
        f"Prepared {len(result.recommendations)} recommendation"
        f"{'' if len(result.recommendations) == 1 else 's'} for the queue."
    )
    if len(tasks) > assistant.MAX_TASKS_PER_PRESS:
        message += (
            f" The press was bounded to {assistant.MAX_TASKS_PER_PRESS} tasks; "
            "press it again for the rest."
        )
    if result.refused:
        message += f" {len(result.refused)} task(s) could not be prepared."
    return Outcome(
        message=message,
        destination="Data issues",
        state=result.run.outcome,
        target_type="agent_run",
        target_id=result.run.id,
        after_version=len(result.recommendations),
        affected=tuple(row.id for row in result.recommendations),
        extra={
            "detail": result.run.outcome_detail,
            "prepared": len(result.recommendations),
            "refused": [f"{kind}:{item}" for kind, item in result.refused],
        },
    )


def _run_from_the_screen(ctx: ActionContext) -> Outcome:
    """Run the assistant on the tasks that are still waiting.

    The awake check comes first.  An empty queue is refused before the
    assistant is asked to prepare anything, so a second press does not
    record a skipped run.
    """
    from acme_city.ui.agent_views import steward_batch_limit, steward_waiting_tasks

    AgentControlService(ctx.session).authorize_manual_run(ctx.actor, assistant.AGENT_KEY)
    waiting = steward_waiting_tasks(ctx.session, ctx.actor)
    if not waiting:
        raise ValidationError("Nothing is waiting")
    chosen = [
        recommenders.Task(issue.kind, issue.item_id)
        for issue in waiting[: steward_batch_limit(ctx.session)]
    ]
    if not chosen:
        raise ValidationError("Nothing is waiting")
    result = assistant.prepare(
        ctx.session, tasks=chosen, actor=ctx.actor, settings=ctx.settings
    )
    inputs = dict(result.run.inputs or {})
    inputs["batch_id"] = uuid4().hex
    result.run.inputs = inputs
    ctx.session.flush()
    count = len(result.recommendations)
    return Outcome(
        message=f"The steward assistant ran on {count} waiting task(s).",
        destination="Steward assistant",
        state=result.run.outcome,
        target_type="agent_run",
        target_id=result.run.id,
        after_version=count,
        affected=tuple(row.id for row in result.recommendations),
    )


def _recommend(ctx: ActionContext) -> Outcome:
    """Prepare the recommendation of one task of the queue."""
    kind = ctx.text("task_kind")
    item_id = ctx.text("task_id")
    if kind not in recommenders.TASK_KINDS:
        raise ValidationError(f"the assistant prepares no recommendation for a {kind!r} task")
    if not item_id:
        raise ValidationError("the request names no task")
    result = assistant.prepare(
        ctx.session,
        tasks=[recommenders.Task(kind, item_id)],
        actor=ctx.actor,
        settings=ctx.settings,
    )
    if not result.recommendations:
        detail = result.refused[0][1] if result.refused else "the task could not be prepared"
        raise ValidationError(detail)
    row = result.recommendations[0]
    return Outcome(
        message=(
            f"The steward assistant prepared a recommendation for this task: "
            f"{row.reason}"
        ),
        destination="Data issues",
        state=row.confidence,
        target_type="steward_recommendation",
        target_id=row.id,
        after_version=row.version,
        affected=(row.id,),
    )


def _clear(ctx: ActionContext) -> Outcome:
    """Clear the recommendation of one task of the queue."""
    kind = ctx.text("task_kind")
    item_id = ctx.text("task_id")
    row = assistant.clear(
        ctx.session, task_kind=kind, task_id=item_id, actor=ctx.actor
    )
    return Outcome(
        message="The recommendation was cleared. The task holds none.",
        destination="Data issues",
        state="cleared",
        target_type="steward_recommendation",
        target_id=row.id,
        after_version=row.version,
    )


def _accept_target(
    session: Any, recommendation: Any, reason: str
) -> tuple[str, dict[str, str]]:
    """Return the existing action of the task kind and the fields it needs.

    The recommendation proposes an outcome; the existing action of the task
    kind performs it.  The steward is the actor of that action, so the
    decision of record is the steward's.

    The version that travels with the action is the version the
    recommendation read, so a link that changed since is refused instead of
    decided on facts nobody read.
    """
    kind = recommendation.task_kind
    outcome = recommendation.outcome
    evidence = dict(recommendation.evidence or {})

    if kind == "link":
        source_system_id = str(evidence.get("source_system", ""))
        source_record_id = str(evidence.get("source_record_id", ""))
        crosswalk_id = str(evidence.get("crosswalk_id", ""))
        if not crosswalk_id:
            raise ValidationError(
                "this source record holds no link a decision could apply to"
            )
        fields = {
            "source_system_id": source_system_id,
            "dataset_key": str(evidence.get("source_dataset", "")),
            "source_record_id": source_record_id,
            "crosswalk_id": crosswalk_id,
            "expected_version": str(int(evidence.get("crosswalk_version") or 0)),
            "reason": reason,
        }
        if outcome == recommenders.OUTCOME_CONFIRM:
            entity_id = str(evidence.get("candidate_entity_id", ""))
            if not entity_id:
                raise ValidationError(
                    "the recommendation names no master record to link to"
                )
            fields["entity_id"] = entity_id
            return "registry.decide", fields
        if outcome == recommenders.OUTCOME_REJECT:
            fields["decision"] = "reject"
            return "registry.decide", fields
        raise ValidationError(
            "this recommendation proposes no decision of a record match"
        )

    if kind == "automatic_link":
        application_id = str(evidence.get("application_id", ""))
        if outcome == recommenders.OUTCOME_KEEP:
            return "registry.automation.review", {
                "application_id": application_id,
                "note": reason,
            }
        if outcome == recommenders.OUTCOME_UNDO:
            crosswalk_id = str(evidence.get("crosswalk_id", ""))
            if not crosswalk_id:
                raise ValidationError("the applied link could not be read")
            return "registry.automation.undo", {
                "application_id": application_id,
                "expected_version": str(int(evidence.get("crosswalk_version") or 0)),
                "reason": reason,
            }
        raise ValidationError(
            "this recommendation proposes no decision of an applied link"
        )

    if kind == "parcel":
        if outcome == recommenders.OUTCOME_APPROVE_PARCEL:
            decision = "approve"
        elif outcome == recommenders.OUTCOME_NONE_FITS:
            decision = "reject"
        else:
            raise ValidationError(
                "this recommendation proposes no decision of a parcel link"
            )
        return "parcel.link.decide", {
            "application_id": recommendation.task_id,
            "decision": decision,
            "expected_version": str(recommendation.record_version),
            "reason": reason,
        }

    if kind == "case":
        if outcome != recommenders.OUTCOME_ACCEPT:
            raise ValidationError(
                "this recommendation proposes no decision of a correction"
            )
        from acme_city.changes.state_machine import allowed_transitions
        from acme_city.persistence.models import change

        case = session.get(change.ChangeCase, recommendation.task_id)
        if case is None:
            raise NotFoundError("the correction this task is about does not exist")
        target = _next_state(case, allowed_transitions(case.status, case.change_kind))
        if target is None:
            raise ValidationError(
                "this correction has no further state a person may move it to"
            )
        return "change.transition", {
            "change_case_id": case.id,
            "to_status": target,
            "expected_version": str(recommendation.record_version),
            "reason": reason,
        }

    raise ValidationError(
        "this task kind has no action a recommendation could be accepted with"
    )


def _next_state(case: Any, transitions: Any) -> str | None:
    """Return the state a correction moves to when it is accepted.

    The correction moves one step along the path to the source: the states
    that end it and the states that only the dispatcher reaches are never
    chosen here.  A step that needs a separate approver is left to the last
    resort, so a person who may approve never loses the step.
    """
    steps = [
        rule
        for rule in transitions
        if str(getattr(rule, "target_status", rule)) not in {"rejected", "closed"}
        and not getattr(rule, "performed_by_dispatcher", False)
    ]
    if not steps:
        return None
    for rule in steps:
        if not getattr(rule, "requires_approver", False):
            return str(getattr(rule, "target_status", rule))
    return str(getattr(steps[0], "target_status", steps[0]))


def _dispatch(ctx: ActionContext, action_id: str, form: dict[str, str]) -> Outcome:
    """Run the existing action of the task kind with the given fields."""
    from acme_city.ui.router import ACTION_HANDLERS

    handler = ACTION_HANDLERS.get(action_id)
    if handler is None:
        raise ValidationError(f"the interface has no action {action_id!r}")
    inner = ActionContext(
        session=ctx.session,
        actor=ctx.actor,
        form=form,
        settings=ctx.settings,
    )
    return handler(inner)


def _accept_one(ctx: ActionContext, recommendation: Any, reason: str) -> Outcome:
    """Accept one recommendation through the existing action of its task kind.

    The write goes through the existing action of the task kind, so the
    steward is the decider of record and the service of the City writes as
    it always does.  The recommendation is recorded in the audit trail and
    cleared, so the task holds no answer twice.

    The decision records whether the steward took the reason of the assistant
    as it was.  The reason the assistant prepared and the words Muse wrote for
    it are the same decision, so either of them counts as unchanged.

    The single acceptance and the batch use this one path, so a batch is
    never more than a sequence of the decisions a steward takes one by one.
    """
    action_id, form = _accept_target(ctx.session, recommendation, reason)
    outcome = _dispatch(ctx, action_id, form)
    unchanged = _reason_unchanged(recommendation, reason)
    AuditService(ctx.session).append(
        action="steward.recommendation.accept",
        actor=ctx.actor,
        target_type=outcome.target_type or "steward_recommendation",
        target_id=outcome.target_id or recommendation.task_id,
        after_version=outcome.after_version,
        reason=reason,
        references=[recommendation.id, recommendation.task_id],
        metadata={
            "recommendation_id": recommendation.id,
            "task_kind": recommendation.task_kind,
            "task_id": recommendation.task_id,
            "confidence": recommendation.confidence,
            "outcome": recommendation.outcome,
            "action_id": action_id,
            "reason_unchanged": unchanged,
            "prepared_reason": recommendation.reason,
        },
    )
    recommendation.cleared = True
    recommendation.cleared_at = utc_now()
    recommendation.version += 1
    ctx.session.flush()
    return Outcome(
        message=f"{outcome.message} The recommendation was accepted.",
        destination=outcome.destination,
        state=outcome.state,
        pending=outcome.pending,
        target_type=outcome.target_type or "steward_recommendation",
        target_id=outcome.target_id or recommendation.task_id,
        after_version=outcome.after_version,
        affected=tuple(outcome.affected) + (recommendation.id,),
        extra={
            **dict(outcome.extra),
            "detail": outcome.extra.get("detail", ""),
            "recommendation_id": recommendation.id,
        },
    )


def _reason_unchanged(recommendation: Any, reason: str) -> bool:
    """Whether the steward took the reason of the assistant as it was.

    The reason the assistant prepared is the reason of the recommendation.
    The words Muse wrote for it say the same thing in other words, so a
    steward who took those words took the reason as it was.  A reason the
    steward wrote is a change, and it is recorded as one.
    """
    prepared = {
        str(recommendation.reason or ""),
        str(recommendation.muse_reason or ""),
    } - {""}
    return bool(prepared) and reason in prepared


def _accept(ctx: ActionContext) -> Outcome:
    """Accept a recommendation of the steward assistant.

    The write goes through the existing action of the task kind, so the
    steward is the decider of record and the service of the City writes as
    it always does.  The recommendation is recorded in the audit trail and
    cleared, so the task holds no answer twice.

    A recommendation that may not be accepted is refused with the reason of
    the guard, in the words the button carries beside it, so the person reads
    why on the page the work is on.
    """
    recommendation_id = ctx.text("recommendation_id")
    if not recommendation_id:
        raise ValidationError("the request names no recommendation")
    # Accepting a recommendation is the work of the Data Steward: the grant of
    # the assistant is checked, and the service of the task kind checks its
    # own grant again.  A sleeping assistant does not stop the steward from
    # deciding.
    AgentControlService(ctx.session).authorize_run(ctx.actor, assistant.AGENT_KEY)
    recommendation = assistant.recommendation_by_id(ctx.session, recommendation_id)
    if recommendation.cleared:
        return _refused(
            recommendation,
            steward_assist_views.CLEARED_ACCEPT_NOTE,
            "cleared",
        )
    try:
        assistant.refuse_unless_acceptable(ctx.session, recommendation)
    except ValidationError:
        refusal = steward_assist_views.accept_refusal(ctx.session, recommendation)
        if not refusal:
            raise
        return _refused(recommendation, refusal, "refused")
    reason = ctx.text("reason") or recommendation.reason
    return _accept_one(ctx, recommendation, reason)


def _refused(recommendation: Any, message: str, state: str) -> Outcome:
    """Return the refusal of an acceptance, with nothing changed.

    The refusal is recorded in the audit trail and reported in the feedback
    region of the page the person came from, so the reason is read where the
    work is.
    """
    return Outcome(
        message=message,
        destination="Data issues",
        state=state,
        target_type="steward_recommendation",
        target_id=recommendation.id,
        refused=True,
        extra={"detail": message},
    )


def _batch_accept(ctx: ActionContext) -> Outcome:
    """Accept the recommendations the steward confirmed in the preview.

    The confirmed set is the previewed set.  The preview names every item
    with the version it showed, and the proof of the preview travels with the
    form: a confirmation that names another list, or another version of a
    recommendation, is refused instead of accepted.

    Every item goes through the same path as a single acceptance, so the
    stale guard and the held guard of the assistant apply to it as well.  An
    item that went stale, that changed its confidence or that was cleared
    since the preview is skipped and named: it is never accepted silently.
    """
    items = ctx.values(steward_assist_views.PREVIEW_FIELD) or ctx.values(
        "recommendation_id"
    )
    AgentControlService(ctx.session).authorize_run(ctx.actor, assistant.AGENT_KEY)
    if not items:
        raise ValidationError("the request names no recommendation")
    if not steward_assist_views.preview_confirmed(
        ctx.settings, items, ctx.text(steward_assist_views.PREVIEW_DIGEST_FIELD)
    ):
        raise ValidationError(steward_assist_views.PREVIEW_MISMATCH_MESSAGE)
    labels = steward_assist_views.task_labels(ctx.session, ctx.actor)
    accepted: list[str] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        identifier, _, version = str(item).rpartition(":")
        if not identifier:
            identifier, version = str(item), ""
        if identifier in seen:
            continue
        seen.add(identifier)
        recommendation = ctx.session.get(StewardRecommendation, identifier)
        if recommendation is None:
            skipped.append(
                {"id": identifier, "label": identifier, "reason": "it does not exist"}
            )
            continue
        label = labels.get(
            (recommendation.task_kind, recommendation.task_id), recommendation.task_id
        )
        if recommendation.cleared:
            skipped.append(
                {"id": identifier, "label": label, "reason": "it was cleared"}
            )
            continue
        if version and version.isdigit() and int(version) != int(recommendation.version):
            skipped.append(
                {
                    "id": identifier,
                    "label": label,
                    "reason": "it changed since the list you were shown",
                }
            )
            continue
        refusal = recommenders.batch_refusal(recommendation)
        if refusal:
            skipped.append({"id": identifier, "label": label, "reason": refusal})
            continue
        if assistant.is_stale(ctx.session, recommendation):
            skipped.append(
                {"id": identifier, "label": label, "reason": assistant.STALE_MESSAGE}
            )
            continue
        _accept_one(ctx, recommendation, recommendation.reason)
        accepted.append(identifier)

    message = f"Accepted {len(accepted)} of {len(seen)} recommendation(s)."
    if skipped:
        message += " Skipped: " + "; ".join(
            f"{item['label']} ({item['reason']})" for item in skipped
        )
    AuditService(ctx.session).append(
        action="steward.assist.batch_accept",
        actor=ctx.actor,
        target_type="steward_recommendation",
        target_id="",
        after_version=len(accepted),
        reason=message,
        references=list(accepted),
        metadata={
            "agent_key": assistant.AGENT_KEY,
            "accepted": list(accepted),
            "skipped": list(skipped),
        },
    )
    return Outcome(
        message=message,
        destination="Data issues",
        state="accepted" if accepted else "skipped",
        target_type="steward_recommendation",
        target_id="",
        after_version=len(accepted),
        affected=tuple(accepted),
        extra={
            "detail": message,
            "accepted": list(accepted),
            "skipped": list(skipped),
        },
    )


def _explain(ctx: ActionContext) -> Outcome:
    """Ask Muse to rewrite the reason of one recommendation in plain words.

    Muse rewrites the words and nothing else: the outcome and the confidence
    of the recommendation stay what the City decided.  The attempt is
    recorded, whether it succeeded or not, and a refused call leaves the
    deterministic reason of the assistant standing.
    """
    from acme_city.agents import steward_explain

    recommendation_id = ctx.text("recommendation_id")
    if not recommendation_id:
        raise ValidationError("the request names no recommendation")
    AgentControlService(ctx.session).authorize_run(ctx.actor, assistant.AGENT_KEY)
    recommendation = assistant.recommendation_by_id(ctx.session, recommendation_id)
    if recommendation.cleared:
        raise ValidationError("this recommendation was cleared; prepare it again")
    result = steward_explain.explain(
        ctx.session, ctx.settings, recommendation, actor_id=ctx.actor.actor_id
    )
    if not result.explained:
        AuditService(ctx.session).append(
            action="steward.recommendation.explain",
            actor=ctx.actor,
            target_type="steward_recommendation",
            target_id=recommendation.id,
            after_version=recommendation.version,
            reason=f"the explanation was refused: {result.error}",
            references=[recommendation.id, result.run_id],
            metadata={
                "recommendation_id": recommendation.id,
                "task_kind": recommendation.task_kind,
                "task_id": recommendation.task_id,
                "model_run_id": result.run_id,
                "refused": True,
                "error": result.error,
            },
        )
        ctx.session.flush()
        return Outcome(
            message=(
                f"Muse could not rewrite the reason: {result.error}. "
                "The assistant's reason stands."
            ),
            destination="Data issues",
            state="refused",
            target_type="steward_recommendation",
            target_id=recommendation.id,
            after_version=recommendation.version,
            extra={"detail": result.error, "model_run_id": result.run_id},
        )
    recommendation.muse_reason = result.text
    recommendation.muse_run_id = result.run_id
    recommendation.version += 1
    AuditService(ctx.session).append(
        action="steward.recommendation.explain",
        actor=ctx.actor,
        target_type="steward_recommendation",
        target_id=recommendation.id,
        after_version=recommendation.version,
        reason="Muse rewrote the reason in plain words.",
        references=[recommendation.id, result.run_id],
        metadata={
            "recommendation_id": recommendation.id,
            "task_kind": recommendation.task_kind,
            "task_id": recommendation.task_id,
            "model_run_id": result.run_id,
            "refused": False,
        },
    )
    ctx.session.flush()
    return Outcome(
        message=(
            "Muse rewrote the reason in plain words. The decision and the "
            "certainty of the recommendation did not change."
        ),
        destination="Data issues",
        state="explained",
        target_type="steward_recommendation",
        target_id=recommendation.id,
        after_version=recommendation.version,
        affected=(recommendation.id,),
        extra={"detail": result.text, "model_run_id": result.run_id},
    )


#: The interface actions of the lane, keyed by their stable identifier.
HANDLERS: dict[str, Callable[[ActionContext], Outcome]] = {
    "agent.run.steward_assist": _run_from_the_screen,
    "steward.assist.prepare": _prepare,
    "steward.assist.recommend": _recommend,
    "steward.assist.clear": _clear,
    "steward.assist.accept": _accept,
    "steward.assist.batch_accept": _batch_accept,
    "steward.assist.explain": _explain,
}

__all__ = ["HANDLERS"]
