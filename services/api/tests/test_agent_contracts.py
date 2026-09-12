from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.agent_contracts import (
    ALLOWED_PLAN_TRANSITIONS,
    AgentCompletionPublication,
    AgentOutcome,
    AgentToolName,
    Approval,
    ApprovalDecision,
    ApprovalRequest,
    AuditAction,
    AuditEvent,
    EscalationDetail,
    EscalationReason,
    EventType,
    EvidenceCategory,
    EvidenceRef,
    EvidenceSource,
    PlanPublicationResult,
    PlanStatus,
    PlanTransition,
    PurchasePlanLine,
    PurchasePlanVersion,
    RecommendedNextStep,
    SpecialistResult,
    SpecialistStatus,
    SpecialistType,
    StateRevisionCheck,
    StateRevisionStaleError,
    ToolErrorEnvelope,
    require_fresh_state_revision,
)
from src.errors import ErrorDetail, ErrorResponse

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


def evidence(
    category: EvidenceCategory = EvidenceCategory.VALIDATION_RESULT,
    reference_id: str = "REF-1",
) -> EvidenceRef:
    return EvidenceRef(
        category=category,
        source=EvidenceSource.DECISION_ENGINE,
        reference_id=reference_id,
        version=1,
    )


def plan_version(status: PlanStatus = PlanStatus.PENDING_APPROVAL) -> PurchasePlanVersion:
    return PurchasePlanVersion(
        plan_id="PLAN-1",
        version=1,
        status=status,
        forecast_ref=evidence(EvidenceCategory.FORECAST_RESULT, "FORECAST-1"),
        inventory_snapshot_ref=evidence(
            EvidenceCategory.INVENTORY_SNAPSHOT, "INVENTORY-1"
        ),
        candidate_result_ref=evidence(
            EvidenceCategory.CANDIDATE_RESULT, "CANDIDATE-1"
        ),
        created_at=NOW,
        trigger_id="EVENT-1",
        state_revision="STATE-1",
        lines=[
            PurchasePlanLine(
                ingredient_id="chicken",
                supplier_id="supplier-a",
                quantity=Decimal(2),
                unit="kg",
                unit_price=Decimal("4.50"),
                delivery_at=NOW,
            )
        ],
        total_purchase_cost=Decimal(9),
        expected_waste_cost=Decimal(0),
        expected_stockout_cost=Decimal(0),
        delivery_cost=Decimal(0),
        emergency_penalty=Decimal(0),
        total_expected_cost=Decimal(9),
        approval_reason="All actionable recommendations require manager approval",
    )


def test_agent_outcomes_are_frozen() -> None:
    assert {item.value for item in AgentOutcome} == {
        "KEEP_CURRENT_PLAN",
        "REVISE_PLAN",
        "REQUEST_HUMAN_APPROVAL",
        "ESCALATE",
    }


def test_event_types_and_specialist_next_steps_are_authoritative() -> None:
    assert {item.value for item in EventType} == {
        "SALES_UPDATED",
        "PROMOTION_CREATED",
        "PROMOTION_CHANGED",
        "INVENTORY_ADJUSTED",
        "INVENTORY_WASTED",
        "SUPPLIER_AVAILABILITY_CHANGED",
        "SUPPLIER_PRICE_CHANGED",
        "DELIVERY_DELAYED",
        "DELIVERY_SHORT",
        "DELIVERY_CANCELLED",
        "MANAGER_INSTRUCTION",
    }
    assert RecommendedNextStep("CHECK_INVENTORY") is RecommendedNextStep.CHECK_INVENTORY


def test_specialist_escalation_requires_a_typed_reason() -> None:
    with pytest.raises(ValidationError, match="requires a reason"):
        SpecialistResult(
            run_id="RUN-1",
            task_id="TASK-1",
            specialist=SpecialistType.DEMAND,
            status=SpecialistStatus.ESCALATED,
            interpreted_impact="Demand evidence is incomplete.",
            recommended_next_step=RecommendedNextStep.ESCALATE,
            summary="Cannot safely continue.",
        )


def test_escalation_reasons_and_search_detail_are_frozen() -> None:
    assert {item.value for item in EscalationReason} == {
        "MISSING_REQUIRED_DATA",
        "NO_FEASIBLE_SUPPLIER",
        "UNRESOLVED_SHORTAGE",
        "POLICY_VIOLATION",
        "CALCULATION_INCOMPLETE",
        "TOOL_FAILURE",
        "CALL_LIMIT_REACHED",
    }
    assert list(EscalationDetail) == [EscalationDetail.SEARCH_LIMIT_REACHED]
    assert EscalationReason.CALCULATION_INCOMPLETE is not EscalationReason.TOOL_FAILURE
    assert (
        EscalationReason.CALCULATION_INCOMPLETE
        is not EscalationReason.NO_FEASIBLE_SUPPLIER
    )


