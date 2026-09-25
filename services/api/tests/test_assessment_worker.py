"""PostgreSQL acceptance tests for the one-shot queued assessment worker."""

from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

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
from src.errors import ApiError
from src.inventory_specialist import (
    InventoryDecisionAction,
    InventoryModelDecision,
    InventoryReasoningContext,
    LocalInventoryReasoning,
)
from src.procurement_contract_schemas import ProcurementContract
from src.procurement_specialist import (
    ProcurementDecisionAction,
    ProcurementModelDecision,
    ProcurementReasoningContext,
)
from src.sales_materiality_adapter import _issued_forecast
from src.sales_materiality_contracts import read_assessment

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


def post_material_sales_coverage(
    client: TestClient, database_url: str, baseline_run_id: str
) -> tuple[str, str, int]:
    """Record full post-count coverage and one threshold-reaching sales deviation."""
    prior_run_ids = {run["id"] for run in client.get("/api/v1/runs").json()}
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            baseline = planning.get_run(session, baseline_run_id)
            contract = ProcurementContract.model_validate(
                baseline.snapshot["procurement_contract"]
            )
            assert contract.sales_threshold_policy is not None
            issued_forecast = _issued_forecast(baseline, contract)
    finally:
        engine.dispose()

    policy = contract.sales_threshold_policy.payload
    candidates = [
        bucket
        for bucket in issued_forecast.buckets
        if bucket.start >= contract.as_of
        and bucket.start.date() == contract.policy.payload.target_date
    ]
    cumulative = {
        item["id"]: Decimal(0)
        for item in (contract.frozen_state or {})["menu_items"]
    }
    selected_index: int | None = None
    selected_dish: str | None = None
    selected_expected = Decimal(0)
    for index, bucket in enumerate(candidates):
        for dish_id, expected in bucket.expected_portions.items():
            cumulative[dish_id] += expected
        if (
            index + 1 >= policy.minimum_complete_buckets
            and all(value >= policy.minimum_expected_portions for value in cumulative.values())
        ):
            selected_dish = max(cumulative, key=cumulative.__getitem__)
            selected_expected = cumulative[selected_dish]
            selected_index = index
            break
    assert selected_index is not None and selected_dish is not None
    assert selected_expected >= max(
        policy.absolute_floor,
        selected_expected * policy.relative_threshold,
    )
    observed = 0

    final_bucket = candidates[selected_index]
    coverage_start = min(
        datetime.fromisoformat(row["counted_at"])
        for row in (contract.frozen_state or {})["inventory"]
    )
    interval = timedelta(minutes=30)
    expected_by_start = {
        bucket.start: bucket for bucket in candidates[: selected_index + 1]
    }
    current = coverage_start
    index = 0
    while current < final_bucket.start:
        bucket = expected_by_start.get(current)
        sales = (
            {
                dish_id: int(value.to_integral_value(rounding=ROUND_CEILING))
                for dish_id, value in bucket.expected_portions.items()
                if dish_id != selected_dish
            }
            if bucket is not None
            else {}
        )
        response = client.post(
            "/api/v1/sales-batches",
            json={
                "source": "worker-materiality",
                "batch_id": f"coverage-{index:02d}",
                "period_start": current.isoformat(),
                "period_end": (current + interval).isoformat(),
                "sales": sales,
            },
        )
        assert response.status_code == 201, response.text
        current += interval
        index += 1

    response = client.post(
        "/api/v1/sales-batches",
        json={
            "source": "worker-materiality",
            "batch_id": "material-final",
            "period_start": final_bucket.start.isoformat(),
            "period_end": final_bucket.end.isoformat(),
            "sales": {
                dish_id: int(value.to_integral_value(rounding=ROUND_CEILING))
                for dish_id, value in final_bucket.expected_portions.items()
                if dish_id != selected_dish
            },
        },
    )
    assert response.status_code == 201, response.text
    new_runs = [
        run
        for run in client.get("/api/v1/runs").json()
        if run["id"] not in prior_run_ids
    ]
    assert len(new_runs) == 1
    queued = new_runs[0]
    return queued["id"], selected_dish, observed


