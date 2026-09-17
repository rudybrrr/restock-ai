"""PostgreSQL acceptance coverage for the local supplier replanning slice."""

from datetime import datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src import changes, planning
from src import database as db
from src.agent_contracts import (
    AgentOutcome,
    AgentToolName,
    AuditAction,
    RecommendedNextStep,
    StateRevisionStaleError,
)
from src.backend_control_plane import run_backend_coordinator
from src.decision_engine_adapter import BackendProcurementTools
from src.errors import ApiError
from src.planning_schemas import PlanDecision
from src.procurement_specialist import (
    ProcurementDecisionAction,
    ProcurementModelDecision,
    ProcurementReasoningContext,
)

ISSUE_TIME = datetime.fromisoformat("2026-02-15T22:00:00+08:00")


class ProcurementOnlyClassifier:
    def classify(self, invocation, context_refs):
        from src.agent_contracts import SpecialistType

        return [SpecialistType.PROCUREMENT]


class SupplierReplanScript:
    """Scripted local reasoning; Backend tools own all supplier calculations."""

    def decide(self, context: ProcurementReasoningContext) -> ProcurementModelDecision:
        sequence = (
            AgentToolName.GET_SUPPLIER_OPTIONS,
            AgentToolName.CHECK_SUPPLIER_FEASIBILITY,
            AgentToolName.OPTIMISE_PURCHASE_PLAN,
            AgentToolName.VALIDATE_PURCHASE_PLAN,
        )
        call = len(context.tool_results)
        if call < len(sequence):
            return ProcurementModelDecision(
                run_id=context.delegation.run_id,
                task_id=context.delegation.task_id,
                action=ProcurementDecisionAction.CALL_TOOL,
                tool=sequence[call],
                input_refs=[
                    context.delegation.trigger_ref
                    if call == 0
                    else context.tool_results[-1].output_ref
                ],
                interpreted_impact="Inspect the authoritative supplier disruption.",
                summary="Continue the bounded deterministic procurement investigation.",
            )
        return ProcurementModelDecision(
            run_id=context.delegation.run_id,
            task_id=context.delegation.task_id,
            action=ProcurementDecisionAction.COMPLETE,
            interpreted_impact="A validated deterministic replacement exists.",
            recommended_next_step=RecommendedNextStep.SUBMIT_REVISION,
            summary="Submit the validated replacement.",
        )


class RecordingBackendTools(BackendProcurementTools):
    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.calls: list[AgentToolName] = []

    def execute(self, request):
        self.calls.append(request.tool)
        return super().execute(request)


def publish_initial_plan(session: Session):
    requested = planning.request_run(session, ISSUE_TIME)
    run = planning.claim_run(session)
    assert run.id == requested.id
    result = run_backend_coordinator(
        session,
        run.id,
        SupplierReplanScript(),
        BackendProcurementTools(session),
        manual_classifier=ProcurementOnlyClassifier(),
    )
    assert result.completion.outcome is AgentOutcome.REVISE_PLAN
    assert result.publication_result is not None
    assert result.publication_result.created_plan_version is not None
    return result.publication_result.created_plan_version


def claim_supplier_change(session: Session, offer_id: str, **change):
    changes.change_supplier(
        session,
        offer_id,
        changes.SupplierChange(effective_at=ISSUE_TIME, **change),
        "manager",
    )
    return planning.claim_run(session)


def version_id(session: Session, plan) -> str:
    return session.execute(
        select(db.plan_versions.c.id).where(
            db.plan_versions.c.plan_id == plan.plan_id,
            db.plan_versions.c.version == plan.version,
        )
    ).scalar_one()


