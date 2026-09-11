"""Canonical contracts shared by Agents, backend publication, and tool adapters.

This module contains schemas and lifecycle rules only. It intentionally contains no
agent runtime, persistence, or deterministic business calculations.
"""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    PositiveInt,
    StringConstraints,
    model_validator,
)

from src.errors import ErrorResponse

Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
StateRevision = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
SchemaVersion = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0)]
PositiveDecimal = Annotated[Decimal, Field(gt=0)]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AgentOutcome(StrEnum):
    KEEP_CURRENT_PLAN = "KEEP_CURRENT_PLAN"
    REVISE_PLAN = "REVISE_PLAN"
    REQUEST_HUMAN_APPROVAL = "REQUEST_HUMAN_APPROVAL"
    ESCALATE = "ESCALATE"


class EscalationReason(StrEnum):
    MISSING_REQUIRED_DATA = "MISSING_REQUIRED_DATA"
    NO_FEASIBLE_SUPPLIER = "NO_FEASIBLE_SUPPLIER"
    UNRESOLVED_SHORTAGE = "UNRESOLVED_SHORTAGE"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    CALCULATION_INCOMPLETE = "CALCULATION_INCOMPLETE"
    TOOL_FAILURE = "TOOL_FAILURE"
    CALL_LIMIT_REACHED = "CALL_LIMIT_REACHED"


class EscalationDetail(StrEnum):
    SEARCH_LIMIT_REACHED = "SEARCH_LIMIT_REACHED"


class EvidenceCategory(StrEnum):
    EVENT_CONTEXT = "EVENT_CONTEXT"
    MATERIALITY = "MATERIALITY"
    FORECAST_RESULT = "FORECAST_RESULT"
    INVENTORY_SNAPSHOT = "INVENTORY_SNAPSHOT"
    SUPPLIER_STATE = "SUPPLIER_STATE"
    CANDIDATE_RESULT = "CANDIDATE_RESULT"
    VALIDATION_RESULT = "VALIDATION_RESULT"
    POLICY_RESULT = "POLICY_RESULT"
    APPROVAL_REQUIREMENT = "APPROVAL_REQUIREMENT"
    AUDIT_EVENT = "AUDIT_EVENT"


class EvidenceSource(StrEnum):
    BACKEND = "BACKEND"
    DECISION_ENGINE = "DECISION_ENGINE"
    POLICY_ENGINE = "POLICY_ENGINE"


class EvidenceRef(ContractModel):
    category: EvidenceCategory
    source: EvidenceSource
    reference_id: Identifier
    version: PositiveInt | None = None
    state_revision: StateRevision | None = None

    @model_validator(mode="after")
    def require_version_or_revision(self) -> "EvidenceRef":
        if self.version is None and self.state_revision is None:
            raise ValueError("evidence must identify a version or state revision")
        return self


class InvocationMode(StrEnum):
    SCHEDULED = "SCHEDULED"
    EVENT = "EVENT"
    MANUAL = "MANUAL"


class AgentInvocation(ContractModel):
    run_id: Identifier
    invocation_mode: InvocationMode
    trigger_id: Identifier
    trigger_type: Identifier
    captured_state_revision: StateRevision
    affected_plan_id: Identifier | None = None
    affected_plan_version: PositiveInt | None = None
    schema_version: SchemaVersion = "1"

    @model_validator(mode="after")
    def bind_plan_version_to_plan(self) -> "AgentInvocation":
        if (self.affected_plan_id is None) != (self.affected_plan_version is None):
            raise ValueError("affected plan id and version must be supplied together")
        return self


class SpecialistType(StrEnum):
    DEMAND = "DEMAND"
    INVENTORY = "INVENTORY"
    PROCUREMENT = "PROCUREMENT"


