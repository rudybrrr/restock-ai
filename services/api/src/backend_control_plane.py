"""Thin Coordinator adapters over the authoritative Backend planning services."""

from collections.abc import Sequence
from typing import Protocol

from sqlalchemy.orm import Session

from src import planning
from src.agent_contracts import (
    AgentCompletionPublication,
    AgentInvocation,
    AuditAction,
    AuditEvent,
    EvidenceCategory,
    EvidenceRef,
    EvidenceSource,
    InvocationMode,
    MaterialityAssessment,
    PlanPublicationResult,
    SpecialistDelegation,
    SpecialistResult,
    SpecialistType,
)
from src.coordinator import Coordinator, CoordinatorExecution, ManualRouteClassifier
from src.demand_specialist import (
    DemandReasoningModel,
    DemandSpecialist,
    DemandToolPort,
    LocalDemandReasoning,
)
from src.demand_tools import BackendDemandTools
from src.errors import ApiError
from src.procurement_specialist import (
    ProcurementReasoningModel,
    ProcurementSpecialist,
    ProcurementToolPort,
)
from src.replanning import supplier_events_for_run, supplier_materiality


class _SpecialistExecutor(Protocol):
    def execute(self, delegation: SpecialistDelegation) -> SpecialistResult: ...


class LocalSpecialistRegistry:
    """Coordinator-only dispatcher; specialists cannot invoke one another."""

    def __init__(self, specialists: dict[SpecialistType, _SpecialistExecutor]) -> None:
        self._specialists = specialists

    def execute(self, delegation: SpecialistDelegation) -> SpecialistResult:
        executor = self._specialists.get(delegation.specialist)
        if executor is None:
            raise ValueError(f"No local executor for {delegation.specialist.value}")
        return executor.execute(delegation)


class BackendCoordinatorControlPlane:
    """Map canonical Agent contracts to Backend-owned service operations."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._specialist_trace: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        """Collect specialist/tool trace events for the publication transaction."""
        self._specialist_trace.append(event)

    def get_invocation(self, run_id: str) -> AgentInvocation:
        """Build the canonical invocation from one claimed Backend run."""
        run = planning.get_run(self._session, run_id)
        if run.status != "RUNNING" or run.trigger_event_id is None:
            raise ApiError(409, "RUN_NOT_RUNNING", "Claim the Backend run first")
        target = run.snapshot.get("revises_plan_id")
        active = planning.get_active_plan(self._session, target) if target else None
        if target is not None and active is None:
            raise ApiError(
                409, "NO_CURRENT_PLAN", "The run's active plan no longer exists"
            )
        mode = (
            InvocationMode.MANUAL
            if run.trigger == "MANUAL_REASSESSMENT_REQUESTED"
            else InvocationMode.SCHEDULED
            if run.trigger == "FULL_PLANNING"
            else InvocationMode.EVENT
        )
        return AgentInvocation(
            run_id=run.id,
            invocation_mode=mode,
            trigger_id=run.trigger_event_id,
            trigger_type=run.trigger,
            captured_state_revision=str(run.input_revision),
            affected_plan_id=active.plan_id if active else None,
            affected_plan_version=active.version if active else None,
        )

    def get_active_plan(self, invocation: AgentInvocation) -> Sequence[EvidenceRef]:
        plan = planning.get_active_plan(self._session, invocation.affected_plan_id)
        if plan is None:
            return []
        certified_revision = planning.get_run(self._session, plan.run_id).input_revision
        return [
            EvidenceRef(
                category=EvidenceCategory.CANDIDATE_RESULT,
                source=EvidenceSource.BACKEND,
                reference_id=f"{plan.run_id}:candidate",
                version=plan.version,
                state_revision=str(certified_revision),
            )
        ]

    def get_event_context(self, invocation: AgentInvocation) -> EvidenceRef:
        planning.get_event_context(
            self._session, invocation.run_id, invocation.trigger_id
        )
        return EvidenceRef(
            category=EvidenceCategory.EVENT_CONTEXT,
            source=EvidenceSource.BACKEND,
            reference_id=invocation.trigger_id,
            state_revision=invocation.captured_state_revision,
        )

    def get_materiality(
        self, invocation: AgentInvocation
    ) -> MaterialityAssessment | None:
        """Read Backend-owned supplier availability/status evidence for an event run."""
        if invocation.invocation_mode is not InvocationMode.EVENT:
            return None
        active = (
            planning.get_active_plan(self._session, invocation.affected_plan_id)
            if invocation.affected_plan_id
            else None
        )
        return supplier_materiality(
            self._session,
            planning.get_run(self._session, invocation.run_id),
            active,
            supplier_events_for_run(self._session, invocation.run_id),
        )

    def validate_final_plan(
        self, invocation: AgentInvocation, candidate_result_ref: EvidenceRef
    ) -> EvidenceRef:
        planning.validate_candidate_reference(
            self._session,
            invocation.run_id,
            candidate_result_ref.reference_id,
            invocation.captured_state_revision,
        )
        return EvidenceRef(
            category=EvidenceCategory.VALIDATION_RESULT,
            source=EvidenceSource.BACKEND,
            reference_id=f"{invocation.run_id}:validation",
            state_revision=invocation.captured_state_revision,
        )

    def record_agent_decision(
        self,
        completion: AgentCompletionPublication,
        trace: Sequence[AuditEvent],
    ) -> PlanPublicationResult:
        completed = [
            event for event in trace if event.action is AuditAction.RUN_COMPLETED
        ]
        preceding = [
            event for event in trace if event.action is not AuditAction.RUN_COMPLETED
        ]
        merged = sorted(
            [*preceding, *self._specialist_trace], key=lambda event: event.timestamp
        )
        merged.extend(completed)
        result = planning.publish_agent_completion(self._session, completion, merged)
        self._specialist_trace.clear()
        return result

    def request_human_review(self, completion: AgentCompletionPublication) -> None:
        planning.validate_human_review_request(self._session, completion)


def run_backend_coordinator(
    session: Session,
    run_id: str,
    reasoning_model: ProcurementReasoningModel,
    procurement_tools: ProcurementToolPort,
    *,
    demand_model: DemandReasoningModel | None = None,
    demand_tools: DemandToolPort | None = None,
    manual_classifier: ManualRouteClassifier | None = None,
) -> CoordinatorExecution:
    """Run the local deterministic specialists against Backend-owned services."""
    control_plane = BackendCoordinatorControlPlane(session)
    procurement = ProcurementSpecialist(
        reasoning_model,
        procurement_tools,
        control_plane,
    )
    demand = DemandSpecialist(
        demand_model or LocalDemandReasoning(),
        demand_tools or BackendDemandTools(session),
        control_plane,
    )
    coordinator = Coordinator(
        control_plane,
        LocalSpecialistRegistry(
            {
                SpecialistType.PROCUREMENT: procurement,
                SpecialistType.DEMAND: demand,
            }
        ),
        manual_classifier=manual_classifier,
    )
    return coordinator.run(control_plane.get_invocation(run_id))
