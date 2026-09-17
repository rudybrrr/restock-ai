"""PostgreSQL integration for the canonical Agent-to-Backend control plane."""

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src import planning
from src.agent_contracts import (
    AgentCompletionPublication,
    AgentInvocation,
    AgentOutcome,
    AgentToolName,
    AuditAction,
    AuditEvent,
    EvidenceCategory,
    EvidenceRef,
    EvidenceSource,
    InvocationMode,
    PlanStatus,
    RecommendedNextStep,
    SpecialistType,
    StateRevisionStaleError,
    ToolRequest,
    ToolResult,
)
from src.backend_control_plane import (
    BackendCoordinatorControlPlane,
    run_backend_coordinator,
)
from src.demand_tools import BackendDemandTools
from src.inventory_tools import BackendInventoryTools
from src.procurement_specialist import (
    ProcurementDecisionAction,
    ProcurementModelDecision,
    ProcurementReasoningContext,
)


def sign_in(client: TestClient) -> None:
    client.headers.pop("Authorization", None)
    client.headers["Origin"] = "https://frontend.example"
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "manager", "password": "test-manager-password"},
        ).status_code
        == 200
    )


def start_calculated_run(
    client: TestClient, *, revises_plan_id: str | None = None
) -> tuple[dict, dict]:
    sign_in(client)
    requested = client.post(
        "/api/v1/assessments",
        json={
            "as_of": "2026-02-15T22:00:00+08:00",
            "revises_plan_id": revises_plan_id,
        },
    )
    assert requested.status_code == 202, requested.text
    client.headers["Authorization"] = "Bearer test-agent-token"
    claimed = client.post("/api/v1/runs/claim")
    assert claimed.status_code == 200, claimed.text
    run = claimed.json()
    candidate = client.post(
        f"/api/v1/runs/{run['id']}/tools/optimise",
        json={"dish_quantities": {"chicken-rice": 200}},
    )
    assert candidate.status_code == 200, candidate.text
    assert candidate.json()["calculation_mode"] == "DEVELOPMENT_FIXTURE"
    return run, candidate.json()


def invocation(run: dict, *, plan: dict | None = None) -> AgentInvocation:
    return AgentInvocation(
        run_id=run["id"],
        invocation_mode=InvocationMode.MANUAL,
        trigger_id=run["trigger_event_id"],
        trigger_type=run["trigger"],
        captured_state_revision=str(run["input_revision"]),
        affected_plan_id=plan["plan_id"] if plan else None,
        affected_plan_version=plan["version"] if plan else None,
    )


class ProcurementOnlyClassifier:
    def classify(
        self, invocation: AgentInvocation, context_refs: Sequence[EvidenceRef]
    ) -> Sequence[SpecialistType]:
        return [SpecialistType.PROCUREMENT]


class DemandOnlyClassifier:
    def classify(
        self, invocation: AgentInvocation, context_refs: Sequence[EvidenceRef]
    ) -> Sequence[SpecialistType]:
        return [SpecialistType.DEMAND]


class TrustedCandidateModel:
    """Test-only reasoning script over a candidate already stored by Backend."""

    def decide(self, context: ProcurementReasoningContext) -> ProcurementModelDecision:
        calls = len(context.tool_results)
        if calls == 0:
            return ProcurementModelDecision(
                run_id=context.delegation.run_id,
                task_id=context.delegation.task_id,
                action=ProcurementDecisionAction.CALL_TOOL,
                tool=AgentToolName.OPTIMISE_PURCHASE_PLAN,
                input_refs=[context.delegation.trigger_ref],
                interpreted_impact="A stored trusted test candidate must be inspected.",
                summary="Inspect the stored candidate.",
            )
        if calls == 1:
            return ProcurementModelDecision(
                run_id=context.delegation.run_id,
                task_id=context.delegation.task_id,
                action=ProcurementDecisionAction.CALL_TOOL,
                tool=AgentToolName.VALIDATE_PURCHASE_PLAN,
                input_refs=[context.tool_results[0].output_ref],
                interpreted_impact="The stored candidate requires Backend validation.",
                summary="Validate the stored candidate.",
            )
        return ProcurementModelDecision(
            run_id=context.delegation.run_id,
            task_id=context.delegation.task_id,
            action=ProcurementDecisionAction.COMPLETE,
            interpreted_impact="The trusted fixture candidate has validation evidence.",
            recommended_next_step=RecommendedNextStep.SUBMIT_REVISION,
            summary="Submit the trusted fixture candidate.",
        )