def persist_incomplete_inventory_adjustment_assessment(
    client: TestClient, run_id: str
) -> tuple[dict, dict]:
    client.headers["Authorization"] = "Bearer test-agent-token"
    context_response = client.get(
        f"/api/v1/runs/{run_id}/inventory-adjustment-context"
    )
    assert context_response.status_code == 200, context_response.text
    context = context_response.json()
    assert context["run_id"] == run_id
    result = {
        "material_change": None,
        "complete": False,
        "inventory_feasible": None,
        "assessed_lot_ids": context["assessed_lot_ids"],
        "assessed_ingredient_ids": context["assessed_ingredient_ids"],
        "findings": [],
        "evidence_refs": context["required_evidence_refs"],
        "required_follow_up": [],
        "run_id": run_id,
        "snapshot_reference": context["snapshot_reference"],
        "inventory_snapshot_reference": context["inventory_snapshot_reference"],
        "captured_state_revision": context["captured_state_revision"],
        "as_of": context["as_of"],
        "known_at": context["known_at"],
        "adjustment_event_ids": [
            event["id"] for event in context["adjustment_events"]
        ],
        "plan_id": context["plan_id"],
        "plan_version_reference": context["plan_version_reference"],
    }
    saved = client.put(
        f"/api/v1/runs/{run_id}/inventory-adjustment-assessment",
        json={"result": result},
    )
    assert saved.status_code == 200, saved.text
    return context, saved.json()


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


def test_worker_maps_sales_materiality_stale_error_without_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        worker.planning,
        "claim_run",
        lambda session: SimpleNamespace(id="sales-run"),
    )
    monkeypatch.setattr(
        worker,
        "ensure_claimed_sales_materiality",
        lambda session, run_id: (_ for _ in ()).throw(
            ApiError(409, "STALE_RUN_INPUT", "captured input is stale")
        ),
    )
    failures: list[str] = []
    monkeypatch.setattr(
        worker.planning,
        "fail_run",
        lambda session, run_id, reason: failures.append(reason),
    )
    monkeypatch.setattr(
        worker,
        "build_organiser_reasoning_models",
        lambda settings: pytest.fail("stale materiality must stop before models"),
    )

    result = worker.run_one_queued_assessment(cast(Session, object()))

    assert result.run_id == "sales-run"
    assert result.outcome is None
    assert result.publication_status == "STALE_REJECTED"
    assert result.failure_classification == "STATE_REVISION_STALE"
    assert failures == ["STATE_REVISION_STALE"]


def test_worker_closes_unexpected_sales_materiality_error_as_tool_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        worker.planning,
        "claim_run",
        lambda session: SimpleNamespace(id="sales-run"),
    )
    monkeypatch.setattr(
        worker,
        "ensure_claimed_sales_materiality",
        lambda session, run_id: (_ for _ in ()).throw(
            RuntimeError("adapter-secret-must-not-escape")
        ),
    )
    failures: list[str] = []
    monkeypatch.setattr(
        worker.planning,
        "fail_run",
        lambda session, run_id, reason: failures.append(reason),
    )
    monkeypatch.setattr(
        worker,
        "build_organiser_reasoning_models",
        lambda settings: pytest.fail("adapter failure must stop before models"),
    )

    result = worker.run_one_queued_assessment(cast(Session, object()))

    assert result.run_id == "sales-run"
    assert result.outcome is None
    assert result.publication_status == "NOT_PUBLISHED"
    assert result.failure_classification is EscalationReason.TOOL_FAILURE
    assert failures == [EscalationReason.TOOL_FAILURE.value]
    assert "adapter-secret-must-not-escape" not in str(result.model_dump())


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
        assert completed.json()["plan_version_id"] is None
        assert (
            completed.json()["escalation_reason"]
            == EscalationReason.MISSING_REQUIRED_DATA.value
        )
        client.headers["Authorization"] = "Bearer test-agent-token"
        assessment = client.get(
            f"/api/v1/runs/{queued['id']}/sales-materiality-assessment"
        )
        assert assessment.status_code == 200, assessment.text
        saved = assessment.json()
        assert saved["request_reference"]
        assert saved["result_reference"]
        assert saved["completed_at"]
        assert saved["result"]["complete"] is False
        assert saved["result"]["material_change"] is True
        assert saved["result"]["findings"]
        return
    assert result.outcome in {AgentOutcome.REVISE_PLAN, AgentOutcome.ESCALATE}
    if result.outcome is AgentOutcome.REVISE_PLAN:
        assert result.publication_reference is not None
        plan = client.get(f"/api/v1/plans/{result.publication_reference}")
        assert plan.status_code == 200, plan.text
        assert plan.json()["calculation_mode"] == "ENGINE"
    else:
        assert result.failure_classification in set(EscalationReason)