def test_unrelated_supplier_change_keeps_current_plan_without_procurement(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            first = publish_initial_plan(session)
            first_id = version_id(session, first)
            run = claim_supplier_change(
                session, "market-chicken", current_status="UNAVAILABLE"
            )
            tools = RecordingBackendTools(session)
            result = run_backend_coordinator(
                session,
                run.id,
                SupplierReplanScript(),
                tools,
            )

            assert result.completion.outcome is AgentOutcome.KEEP_CURRENT_PLAN
            assert tools.calls == []
            assert result.publication_result is not None
            assert result.publication_result.created_plan_version is None
            assert planning.read_plan(session, first_id).status.value == "PENDING_APPROVAL"
            materiality = next(
                event
                for event in result.trace
                if event.action is AuditAction.MATERIALITY_ASSESSED
            )
            assert materiality.materiality is not None
            assert materiality.materiality.material is False
            assert materiality.materiality.source_event_ids
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("change", "approve_first"),
    (
        ({"current_status": "UNAVAILABLE"}, False),
        ({"available_quantity": 0}, False),
        ({"current_status": "UNAVAILABLE"}, True),
    ),
)
def test_selected_supplier_unavailable_publishes_replacement_then_supersedes(
    database_url: str,
    change: dict[str, object],
    approve_first: bool,
) -> None:
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            first = publish_initial_plan(session)
            first_id = version_id(session, first)
            if approve_first:
                assert (
                    planning.decide_plan(
                        session,
                        first_id,
                        PlanDecision(
                            plan_id=first.plan_id,
                            plan_version=first.version,
                            decision="APPROVED",
                        ),
                        "manager",
                    ).status.value
                    == "APPROVED"
                )
            selected = next(line.offer_id for line in first.lines if line.ingredient_id == "chicken")
            assert selected is not None
            run = claim_supplier_change(session, selected, **change)
            tools = RecordingBackendTools(session)
            result = run_backend_coordinator(
                session, run.id, SupplierReplanScript(), tools
            )

            assert result.completion.outcome is AgentOutcome.REVISE_PLAN
            assert result.publication_result is not None
            second = result.publication_result.created_plan_version
            assert second is not None
            assert second.version == 2
            assert second.status.value == "PENDING_APPROVAL"
            assert planning.read_plan(session, first_id).status.value == "SUPERSEDED"
            assert all(line.offer_id != selected for line in second.lines)
            materiality = next(
                event
                for event in result.trace
                if event.action is AuditAction.MATERIALITY_ASSESSED
            )
            assert materiality.materiality is not None
            assert materiality.materiality.affected_offer_ids == [selected]
            actionable = session.execute(
                select(db.plan_versions.c.id).where(
                    db.plan_versions.c.status.in_(("PENDING_APPROVAL", "APPROVED"))
                )
            ).scalars().all()
            assert actionable == [version_id(session, second)]
            assert tools.calls == [
                AgentToolName.GET_SUPPLIER_OPTIONS,
                AgentToolName.CHECK_SUPPLIER_FEASIBILITY,
                AgentToolName.OPTIMISE_PURCHASE_PLAN,
                AgentToolName.VALIDATE_PURCHASE_PLAN,
            ]
            transitions = session.execute(
                select(db.audit_entries.c.payload).where(
                    db.audit_entries.c.action == AuditAction.PLAN_TRANSITIONED.value
                )
            ).scalars().all()
            assert any(
                payload["from_plan_status"]
                == ("APPROVED" if approve_first else "PENDING_APPROVAL")
                and payload["to_plan_status"] == "SUPERSEDED"
                for payload in transitions
            )
            actions = set(
                session.execute(
                    select(db.audit_entries.c.action).where(
                        db.audit_entries.c.event_id == run.trigger_event_id
                    )
                ).scalars()
            )
            assert {
                AuditAction.MATERIALITY_ASSESSED.value,
                AuditAction.SPECIALIST_CALLED.value,
                AuditAction.TOOL_CALLED.value,
                AuditAction.TOOL_RESULT_RECORDED.value,
                AuditAction.PLAN_TRANSITIONED.value,
                AuditAction.RUN_COMPLETED.value,
            } <= actions
            with pytest.raises(ApiError, match="PLAN_VERSION_STALE"):
                planning.decide_plan(
                    session,
                    first_id,
                    PlanDecision(
                        plan_id=first.plan_id,
                        plan_version=first.version,
                        decision="APPROVED",
                    ),
                    "manager",
                )
            assert any(
                payload["reason_codes"] == ["PLAN_VERSION_STALE"]
                for payload in session.execute(
                    select(db.audit_entries.c.payload).where(
                        db.audit_entries.c.action
                        == AuditAction.APPROVAL_RECORDED.value
                    )
                ).scalars()
            )
            assert (
                planning.decide_plan(
                    session,
                    version_id(session, second),
                    PlanDecision(
                        plan_id=second.plan_id,
                        plan_version=second.version,
                        decision="APPROVED",
                    ),
                    "manager",
                ).status.value
                == "APPROVED"
            )
    finally:
        engine.dispose()