class TrustedCandidateTools:
    """Test-only references; no candidate calculation occurs in Agent code."""

    def execute(self, request: ToolRequest) -> ToolResult:
        category = (
            EvidenceCategory.CANDIDATE_RESULT
            if request.tool is AgentToolName.OPTIMISE_PURCHASE_PLAN
            else EvidenceCategory.VALIDATION_RESULT
        )
        reference_id = (
            f"{request.run_id}:candidate"
            if category is EvidenceCategory.CANDIDATE_RESULT
            else f"{request.run_id}:fixture-validation"
        )
        return ToolResult(
            tool_call_id=request.tool_call_id,
            run_id=request.run_id,
            tool=request.tool,
            output_ref=EvidenceRef(
                category=category,
                source=EvidenceSource.DECISION_ENGINE,
                reference_id=reference_id,
                state_revision=request.captured_state_revision,
                run_id=request.run_id,
                specialist_call_id=request.tool_call_id.rsplit("-TOOL-", 1)[0],
                tool_call_id=request.tool_call_id,
                producer_tool=request.tool,
                call_sequence=int(request.tool_call_id.rsplit("-TOOL-", 1)[1]),
            ),
        )


def run_coordinator(session: Session, run: dict):
    return run_backend_coordinator(
        session,
        run["id"],
        TrustedCandidateModel(),
        TrustedCandidateTools(),
        manual_classifier=ProcurementOnlyClassifier(),
    )


def tool_request(run: dict, tool: AgentToolName) -> ToolRequest:
    return ToolRequest(
        tool_call_id=f"{run['id']}-TASK-LOCAL-TOOL-1",
        run_id=run["id"],
        tool=tool,
        captured_state_revision=str(run["input_revision"]),
        input_refs=[
            EvidenceRef(
                category=EvidenceCategory.EVENT_CONTEXT,
                source=EvidenceSource.BACKEND,
                reference_id=run["trigger_event_id"],
                state_revision=str(run["input_revision"]),
            )
        ],
    )


def test_local_demand_and_inventory_tools_read_frozen_backend_state_without_mutation(
    client: TestClient, database_url: str
) -> None:
    run, _ = start_calculated_run(client)
    engine = create_engine(database_url)
    with Session(engine) as session:
        before = planning.get_run(session, run["id"]).snapshot
        forecast = BackendDemandTools(session).execute(
            tool_request(run, AgentToolName.FORECAST_DEMAND)
        )
        projection = BackendInventoryTools(session).execute(
            tool_request(run, AgentToolName.PROJECT_INVENTORY)
        )
        after = planning.get_run(session, run["id"]).snapshot
    engine.dispose()

    assert isinstance(forecast, ToolResult)
    assert forecast.output_ref.category is EvidenceCategory.FORECAST_RESULT
    assert forecast.output_ref.source is EvidenceSource.DECISION_ENGINE
    assert forecast.output_data == {"forecast_complete": True}
    assert isinstance(projection, ToolResult)
    assert projection.output_ref.category is EvidenceCategory.INVENTORY_PROJECTION
    assert projection.output_data["provenance"] == "PROJECTED"
    assert before == after


def test_local_specialists_are_selectively_routed_by_the_real_backend_coordinator(
    client: TestClient, database_url: str
) -> None:
    run, _ = start_calculated_run(client)
    engine = create_engine(database_url)
    with Session(engine) as session:
        result = run_backend_coordinator(
            session,
            run["id"],
            TrustedCandidateModel(),
            TrustedCandidateTools(),
            manual_classifier=DemandOnlyClassifier(),
        )
    engine.dispose()

    calls = [
        event.specialist
        for event in result.trace
        if event.action is AuditAction.SPECIALIST_CALLED
    ]
    assert calls == [SpecialistType.DEMAND]


def test_coordinator_procurement_publishes_through_real_backend_services(
    client: TestClient, database_url: str
) -> None:
    run, _ = start_calculated_run(client)
    engine = create_engine(database_url)
    with Session(engine) as session:
        assert planning.current_state_revision(session) == str(run["input_revision"])
        result = run_backend_coordinator(
            session,
            run["id"],
            TrustedCandidateModel(),
            TrustedCandidateTools(),
            manual_classifier=ProcurementOnlyClassifier(),
        )
        assert result.completion.outcome is AgentOutcome.REVISE_PLAN
        assert result.publication_result is not None
        created = result.publication_result.created_plan_version
        assert created is not None
        assert created.status is PlanStatus.PENDING_APPROVAL
        assert created.version == 1
        active = BackendCoordinatorControlPlane(session).get_active_plan(
            invocation(
                run,
                plan={"plan_id": created.plan_id, "version": created.version},
            )
        )
        assert len(active) == 1
        assert active[0].version == 1
        assert active[0].category is EvidenceCategory.CANDIDATE_RESULT
    engine.dispose()

    history = client.get("/api/v1/plan-history")
    assert history.status_code == 200, history.text
    assert len(history.json()) == 1
    assert history.json()[0]["status"] == "PENDING_APPROVAL"
    audit = client.get("/api/v1/audit")
    completed_audit = next(
        row
        for row in audit.json()
        if row["action"] == AuditAction.RUN_COMPLETED
        and row["payload"]["run_id"] == run["id"]
    )
    assert (
        completed_audit["payload"]["backend_publication"]["plan_version"]["status"]
        == "PENDING_APPROVAL"
    )
    tool_actions = {
        row["action"]
        for row in audit.json()
        if row["payload"] and row["payload"].get("run_id") == run["id"]
    }
    assert AuditAction.TOOL_CALLED in tool_actions
    assert AuditAction.TOOL_RESULT_RECORDED in tool_actions


