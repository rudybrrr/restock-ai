"""Provider-independent orchestration for the ReStock Coordinator.

This module owns routing and synthesis only. All context, specialist execution,
validation, persistence, and human-review effects are supplied through narrow ports.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, TypeVar

from src.agent_contracts import (
    AgentCompletionPublication,
    AgentInvocation,
    AgentOutcome,
    AuditAction,
    AuditEvent,
    EscalationDetail,
    EscalationReason,
    EventType,
    EvidenceCategory,
    EvidenceRef,
    EvidenceSource,
    InvocationMode,
    RecommendedNextStep,
    SpecialistDelegation,
    SpecialistResult,
    SpecialistStatus,
    SpecialistType,
)

MAX_SPECIALIST_ROUNDS = 2
MAX_SPECIALIST_CALLS = 6
MAX_EXTERNAL_RETRIES = 1
FULL_PLANNING_TRIGGER = "FULL_PLANNING"
CallResult = TypeVar("CallResult")


class ControlPlaneFailure(RuntimeError):
    """A required control-plane call could not produce authoritative evidence."""


class SpecialistExecutionFailure(RuntimeError):
    """The external specialist boundary failed after its allowed retry."""


class CoordinatorControlPlane(Protocol):
    def get_active_plan(self, invocation: AgentInvocation) -> Sequence[EvidenceRef]: ...

    def get_event_context(self, invocation: AgentInvocation) -> EvidenceRef: ...

    def validate_final_plan(
        self, invocation: AgentInvocation, candidate_result_ref: EvidenceRef
    ) -> EvidenceRef: ...

    def record_agent_decision(
        self,
        completion: AgentCompletionPublication,
        trace: Sequence[AuditEvent],
    ) -> None: ...

    def request_human_review(self, completion: AgentCompletionPublication) -> None: ...


class SpecialistExecutor(Protocol):
    def execute(self, delegation: SpecialistDelegation) -> SpecialistResult: ...


class ManualRouteClassifier(Protocol):
    def classify(
        self, invocation: AgentInvocation, context_refs: Sequence[EvidenceRef]
    ) -> Sequence[SpecialistType]: ...


@dataclass(frozen=True)
class CoordinatorExecution:
    completion: AgentCompletionPublication
    trace: tuple[AuditEvent, ...]


EVENT_INITIAL_ROUTE: dict[EventType, SpecialistType | None] = {
    EventType.SALES_UPDATED: SpecialistType.DEMAND,
    EventType.PROMOTION_CREATED: SpecialistType.DEMAND,
    EventType.PROMOTION_CHANGED: SpecialistType.DEMAND,
    EventType.INVENTORY_ADJUSTED: SpecialistType.INVENTORY,
    EventType.INVENTORY_WASTED: SpecialistType.INVENTORY,
    EventType.SUPPLIER_AVAILABILITY_CHANGED: SpecialistType.PROCUREMENT,
    EventType.SUPPLIER_PRICE_CHANGED: SpecialistType.PROCUREMENT,
    EventType.DELIVERY_DELAYED: SpecialistType.PROCUREMENT,
    EventType.DELIVERY_SHORT: SpecialistType.PROCUREMENT,
    EventType.DELIVERY_CANCELLED: SpecialistType.PROCUREMENT,
    EventType.MANAGER_INSTRUCTION: None,
}

FOLLOW_UP_ROUTE = {
    RecommendedNextStep.CHECK_DEMAND: SpecialistType.DEMAND,
    RecommendedNextStep.CHECK_INVENTORY: SpecialistType.INVENTORY,
    RecommendedNextStep.CHECK_PROCUREMENT: SpecialistType.PROCUREMENT,
}


def _unique_refs(refs: Sequence[EvidenceRef]) -> list[EvidenceRef]:
    unique: dict[tuple[object, ...], EvidenceRef] = {}
    for ref in refs:
        key = (ref.category, ref.source, ref.reference_id, ref.version, ref.state_revision)
        unique[key] = ref
    return list(unique.values())


class Coordinator:
    def __init__(
        self,
        control_plane: CoordinatorControlPlane,
        specialist_executor: SpecialistExecutor,
        *,
        manual_classifier: ManualRouteClassifier | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._control_plane = control_plane
        self._specialist_executor = specialist_executor
        self._manual_classifier = manual_classifier
        self._clock = clock

    def run(self, invocation: AgentInvocation) -> CoordinatorExecution:
        trace: list[AuditEvent] = []
        try:
            event_ref = self._retry_control_plane(
                lambda: self._control_plane.get_event_context(invocation)
            )
            active_plan_refs = list(
                self._retry_control_plane(
                    lambda: self._control_plane.get_active_plan(invocation)
                )
            )
        except ControlPlaneFailure:
            return self._finish(
                invocation,
                AgentOutcome.ESCALATE,
                [self._trigger_ref(invocation)],
                trace,
                "Required control-plane context could not be retrieved.",
                EscalationReason.TOOL_FAILURE,
            )

        evidence_refs = _unique_refs([event_ref, *active_plan_refs])
        initial = self._initial_routes(invocation, evidence_refs)
        if initial is None:
            return self._finish(
                invocation,
                AgentOutcome.ESCALATE,
                evidence_refs,
                trace,
                "Manual intent could not be safely classified.",
                EscalationReason.MISSING_REQUIRED_DATA,
            )
        if not initial:
            return self._finish(
                invocation,
                AgentOutcome.KEEP_CURRENT_PLAN,
                evidence_refs,
                trace,
                "No specialist investigation is required for this invocation.",
            )

        pending = list(initial)
        call_count = 0
        task_number = 0
        final_step = RecommendedNextStep.NONE
        candidate_ref: EvidenceRef | None = None
        escalation_reason: EscalationReason | None = None

        for round_number in range(1, MAX_SPECIALIST_ROUNDS + 1):
            called_this_round: set[SpecialistType] = set()
            deferred: list[SpecialistType] = []
            while pending:
                specialist = pending.pop(0)
                if specialist in called_this_round:
                    if specialist not in deferred:
                        deferred.append(specialist)
                    continue
                if call_count >= MAX_SPECIALIST_CALLS:
                    return self._call_limit(invocation, evidence_refs, trace)
                called_this_round.add(specialist)
                call_count += 1
                task_number += 1
                delegation = self._delegation(
                    invocation,
                    specialist,
                    task_number,
                    event_ref,
                    evidence_refs,
                )
                trace.append(self._specialist_trace(invocation, delegation, call_count))
                try:
                    result = self._execute_with_retry(delegation)
                except SpecialistExecutionFailure:
                    return self._finish(
                        invocation,
                        AgentOutcome.ESCALATE,
                        evidence_refs,
                        trace,
                        "Required specialist execution failed.",
                        EscalationReason.TOOL_FAILURE,
                    )
                if not self._identity_matches(delegation, result):
                    return self._finish(
                        invocation,
                        AgentOutcome.ESCALATE,
                        evidence_refs,
                        trace,
                        "Specialist result identity did not match its delegation.",
                        EscalationReason.TOOL_FAILURE,
                    )
                if not self._evidence_matches_revision(invocation, result):
                    return self._finish(
                        invocation,
                        AgentOutcome.ESCALATE,
                        evidence_refs,
                        trace,
                        "Specialist evidence did not match the captured state revision.",
                        EscalationReason.TOOL_FAILURE,
                    )
                evidence_refs = _unique_refs(
                    [
                        *evidence_refs,
                        *result.materiality_evidence_refs,
                        *result.evidence_refs,
                        *([result.candidate_result_ref] if result.candidate_result_ref else []),
                    ]
                )
                if result.missing_information:
                    return self._finish(
                        invocation,
                        AgentOutcome.ESCALATE,
                        evidence_refs,
                        trace,
                        f"Required information is missing: {', '.join(result.missing_information)}.",
                        EscalationReason.MISSING_REQUIRED_DATA,
                    )
                if result.status is SpecialistStatus.FAILED:
                    return self._finish(
                        invocation,
                        AgentOutcome.ESCALATE,
                        evidence_refs,
                        trace,
                        "Specialist execution returned a failed status.",
                        EscalationReason.TOOL_FAILURE,
                    )
                if result.status is SpecialistStatus.ESCALATED:
                    return self._finish(
                        invocation,
                        AgentOutcome.ESCALATE,
                        evidence_refs,
                        trace,
                        result.summary,
                        result.escalation_reason,
                        result.escalation_detail,
                    )
                final_step = result.recommended_next_step
                if result.candidate_result_ref is not None:
                    candidate_ref = result.candidate_result_ref
                follow_up = FOLLOW_UP_ROUTE.get(result.recommended_next_step)
                if follow_up is not None:
                    if follow_up in called_this_round:
                        if follow_up not in deferred:
                            deferred.append(follow_up)
                    elif follow_up not in pending:
                        pending.append(follow_up)
            pending = deferred
            if not pending:
                break
            if round_number == MAX_SPECIALIST_ROUNDS:
                return self._call_limit(invocation, evidence_refs, trace)

        if pending:
            return self._call_limit(invocation, evidence_refs, trace)
        if final_step is RecommendedNextStep.SUBMIT_REVISION:
            if candidate_ref is None:
                escalation_reason = EscalationReason.MISSING_REQUIRED_DATA
            else:
                try:
                    validation_ref = self._retry_control_plane(
                        lambda: self._control_plane.validate_final_plan(
                            invocation, candidate_ref
                        )
                    )
                except ControlPlaneFailure:
                    escalation_reason = EscalationReason.TOOL_FAILURE
                else:
                    if validation_ref.category is EvidenceCategory.VALIDATION_RESULT:
                        evidence_refs = _unique_refs([*evidence_refs, validation_ref])
                        return self._finish(
                            invocation,
                            AgentOutcome.REVISE_PLAN,
                            evidence_refs,
                            trace,
                            "A candidate plan has authoritative validation evidence.",
                            candidate_ref=candidate_ref,
                        )
                    escalation_reason = EscalationReason.POLICY_VIOLATION
        if escalation_reason is not None:
            return self._finish(
                invocation,
                AgentOutcome.ESCALATE,
                evidence_refs,
                trace,
                "A safe plan revision could not be established.",
                escalation_reason,
            )
        if final_step is RecommendedNextStep.REQUEST_HUMAN_APPROVAL:
            completion = self._completion(
                invocation,
                AgentOutcome.REQUEST_HUMAN_APPROVAL,
                evidence_refs,
                "Authoritative evidence requires human review.",
            )
            try:
                self._retry_control_plane(
                    lambda: self._control_plane.request_human_review(completion)
                )
            except ControlPlaneFailure:
                return self._finish(
                    invocation,
                    AgentOutcome.ESCALATE,
                    evidence_refs,
                    trace,
                    "Human review could not be requested.",
                    EscalationReason.TOOL_FAILURE,
                )
            return self._record(invocation, completion, trace)
        return self._finish(
            invocation,
            AgentOutcome.KEEP_CURRENT_PLAN,
            evidence_refs,
            trace,
            "The bounded investigation produced no validated revision.",
        )

    def _initial_routes(
        self, invocation: AgentInvocation, refs: Sequence[EvidenceRef]
    ) -> list[SpecialistType] | None:
        if invocation.invocation_mode is InvocationMode.SCHEDULED:
            if invocation.trigger_type == FULL_PLANNING_TRIGGER:
                return [
                    SpecialistType.DEMAND,
                    SpecialistType.INVENTORY,
                    SpecialistType.PROCUREMENT,
                ]
            return []
        if invocation.invocation_mode is InvocationMode.MANUAL:
            return self._classify_manual(invocation, refs)
        try:
            event_type = EventType(invocation.trigger_type)
        except ValueError:
            return []
        if event_type is EventType.MANAGER_INSTRUCTION:
            return self._classify_manual(invocation, refs)
        route = EVENT_INITIAL_ROUTE[event_type]
        return [route] if route is not None else []

    def _classify_manual(
        self, invocation: AgentInvocation, refs: Sequence[EvidenceRef]
    ) -> list[SpecialistType] | None:
        if self._manual_classifier is None:
            return None
        allowed = set(SpecialistType)
        return list(
            dict.fromkeys(
                route
                for route in self._manual_classifier.classify(invocation, refs)
                if isinstance(route, SpecialistType) and route in allowed
            )
        )

    def _delegation(
        self,
        invocation: AgentInvocation,
        specialist: SpecialistType,
        task_number: int,
        event_ref: EvidenceRef,
        refs: Sequence[EvidenceRef],
    ) -> SpecialistDelegation:
        return SpecialistDelegation(
            run_id=invocation.run_id,
            task_id=f"{invocation.run_id}-TASK-{task_number}",
            specialist=specialist,
            objective=f"Investigate the scoped {specialist.value.lower()} impact.",
            trigger_ref=event_ref,
            captured_state_revision=invocation.captured_state_revision,
            active_plan_id=invocation.affected_plan_id,
            active_plan_version=invocation.affected_plan_version,
            materiality_evidence_refs=[
                ref for ref in refs if ref.category is EvidenceCategory.MATERIALITY
            ],
            context_refs=list(refs),
        )

    def _execute_with_retry(self, delegation: SpecialistDelegation) -> SpecialistResult:
        for attempt in range(MAX_EXTERNAL_RETRIES + 1):
            try:
                return self._specialist_executor.execute(delegation)
            except Exception as error:
                if attempt == MAX_EXTERNAL_RETRIES:
                    raise SpecialistExecutionFailure from error
        raise AssertionError("unreachable")

    def _retry_control_plane(
        self, call: Callable[[], CallResult]
    ) -> CallResult:
        for attempt in range(MAX_EXTERNAL_RETRIES + 1):
            try:
                return call()
            except Exception as error:
                if attempt == MAX_EXTERNAL_RETRIES:
                    raise ControlPlaneFailure from error
        raise AssertionError("unreachable")

    @staticmethod
    def _identity_matches(
        delegation: SpecialistDelegation, result: SpecialistResult
    ) -> bool:
        return (
            result.run_id == delegation.run_id
            and result.task_id == delegation.task_id
            and result.specialist is delegation.specialist
            and result.schema_version == delegation.required_output_schema_version
        )

    @staticmethod
    def _evidence_matches_revision(
        invocation: AgentInvocation, result: SpecialistResult
    ) -> bool:
        refs = [
            *result.materiality_evidence_refs,
            *result.evidence_refs,
            *([result.candidate_result_ref] if result.candidate_result_ref else []),
        ]
        return all(
            ref.state_revision is None
            or ref.state_revision == invocation.captured_state_revision
            for ref in refs
        )

    def _call_limit(
        self,
        invocation: AgentInvocation,
        refs: Sequence[EvidenceRef],
        trace: list[AuditEvent],
    ) -> CoordinatorExecution:
        return self._finish(
            invocation,
            AgentOutcome.ESCALATE,
            refs,
            trace,
            "Coordinator specialist-call or round budget was exhausted.",
            EscalationReason.CALL_LIMIT_REACHED,
        )

    def _finish(
        self,
        invocation: AgentInvocation,
        outcome: AgentOutcome,
        refs: Sequence[EvidenceRef],
        trace: list[AuditEvent],
        summary: str,
        escalation_reason: EscalationReason | None = None,
        escalation_detail: EscalationDetail | None = None,
        *,
        candidate_ref: EvidenceRef | None = None,
    ) -> CoordinatorExecution:
        completion = self._completion(
            invocation,
            outcome,
            refs,
            summary,
            escalation_reason,
            escalation_detail,
            candidate_ref,
        )
        return self._record(invocation, completion, trace)

    def _record(
        self,
        invocation: AgentInvocation,
        completion: AgentCompletionPublication,
        trace: list[AuditEvent],
    ) -> CoordinatorExecution:
        trace.append(
            AuditEvent(
                audit_event_id=f"{invocation.run_id}-RUN-COMPLETED",
                timestamp=self._clock(),
                actor="COORDINATOR",
                action=AuditAction.RUN_COMPLETED,
                state_revision=invocation.captured_state_revision,
                trigger_id=invocation.trigger_id,
                plan_id=invocation.affected_plan_id,
                plan_version=invocation.affected_plan_version,
                run_id=invocation.run_id,
                evidence_refs=completion.evidence_refs,
                final_outcome=completion.outcome,
                reason_codes=[completion.escalation_reason.value]
                if completion.escalation_reason
                else [],
                summary=completion.summary,
            )
        )
        try:
            self._retry_control_plane(
                lambda: self._control_plane.record_agent_decision(completion, trace)
            )
        except ControlPlaneFailure:
            if completion.outcome is not AgentOutcome.ESCALATE:
                completion = self._completion(
                    invocation,
                    AgentOutcome.ESCALATE,
                    completion.evidence_refs,
                    "The Coordinator decision could not be recorded.",
                    EscalationReason.TOOL_FAILURE,
                    None,
                )
                trace[-1] = trace[-1].model_copy(
                    update={
                        "final_outcome": completion.outcome,
                        "reason_codes": [EscalationReason.TOOL_FAILURE.value],
                        "summary": completion.summary,
                    }
                )
        return CoordinatorExecution(completion=completion, trace=tuple(trace))

    def _completion(
        self,
        invocation: AgentInvocation,
        outcome: AgentOutcome,
        refs: Sequence[EvidenceRef],
        summary: str,
        escalation_reason: EscalationReason | None = None,
        escalation_detail: EscalationDetail | None = None,
        candidate_ref: EvidenceRef | None = None,
    ) -> AgentCompletionPublication:
        return AgentCompletionPublication(
            run_id=invocation.run_id,
            captured_state_revision=invocation.captured_state_revision,
            outcome=outcome,
            escalation_reason=escalation_reason,
            escalation_detail=escalation_detail,
            candidate_result_ref=candidate_ref,
            affected_plan_id=invocation.affected_plan_id,
            affected_plan_version=invocation.affected_plan_version,
            reason_codes=[escalation_reason.value] if escalation_reason else [],
            evidence_refs=_unique_refs(refs) or [self._trigger_ref(invocation)],
            summary=summary,
        )

    def _specialist_trace(
        self,
        invocation: AgentInvocation,
        delegation: SpecialistDelegation,
        call_order: int,
    ) -> AuditEvent:
        return AuditEvent(
            audit_event_id=f"{invocation.run_id}-SPECIALIST-{call_order}",
            timestamp=self._clock(),
            actor="COORDINATOR",
            action=AuditAction.SPECIALIST_CALLED,
            state_revision=invocation.captured_state_revision,
            trigger_id=invocation.trigger_id,
            plan_id=invocation.affected_plan_id,
            plan_version=invocation.affected_plan_version,
            run_id=invocation.run_id,
            specialist_call_id=delegation.task_id,
            specialist=delegation.specialist,
            call_sequence=call_order,
            evidence_refs=delegation.context_refs,
            summary=f"Called {delegation.specialist.value} specialist.",
        )

    @staticmethod
    def _trigger_ref(invocation: AgentInvocation) -> EvidenceRef:
        return EvidenceRef(
            category=EvidenceCategory.EVENT_CONTEXT,
            source=EvidenceSource.BACKEND,
            reference_id=invocation.trigger_id,
            state_revision=invocation.captured_state_revision,
        )
