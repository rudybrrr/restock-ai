from datetime import datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.agent_contracts import (
    AgentOutcome,
    AgentToolName,
    EvidenceCategory,
    EvidenceSource,
    RecommendedNextStep,
    SpecialistDelegation,
    SpecialistType,
    ToolRequest,
)
from src.backend_control_plane import (
    BackendCoordinatorControlPlane,
    run_backend_coordinator,
)
from src.decision_engine_adapter import BackendProcurementTools, run_first_slice_engine
from src.errors import ErrorResponse
from src.planning import claim_run, request_run
from src.procurement_specialist import (
    ProcurementDecisionAction,
    ProcurementModelDecision,
    ProcurementReasoningContext,
    ProcurementSpecialist,
)

ISSUE_TIME = datetime.fromisoformat("2026-02-15T22:00:00+08:00")


class ProcurementOnlyClassifier:
    def classify(self, invocation, context_refs):
        from src.agent_contracts import SpecialistType

        return [SpecialistType.PROCUREMENT]


class EngineScript:
    """A local scripted reasoning boundary; it has no business inputs."""

    def decide(self, context: ProcurementReasoningContext) -> ProcurementModelDecision:
        if not context.tool_results:
            return ProcurementModelDecision(
                run_id=context.delegation.run_id,
                task_id=context.delegation.task_id,
                action=ProcurementDecisionAction.CALL_TOOL,
                tool=AgentToolName.OPTIMISE_PURCHASE_PLAN,
                input_refs=[context.delegation.trigger_ref],
                interpreted_impact="Search the frozen approved domain.",
                summary="Produce the deterministic candidate.",
            )
        if len(context.tool_results) == 1:
            return ProcurementModelDecision(
                run_id=context.delegation.run_id,
                task_id=context.delegation.task_id,
                action=ProcurementDecisionAction.CALL_TOOL,
                tool=AgentToolName.VALIDATE_PURCHASE_PLAN,
                input_refs=[context.tool_results[0].output_ref],
                interpreted_impact="Independently validate the candidate.",
                summary="Validate the deterministic candidate.",
            )
        return ProcurementModelDecision(
            run_id=context.delegation.run_id,
            task_id=context.delegation.task_id,
            action=ProcurementDecisionAction.COMPLETE,
            interpreted_impact="The Backend engine evidence is complete.",
            recommended_next_step=RecommendedNextStep.SUBMIT_REVISION,
            summary="Submit the validated candidate.",
        )


class ContextSensitiveEngineScript:
    """Use a cached authoritative feasibility ref only while it is current."""

    def decide(self, context: ProcurementReasoningContext) -> ProcurementModelDecision:
        cached = any(
            item.category is EvidenceCategory.SUPPLIER_STATE
            and item.source is EvidenceSource.DECISION_ENGINE
            for item in context.available_evidence_refs
        )
        if cached and not context.tool_results:
            return ProcurementModelDecision(
                run_id=context.delegation.run_id,
                task_id=context.delegation.task_id,
                action=ProcurementDecisionAction.COMPLETE,
                interpreted_impact="Current feasibility evidence remains authoritative.",
                recommended_next_step=RecommendedNextStep.KEEP_CURRENT_PLAN,
                summary="No redundant supplier search is justified.",
            )
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
                interpreted_impact="Fresh supplier evidence requires deterministic reassessment.",
                summary="Continue the justified procurement investigation.",
            )
        return ProcurementModelDecision(
            run_id=context.delegation.run_id,
            task_id=context.delegation.task_id,
            action=ProcurementDecisionAction.COMPLETE,
            interpreted_impact="Fresh deterministic candidate and validation evidence exist.",
            recommended_next_step=RecommendedNextStep.SUBMIT_REVISION,
            summary="Submit the validated candidate.",
        )


class RecordingBackendTools(BackendProcurementTools):
    def __init__(self, session: Session) -> None:
        super().__init__(session)
        self.calls: list[AgentToolName] = []

    def execute(self, request: ToolRequest):
        self.calls.append(request.tool)
        return super().execute(request)


