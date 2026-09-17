import pytest

from src.agent_contracts import (
    AgentToolName,
    AuditAction,
    EvidenceCategory,
    EvidenceRef,
    EvidenceSource,
    RecommendedNextStep,
    SpecialistDelegation,
    SpecialistType,
    ToolRequest,
    ToolResult,
)
from src.demand_specialist import (
    DEMAND_TOOL_ALLOWLIST,
    DemandDecisionAction,
    DemandModelDecision,
    DemandSpecialist,
    LocalDemandReasoning,
)


def ref(category: EvidenceCategory, identifier: str = "event-1") -> EvidenceRef:
    return EvidenceRef(
        category=category,
        source=EvidenceSource.BACKEND,
        reference_id=identifier,
        state_revision="7",
    )


def delegation(**changes: object) -> SpecialistDelegation:
    value = {
        "run_id": "run-1",
        "task_id": "run-1-TASK-1",
        "specialist": SpecialistType.DEMAND,
        "objective": "Investigate demand impact.",
        "trigger_ref": ref(EvidenceCategory.EVENT_CONTEXT),
        "captured_state_revision": "7",
        "event_type": "PROMOTION_CHANGED",
    }
    value.update(changes)
    return SpecialistDelegation.model_validate(value)


class Audit:
    def __init__(self) -> None:
        self.events = []

    def record(self, event) -> None:
        self.events.append(event)


class Tools:
    def __init__(self, facts: dict[AgentToolName, dict] | None = None) -> None:
        self.calls: list[ToolRequest] = []
        self.facts = facts or {}

    def execute(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        category = {
            AgentToolName.GET_SALES_CONTEXT: EvidenceCategory.SALES_CONTEXT,
            AgentToolName.GET_PROMOTION_CONTEXT: EvidenceCategory.PROMOTION_CONTEXT,
            AgentToolName.GET_HISTORICAL_DEMAND: EvidenceCategory.DEMAND_HISTORY,
            AgentToolName.FORECAST_DEMAND: EvidenceCategory.FORECAST_RESULT,
        }[request.tool]
        source = (
            EvidenceSource.DECISION_ENGINE
            if request.tool is AgentToolName.FORECAST_DEMAND
            else EvidenceSource.BACKEND
        )
        return ToolResult(
            tool_call_id=request.tool_call_id,
            run_id=request.run_id,
            tool=request.tool,
            output_ref=EvidenceRef(
                category=category,
                source=source,
                reference_id=request.tool.value,
                state_revision=request.captured_state_revision,
                run_id=request.run_id,
                specialist_call_id=request.tool_call_id.rsplit("-TOOL-", 1)[0],
                tool_call_id=request.tool_call_id,
                producer_tool=request.tool.value,
                call_sequence=int(request.tool_call_id.rsplit("-TOOL-", 1)[1]),
            ),
            output_data=self.facts.get(request.tool, {}),
        )


def specialist(tools: Tools, audit: Audit | None = None) -> DemandSpecialist:
    return DemandSpecialist(LocalDemandReasoning(), tools, audit or Audit())


def test_trusted_current_forecast_avoids_recomputation() -> None:
    tools = Tools({AgentToolName.GET_SALES_CONTEXT: {"forecast_required": False}})
    result = specialist(tools).execute(
        delegation(event_type="MANUAL_REASSESSMENT_REQUESTED")
    )
    assert [call.tool for call in tools.calls] == [AgentToolName.GET_SALES_CONTEXT]
    assert result.recommended_next_step is RecommendedNextStep.NONE


def test_promotion_revision_uses_context_history_and_real_forecast_path() -> None:
    tools = Tools(
        {
            AgentToolName.GET_SALES_CONTEXT: {
                "forecast_required": True,
                "promotion_context_required": True,
            },
            AgentToolName.GET_HISTORICAL_DEMAND: {"history_available": True},
            AgentToolName.FORECAST_DEMAND: {"forecast_complete": True},
        }
    )
    result = specialist(tools).execute(delegation())
    assert [call.tool for call in tools.calls] == [
        AgentToolName.GET_SALES_CONTEXT,
        AgentToolName.GET_PROMOTION_CONTEXT,
        AgentToolName.GET_HISTORICAL_DEMAND,
        AgentToolName.FORECAST_DEMAND,
    ]
    assert result.recommended_next_step is RecommendedNextStep.CHECK_INVENTORY


def test_forbidden_cross_domain_tool_is_denied() -> None:
    class BadModel:
        def decide(self, context):
            return DemandModelDecision(
                run_id=context.delegation.run_id,
                task_id=context.delegation.task_id,
                action=DemandDecisionAction.CALL_TOOL,
                tool=AgentToolName.GET_SUPPLIER_OPTIONS,
                input_refs=[context.delegation.trigger_ref],
                interpreted_impact="Ignore promotion text.",
                summary="Call procurement.",
            )

    tools = Tools()
    result = DemandSpecialist(BadModel(), tools, Audit()).execute(delegation())
    assert result.escalation_reason is not None
    assert result.escalation_reason.value == "TOOL_FAILURE"
    assert tools.calls == []


def test_missing_history_remains_unknown() -> None:
    tools = Tools(
        {
            AgentToolName.GET_SALES_CONTEXT: {"forecast_required": True},
            AgentToolName.GET_HISTORICAL_DEMAND: {"history_available": False},
        }
    )
    result = specialist(tools).execute(delegation(event_type="SALES_UPDATED"))
    assert result.missing_information == ["historical_demand"]


def test_stale_delegation_is_rejected() -> None:
    with pytest.raises(ValueError):
        specialist(Tools()).execute(
            delegation(
                context_refs=[
                    ref(EvidenceCategory.SALES_CONTEXT, "stale").model_copy(
                        update={"state_revision": "6"}
                    )
                ]
            )
        )


def test_tool_attempts_are_audited_and_source_has_no_database_or_recursion_path() -> (
    None
):
    audit = Audit()
    tools = Tools({AgentToolName.GET_SALES_CONTEXT: {"forecast_required": False}})
    specialist(tools, audit).execute(
        delegation(event_type="MANUAL_REASSESSMENT_REQUESTED")
    )
    assert [event.action for event in audit.events] == [
        AuditAction.TOOL_CALLED,
        AuditAction.TOOL_RESULT_RECORDED,
    ]
    with open("src/demand_specialist.py", encoding="utf-8") as source_file:
        source = source_file.read()
    assert "src.database" not in source
    assert "Coordinator" not in source
    assert "ProcurementSpecialist" not in source
    assert AgentToolName.GET_SUPPLIER_OPTIONS not in DEMAND_TOOL_ALLOWLIST