def test_agent_tool_contract_names_are_frozen() -> None:
    assert {item.value for item in AgentToolName} == {
        "forecast_demand",
        "compare_forecast_versions",
        "calculate_ingredient_requirements",
        "calculate_estimated_inventory",
        "calculate_expiry_risk",
        "calculate_stockout_risk",
        "get_supplier_options",
        "check_supplier_feasibility",
        "enumerate_supplier_allocations",
        "optimise_purchase_plan",
        "validate_purchase_plan",
        "get_approval_requirement",
        "request_human_review",
        "record_agent_decision",
    }


def test_tool_errors_reuse_the_backend_error_contract() -> None:
    assert ToolErrorEnvelope is ErrorResponse
    error = ToolErrorEnvelope(
        error=ErrorDetail(
            code="TOOL_FAILURE",
            message="Deterministic tool failed.",
            retryable=True,
            details={"tool": "forecast_demand"},
        )
    )
    assert error.error.details == {"tool": "forecast_demand"}


def test_branching_plan_lifecycle_is_frozen_without_valid() -> None:
    assert "VALID" not in PlanStatus.__members__
    assert ALLOWED_PLAN_TRANSITIONS == {
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
    PlanTransition(
        plan_id="PLAN-1",
        plan_version=1,
        from_status=PlanStatus.PENDING_APPROVAL,
        to_status=PlanStatus.APPROVED,
        reason="Manager approved exact version",
    )
    with pytest.raises(ValidationError, match="invalid plan transition"):
        PlanTransition(
            plan_id="PLAN-1",
            plan_version=1,
            from_status=PlanStatus.APPROVED,
            to_status=PlanStatus.REJECTED,
            reason="Not allowed",
        )


def test_agent_completion_enforces_typed_outcome_semantics() -> None:
    completion = AgentCompletionPublication(
        run_id="RUN-1",
        captured_state_revision="STATE-1",
        outcome=AgentOutcome.REVISE_PLAN,
        candidate_result_ref=evidence(
            EvidenceCategory.CANDIDATE_RESULT, "CANDIDATE-1"
        ),
        affected_plan_id="PLAN-1",
        affected_plan_version=1,
        reason_codes=["SUPPLIER_ALLOCATION_CHANGED"],
        evidence_refs=[evidence()],
        summary="Validated candidate requires a new version.",
    )
    assert completion.outcome is AgentOutcome.REVISE_PLAN

    with pytest.raises(ValidationError, match="requires a candidate"):
        AgentCompletionPublication(
            run_id="RUN-1",
            captured_state_revision="STATE-1",
            outcome=AgentOutcome.REVISE_PLAN,
            evidence_refs=[evidence()],
            summary="Missing candidate.",
        )
    with pytest.raises(ValidationError, match="requires an escalation reason"):
        AgentCompletionPublication(
            run_id="RUN-1",
            captured_state_revision="STATE-1",
            outcome=AgentOutcome.ESCALATE,
            evidence_refs=[evidence()],
            summary="Unsafe to continue.",
        )
    with pytest.raises(ValidationError, match="only valid with"):
        AgentCompletionPublication(
            run_id="RUN-1",
            captured_state_revision="STATE-1",
            outcome=AgentOutcome.ESCALATE,
            escalation_reason=EscalationReason.TOOL_FAILURE,
            escalation_detail=EscalationDetail.SEARCH_LIMIT_REACHED,
            evidence_refs=[evidence()],
            summary="Tool failed.",
        )


def test_evidence_requires_stable_id_and_version_or_revision() -> None:
    assert evidence().reference_id == "REF-1"
    assert EvidenceRef(
        category=EvidenceCategory.MATERIALITY,
        source=EvidenceSource.DECISION_ENGINE,
        reference_id="MAT-1",
        state_revision="STATE-7",
    ).state_revision == "STATE-7"
    with pytest.raises(ValidationError, match="version or state revision"):
        EvidenceRef(
            category=EvidenceCategory.FORECAST_RESULT,
            source=EvidenceSource.DECISION_ENGINE,
            reference_id="F-1",
        )
    with pytest.raises(ValidationError):
        EvidenceRef(
            category=EvidenceCategory.FORECAST_RESULT,
            source=EvidenceSource.DECISION_ENGINE,
            reference_id="",
            version=1,
        )


def test_state_revision_guard_rejects_stale_publication_contract() -> None:
    require_fresh_state_revision(
        StateRevisionCheck(
            captured_state_revision="STATE-1", current_state_revision="STATE-1"
        )
    )
    with pytest.raises(StateRevisionStaleError) as caught:
        require_fresh_state_revision(
            StateRevisionCheck(
                captured_state_revision="STATE-1", current_state_revision="STATE-2"
            )
        )
    assert caught.value.code == "STATE_REVISION_STALE"
    with pytest.raises(ValidationError):
        StateRevisionCheck(
            captured_state_revision="", current_state_revision="STATE-2"
        )


def test_new_actionable_plan_version_must_be_pending_approval() -> None:
    result = PlanPublicationResult(
        run_id="RUN-1",
        state_revision="STATE-1",
        requested_outcome=AgentOutcome.REVISE_PLAN,
        created_plan_version=plan_version(),
        audit_event_refs=[evidence(EvidenceCategory.AUDIT_EVENT, "AUDIT-1")],
        published_at=NOW,
    )
    assert result.created_plan_version is not None
    assert result.created_plan_version.status is PlanStatus.PENDING_APPROVAL
    with pytest.raises(ValidationError, match="must be PENDING_APPROVAL"):
        PlanPublicationResult(
            run_id="RUN-1",
            state_revision="STATE-1",
            requested_outcome=AgentOutcome.REVISE_PLAN,
            created_plan_version=plan_version(PlanStatus.APPROVED),
            audit_event_refs=[evidence(EvidenceCategory.AUDIT_EVENT, "AUDIT-1")],
            published_at=NOW,
        )


def test_approval_is_bound_to_exact_positive_plan_version() -> None:
    request = ApprovalRequest(
        plan_id="PLAN-1",
        plan_version=2,
        requested_by="backend",
        captured_state_revision="STATE-2",
        reason="A new actionable recommendation requires manager review.",
        evidence_refs=[evidence(EvidenceCategory.POLICY_RESULT, "POLICY-1")],
    )
    assert (request.plan_id, request.plan_version) == ("PLAN-1", 2)
    approval = Approval(
        approval_id="APPROVAL-1",
        plan_id="PLAN-1",
        plan_version=2,
        approver="manager",
        decision=ApprovalDecision.APPROVED,
        timestamp=NOW,
    )
    assert (approval.plan_id, approval.plan_version) == ("PLAN-1", 2)
    with pytest.raises(ValidationError):
        Approval(
            approval_id="APPROVAL-1",
            plan_id="PLAN-1",
            plan_version=0,
            approver="manager",
            decision=ApprovalDecision.APPROVED,
            timestamp=NOW,
        )


def test_audit_event_is_business_level_and_strict() -> None:
    event = AuditEvent(
        audit_event_id="AUDIT-1",
        timestamp=NOW,
        actor="backend",
        action=AuditAction.PLAN_TRANSITIONED,
        state_revision="STATE-2",
        trigger_id="EVENT-1",
        plan_id="PLAN-1",
        plan_version=2,
        run_id="RUN-1",
        evidence_refs=[evidence()],
        requested_outcome=AgentOutcome.REVISE_PLAN,
        from_plan_status=PlanStatus.APPROVED,
        to_plan_status=PlanStatus.SUPERSEDED,
        reason_codes=["NEW_VERSION_CREATED"],
        summary="PLAN-v1 was superseded by PLAN-v2.",
    )
    assert event.action is AuditAction.PLAN_TRANSITIONED
    with pytest.raises(ValidationError):
        AuditEvent.model_validate(
            {
                "audit_event_id": "AUDIT-1",
                "timestamp": NOW,
                "actor": "backend",
                "action": AuditAction.RUN_COMPLETED,
                "state_revision": "STATE-2",
                "plan_id": "PLAN-1",
                "summary": "Malformed because the plan version is absent.",
                "chain_of_thought": "must not be accepted",
            }
        )


def test_audit_event_has_backward_compatible_structural_agent_metadata() -> None:
    event = AuditEvent(
        audit_event_id="AUDIT-SPECIALIST-1",
        timestamp=NOW,
        actor="COORDINATOR",
        action=AuditAction.SPECIALIST_CALLED,
        state_revision="STATE-1",
        run_id="RUN-1",
        specialist_call_id="TASK-1",
        specialist=SpecialistType.PROCUREMENT,
        call_sequence=1,
        summary="Called the Procurement specialist.",
    )
    assert event.specialist is SpecialistType.PROCUREMENT
    assert event.call_sequence == 1
    assert event.reason_codes == []

    legacy = AuditEvent(
        audit_event_id="AUDIT-LEGACY-1",
        timestamp=NOW,
        actor="backend",
        action=AuditAction.RUN_COMPLETED,
        state_revision="STATE-1",
        summary="Legacy events remain valid without optional structural metadata.",
    )
    assert legacy.specialist is None
    assert legacy.call_sequence is None
    assert legacy.attempt_number is None