def test_backend_adapter_derives_first_slice_oracle_from_frozen_contract(
    database_url: str,
) -> None:
    """The Backend, not an Agent caller, builds the numerical-kernel bundle."""
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            requested = request_run(session, ISSUE_TIME)
            run = claim_run(session)
            assert run.id == requested.id

            artifacts = run_first_slice_engine(session, run)

            candidate = artifacts["candidate"]["candidate"]
            assert candidate["calculation_mode"] == "ENGINE"
            assert Decimal(candidate["total_purchase_cost"]) == Decimal("55.50")
            assert Decimal(candidate["delivery_cost"]) == Decimal("5.00")
            assert Decimal(candidate["total_expected_cost"]) == Decimal("60.50")
            assert {
                line["ingredient_id"]: Decimal(line["quantity"])
                for line in candidate["lines"]
            } == {"chicken": Decimal("8.000"), "noodles": Decimal("3.000")}
            assert artifacts["validation"]["complete"] is True
            assert artifacts["validation"]["feasible"] is True
    finally:
        engine.dispose()


def test_real_engine_path_publishes_pending_plan_without_development_fixture(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            requested = request_run(session, ISSUE_TIME)
            run = claim_run(session)
            result = run_backend_coordinator(
                session,
                run.id,
                EngineScript(),
                BackendProcurementTools(session),
                manual_classifier=ProcurementOnlyClassifier(),
            )
            assert result.completion.outcome is AgentOutcome.REVISE_PLAN
            assert result.publication_result is not None
            plan = result.publication_result.created_plan_version
            assert plan is not None
            assert plan.status.value == "PENDING_APPROVAL"
            assert plan.total_expected_cost == Decimal("60.50")
            assert {(line.offer_id, line.opportunity_id) for line in plan.lines} == {
                ("fresh-chicken", "fresh-chicken:normal:20260215T2200+0800"),
                ("fresh-noodles", "fresh-noodles:normal:20260215T2200+0800"),
            }
            assert requested.id == run.id
    finally:
        engine.dispose()


def test_real_procurement_tools_change_sequence_when_cached_feasibility_is_stale(
    database_url: str,
) -> None:
    """The retained specialist skips work only for a real current engine ref."""
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            request_run(session, ISSUE_TIME)
            run = claim_run(session)
            revision = str(run.input_revision)
            control = BackendCoordinatorControlPlane(session)
            event_ref = control.get_event_context(control.get_invocation(run.id))
            tools = RecordingBackendTools(session)
            seeded = tools.execute(
                ToolRequest(
                    tool_call_id="seed-TOOL-1",
                    run_id=run.id,
                    tool=AgentToolName.CHECK_SUPPLIER_FEASIBILITY,
                    captured_state_revision=revision,
                    input_refs=[event_ref],
                )
            )
            assert not isinstance(seeded, ErrorResponse)
            cached_ref = seeded.output_ref
            cached = ProcurementSpecialist(ContextSensitiveEngineScript(), tools, control)
            cached_result = cached.execute(
                SpecialistDelegation(
                    run_id=run.id,
                    task_id="cached",
                    specialist=SpecialistType.PROCUREMENT,
                    objective="Use current feasibility evidence.",
                    trigger_ref=event_ref,
                    captured_state_revision=revision,
                    context_refs=[cached_ref],
                )
            )
            assert cached_result.recommended_next_step is RecommendedNextStep.KEEP_CURRENT_PLAN
            assert tools.calls == [AgentToolName.CHECK_SUPPLIER_FEASIBILITY]

            fresh = ProcurementSpecialist(ContextSensitiveEngineScript(), tools, control)
            fresh_result = fresh.execute(
                SpecialistDelegation(
                    run_id=run.id,
                    task_id="fresh",
                    specialist=SpecialistType.PROCUREMENT,
                    objective="Reassess after supplier evidence is no longer current.",
                    trigger_ref=event_ref,
                    captured_state_revision=revision,
                )
            )
            assert fresh_result.recommended_next_step is RecommendedNextStep.SUBMIT_REVISION
            assert tools.calls[1:] == [
                AgentToolName.GET_SUPPLIER_OPTIONS,
                AgentToolName.CHECK_SUPPLIER_FEASIBILITY,
                AgentToolName.OPTIMISE_PURCHASE_PLAN,
                AgentToolName.VALIDATE_PURCHASE_PLAN,
            ]
    finally:
        engine.dispose()