class SpecialistDelegation(ContractModel):
    run_id: Identifier
    task_id: Identifier
    specialist: SpecialistType
    objective: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    trigger_ref: EvidenceRef
    captured_state_revision: StateRevision
    active_plan_id: Identifier | None = None
    active_plan_version: PositiveInt | None = None
    materiality_evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    context_refs: list[EvidenceRef] = Field(default_factory=list)
    required_output_schema_version: SchemaVersion = "1"

    @model_validator(mode="after")
    def bind_active_plan_version(self) -> "SpecialistDelegation":
        if (self.active_plan_id is None) != (self.active_plan_version is None):
            raise ValueError("active plan id and version must be supplied together")
        return self


class SpecialistStatus(StrEnum):
    COMPLETED = "COMPLETED"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"


class SpecialistResult(ContractModel):
    run_id: Identifier
    task_id: Identifier
    specialist: SpecialistType
    status: SpecialistStatus
    materiality_evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    interpreted_impact: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    candidate_result_ref: EvidenceRef | None = None
    missing_information: list[Identifier] = Field(default_factory=list)
    recommended_next_step: Identifier
    summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    schema_version: SchemaVersion = "1"


class AgentCompletionPublication(ContractModel):
    run_id: Identifier
    captured_state_revision: StateRevision
    outcome: AgentOutcome
    escalation_reason: EscalationReason | None = None
    escalation_detail: EscalationDetail | None = None
    candidate_result_ref: EvidenceRef | None = None
    affected_plan_id: Identifier | None = None
    affected_plan_version: PositiveInt | None = None
    reason_codes: list[Identifier] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(min_length=1)
    summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
    schema_version: SchemaVersion = "1"

    @model_validator(mode="after")
    def enforce_outcome_semantics(self) -> "AgentCompletionPublication":
        if (self.affected_plan_id is None) != (self.affected_plan_version is None):
            raise ValueError("affected plan id and version must be supplied together")
        if self.outcome is AgentOutcome.ESCALATE:
            if self.escalation_reason is None:
                raise ValueError("ESCALATE requires an escalation reason")
        elif self.escalation_reason is not None or self.escalation_detail is not None:
            raise ValueError("escalation fields are only valid for ESCALATE")
        if self.escalation_detail is not None and (
            self.escalation_reason is not EscalationReason.CALCULATION_INCOMPLETE
        ):
            raise ValueError(
                "SEARCH_LIMIT_REACHED is only valid with CALCULATION_INCOMPLETE"
            )
        if self.outcome is AgentOutcome.REVISE_PLAN:
            if self.candidate_result_ref is None:
                raise ValueError("REVISE_PLAN requires a candidate result reference")
            if self.candidate_result_ref.category is not EvidenceCategory.CANDIDATE_RESULT:
                raise ValueError("candidate result reference has the wrong category")
        return self


