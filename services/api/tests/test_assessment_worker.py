"""PostgreSQL acceptance tests for the one-shot queued assessment worker."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from test_sales_materiality_contract import incomplete_result, request_body

from src import assessment_worker as worker
from src import database as db
from src import planning
from src.agent_contracts import (
    AgentOutcome,
    AgentToolName,
    EscalationReason,
    EvidenceRef,
    RecommendedNextStep,
    ToolRequest,
)
from src.decision_engine_adapter import BackendProcurementTools
from src.demand_specialist import (
    DemandDecisionAction,
    DemandModelDecision,
    DemandReasoningContext,
    LocalDemandReasoning,
)
from src.inventory_specialist import (
    InventoryDecisionAction,
    InventoryModelDecision,
    InventoryReasoningContext,
    LocalInventoryReasoning,
)
from src.procurement_specialist import (
    ProcurementDecisionAction,
    ProcurementModelDecision,
    ProcurementReasoningContext,
)

ISSUE_TIME = "2026-02-15T22:00:00+08:00"


def sign_in(client: TestClient) -> None:
    client.headers.pop("Authorization", None)
    client.headers["Origin"] = "https://frontend.example"
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "manager", "password": "test-manager-password"},
    )
    assert response.status_code == 200, response.text


class CompleteDemand:
    def decide(self, context: DemandReasoningContext) -> DemandModelDecision:
        return DemandModelDecision(
            run_id=context.delegation.run_id,
            task_id=context.delegation.task_id,
            action=DemandDecisionAction.COMPLETE,
            interpreted_impact="The test keeps demand reasoning typed and bounded.",
            summary="Demand investigation completed.",
        )


class CompleteInventory:
    def decide(self, context: InventoryReasoningContext) -> InventoryModelDecision:
        return InventoryModelDecision(
            run_id=context.delegation.run_id,
            task_id=context.delegation.task_id,
            action=InventoryDecisionAction.COMPLETE,
            interpreted_impact="The test keeps inventory reasoning typed and bounded.",
            summary="Inventory investigation completed.",
        )


class EngineProcurement:
    """Typed reasoning stub; all calculation remains in Backend tools."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, str]] = []

    def decide(self, context: ProcurementReasoningContext) -> ProcurementModelDecision:
        self.seen.append(
            (
                context.delegation.run_id,
                context.delegation.captured_state_revision,
            )
        )
        if not context.tool_results:
            return self._call(context, AgentToolName.OPTIMISE_PURCHASE_PLAN)
        if len(context.tool_results) == 1:
            return self._call(
                context,
                AgentToolName.VALIDATE_PURCHASE_PLAN,
                context.tool_results[-1].output_ref,
            )
        return ProcurementModelDecision(
            run_id=context.delegation.run_id,
            task_id=context.delegation.task_id,
            action=ProcurementDecisionAction.COMPLETE,
            interpreted_impact="The Backend engine returned candidate and validation evidence.",
            recommended_next_step=RecommendedNextStep.SUBMIT_REVISION,
            summary="Submit the validated engine candidate.",
        )

    @staticmethod
    def _call(
        context: ProcurementReasoningContext,
        tool: AgentToolName,
        reference: EvidenceRef | None = None,
    ) -> ProcurementModelDecision:
        return ProcurementModelDecision(
            run_id=context.delegation.run_id,
            task_id=context.delegation.task_id,
            action=ProcurementDecisionAction.CALL_TOOL,
            tool=tool,
            input_refs=[reference or context.delegation.trigger_ref],
            interpreted_impact="Use only the frozen Backend evidence.",
            summary=f"Call the deterministic {tool.value} tool.",
        )


class FailingProcurement:
    def decide(self, context: ProcurementReasoningContext) -> ProcurementModelDecision:
        raise RuntimeError("controlled worker model failure")


def models(
    *,
    procurement=None,
    demand=None,
    inventory=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        procurement=procurement or EngineProcurement(),
        demand=demand or CompleteDemand(),
        inventory=inventory or CompleteInventory(),
    )


def invoke_worker(database_url: str) -> worker.QueuedAssessmentWorkerResult:
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            return worker.run_one_queued_assessment(session)
    finally:
        engine.dispose()


def queue_manager_assessment(client: TestClient) -> dict:
    sign_in(client)
    response = client.post(
        "/api/v1/assessments", json={"as_of": ISSUE_TIME}
    )
    assert response.status_code == 202, response.text
    return response.json()