def test_sales_materiality_uses_issued_plan_origin_and_complete_observed_coverage(
    client: TestClient,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline, _ = prepare_engine_plan(client, database_url, monkeypatch)
    run_id, _, _ = post_material_sales_coverage(client, database_url, baseline["id"])

    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            claimed = planning.claim_run(session)
            assert claimed.id == run_id
            assert claimed.snapshot["issued_forecast_origin"]["run_id"] == baseline["id"]
            worker.ensure_claimed_sales_materiality(session, run_id)
            assessment = read_assessment(session, run_id)
            assert assessment.result is not None
            assert assessment.result.complete is True
            assert assessment.result.material_change is True
            assert assessment.result.findings == []
            assert assessment.result.missing_intervals == []
            assert assessment.result.assessed_scope == [
                "SALES_DEVIATION", "PHYSICAL_SHORTAGE", "SAFETY_STOCK"
            ]
            issued = assessment.engine_request.issued_forecast
            assert issued.reference.startswith(f"{baseline['id']}:")
            assert (
                dict(issued.sources)["history"].reference
                == assessment.engine_request.contract.forecast_input.id
            )
            assert assessment.engine_request.risk is not None
            inventory = assessment.engine_request.risk["inventory"]
            assert isinstance(inventory, dict)
            evidence = inventory["evidence"]
            assert isinstance(evidence, dict)
            forecast_evidence = evidence["forecast"]
            assert isinstance(forecast_evidence, dict)
            assert forecast_evidence["reference"] == issued.reference
    finally:
        engine.dispose()


def test_material_sales_persists_before_coordination_and_escalates_late_issue(
    client: TestClient,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline, _ = prepare_engine_plan(client, database_url, monkeypatch)
    prior_plan_id = baseline["plan_version_id"]
    prior_plan = client.get(f"/api/v1/plans/{prior_plan_id}").json()
    event_models = models(
        demand=LocalDemandReasoning(), inventory=LocalInventoryReasoning()
    )
    build_calls: list[str] = []
    search_results: list[tuple[bool, bool, set[tuple[str, str]]]] = []

    def record_model_build(settings):
        build_calls.append("called")
        return event_models

    monkeypatch.setattr(worker, "build_organiser_reasoning_models", record_model_build)
    from src import decision_engine_adapter

    original_search = decision_engine_adapter.search_procurement

    def record_deterministic_search(inputs):
        search = original_search(inputs)
        search_results.append(
            (
                search.search_complete,
                search.candidate is None,
                {(finding.code, finding.source) for finding in search.findings},
            )
        )
        return search

    monkeypatch.setattr(
        decision_engine_adapter, "search_procurement", record_deterministic_search
    )
    original_coordinator = worker.run_backend_coordinator

    def coordinator_after_persisted_materiality(session, claimed_run_id, *args, **kwargs):
        persisted = read_assessment(session, claimed_run_id)
        assert persisted.result is not None
        assert persisted.result.complete is True
        assert persisted.result.material_change is True
        assert persisted.result.findings == []
        assert persisted.engine_request.issued_forecast.reference.startswith(
            f"{baseline['id']}:"
        )
        assert (
            dict(persisted.engine_request.issued_forecast.sources)["history"].reference
            == persisted.engine_request.issued_input.id
        )
        return original_coordinator(
            session, claimed_run_id, *args, **kwargs
        )

    monkeypatch.setattr(
        worker, "run_backend_coordinator", coordinator_after_persisted_materiality
    )
    run_id, _, _ = post_material_sales_coverage(
        client, database_url, baseline["id"]
    )
    assert build_calls == []  # Batch ingestion only queues; it does not build/call a model.

    result = invoke_worker(database_url)
    assert build_calls == ["called"]
    assert result.run_id == run_id
    assert result.outcome is AgentOutcome.ESCALATE
    assert result.failure_classification is EscalationReason.CALCULATION_INCOMPLETE
    assert result.publication_status == "PUBLISHED"  # Business escalation was recorded.
    assert result.publication_reference is None
    assert search_results == [
        (False, True, {("UNSUPPORTED_ISSUE_OPENING", "issue_time")})
    ]

    completed = client.get(f"/api/v1/runs/{run_id}").json()
    assert completed["status"] == "SUCCEEDED"
    assert completed["outcome"] == AgentOutcome.ESCALATE.value
    assert completed["escalation_reason"] == EscalationReason.CALCULATION_INCOMPLETE.value
    assert completed["plan_version_id"] is None
    assert client.get(f"/api/v1/plans/{prior_plan_id}").json() == {
        **prior_plan,
        "status": "INVALIDATED",
    }
    assert [plan["id"] for plan in client.get("/api/v1/plan-history").json()] == [
        prior_plan_id
    ]

    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            run = planning.get_run(session, run_id)
            assert run.snapshot.get("decision_engine_artifacts") is None
            assert run.snapshot.get("calculated_candidate") is None
            contract = ProcurementContract.model_validate(
                run.snapshot["procurement_contract"]
            )
            assert contract.frozen_state is not None
            assessment = read_assessment(session, run_id)
            assert assessment.engine_request.contract.frozen_state is not None
            assert assessment.engine_request.contract.run_id == run_id
            assert (
                assessment.engine_request.contract.captured_state_revision
                == str(run.input_revision)
                == contract.captured_state_revision
            )
            assert assessment.engine_request.contract.as_of == contract.as_of
            assert assessment.engine_request.contract.known_at == contract.known_at
            assert (
                assessment.engine_request.issued_forecast
                == _issued_forecast(run, contract)
            )
            assert (
                assessment.engine_request.issued_input.model_dump(mode="json")
                == contract.forecast_input.model_dump(mode="json")
            )
            assert (
                assessment.engine_request.contract.frozen_state["sales_batches"]
                == contract.frozen_state["sales_batches"]
            )
            assert (
                assessment.engine_request.threshold_policy.version
                == "SALES_MATERIALITY_V1"
            )
            assert (
                assessment.engine_request.threshold_policy.evidence.captured_revision
                == contract.captured_state_revision
            )
            assert assessment.result is not None
            assert assessment.result.complete is True
            assert assessment.result.material_change is True
            assert assessment.result.run_id == run_id
            assert (
                assessment.result.captured_state_revision
                == str(run.input_revision)
            )
            assert assessment.request_sha256
            assert assessment.result_sha256

            worker.ensure_claimed_sales_materiality(session, run_id)
            retried = read_assessment(session, run_id)
            rows = session.execute(
                select(db.sales_materiality_assessments.c.id).where(
                    db.sales_materiality_assessments.c.run_id == run_id
                )
            ).all()
            assert len(rows) == 1
            assert retried.request_sha256 == assessment.request_sha256
            assert retried.result_sha256 == assessment.result_sha256
    finally:
        engine.dispose()


def test_inventory_adjustment_event_uses_normal_api_path_and_escalates_when_incomplete(
    client: TestClient,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_run, _ = prepare_engine_plan(client, database_url, monkeypatch)
    original_plan = client.get(
        f"/api/v1/plans/{original_run['plan_version_id']}"
    ).json()
    assert original_plan["status"] == "PENDING_APPROVAL"
    assert original_plan["calculation_mode"] == "ENGINE"
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
    assert first_result.outcome is AgentOutcome.REVISE_PLAN
    assert first_result.publication_reference is not None
    first_completed = client.get(f"/api/v1/runs/{first_run['id']}").json()
    assert first_completed["status"] == "SUCCEEDED"
    assert first_completed["outcome"] == AgentOutcome.REVISE_PLAN.value
    assert first_completed["plan_version_id"] == first_result.publication_reference
    current_plan = client.get(
        f"/api/v1/plans/{first_result.publication_reference}"
    ).json()
    assert current_plan["calculation_mode"] == "ENGINE"
    assert current_plan["plan_id"] == original_plan["plan_id"]
    assert current_plan["version"] == original_plan["version"] + 1
    assert current_plan["status"] == "PENDING_APPROVAL"
    assert (
        client.get(f"/api/v1/plans/{original_plan['id']}").json()["status"]
        == "SUPERSEDED"
    )
    plan_history_before_correction = [
        plan["id"] for plan in client.get("/api/v1/plan-history").json()
    ]

    corrected = {**initial, "counts": dict(initial["counts"])}
    corrected["counts"][lots[0]["id"]] = str(float(lots[0]["quantity"]) + 1)
    assert client.post(day + "/draft", json=corrected).status_code == 200
    assert client.post(day + "/submit").status_code == 200
    correction_run = client.get("/api/v1/runs").json()[0]
    correction_models = models(
        demand=LocalDemandReasoning(), inventory=LocalInventoryReasoning()
    )
    persisted_assessment: list[tuple[dict, dict]] = []

    def persist_assessment_after_claim(settings):
        persisted_assessment.append(
            persist_incomplete_inventory_adjustment_assessment(
                client, correction_run["id"]
            )
        )
        return correction_models

    monkeypatch.setattr(
        worker, "build_organiser_reasoning_models", persist_assessment_after_claim
    )
    second_result = invoke_worker(database_url)

    assert len(persisted_assessment) == 1
    context, saved_assessment = persisted_assessment[0]
    assert context["plan_id"] == current_plan["plan_id"]
    assert context["plan_version_reference"] == current_plan["id"]
    assessment_result = saved_assessment["result"]
    assert assessment_result["assessed_lot_ids"] == context["assessed_lot_ids"]
    assert assessment_result["assessed_ingredient_ids"] == context[
        "assessed_ingredient_ids"
    ]
    assert assessment_result["evidence_refs"] == context["required_evidence_refs"]
    assert assessment_result["adjustment_event_ids"] == [
        event["id"] for event in context["adjustment_events"]
    ]
    assert assessment_result["run_id"] == correction_run["id"]
    assert assessment_result["snapshot_reference"] == context["snapshot_reference"]
    assert assessment_result["inventory_snapshot_reference"] == context[
        "inventory_snapshot_reference"
    ]
    assert assessment_result["captured_state_revision"] == context[
        "captured_state_revision"
    ]
    assert assessment_result["as_of"] == context["as_of"]
    assert assessment_result["known_at"] == context["known_at"]
    assert assessment_result["plan_id"] == context["plan_id"]
    assert assessment_result["plan_version_reference"] == context[
        "plan_version_reference"
    ]
    assert assessment_result["complete"] is False
    assert assessment_result["material_change"] is None

    assert second_result.outcome is AgentOutcome.ESCALATE
    assert second_result.failure_classification is EscalationReason.MISSING_REQUIRED_DATA
    assert second_result.publication_status == "PUBLISHED"
    assert second_result.publication_reference is None
    correction_completed = client.get(
        f"/api/v1/runs/{correction_run['id']}"
    ).json()
    assert correction_completed["status"] == "SUCCEEDED"
    assert correction_completed["outcome"] == AgentOutcome.ESCALATE.value
    assert (
        correction_completed["escalation_reason"]
        == EscalationReason.MISSING_REQUIRED_DATA.value
    )
    assert correction_completed["plan_version_id"] is None
    assessment_readback = client.get(
        f"/api/v1/runs/{correction_run['id']}/inventory-adjustment-assessment"
    )
    assert assessment_readback.status_code == 200, assessment_readback.text
    assert assessment_readback.json() == saved_assessment
    assert assessment_readback.json()["result"]["complete"] is False
    assert assessment_readback.json()["result"]["material_change"] is None
    assert assessment_readback.json()["result"]["inventory_feasible"] is None
    client.headers.pop("Authorization", None)
    assert [plan["id"] for plan in client.get("/api/v1/plan-history").json()] == (
        plan_history_before_correction
    )


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


def test_newer_sales_after_claim_is_rejected_before_materiality_or_publication(
    client: TestClient,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline, _ = prepare_engine_plan(client, database_url, monkeypatch)
    original_plan_id = baseline["plan_version_id"]
    first = client.post(
        "/api/v1/sales-batches",
        json={
            "source": "worker-stale-sales",
            "batch_id": "sales-before-claim",
            "period_start": "2026-02-16T04:00:00+08:00",
            "period_end": "2026-02-16T04:30:00+08:00",
            "sales": {"chicken-rice": 1},
        },
    )
    assert first.status_code == 201, first.text
    run_id = client.get("/api/v1/runs").json()[0]["id"]
    original_adapter = worker.ensure_claimed_sales_materiality
    build_calls: list[str] = []

    def add_newer_sales_then_assess(session, claimed_run_id: str) -> None:
        assert claimed_run_id == run_id
        newer = client.post(
            "/api/v1/sales-batches",
            json={
                "source": "worker-stale-sales",
                "batch_id": "sales-after-claim",
                "period_start": "2026-02-16T04:30:00+08:00",
                "period_end": "2026-02-16T05:00:00+08:00",
                "sales": {"chicken-rice": 2},
            },
        )
        assert newer.status_code == 201, newer.text
        original_adapter(session, claimed_run_id)

    def unexpected_model_build(settings):
        build_calls.append("called")
        pytest.fail("stale sales must be rejected before model construction")

    monkeypatch.setattr(
        worker, "ensure_claimed_sales_materiality", add_newer_sales_then_assess
    )
    monkeypatch.setattr(
        worker, "build_organiser_reasoning_models", unexpected_model_build
    )
    result = invoke_worker(database_url)

    stale = client.get(f"/api/v1/runs/{run_id}").json()
    assert result.run_id == run_id
    assert result.outcome is None
    assert result.publication_status == "STALE_REJECTED"
    assert result.failure_classification == "STATE_REVISION_STALE"
    assert stale["status"] == "FAILED"
    assert stale["failure_reason"] == "STATE_REVISION_STALE"
    assert stale["plan_version_id"] is None
    assert build_calls == []
    remaining_runs = [
        run
        for run in client.get("/api/v1/runs").json()
        if run["id"] != run_id and run["status"] == "QUEUED"
    ]
    assert len(remaining_runs) == 1
    assert [plan["id"] for plan in client.get("/api/v1/plan-history").json()] == [
        original_plan_id
    ]

    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            assert session.execute(
                select(db.sales_materiality_assessments.c.id).where(
                    db.sales_materiality_assessments.c.run_id == run_id
                )
            ).all() == []
    finally:
        engine.dispose()


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


def test_sales_materiality_adapter_failure_uses_tool_failure_handling(
    client: TestClient,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested = queue_manager_assessment(client)

    def fail_materiality(session, run_id: str) -> None:
        raise RuntimeError("adapter-secret-must-not-escape")

    monkeypatch.setattr(worker, "ensure_claimed_sales_materiality", fail_materiality)
    monkeypatch.setattr(
        worker,
        "build_organiser_reasoning_models",
        lambda settings: pytest.fail("Coordinator must not run after adapter failure"),
    )
    result = invoke_worker(database_url)

    assert result.run_id == requested["id"]
    assert result.outcome is None
    assert result.publication_status == "NOT_PUBLISHED"
    assert result.publication_reference is None
    assert result.failure_classification is EscalationReason.TOOL_FAILURE
    assert "adapter-secret-must-not-escape" not in str(result.model_dump())
    failed = client.get(f"/api/v1/runs/{requested['id']}").json()
    assert failed["status"] == "FAILED"
    assert failed["failure_reason"] == EscalationReason.TOOL_FAILURE.value
    assert failed["outcome"] is None
    assert failed["plan_version_id"] is None
    assert client.get("/api/v1/plan-history").json() == []


def test_coordinator_unexpected_failure_after_claim_fails_run_closed(
    client: TestClient,
    database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested = queue_manager_assessment(client)
    install_models(monkeypatch, models())
    coordinator_calls: list[tuple[str, BackendProcurementTools]] = []

    def fail_coordinator(session, run_id, procurement_model, procurement_tools, **kwargs):
        coordinator_calls.append((run_id, procurement_tools))
        raise RuntimeError("coordinator-crash-secret-must-not-escape")

    monkeypatch.setattr(worker, "run_backend_coordinator", fail_coordinator)
    result = invoke_worker(database_url)

    assert len(coordinator_calls) == 1
    assert coordinator_calls[0][0] == requested["id"]
    assert isinstance(coordinator_calls[0][1], BackendProcurementTools)
    assert result.run_id == requested["id"]
    assert result.outcome is None
    assert result.publication_status == "NOT_PUBLISHED"
    assert result.publication_reference is None
    assert result.failure_classification is EscalationReason.TOOL_FAILURE
    assert "coordinator-crash-secret-must-not-escape" not in str(result.model_dump())

    failed = client.get(f"/api/v1/runs/{requested['id']}").json()
    assert failed["status"] == "FAILED"
    assert failed["failure_reason"] == EscalationReason.TOOL_FAILURE.value
    assert failed["outcome"] is None
    assert failed["plan_version_id"] is None
    assert "coordinator-crash-secret-must-not-escape" not in str(failed)
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