class PlanStatus(StrEnum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    INVALIDATED = "INVALIDATED"
    SUPERSEDED = "SUPERSEDED"


ALLOWED_PLAN_TRANSITIONS: dict[PlanStatus, frozenset[PlanStatus]] = {
    PlanStatus.PENDING_APPROVAL: frozenset(
        {
            PlanStatus.APPROVED,
            PlanStatus.REJECTED,
            PlanStatus.INVALIDATED,
            PlanStatus.SUPERSEDED,
        }
    ),
    PlanStatus.APPROVED: frozenset(
        {PlanStatus.INVALIDATED, PlanStatus.SUPERSEDED}
    ),
    PlanStatus.REJECTED: frozenset(),
    PlanStatus.INVALIDATED: frozenset(),
    PlanStatus.SUPERSEDED: frozenset(),
}


class PurchasePlanLine(ContractModel):
    ingredient_id: Identifier
    supplier_id: Identifier
    quantity: PositiveDecimal
    unit: Identifier
    unit_price: NonNegativeDecimal
    delivery_at: AwareDatetime


class PurchasePlanVersion(ContractModel):
    plan_id: Identifier
    version: PositiveInt
    status: PlanStatus
    forecast_ref: EvidenceRef
    inventory_snapshot_ref: EvidenceRef
    candidate_result_ref: EvidenceRef
    created_at: AwareDatetime
    trigger_id: Identifier
    state_revision: StateRevision
    lines: list[PurchasePlanLine] = Field(min_length=1)
    total_purchase_cost: NonNegativeDecimal
    expected_waste_cost: NonNegativeDecimal
    expected_stockout_cost: NonNegativeDecimal
    delivery_cost: NonNegativeDecimal
    emergency_penalty: NonNegativeDecimal
    total_expected_cost: NonNegativeDecimal
    requires_approval: Literal[True] = True
    approval_reason: Identifier
    invalidation_reason: str | None = None

    @model_validator(mode="after")
    def validate_plan_evidence(self) -> "PurchasePlanVersion":
        expected_categories = {
            "forecast_ref": EvidenceCategory.FORECAST_RESULT,
            "inventory_snapshot_ref": EvidenceCategory.INVENTORY_SNAPSHOT,
            "candidate_result_ref": EvidenceCategory.CANDIDATE_RESULT,
        }
        for field_name, expected in expected_categories.items():
            if getattr(self, field_name).category is not expected:
                raise ValueError(f"{field_name} must reference {expected}")
        if self.status is PlanStatus.INVALIDATED and not self.invalidation_reason:
            raise ValueError("INVALIDATED plan versions require an invalidation reason")
        if self.status is not PlanStatus.INVALIDATED and self.invalidation_reason:
            raise ValueError("invalidation reason is only valid for INVALIDATED versions")
        return self


class PurchasePlan(ContractModel):
    id: Identifier
    versions: list[PurchasePlanVersion] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_versions(self) -> "PurchasePlan":
        expected = list(range(1, len(self.versions) + 1))
        actual = [version.version for version in self.versions]
        if any(version.plan_id != self.id for version in self.versions):
            raise ValueError("all plan versions must belong to the plan")
        if actual != expected:
            raise ValueError("plan versions must be ordered and contiguous from 1")
        return self


class PlanTransition(ContractModel):
    plan_id: Identifier
    plan_version: PositiveInt
    from_status: PlanStatus
    to_status: PlanStatus
    reason: Identifier

    @model_validator(mode="after")
    def enforce_lifecycle(self) -> "PlanTransition":
        if self.to_status not in ALLOWED_PLAN_TRANSITIONS[self.from_status]:
            raise ValueError(
                f"invalid plan transition: {self.from_status} -> {self.to_status}"
            )
        return self


class ApprovalDecision(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ApprovalRequest(ContractModel):
    plan_id: Identifier
    plan_version: PositiveInt
    requested_by: Identifier
    captured_state_revision: StateRevision
    reason: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
    ]
    evidence_refs: list[EvidenceRef] = Field(min_length=1)


class Approval(ContractModel):
    approval_id: Identifier
    plan_id: Identifier
    plan_version: PositiveInt
    approver: Identifier
    decision: ApprovalDecision
    timestamp: AwareDatetime


class StateRevisionCheck(ContractModel):
    captured_state_revision: StateRevision
    current_state_revision: StateRevision

    @property
    def is_fresh(self) -> bool:
        return self.captured_state_revision == self.current_state_revision


class StateRevisionStaleError(ValueError):
    code = "STATE_REVISION_STALE"


def require_fresh_state_revision(check: StateRevisionCheck) -> None:
    """Backend publication guard; callers must invoke it before any mutation."""
    if not check.is_fresh:
        raise StateRevisionStaleError(
            "captured state revision does not match current authoritative revision"
        )


class AgentToolName(StrEnum):
    FORECAST_DEMAND = "forecast_demand"
    COMPARE_FORECAST_VERSIONS = "compare_forecast_versions"
    CALCULATE_INGREDIENT_REQUIREMENTS = "calculate_ingredient_requirements"
    CALCULATE_ESTIMATED_INVENTORY = "calculate_estimated_inventory"
    CALCULATE_EXPIRY_RISK = "calculate_expiry_risk"
    CALCULATE_STOCKOUT_RISK = "calculate_stockout_risk"
    GET_SUPPLIER_OPTIONS = "get_supplier_options"
    CHECK_SUPPLIER_FEASIBILITY = "check_supplier_feasibility"
    ENUMERATE_SUPPLIER_ALLOCATIONS = "enumerate_supplier_allocations"
    OPTIMISE_PURCHASE_PLAN = "optimise_purchase_plan"
    VALIDATE_PURCHASE_PLAN = "validate_purchase_plan"
    GET_APPROVAL_REQUIREMENT = "get_approval_requirement"
    REQUEST_HUMAN_REVIEW = "request_human_review"
    RECORD_AGENT_DECISION = "record_agent_decision"


class ToolRequest(ContractModel):
    tool_call_id: Identifier
    run_id: Identifier
    tool: AgentToolName
    captured_state_revision: StateRevision
    input_refs: list[EvidenceRef]
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    schema_version: SchemaVersion = "1"


class ToolResult(ContractModel):
    tool_call_id: Identifier
    run_id: Identifier
    tool: AgentToolName
    output_ref: EvidenceRef
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    schema_version: SchemaVersion = "1"


ToolErrorEnvelope = ErrorResponse


class AuditAction(StrEnum):
    TRIGGER_RECEIVED = "TRIGGER_RECEIVED"
    AGENT_RUN_STARTED = "AGENT_RUN_STARTED"
    SPECIALIST_CALLED = "SPECIALIST_CALLED"
    TOOL_CALLED = "TOOL_CALLED"
    TOOL_RESULT_RECORDED = "TOOL_RESULT_RECORDED"
    AGENT_COMPLETION_SUBMITTED = "AGENT_COMPLETION_SUBMITTED"
    VALIDATION_COMPLETED = "VALIDATION_COMPLETED"
    PLAN_TRANSITIONED = "PLAN_TRANSITIONED"
    APPROVAL_RECORDED = "APPROVAL_RECORDED"
    RUN_COMPLETED = "RUN_COMPLETED"


class AuditEvent(ContractModel):
    audit_event_id: Identifier
    timestamp: AwareDatetime
    actor: Identifier
    action: AuditAction
    state_revision: StateRevision
    trigger_id: Identifier | None = None
    plan_id: Identifier | None = None
    plan_version: PositiveInt | None = None
    run_id: Identifier | None = None
    specialist_call_id: Identifier | None = None
    tool_call_id: Identifier | None = None
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    requested_outcome: AgentOutcome | None = None
    from_plan_status: PlanStatus | None = None
    to_plan_status: PlanStatus | None = None
    approval_id: Identifier | None = None
    final_outcome: AgentOutcome | None = None
    reason_codes: list[Identifier] = Field(default_factory=list)
    summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]

    @model_validator(mode="after")
    def validate_bound_fields(self) -> "AuditEvent":
        if (self.plan_id is None) != (self.plan_version is None):
            raise ValueError("plan id and version must be supplied together")
        if (self.from_plan_status is None) != (self.to_plan_status is None):
            raise ValueError("plan transition statuses must be supplied together")
        return self


class PlanPublicationResult(ContractModel):
    """Authoritative backend response after freshness/validation/publication."""

    run_id: Identifier
    state_revision: StateRevision
    requested_outcome: AgentOutcome
    created_plan_version: PurchasePlanVersion | None = None
    audit_event_refs: list[EvidenceRef] = Field(min_length=1)
    published_at: AwareDatetime

    @model_validator(mode="after")
    def new_actionable_version_is_pending(self) -> "PlanPublicationResult":
        if self.created_plan_version is not None:
            if self.requested_outcome is not AgentOutcome.REVISE_PLAN:
                raise ValueError("only REVISE_PLAN may create a new plan version")
            if self.created_plan_version.status is not PlanStatus.PENDING_APPROVAL:
                raise ValueError("new actionable plan versions must be PENDING_APPROVAL")
        return self