def persist_incomplete_sales_materiality(client: TestClient, run_id: str) -> None:
    client.headers["Authorization"] = "Bearer test-agent-token"
    context_response = client.get(f"/api/v1/runs/{run_id}/sales-materiality-context")
    assert context_response.status_code == 200, context_response.text
    context = context_response.json()
    body = request_body(context)
    created = client.post(
        f"/api/v1/runs/{run_id}/sales-materiality-requests", json=body
    )
    assert created.status_code == 201, created.text
    saved = client.put(
        f"/api/v1/runs/{run_id}/sales-materiality-requests/{body['request_id']}/result",
        json={
            "request_reference": created.json()["request_reference"],
            "result": incomplete_result(context),
        },
    )
    assert saved.status_code == 200, saved.text


def prepare_engine_plan(
    client: TestClient,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict, SimpleNamespace]:
    requested = queue_manager_assessment(client)
    initial_models = models()
    monkeypatch.setattr(
        worker,
        "build_organiser_reasoning_models",
        lambda settings: initial_models,
    )
    result = invoke_worker(database_url)
    assert result.run_id == requested["id"]
    assert result.outcome is AgentOutcome.REVISE_PLAN
    assert result.publication_status == "PUBLISHED"
    completed = client.get(f"/api/v1/runs/{requested['id']}").json()
    assert completed["status"] == "SUCCEEDED"
    assert completed["plan_version_id"] == result.publication_reference
    return completed, initial_models


def install_models(
    monkeypatch: pytest.MonkeyPatch, models_to_use: SimpleNamespace
) -> None:
    monkeypatch.setattr(
        worker,
        "build_organiser_reasoning_models",
        lambda settings: models_to_use,
    )


def test_no_queued_run_returns_safe_no_work_result(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        worker,
        "build_organiser_reasoning_models",
        lambda settings: pytest.fail("model construction must not run without work"),
    )

    result = invoke_worker(database_url)

    assert result.model_dump(exclude_none=True) == {
        "publication_status": "NO_WORK",
        "failure_classification": "NO_QUEUED_RUN",
    }


