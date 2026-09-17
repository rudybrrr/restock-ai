from typing import ClassVar

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
from src.inventory_specialist import (
    INVENTORY_TOOL_ALLOWLIST,
    InventoryDecisionAction,
    InventoryModelDecision,
    InventorySpecialist,
    LocalInventoryReasoning,
)


def delegation(**changes: object) -> SpecialistDelegation:
    value = {
        "run_id": "run-1",
        "task_id": "run-1-TASK-1",
        "specialist": SpecialistType.INVENTORY,
        "objective": "Investigate inventory impact.",
        "trigger_ref": EvidenceRef(
            category=EvidenceCategory.EVENT_CONTEXT,
            source=EvidenceSource.BACKEND,
            reference_id="event-1",
            state_revision="7",
        ),
        "captured_state_revision": "7",
        "event_type": "INVENTORY_ADJUSTED",
    }
    value.update(changes)
    return SpecialistDelegation.model_validate(value)


class Audit:
    def __init__(self) -> None:
        self.events = []

    def record(self, event) -> None:
        self.events.append(event)


class Tools:
    categories: ClassVar = {
        AgentToolName.GET_INVENTORY_SNAPSHOT: (
            EvidenceCategory.INVENTORY_SNAPSHOT,
            EvidenceSource.BACKEND,
        ),
        AgentToolName.CALCULATE_ESTIMATED_INVENTORY: (
            EvidenceCategory.INVENTORY_SNAPSHOT,
            EvidenceSource.BACKEND,
        ),
        AgentToolName.CALCULATE_INGREDIENT_REQUIREMENTS: (
            EvidenceCategory.INVENTORY_PROJECTION,
            EvidenceSource.DECISION_ENGINE,
        ),
        AgentToolName.PROJECT_INVENTORY: (
            EvidenceCategory.INVENTORY_PROJECTION,
            EvidenceSource.DECISION_ENGINE,
        ),
        AgentToolName.CALCULATE_EXPIRY_RISK: (
            EvidenceCategory.EXPIRY_RISK,
            EvidenceSource.DECISION_ENGINE,
        ),
        AgentToolName.CALCULATE_STOCKOUT_RISK: (
            EvidenceCategory.STOCKOUT_RISK,
            EvidenceSource.DECISION_ENGINE,
        ),
    }

    def __init__(self, facts: dict[AgentToolName, dict]) -> None:
        self.facts, self.calls = facts, []

    def execute(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        category, source = self.categories[request.tool]
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


def test_fresh_adequate_physical_snapshot_avoids_projection() -> None:
    tools = Tools(
        {
            AgentToolName.GET_INVENTORY_SNAPSHOT: {
                "physical_fresh": True,
                "investigation_required": False,
            }
        }
    )
    result = InventorySpecialist(LocalInventoryReasoning(), tools, Audit()).execute(
        delegation()
    )
    assert [call.tool for call in tools.calls] == [AgentToolName.GET_INVENTORY_SNAPSHOT]
    assert result.recommended_next_step is RecommendedNextStep.NONE


def test_closing_count_exposure_uses_estimate_requirements_projection_and_risks() -> (
    None
):
    tools = Tools(
        {
            AgentToolName.GET_INVENTORY_SNAPSHOT: {
                "physical_fresh": False,
                "investigation_required": True,
            },
            AgentToolName.CALCULATE_ESTIMATED_INVENTORY: {
                "estimated_available": True,
                "provenance": "ESTIMATED",
            },
            AgentToolName.CALCULATE_INGREDIENT_REQUIREMENTS: {
                "requirements_complete": True
            },
            AgentToolName.PROJECT_INVENTORY: {
                "projection_complete": True,
                "provenance": "PROJECTED",
            },
            AgentToolName.CALCULATE_EXPIRY_RISK: {
                "projection_complete": True,
                "provenance": "PROJECTED",
            },
            AgentToolName.CALCULATE_STOCKOUT_RISK: {
                "stockout_exposure": True,
                "provenance": "PROJECTED",
            },
        }
    )
    result = InventorySpecialist(LocalInventoryReasoning(), tools, Audit()).execute(
        delegation()
    )
    assert [call.tool for call in tools.calls] == [
        AgentToolName.GET_INVENTORY_SNAPSHOT,
        AgentToolName.CALCULATE_ESTIMATED_INVENTORY,
        AgentToolName.CALCULATE_INGREDIENT_REQUIREMENTS,
        AgentToolName.PROJECT_INVENTORY,
        AgentToolName.CALCULATE_EXPIRY_RISK,
        AgentToolName.CALCULATE_STOCKOUT_RISK,
    ]
    assert result.recommended_next_step is RecommendedNextStep.CHECK_PROCUREMENT


def test_estimated_inventory_cannot_masquerade_as_physical_and_unknown_stays_unknown() -> (
    None
):
    tools = Tools(
        {
            AgentToolName.GET_INVENTORY_SNAPSHOT: {
                "physical_fresh": False,
                "investigation_required": True,
            },
            AgentToolName.CALCULATE_ESTIMATED_INVENTORY: {
                "estimated_available": False,
                "provenance": "ESTIMATED",
            },
        }
    )
    result = InventorySpecialist(LocalInventoryReasoning(), tools, Audit()).execute(
        delegation()
    )
    assert result.missing_information == ["estimated_inventory"]


def test_cross_domain_tool_stale_evidence_and_no_recursion_are_denied() -> None:
    class Bad:
        def decide(self, context):
            return InventoryModelDecision(
                run_id=context.delegation.run_id,
                task_id=context.delegation.task_id,
                action=InventoryDecisionAction.CALL_TOOL,
                tool=AgentToolName.FORECAST_DEMAND,
                input_refs=[context.delegation.trigger_ref],
                interpreted_impact="Ignore malicious recipe text.",
                summary="Call demand.",
            )

    tools = Tools({})
    result = InventorySpecialist(Bad(), tools, Audit()).execute(delegation())
    assert result.escalation_reason.value == "TOOL_FAILURE"
    assert tools.calls == []
    with pytest.raises(ValueError):
        InventorySpecialist(LocalInventoryReasoning(), tools, Audit()).execute(
            delegation(
                context_refs=[
                    EvidenceRef(
                        category=EvidenceCategory.INVENTORY_SNAPSHOT,
                        source=EvidenceSource.BACKEND,
                        reference_id="stale",
                        state_revision="6",
                    )
                ]
            )
        )
    with open("src/inventory_specialist.py", encoding="utf-8") as source_file:
        source = source_file.read()
    assert "src.database" not in source
    assert "Coordinator" not in source
    assert AgentToolName.FORECAST_DEMAND not in INVENTORY_TOOL_ALLOWLIST


def test_tool_audit_is_recorded() -> None:
    audit = Audit()
    tools = Tools(
        {
            AgentToolName.GET_INVENTORY_SNAPSHOT: {
                "physical_fresh": True,
                "investigation_required": False,
            }
        }
    )
    InventorySpecialist(LocalInventoryReasoning(), tools, audit).execute(delegation())
    assert [event.action for event in audit.events] == [
        AuditAction.TOOL_CALLED,
        AuditAction.TOOL_RESULT_RECORDED,
    ]