def test_stale_agent_completion_has_no_plan_or_audit_mutation(
    client: TestClient, database_url: str
) -> None:
    run, _ = start_calculated_run(client)
    sign_in(client)
    newer = client.post(
        "/api/v1/assessments", json={"as_of": "2026-02-16T08:00:00+08:00"}
    )
    assert newer.status_code == 202, newer.text
    audit_before = client.get("/api/v1/audit").json()

    engine = create_engine(database_url)
    with Session(engine) as session, pytest.raises(StateRevisionStaleError):
        run_coordinator(session, run)
    engine.dispose()

    assert client.get("/api/v1/plan-history").json() == []
    assert client.get("/api/v1/audit").json() == audit_before
    failed = client.get(f"/api/v1/runs/{run['id']}").json()
    assert failed["status"] == "FAILED"
    assert failed["failure_reason"] == "STATE_REVISION_STALE"


def test_human_review_request_is_bound_to_the_exact_pending_version(
    client: TestClient, database_url: str
) -> None:
    first_run, _ = start_calculated_run(client)
    engine = create_engine(database_url)
    with Session(engine) as session:
        published = run_coordinator(session, first_run).publication_result
        assert published is not None
        plan = published.created_plan_version
        assert plan is not None

    second_run, _ = start_calculated_run(client, revises_plan_id=plan.plan_id)
    review = AgentCompletionPublication(
        run_id=second_run["id"],
        captured_state_revision=str(second_run["input_revision"]),
        outcome=AgentOutcome.REQUEST_HUMAN_APPROVAL,
        affected_plan_id=plan.plan_id,
        affected_plan_version=plan.version,
        evidence_refs=[
            EvidenceRef(
                category=EvidenceCategory.EVENT_CONTEXT,
                source=EvidenceSource.BACKEND,
                reference_id=second_run["trigger_event_id"],
                state_revision=str(second_run["input_revision"]),
            )
        ],
        summary="The exact pending version still requires manager review.",
    )
    audit = AuditEvent(
        audit_event_id=f"{second_run['id']}-RUN-COMPLETED",
        timestamp=datetime.now(UTC),
        actor="COORDINATOR",
        action=AuditAction.RUN_COMPLETED,
        state_revision=str(second_run["input_revision"]),
        trigger_id=second_run["trigger_event_id"],
        plan_id=plan.plan_id,
        plan_version=plan.version,
        run_id=second_run["id"],
        invocation_mode=InvocationMode.MANUAL,
        event_type=second_run["trigger"],
        evidence_refs=review.evidence_refs,
        final_outcome=review.outcome,
        summary=review.summary,
    )
    with Session(engine) as session:
        adapter = BackendCoordinatorControlPlane(session)
        adapter.request_human_review(review)
        result = adapter.record_agent_decision(review, [audit])
        assert result.requested_outcome is AgentOutcome.REQUEST_HUMAN_APPROVAL
        assert result.created_plan_version is None
    engine.dispose()

    assert len(client.get("/api/v1/plan-history").json()) == 1


@pytest.mark.parametrize("reject_audit_write", ["RUN_COMPLETED"], indirect=True)
def test_publication_rolls_back_when_agent_audit_cannot_persist(
    client: TestClient, database_url: str, reject_audit_write: None
) -> None:
    run, _ = start_calculated_run(client)
    engine = create_engine(database_url)
    with Session(engine) as session:
        result = run_coordinator(session, run)
        assert result.completion.outcome is AgentOutcome.ESCALATE
        assert result.publication_result is None
    engine.dispose()

    assert client.get("/api/v1/plan-history").json() == []
    assert client.get(f"/api/v1/runs/{run['id']}").json()["status"] == "RUNNING"