def test_manager_assessment_worker_publishes_real_engine_plan_and_frozen_refs(
    client: TestClient,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested = queue_manager_assessment(client)
    procurement = EngineProcurement()
    test_models = models(procurement=procurement)
    install_models(monkeypatch, test_models)

    seen_tools: list[ToolRequest] = []

    class RecordingTools(BackendProcurementTools):
        def execute(self, request: ToolRequest):
            seen_tools.append(request)
            return super().execute(request)

    monkeypatch.setattr(worker, "BackendProcurementTools", RecordingTools)
    result = invoke_worker(database_url)

    completed = client.get(f"/api/v1/runs/{requested['id']}").json()
    assert result.outcome is AgentOutcome.REVISE_PLAN
    assert result.publication_status == "PUBLISHED"
    assert completed["status"] == "SUCCEEDED"
    assert completed["outcome"] == AgentOutcome.REVISE_PLAN.value
    assert completed["plan_version_id"] == result.publication_reference

    plan = client.get(f"/api/v1/plans/{completed['plan_version_id']}")
    assert plan.status_code == 200, plan.text
    assert plan.json()["status"] == "PENDING_APPROVAL"
    assert plan.json()["calculation_mode"] == "ENGINE"
    assert all(
        request.run_id == requested["id"]
        and request.captured_state_revision == str(completed["input_revision"])
        for request in seen_tools
    )
    assert procurement.seen
    assert all(run_id == requested["id"] for run_id, _ in procurement.seen)
    assert all(
        revision == str(completed["input_revision"])
        for _, revision in procurement.seen
    )
    assert "DEVELOPMENT_FIXTURE" not in str(plan.json())

    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            run = planning.get_run(session, requested["id"])
            plan_rows = session.execute(select(db.plan_versions)).mappings().all()
    finally:
        engine.dispose()

    assert result.publication_status == "PUBLISHED"
    contract = run.snapshot["procurement_contract"]
    assert contract["captured_state_revision"] == str(run.input_revision)
    assert len(plan_rows) == 1
    assert plan_rows[0]["run_id"] == run.id


def test_harmless_supplier_event_keeps_current_plan_without_replacement(
    client: TestClient,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed, _ = prepare_engine_plan(client, database_url, monkeypatch)
    original_plan_id = completed["plan_version_id"]

    change = client.patch(
        "/api/v1/supplier-offers/market-chicken",
        json={
            "effective_at": "2026-02-16T08:00:00+08:00",
            "current_status": "UNAVAILABLE",
        },
    )
    assert change.status_code == 200, change.text
    queued = client.get("/api/v1/runs").json()[0]

    result = invoke_worker(database_url)

    assert result.run_id == queued["id"]
    assert result.outcome is AgentOutcome.KEEP_CURRENT_PLAN
    assert result.publication_status == "PUBLISHED"
    assert result.publication_reference is None
    assert client.get(f"/api/v1/runs/{queued['id']}").json()["plan_version_id"] == original_plan_id
    assert client.get(f"/api/v1/plans/{original_plan_id}").json()["status"] == "PENDING_APPROVAL"


@pytest.mark.parametrize("event_family", ["promotion", "supplier", "sales"])
def test_material_event_families_use_normal_api_path_and_fail_closed_or_revise(
    client: TestClient,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    event_family: str,
) -> None:
    prepare_engine_plan(client, database_url, monkeypatch)
    if event_family == "promotion":
        menu_item = client.get("/api/v1/menu-items").json()[0]["id"]
        response = client.put(
            "/api/v1/promotions/worker-promotion",
            json={
                "revision": 1,
                "name": "Worker promotion",
                "start_date": "2026-02-16",
                "end_date": "2026-02-16",
                "menu_item_ids": [menu_item],
                "demand_multiplier": "2",
                "active": True,
                "effective_at": "2026-02-16T08:00:00+08:00",
            },
        )
    elif event_family == "supplier":
        response = client.patch(
            "/api/v1/supplier-offers/fresh-chicken",
            json={
                "effective_at": "2026-02-16T08:00:00+08:00",
                "current_status": "UNAVAILABLE",
            },
        )
    else:
        response = client.post(
            "/api/v1/sales-batches",
            json={
                "source": "worker-test",
                "batch_id": "worker-material-sales-001",
                "period_start": "2026-02-15T22:00:00+08:00",
                "period_end": "2026-02-16T01:00:00+08:00",
                "sales": {"chicken-rice": 10},
            },
        )
    assert response.status_code in {200, 201}, response.text

    event_models = models(
        demand=LocalDemandReasoning(), inventory=LocalInventoryReasoning()
    )
    queued = client.get("/api/v1/runs").json()[0]
    if event_family == "sales":
        def build_after_claim(settings):
            persist_incomplete_sales_materiality(client, queued["id"])
            return event_models

        monkeypatch.setattr(worker, "build_organiser_reasoning_models", build_after_claim)
    else:
        install_models(monkeypatch, event_models)
    result = invoke_worker(database_url)

    assert result.publication_status == "PUBLISHED"
    if event_family == "sales":
        assert result.outcome is AgentOutcome.ESCALATE
        assert result.failure_classification is EscalationReason.MISSING_REQUIRED_DATA
        completed = client.get(f"/api/v1/runs/{queued['id']}")
        assert completed.status_code == 200, completed.text
        assert completed.json()["status"] == "SUCCEEDED"
        assert completed.json()["outcome"] == AgentOutcome.ESCALATE.value
        assert (
            completed.json()["escalation_reason"]
            == EscalationReason.MISSING_REQUIRED_DATA.value
        )
        assessment = client.get(
            f"/api/v1/runs/{queued['id']}/sales-materiality-assessment"
        )
        assert assessment.status_code == 200, assessment.text
        saved = assessment.json()
        assert saved["request_reference"]
        assert saved["result_reference"]
        assert saved["completed_at"]
        assert saved["result"]["complete"] is False
        assert saved["result"]["material_change"] is None
        return
    assert result.outcome in {AgentOutcome.REVISE_PLAN, AgentOutcome.ESCALATE}
    if result.outcome is AgentOutcome.REVISE_PLAN:
        assert result.publication_reference is not None
        plan = client.get(f"/api/v1/plans/{result.publication_reference}")
        assert plan.status_code == 200, plan.text
        assert plan.json()["calculation_mode"] == "ENGINE"
    else:
        assert result.failure_classification in set(EscalationReason)


def test_inventory_adjustment_event_uses_normal_api_path_and_escalates_when_incomplete(
    client: TestClient,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_engine_plan(client, database_url, monkeypatch)
    sign_in(client)
    lots = client.get("/api/v1/inventory").json()
    dishes = client.get("/api/v1/menu-items").json()
    day = "/api/v1/daily-updates/2026-02-15"
    initial = {
        "cutoff": "2026-02-15T22:00:00+08:00",
        "counts": {lot["id"]: lot["quantity"] for lot in lots},
        "sales": {dish["id"]: 0 for dish in dishes},
    }
    assert client.post(day + "/draft", json=initial).status_code == 200
    assert client.post(day + "/submit").status_code == 200
    first_daily = models(demand=LocalDemandReasoning(), inventory=LocalInventoryReasoning())
    install_models(monkeypatch, first_daily)
    first_run = client.get("/api/v1/runs").json()[0]
    first_result = invoke_worker(database_url)
    assert first_result.outcome is AgentOutcome.KEEP_CURRENT_PLAN
    assert first_result.publication_reference is None
    assert client.get(f"/api/v1/runs/{first_run['id']}").json()["status"] == "SUCCEEDED"

    corrected = {**initial, "counts": dict(initial["counts"])}
    corrected["counts"][lots[0]["id"]] = str(float(lots[0]["quantity"]) + 1)
    assert client.post(day + "/draft", json=corrected).status_code == 200
    assert client.post(day + "/submit").status_code == 200
    second_result = invoke_worker(database_url)

    assert second_result.outcome is AgentOutcome.ESCALATE
    assert second_result.failure_classification is EscalationReason.MISSING_REQUIRED_DATA
    assert second_result.publication_status == "PUBLISHED"


def test_new_input_after_claim_is_rejected_after_backend_stale_publication_guard(
    client: TestClient,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested = queue_manager_assessment(client)
    test_models = models()

    def build_after_claim(settings):
        response = client.patch(
            "/api/v1/supplier-offers/market-chicken",
            json={
                "effective_at": "2026-02-16T08:00:00+08:00",
                "current_status": "UNAVAILABLE",
            },
        )
        assert response.status_code == 200, response.text
        return test_models

    monkeypatch.setattr(worker, "build_organiser_reasoning_models", build_after_claim)
    result = invoke_worker(database_url)

    assert result.run_id == requested["id"]
    assert result.outcome is None
    assert result.publication_status == "STALE_REJECTED"
    assert result.failure_classification == "STATE_REVISION_STALE"
    stale = client.get(f"/api/v1/runs/{requested['id']}").json()
    assert stale["status"] == "FAILED"
    assert stale["failure_reason"] == "STATE_REVISION_STALE"
    assert stale["plan_version_id"] is None
    assert client.get("/api/v1/plan-history").json() == []


def test_organiser_configuration_failure_after_claim_fails_run_closed(
    client: TestClient,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested = queue_manager_assessment(client)

    def fail_build(settings):
        raise RuntimeError("LLM_GATEWAY_API_KEY=secret-must-not-escape")

    monkeypatch.setattr(worker, "build_organiser_reasoning_models", fail_build)
    result = invoke_worker(database_url)

    assert result.run_id == requested["id"]
    assert result.outcome is None
    assert result.publication_status == "NOT_PUBLISHED"
    assert result.publication_reference is None
    assert result.failure_classification is EscalationReason.TOOL_FAILURE
    failed = client.get(f"/api/v1/runs/{requested['id']}").json()
    assert failed["status"] == "FAILED"
    assert failed["failure_reason"] == EscalationReason.TOOL_FAILURE.value
    assert failed["plan_version_id"] is None
    assert "secret-must-not-escape" not in str(result.model_dump())
    assert "secret-must-not-escape" not in str(failed)
    assert client.get("/api/v1/plan-history").json() == []


def test_model_failure_preserves_canonical_tool_failure_without_fixture_fallback(
    client: TestClient,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested = queue_manager_assessment(client)
    failing = models(procurement=FailingProcurement())
    install_models(monkeypatch, failing)

    result = invoke_worker(database_url)

    assert result.run_id == requested["id"]
    assert result.outcome is AgentOutcome.ESCALATE
    assert result.failure_classification is EscalationReason.TOOL_FAILURE
    assert result.publication_status == "PUBLISHED"
    completed = client.get(f"/api/v1/runs/{requested['id']}").json()
    assert completed["status"] == "SUCCEEDED"
    assert completed["plan_version_id"] is None
    assert client.get("/api/v1/plan-history").json() == []