@pytest.mark.parametrize("approve_first", (False, True))
def test_unusable_plan_is_invalidated_when_no_supplier_replacement_exists(
    database_url: str,
    approve_first: bool,
) -> None:
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            first = publish_initial_plan(session)
            first_id = version_id(session, first)
            if approve_first:
                assert (
                    planning.decide_plan(
                        session,
                        first_id,
                        PlanDecision(
                            plan_id=first.plan_id,
                            plan_version=first.version,
                            decision="APPROVED",
                        ),
                        "manager",
                    ).status.value
                    == "APPROVED"
                )
            for offer_id in ("market-chicken", "pantry-chicken"):
                changes.change_supplier(
                    session,
                    offer_id,
                    changes.SupplierChange(
                        effective_at=ISSUE_TIME, current_status="UNAVAILABLE"
                    ),
                    "manager",
                )
            selected = next(line.offer_id for line in first.lines if line.ingredient_id == "chicken")
            assert selected is not None
            run = claim_supplier_change(session, selected, current_status="UNAVAILABLE")
            result = run_backend_coordinator(
                session,
                run.id,
                SupplierReplanScript(),
                BackendProcurementTools(session),
            )

            assert result.completion.outcome is AgentOutcome.ESCALATE
            assert result.completion.escalation_reason is not None
            assert result.completion.escalation_reason.value == "NO_FEASIBLE_SUPPLIER"
            assert result.publication_result is not None
            assert result.publication_result.created_plan_version is None
            assert planning.read_plan(session, first_id).status.value == "INVALIDATED"
            assert any(
                payload["to_plan_status"] == "INVALIDATED"
                for payload in session.execute(
                    select(db.audit_entries.c.payload).where(
                        db.audit_entries.c.action
                        == AuditAction.PLAN_TRANSITIONED.value
                    )
                ).scalars()
            )
            with pytest.raises(ApiError, match="PLAN_VERSION_STALE"):
                planning.decide_plan(
                    session,
                    first_id,
                    PlanDecision(
                        plan_id=first.plan_id,
                        plan_version=first.version,
                        decision="APPROVED",
                    ),
                    "manager",
                )
            assert any(
                payload["reason_codes"] == ["PLAN_VERSION_STALE"]
                for payload in session.execute(
                    select(db.audit_entries.c.payload).where(
                        db.audit_entries.c.action
                        == AuditAction.APPROVAL_RECORDED.value
                    )
                ).scalars()
            )
    finally:
        engine.dispose()


def test_replan_result_is_rejected_when_authoritative_state_changes_mid_run(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            first = publish_initial_plan(session)
            first_id = version_id(session, first)
            selected = next(
                line.offer_id for line in first.lines if line.ingredient_id == "chicken"
            )
            assert selected is not None
            run = claim_supplier_change(session, selected, current_status="UNAVAILABLE")
            changes.change_supplier(
                session,
                "market-vegetables",
                changes.SupplierChange(
                    effective_at=ISSUE_TIME, current_status="UNAVAILABLE"
                ),
                "manager",
            )

            with pytest.raises(StateRevisionStaleError):
                run_backend_coordinator(
                    session,
                    run.id,
                    SupplierReplanScript(),
                    BackendProcurementTools(session),
                )

            assert planning.read_plan(session, first_id).status.value == "PENDING_APPROVAL"
            assert (
                session.execute(
                    select(db.plan_versions.c.id).where(
                        db.plan_versions.c.plan_id == first.plan_id
                    )
                ).scalars().all()
                == [first_id]
            )
            failed = planning.get_run(session, run.id)
            assert failed.status == "FAILED"
            assert failed.failure_reason == "STATE_REVISION_STALE"
    finally:
        engine.dispose()
