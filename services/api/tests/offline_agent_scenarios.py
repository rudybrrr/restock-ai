"""Test-only offline harness for Coordinator -> Procurement scenarios.

The harness scripts decisions and contract-shaped tool outcomes. It deliberately
contains no supplier calculations, persistence, publication, or provider access.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from src.agent_contracts import (
    AgentInvocation,
    AgentToolName,
    AuditEvent,
    EventType,
    EvidenceCategory,
    EvidenceRef,
    EvidenceSource,
    InvocationMode,
    SpecialistDelegation,
    SpecialistType,
    ToolRequest,
    ToolResult,
)
from src.coordinator import Coordinator, CoordinatorExecution
from src.errors import ErrorResponse
from src.procurement_specialist import (
    PROCUREMENT_PRIMARY_EVIDENCE,
    ProcurementModelDecision,
    ProcurementReasoningContext,
    ProcurementSpecialist,
)

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
RUN_ID = "OFFLINE-RUN-1"
STATE_REVISION = "OFFLINE-STATE-1"

DecisionScript = Callable[[ProcurementReasoningContext], ProcurementModelDecision]
ToolOutcome = ToolResult | ErrorResponse | Exception
ToolScript = dict[AgentToolName, list[ToolOutcome]]


def evidence(
    category: EvidenceCategory,
    reference_id: str,
    source: EvidenceSource,
) -> EvidenceRef:
    return EvidenceRef(
        category=category,
        source=source,
        reference_id=reference_id,
        state_revision=STATE_REVISION,
    )


def trusted_tool_result(request: ToolRequest, reference_id: str) -> ToolResult:
    category, source = PROCUREMENT_PRIMARY_EVIDENCE[request.tool]
    specialist_call_id, raw_sequence = request.tool_call_id.rsplit("-TOOL-", 1)
    return ToolResult(
        tool_call_id=request.tool_call_id,
        run_id=request.run_id,
        tool=request.tool,
        output_ref=EvidenceRef(
            category=category,
            source=source,
            reference_id=reference_id,
            state_revision=request.captured_state_revision,
            run_id=request.run_id,
            specialist_call_id=specialist_call_id,
            tool_call_id=request.tool_call_id,
            producer_tool=request.tool.value,
            call_sequence=int(raw_sequence),
        ),
    )


class ScriptedReasoning:
    def __init__(self, decide: DecisionScript) -> None:
        self._decide = decide
        self.contexts: list[ProcurementReasoningContext] = []

    def decide(self, context: ProcurementReasoningContext) -> ProcurementModelDecision:
        self.contexts.append(context)
        return self._decide(context)


class ScriptedTools:
    def __init__(self, script: ToolScript | None = None) -> None:
        self._script = {tool: list(outcomes) for tool, outcomes in (script or {}).items()}
        self.calls: list[ToolRequest] = []

    def execute(self, request: ToolRequest) -> ToolResult | ErrorResponse:
        self.calls.append(request)
        outcomes = self._script.get(request.tool, [])
        if outcomes:
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return trusted_tool_result(request, f"{request.tool.value}-RESULT-{len(self.calls)}")


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)


class OfflineControlPlane:
    def __init__(self, context_refs: Sequence[EvidenceRef]) -> None:
        self._context_refs = list(context_refs)
        self.recorded: list[tuple[object, tuple[AuditEvent, ...]]] = []
        self.review_requests: list[object] = []

    def get_active_plan(self, invocation: AgentInvocation) -> Sequence[EvidenceRef]:
        return [
            evidence(
                EvidenceCategory.MATERIALITY,
                "OFFLINE-MATERIALITY-1",
                EvidenceSource.DECISION_ENGINE,
            ),
            *self._context_refs,
        ]

    def get_event_context(self, invocation: AgentInvocation) -> EvidenceRef:
        return evidence(
            EvidenceCategory.EVENT_CONTEXT,
            invocation.trigger_id,
            EvidenceSource.BACKEND,
        )

    def validate_final_plan(
        self, invocation: AgentInvocation, candidate_result_ref: EvidenceRef
    ) -> EvidenceRef:
        return evidence(
            EvidenceCategory.VALIDATION_RESULT,
            "OFFLINE-FINAL-VALIDATION-1",
            EvidenceSource.DECISION_ENGINE,
        )

    def record_agent_decision(self, completion, trace: Sequence[AuditEvent]) -> None:
        self.recorded.append((completion, tuple(trace)))

    def request_human_review(self, completion) -> None:
        self.review_requests.append(completion)


class ProcurementOnlyExecutor:
    def __init__(self, specialist: ProcurementSpecialist) -> None:
        self._specialist = specialist
        self.delegations: list[SpecialistDelegation] = []

    def execute(self, delegation: SpecialistDelegation):
        self.delegations.append(delegation)
        if delegation.specialist is not SpecialistType.PROCUREMENT:
            raise RuntimeError("offline harness exposes Procurement only")
        return self._specialist.execute(delegation)


@dataclass(frozen=True)
class OfflineScenarioResult:
    execution: CoordinatorExecution
    tools: ScriptedTools
    reasoning: ScriptedReasoning
    delegations: tuple[SpecialistDelegation, ...]
    audit_events: tuple[AuditEvent, ...]
    control_plane: OfflineControlPlane


def run_procurement_scenario(
    decide: DecisionScript,
    *,
    tool_script: ToolScript | None = None,
    context_refs: Sequence[EvidenceRef] = (),
    trigger_type: str = EventType.SUPPLIER_AVAILABILITY_CHANGED,
) -> OfflineScenarioResult:
    reasoning = ScriptedReasoning(decide)
    tools = ScriptedTools(tool_script)
    specialist_audit = RecordingAudit()
    specialist = ProcurementSpecialist(
        reasoning,
        tools,
        specialist_audit,
        clock=lambda: NOW,
    )
    executor = ProcurementOnlyExecutor(specialist)
    control_plane = OfflineControlPlane(context_refs)
    execution = Coordinator(
        control_plane,
        executor,
        clock=lambda: NOW,
    ).run(
        AgentInvocation(
            run_id=RUN_ID,
            invocation_mode=InvocationMode.EVENT,
            trigger_id="OFFLINE-EVENT-1",
            trigger_type=trigger_type,
            captured_state_revision=STATE_REVISION,
            affected_plan_id="OFFLINE-PLAN-1",
            affected_plan_version=1,
        )
    )
    coordinator_events = execution.trace
    combined = (
        coordinator_events[:1]
        + tuple(specialist_audit.events)
        + coordinator_events[1:]
    )
    return OfflineScenarioResult(
        execution=execution,
        tools=tools,
        reasoning=reasoning,
        delegations=tuple(executor.delegations),
        audit_events=combined,
        control_plane=control_plane,
    )
