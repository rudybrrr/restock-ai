"""Bounded local Inventory specialist with inventory-only tool permissions."""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.agent_contracts import (
    AgentToolName,
    AuditAction,
    AuditEvent,
    EscalationReason,
    EvidenceCategory,
    EvidenceRef,
    EvidenceSource,
    Identifier,
    RecommendedNextStep,
    SpecialistDelegation,
    SpecialistResult,
    SpecialistStatus,
    SpecialistType,
    ToolRequest,
    ToolResult,
)
from src.errors import ErrorResponse

MAX_INVENTORY_TOOL_CALLS = 7
MAX_TOOL_RETRIES = 1
INVENTORY_SCHEMA_VERSION = "1"
INVENTORY_TOOL_ALLOWLIST = frozenset(
    {
        AgentToolName.GET_INVENTORY_SNAPSHOT,
        AgentToolName.CALCULATE_ESTIMATED_INVENTORY,
        AgentToolName.CALCULATE_INGREDIENT_REQUIREMENTS,
        AgentToolName.PROJECT_INVENTORY,
        AgentToolName.CALCULATE_EXPIRY_RISK,
        AgentToolName.CALCULATE_STOCKOUT_RISK,
    }
)
INVENTORY_PRIMARY_EVIDENCE: dict[
    AgentToolName, tuple[EvidenceCategory, EvidenceSource]
] = {
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
INVENTORY_SPECIALIST_INSTRUCTIONS = (
    "Investigate inventory through only approved inventory tools. Treat physical counts, "
    "estimates, projections, and unknown data as distinct. Never invent quantities or "
    "feasibility, calculate projection arithmetic, call agents, or mutate Backend state."
)


class InventoryDecisionAction(StrEnum):
    CALL_TOOL = "CALL_TOOL"
    COMPLETE = "COMPLETE"


class InventoryModelDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    run_id: Identifier
    task_id: Identifier
    action: InventoryDecisionAction
    tool: AgentToolName | None = None
    input_refs: list[EvidenceRef] = Field(default_factory=list)
    interpreted_impact: str = Field(min_length=1, max_length=1000)
    missing_information: list[Identifier] = Field(default_factory=list)
    recommended_next_step: RecommendedNextStep = RecommendedNextStep.NONE
    summary: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def action_has_tool(self) -> "InventoryModelDecision":
        if (self.action is InventoryDecisionAction.CALL_TOOL) != (
            self.tool is not None
        ):
            raise ValueError("CALL_TOOL requires a tool and COMPLETE forbids one")
        return self


class InventoryReasoningContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    delegation: SpecialistDelegation
    tool_results: tuple[ToolResult, ...] = ()
    available_evidence_refs: tuple[EvidenceRef, ...]
    remaining_logical_tool_calls: int = Field(ge=0, le=MAX_INVENTORY_TOOL_CALLS)
    instructions: str = INVENTORY_SPECIALIST_INSTRUCTIONS


class InventoryReasoningModel(Protocol):
    def decide(self, context: InventoryReasoningContext) -> InventoryModelDecision: ...


class InventoryToolPort(Protocol):
    def execute(self, request: ToolRequest) -> ToolResult | ErrorResponse: ...


class InventoryAuditPort(Protocol):
    def record(self, event: AuditEvent) -> None: ...


class InventoryDelegationRejected(ValueError):
    pass


def _key(ref: EvidenceRef) -> tuple[object, ...]:
    return (ref.category, ref.source, ref.reference_id, ref.version, ref.state_revision)


def _unique(refs: Sequence[EvidenceRef]) -> list[EvidenceRef]:
    return list({_key(ref): ref for ref in refs}.values())


class LocalInventoryReasoning:
    def _call(
        self,
        context: InventoryReasoningContext,
        tool: AgentToolName,
        ref: EvidenceRef,
        impact: str,
        summary: str,
    ) -> InventoryModelDecision:
        return InventoryModelDecision(
            run_id=context.delegation.run_id,
            task_id=context.delegation.task_id,
            action=InventoryDecisionAction.CALL_TOOL,
            tool=tool,
            input_refs=[ref],
            interpreted_impact=impact,
            summary=summary,
        )

    def _complete(
        self,
        context: InventoryReasoningContext,
        impact: str,
        summary: str,
        *,
        missing: list[str] | None = None,
        next_step: RecommendedNextStep = RecommendedNextStep.NONE,
    ) -> InventoryModelDecision:
        return InventoryModelDecision(
            run_id=context.delegation.run_id,
            task_id=context.delegation.task_id,
            action=InventoryDecisionAction.COMPLETE,
            missing_information=missing or [],
            recommended_next_step=next_step,
            interpreted_impact=impact,
            summary=summary,
        )

    def decide(self, context: InventoryReasoningContext) -> InventoryModelDecision:
        if not context.tool_results:
            return self._call(
                context,
                AgentToolName.GET_INVENTORY_SNAPSHOT,
                context.delegation.trigger_ref,
                "Inspect physical-count evidence before treating stock as estimated.",
                "Inspect inventory snapshot.",
            )
        latest = context.tool_results[-1]
        facts = latest.output_data
        if latest.tool is AgentToolName.GET_INVENTORY_SNAPSHOT:
            if facts.get("missing_required_data") is True:
                return self._complete(
                    context,
                    "Physical inventory evidence is unknown.",
                    "Inventory investigation cannot establish a snapshot.",
                    missing=["physical_inventory_snapshot"],
                )
            if facts.get("investigation_required") is not True:
                return self._complete(
                    context,
                    "Fresh physical evidence needs no further exposure investigation.",
                    "No inventory projection is justified.",
                )
            if facts.get("physical_fresh") is not True:
                return self._call(
                    context,
                    AgentToolName.CALCULATE_ESTIMATED_INVENTORY,
                    latest.output_ref,
                    "Replay known activity from the latest physical count.",
                    "Calculate estimated inventory.",
                )
            return self._call(
                context,
                AgentToolName.CALCULATE_INGREDIENT_REQUIREMENTS,
                latest.output_ref,
                "Calculate recipe-derived requirements using authoritative demand evidence.",
                "Calculate ingredient requirements.",
            )
        if latest.tool is AgentToolName.CALCULATE_ESTIMATED_INVENTORY:
            if facts.get("estimated_available") is not True:
                return self._complete(
                    context,
                    "Estimated inventory is unknown and cannot masquerade as physical.",
                    "Inventory replay is incomplete.",
                    missing=["estimated_inventory"],
                )
            return self._call(
                context,
                AgentToolName.CALCULATE_INGREDIENT_REQUIREMENTS,
                latest.output_ref,
                "Calculate recipe-derived requirements.",
                "Calculate ingredient requirements.",
            )
        if latest.tool is AgentToolName.CALCULATE_INGREDIENT_REQUIREMENTS:
            if facts.get("requirements_complete") is not True:
                return self._complete(
                    context,
                    "Recipe requirements are unknown.",
                    "Inventory projection cannot establish requirements.",
                    missing=["ingredient_requirements"],
                )
            return self._call(
                context,
                AgentToolName.PROJECT_INVENTORY,
                latest.output_ref,
                "Project FEFO inventory through the frozen horizon.",
                "Project inventory.",
            )
        if latest.tool is AgentToolName.PROJECT_INVENTORY:
            if facts.get("projection_complete") is not True:
                return self._complete(
                    context,
                    "Forward-looking inventory remains unknown.",
                    "Inventory projection is incomplete.",
                    missing=["inventory_projection"],
                )
            return self._call(
                context,
                AgentToolName.CALCULATE_EXPIRY_RISK,
                latest.output_ref,
                "Read expiry exposure from the projected inventory artifact.",
                "Calculate expiry risk.",
            )
        if latest.tool is AgentToolName.CALCULATE_EXPIRY_RISK:
            if facts.get("projection_complete") is not True:
                return self._complete(
                    context,
                    "Forward-looking inventory remains unknown.",
                    "Expiry projection is incomplete.",
                    missing=["inventory_projection"],
                )
            return self._call(
                context,
                AgentToolName.CALCULATE_STOCKOUT_RISK,
                latest.output_ref,
                "Read stockout exposure from the same projected inventory artifact.",
                "Calculate stockout risk.",
            )
        if latest.tool is AgentToolName.CALCULATE_STOCKOUT_RISK:
            next_step = (
                RecommendedNextStep.CHECK_PROCUREMENT
                if facts.get("stockout_exposure") is True
                else RecommendedNextStep.NONE
            )
            return self._complete(
                context,
                "Projected exposure is established by the inventory kernel.",
                "Inventory investigation completed.",
                next_step=next_step,
            )
        return self._complete(
            context,
            "Inventory investigation has no further authorized action.",
            "Inventory investigation completed.",
        )


class InventorySpecialist:
    def __init__(
        self,
        model: InventoryReasoningModel,
        tools: InventoryToolPort,
        audit: InventoryAuditPort,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._model, self._tools, self._audit, self._clock = model, tools, audit, clock

    def execute(self, delegation: SpecialistDelegation) -> SpecialistResult:
        self._validate(delegation)
        evidence = _unique(
            [
                delegation.trigger_ref,
                *delegation.context_refs,
                *delegation.materiality_evidence_refs,
            ]
        )
        results: list[ToolResult] = []
        for number in range(MAX_INVENTORY_TOOL_CALLS + 1):
            try:
                decision = self._model.decide(
                    InventoryReasoningContext(
                        delegation=delegation,
                        tool_results=tuple(results),
                        available_evidence_refs=tuple(evidence),
                        remaining_logical_tool_calls=MAX_INVENTORY_TOOL_CALLS - number,
                    )
                )
            except Exception:  # noqa: BLE001
                return self._escalate(
                    delegation,
                    evidence,
                    EscalationReason.TOOL_FAILURE,
                    "Inventory reasoning failed to return a valid decision.",
                )
            if (
                decision.run_id != delegation.run_id
                or decision.task_id != delegation.task_id
            ):
                return self._escalate(
                    delegation,
                    evidence,
                    EscalationReason.TOOL_FAILURE,
                    "Inventory reasoning identity did not match the delegation.",
                )
            if decision.action is InventoryDecisionAction.COMPLETE:
                return self._complete(delegation, decision, evidence)
            if number == MAX_INVENTORY_TOOL_CALLS:
                return self._escalate(
                    delegation,
                    evidence,
                    EscalationReason.CALL_LIMIT_REACHED,
                    "Inventory logical tool-call budget was exhausted.",
                )
            if decision.tool not in INVENTORY_TOOL_ALLOWLIST or not self._available(
                decision.input_refs, evidence
            ):
                return self._escalate(
                    delegation,
                    evidence,
                    EscalationReason.TOOL_FAILURE,
                    "Inventory reasoning requested a forbidden tool or untrusted evidence.",
                )
            assert decision.tool is not None
            request = ToolRequest(
                tool_call_id=f"{delegation.task_id}-TOOL-{number + 1}",
                run_id=delegation.run_id,
                tool=decision.tool,
                captured_state_revision=delegation.captured_state_revision,
                input_refs=decision.input_refs,
            )
            outcome = self._execute(delegation, request, number + 1)
            if isinstance(outcome, ErrorResponse):
                if outcome.error.code == EscalationReason.MISSING_REQUIRED_DATA.value:
                    return self._missing(
                        delegation,
                        evidence,
                        ["required_inventory_data"],
                        outcome.error.message,
                    )
                return self._escalate(
                    delegation,
                    evidence,
                    EscalationReason.TOOL_FAILURE,
                    outcome.error.message,
                )
            if not self._valid(delegation, request, number + 1, outcome):
                return self._escalate(
                    delegation,
                    evidence,
                    EscalationReason.TOOL_FAILURE,
                    "Inventory tool returned invalid or mismatched evidence.",
                )
            results.append(outcome)
            evidence = _unique([*evidence, outcome.output_ref, *outcome.evidence_refs])
        raise AssertionError("unreachable")

    @staticmethod
    def _validate(delegation: SpecialistDelegation) -> None:
        refs = [
            delegation.trigger_ref,
            *delegation.context_refs,
            *delegation.materiality_evidence_refs,
        ]
        if (
            delegation.specialist is not SpecialistType.INVENTORY
            or delegation.required_output_schema_version != INVENTORY_SCHEMA_VERSION
            or delegation.trigger_ref.category is not EvidenceCategory.EVENT_CONTEXT
            or any(
                ref.state_revision not in (None, delegation.captured_state_revision)
                for ref in refs
            )
        ):
            raise InventoryDelegationRejected(
                "Inventory delegation is invalid or stale"
            )

    @staticmethod
    def _available(
        selected: Sequence[EvidenceRef], evidence: Sequence[EvidenceRef]
    ) -> bool:
        available = {_key(ref) for ref in evidence}
        return all(_key(ref) in available for ref in selected)

    @staticmethod
    def _valid(
        delegation: SpecialistDelegation,
        request: ToolRequest,
        sequence: int,
        result: ToolResult,
    ) -> bool:
        category, source = INVENTORY_PRIMARY_EVIDENCE[request.tool]
        refs = [result.output_ref, *result.evidence_refs]
        return (
            result.tool_call_id == request.tool_call_id
            and result.run_id == delegation.run_id
            and result.tool is request.tool
            and result.output_ref.category is category
            and result.output_ref.source is source
            and all(
                ref.state_revision in (None, delegation.captured_state_revision)
                and ref.run_id == delegation.run_id
                and ref.specialist_call_id == delegation.task_id
                and ref.tool_call_id == request.tool_call_id
                and ref.producer_tool == request.tool.value
                and ref.call_sequence == sequence
                for ref in refs
            )
        )

    def _execute(
        self, delegation: SpecialistDelegation, request: ToolRequest, sequence: int
    ) -> ToolResult | ErrorResponse:
        for attempt in range(1, MAX_TOOL_RETRIES + 2):
            self._audit_event(
                delegation,
                request,
                sequence,
                attempt,
                AuditAction.TOOL_CALLED,
                request.input_refs,
                [],
                f"Called {request.tool.value} (attempt {attempt}).",
            )
            try:
                outcome = self._tools.execute(request)
            except Exception:  # noqa: BLE001
                outcome = ErrorResponse.model_validate(
                    {
                        "error": {
                            "code": "TOOL_FAILURE",
                            "message": "Inventory tool execution failed.",
                            "retryable": True,
                        }
                    }
                )
            refs = (
                request.input_refs
                if isinstance(outcome, ErrorResponse)
                else [outcome.output_ref, *outcome.evidence_refs]
            )
            codes = [outcome.error.code] if isinstance(outcome, ErrorResponse) else []
            self._audit_event(
                delegation,
                request,
                sequence,
                attempt,
                AuditAction.TOOL_RESULT_RECORDED,
                refs,
                codes,
                f"{request.tool.value} returned {'an error' if codes else 'trusted evidence'}.",
            )
            if (
                isinstance(outcome, ErrorResponse)
                and outcome.error.retryable
                and attempt <= MAX_TOOL_RETRIES
            ):
                continue
            return outcome
        raise AssertionError("unreachable")

    def _audit_event(
        self,
        delegation: SpecialistDelegation,
        request: ToolRequest,
        sequence: int,
        attempt: int,
        action: AuditAction,
        refs: Sequence[EvidenceRef],
        codes: list[str],
        summary: str,
    ) -> None:
        self._audit.record(
            AuditEvent(
                audit_event_id=f"{request.tool_call_id}-ATTEMPT-{attempt}-{'CALLED' if action is AuditAction.TOOL_CALLED else 'RESULT'}",
                timestamp=self._clock(),
                actor=SpecialistType.INVENTORY.value,
                action=action,
                state_revision=delegation.captured_state_revision,
                trigger_id=delegation.trigger_ref.reference_id,
                plan_id=delegation.active_plan_id,
                plan_version=delegation.active_plan_version,
                run_id=delegation.run_id,
                invocation_mode=delegation.invocation_mode,
                event_type=delegation.event_type,
                specialist_call_id=delegation.task_id,
                specialist=SpecialistType.INVENTORY,
                call_sequence=sequence,
                tool_call_id=request.tool_call_id,
                tool_name=request.tool,
                attempt_number=attempt,
                request_schema_version=request.schema_version,
                tool_succeeded=(None if action is AuditAction.TOOL_CALLED else not codes),
                evidence_refs=list(refs),
                reason_codes=codes,
                summary=summary,
            )
        )

    def _complete(
        self,
        delegation: SpecialistDelegation,
        decision: InventoryModelDecision,
        evidence: Sequence[EvidenceRef],
    ) -> SpecialistResult:
        if decision.missing_information:
            return self._missing(
                delegation,
                evidence,
                decision.missing_information,
                decision.summary,
                decision.interpreted_impact,
            )
        if decision.recommended_next_step in {
            RecommendedNextStep.CHECK_DEMAND,
            RecommendedNextStep.CHECK_INVENTORY,
            RecommendedNextStep.SUBMIT_REVISION,
        }:
            return self._escalate(
                delegation,
                evidence,
                EscalationReason.TOOL_FAILURE,
                "Inventory requested a forbidden agent route or plan action.",
            )
        return SpecialistResult(
            run_id=delegation.run_id,
            task_id=delegation.task_id,
            specialist=SpecialistType.INVENTORY,
            status=SpecialistStatus.COMPLETED,
            materiality_evidence_refs=delegation.materiality_evidence_refs,
            interpreted_impact=decision.interpreted_impact,
            evidence_refs=list(evidence),
            recommended_next_step=decision.recommended_next_step,
            summary=decision.summary,
            schema_version=delegation.required_output_schema_version,
        )

    @staticmethod
    def _missing(
        delegation: SpecialistDelegation,
        evidence: Sequence[EvidenceRef],
        missing: Sequence[str],
        summary: str,
        impact: str = "Required inventory information is unknown.",
    ) -> SpecialistResult:
        return SpecialistResult(
            run_id=delegation.run_id,
            task_id=delegation.task_id,
            specialist=SpecialistType.INVENTORY,
            status=SpecialistStatus.ESCALATED,
            materiality_evidence_refs=delegation.materiality_evidence_refs,
            interpreted_impact=impact,
            evidence_refs=list(evidence),
            missing_information=list(missing),
            recommended_next_step=RecommendedNextStep.ESCALATE,
            escalation_reason=EscalationReason.MISSING_REQUIRED_DATA,
            summary=summary,
            schema_version=delegation.required_output_schema_version,
        )

    @staticmethod
    def _escalate(
        delegation: SpecialistDelegation,
        evidence: Sequence[EvidenceRef],
        reason: EscalationReason,
        summary: str,
    ) -> SpecialistResult:
        return SpecialistResult(
            run_id=delegation.run_id,
            task_id=delegation.task_id,
            specialist=SpecialistType.INVENTORY,
            status=SpecialistStatus.ESCALATED,
            materiality_evidence_refs=delegation.materiality_evidence_refs,
            interpreted_impact="Inventory investigation could not complete safely.",
            evidence_refs=list(evidence),
            recommended_next_step=RecommendedNextStep.ESCALATE,
            escalation_reason=reason,
            summary=summary,
            schema_version=delegation.required_output_schema_version,
        )
