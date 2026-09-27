"""Connected API oracles; real PostgreSQL/numerical engine, controlled initial model."""

from copy import deepcopy
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session
from test_contingency_first_case_backend import (
    test_first_case_stock_and_delayed_commitment_are_frozen_once as prepare_first_case,
)

from src import assessment_worker as worker
from src import database as db
from src import planning
from src.agent_contracts import AgentOutcome, EvidenceCategory
from src.coordinator import CoordinatorExecution
from src.errors import ApiError
from src.post_purchase_contingency import (
    RESULT_KEY,
    PostPurchaseInput,
    PostPurchaseResult,
    freeze_post_purchase_input,
    read_post_purchase_result,
)

ISSUE = "2026-02-16T10:00:00+08:00"
RECEIPT = "2026-02-16T11:00:00+08:00"


def manager(client):
    client.headers.pop("Authorization", None)


def agent(client):
    client.headers["Authorization"] = "Bearer test-agent-token"


@pytest.fixture
def recorded(client, database_url):
    prepare_first_case(client, database_url)
    deliveries = client.get("/api/v1/deliveries").json()
    return {row["kind"]: row for row in deliveries}


def queue_worker_run(client, issue=ISSUE):
    manager(client)
    queued = next(
        (row for row in client.get("/api/v1/runs").json() if row["status"] == "QUEUED"),
        None,
    )
    body = {"as_of": issue}
    if queued is not None and queued["snapshot"].get("revises_plan_id"):
        body["revises_plan_id"] = queued["snapshot"]["revises_plan_id"]
    response = client.post("/api/v1/assessments", json=body)
    assert response.status_code == 202, response.text
    return response.json()["id"]


def run_worker(database_url):
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            return worker.run_one_queued_assessment(session)
    finally:
        engine.dispose()


def forbid_model_construction(monkeypatch):
    monkeypatch.setattr(
        worker,
        "build_organiser_reasoning_models",
        lambda _settings: pytest.fail("post-purchase routing must not construct a model"),
    )


def capture_worker_execution(monkeypatch):
    executions: list[CoordinatorExecution] = []
    original = worker.run_backend_coordinator

    def capture(*args, **kwargs):
        execution = original(*args, **kwargs)
        executions.append(execution)
        return execution

    monkeypatch.setattr(worker, "run_backend_coordinator", capture)
    return executions


def assert_worker_evidence(execution, completed_run, *, has_candidate):
    result = PostPurchaseResult.model_validate(
        completed_run["snapshot"][RESULT_KEY]
    )
    completion = execution.completion
    result_refs = [
        ref
        for ref in completion.evidence_refs
        if ref.category is EvidenceCategory.POST_PURCHASE_RESULT
    ]
    assert len(result_refs) == 1
    assert result_refs[0].reference_id == result.id
    assert result_refs[0].run_id == completed_run["id"]
    assert result_refs[0].state_revision == str(completed_run["input_revision"])
    if has_candidate:
        candidate_ref = completion.candidate_result_ref
        assert candidate_ref is not None
        assert candidate_ref.reference_id == result.candidate_reference
        assert candidate_ref.run_id == completed_run["id"]
        assert candidate_ref.state_revision == str(completed_run["input_revision"])
    else:
        assert completion.candidate_result_ref is None
    return result


def claim(client, issue=ISSUE):
    manager(client)
    queued = next(
        (r for r in client.get("/api/v1/runs").json() if r["status"] == "QUEUED"), None
    )
    target = queued["snapshot"].get("revises_plan_id") if queued else None
    response = client.post(
        "/api/v1/assessments", json={"as_of": issue, "revises_plan_id": target}
    )
    assert response.status_code == 202, response.text
    agent(client)
    response = client.post("/api/v1/runs/claim")
    assert response.status_code == 200, response.text
    run = response.json()
    response = client.get(f"/api/v1/runs/{run['id']}/post-purchase-contingency-input")
    assert response.status_code == 200, response.text
    frozen = PostPurchaseInput.model_validate(response.json())
    assert frozen.complete, frozen.findings
    assert frozen.run_id == run["id"]
    assert frozen.captured_state_revision == str(run["input_revision"])
    return run, frozen


def calculate(client, run):
    path = f"/api/v1/runs/{run['id']}/post-purchase-contingency-result"
    response = client.put(path)
    assert response.status_code == 200, response.text
    assert client.put(path).json() == response.json()
    assert client.get(path).json() == response.json()
    return PostPurchaseResult.model_validate(response.json())


def complete(client, run, result):
    body = {"outcome": result.outcome, "escalation_reason": result.escalation_reason}
    if result.outcome == "REVISE_PLAN":
        assert result.candidate is not None
        body["candidate"] = result.candidate.model_dump(mode="json")
    response = client.post(f"/api/v1/runs/{run['id']}/complete", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def zero_coverage(client):
    manager(client)
    response = client.post(
        "/api/v1/sales-batches",
        json={
            "source": "post-purchase-demo",
            "batch_id": "until-receipt",
            "period_start": ISSUE,
            "period_end": RECEIPT,
            "sales": {},
        },
    )
    assert response.status_code == 201, response.text


def test_recorded_purchase_keep_then_receipt_no_duplicate(
    client, database_url, recorded
):
    original = deepcopy(recorded["NORMAL"])
    emergency = recorded["EMERGENCY"]
    plan_before = client.get("/api/v1/plan-history").json()
    run, frozen = claim(client)
    assert set(frozen.fixed_delivery_ids) == {original["id"], emergency["id"]}
    assert (
        frozen.case and frozen.case.case_input and frozen.case.case_input.version == 5
    )
    assert (
        client.get(
            f"/api/v1/runs/{run['id']}/post-purchase-contingency-result"
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/runs/{run['id']}/complete", json={"outcome": "KEEP_CURRENT_PLAN"}
        ).status_code
        == 409
    )
    result = calculate(client, run)
    assert result.complete and result.outcome == "KEEP_CURRENT_PLAN"
    assert result.candidate and result.candidate.lines == []
    assert result.candidate.new_purchase_cash_cost == 0
    assert result.candidate.total_expected_cost is None
    assert (
        result.independent_validation
        and result.independent_validation["feasible"] is True
    )
    assert complete(client, run, result)["outcome"] == "KEEP_CURRENT_PLAN"
    assert client.get("/api/v1/plan-history").json() == plan_before
    manager(client)
    zero_coverage(client)
    response = client.post(
        f"/api/v1/deliveries/{emergency['id']}/receive",
        json={
            "request_id": "post-purchase-four",
            "quantity": "4",
            "received_at": RECEIPT,
            "expiry_date": "2026-02-17",
            "remainder": "EXPECTED",
        },
    )
    assert response.status_code == 200, response.text
    assert Decimal(response.json()["outstanding_quantity"]) == 0
    run2, frozen2 = claim(client, RECEIPT)
    assert (
        frozen2.case
        and frozen2.case.case_input
        and frozen2.case.case_input.version == 6
    )
    opening = sum(
        x.quantity
        for x in frozen2.case.opening_lots or []
        if x.ingredient_id == "vegetables" and x.status == "ACTIVE"
    )
    assert opening == 10  # 6 physical original + 4 actual emergency, once.
    projection = frozen2.case.commitment_projection
    assert projection is not None
    assert sum(x.delivery.outstanding_quantity for x in projection.supplies) == 4
    result2 = calculate(client, run2)
    assert result2.outcome == "KEEP_CURRENT_PLAN" and result2.complete, (
        result2.escalation_reason,
        result2.findings,
    )
    assert result2.candidate and result2.candidate.lines == []
    complete(client, run2, result2)
    assert client.get(f"/api/v1/deliveries/{original['id']}").json() == original
    assert len(client.get("/api/v1/deliveries").json()) == 2
    assert client.get("/api/v1/plan-history").json() == plan_before


def test_worker_keeps_sufficient_purchase_and_counts_later_receipt_once(
    client, database_url, recorded, monkeypatch
):
    deliveries_before = client.get("/api/v1/deliveries").json()
    plans_before = client.get("/api/v1/plan-history").json()
    first_id = queue_worker_run(client)
    forbid_model_construction(monkeypatch)
    executions = capture_worker_execution(monkeypatch)

    first = run_worker(database_url)

    assert first.run_id == first_id
    assert first.outcome is AgentOutcome.KEEP_CURRENT_PLAN
    assert first.publication_status == "PUBLISHED"
    assert first.publication_reference is None
    first_run = client.get(f"/api/v1/runs/{first_id}").json()
    first_contract = assert_worker_evidence(
        executions[0], first_run, has_candidate=False
    )
    assert first_contract.complete and first_contract.outcome == "KEEP_CURRENT_PLAN"
    assert first_contract.candidate is not None
    assert first_contract.candidate.lines == []
    assert client.get("/api/v1/deliveries").json() == deliveries_before
    assert client.get("/api/v1/plan-history").json() == plans_before

    emergency = recorded["EMERGENCY"]
    zero_coverage(client)
    received = client.post(
        f"/api/v1/deliveries/{emergency['id']}/receive",
        json={
            "request_id": "worker-post-purchase-four",
            "quantity": "4",
            "received_at": RECEIPT,
            "expiry_date": "2026-02-17",
            "remainder": "EXPECTED",
        },
    )
    assert received.status_code == 200, received.text
    deliveries_after_receipt = client.get("/api/v1/deliveries").json()
    second_id = queue_worker_run(client, RECEIPT)

    second = run_worker(database_url)

    assert second.run_id == second_id
    assert second.outcome is AgentOutcome.KEEP_CURRENT_PLAN
    assert second.publication_status == "PUBLISHED"
    second_run = client.get(f"/api/v1/runs/{second_id}").json()
    second_contract = assert_worker_evidence(
        executions[1], second_run, has_candidate=False
    )
    assert second_contract.complete and second_contract.outcome == "KEEP_CURRENT_PLAN"
    frozen = second_run["snapshot"]["post_purchase_contingency_input"]
    opening_vegetables = sum(
        Decimal(lot["quantity"])
        for lot in frozen["case"]["opening_lots"]
        if lot["ingredient_id"] == "vegetables" and lot["status"] == "ACTIVE"
    )
    assert opening_vegetables == Decimal(10)
    assert client.get("/api/v1/deliveries").json() == deliveries_after_receipt
    assert client.get(f"/api/v1/deliveries/{recorded['NORMAL']['id']}").json() == recorded[
        "NORMAL"
    ]
    assert len(client.get("/api/v1/deliveries").json()) == 2
    assert client.get("/api/v1/plan-history").json() == plans_before


def test_worker_revises_with_only_exact_additional_candidate(
    client, database_url, recorded, monkeypatch
):
    emergency = recorded["EMERGENCY"]
    updated = client.post(
        f"/api/v1/deliveries/{emergency['id']}/update",
        json={
            "expected_quantity": "2",
            "expected_at": RECEIPT,
            "expected_expiry_date": "2026-02-17",
            "effective_at": ISSUE,
        },
    )
    assert updated.status_code == 200, updated.text
    fixed_before = client.get("/api/v1/deliveries").json()
    requested_id = queue_worker_run(client)
    forbid_model_construction(monkeypatch)
    executions = capture_worker_execution(monkeypatch)

    result = run_worker(database_url)

    assert result.run_id == requested_id
    assert result.outcome is AgentOutcome.REVISE_PLAN
    assert result.publication_status == "PUBLISHED"
    assert result.publication_reference is not None
    completed = client.get(f"/api/v1/runs/{requested_id}").json()
    persisted = assert_worker_evidence(executions[0], completed, has_candidate=True)
    assert persisted.outcome == "REVISE_PLAN" and persisted.complete
    assert persisted.candidate is not None and persisted.candidate_reference
    assert [line.quantity for line in persisted.candidate.lines] == [Decimal(2)]
    plan_response = client.get(f"/api/v1/plans/{result.publication_reference}")
    assert plan_response.status_code == 200, plan_response.text
    plan = plan_response.json()
    assert plan["status"] == "PENDING_APPROVAL"
    assert plan["calculation_mode"] == "CONTINGENCY_ENGINE"
    assert plan["cost_scope"] == "NEW_PURCHASE_CASH_ONLY"
    assert [Decimal(line["quantity"]) for line in plan["lines"]] == [Decimal(2)]
    assert client.get("/api/v1/deliveries").json() == fixed_before


def test_worker_preserves_no_feasible_supplier_escalation(
    client, database_url, recorded, monkeypatch
):
    emergency = recorded["EMERGENCY"]
    updated = client.post(
        f"/api/v1/deliveries/{emergency['id']}/update",
        json={
            "expected_quantity": "4",
            "expected_at": "2026-02-17T09:00:00+08:00",
            "expected_expiry_date": "2026-02-17",
            "effective_at": ISSUE,
        },
    )
    assert updated.status_code == 200, updated.text
    zero_coverage(client)
    fixed_before = client.get("/api/v1/deliveries").json()
    plans_before = client.get("/api/v1/plan-history").json()
    requested_id = queue_worker_run(client, RECEIPT)
    forbid_model_construction(monkeypatch)
    executions = capture_worker_execution(monkeypatch)

    result = run_worker(database_url)

    assert result.run_id == requested_id
    assert result.outcome is AgentOutcome.ESCALATE
    assert result.failure_classification == "NO_FEASIBLE_SUPPLIER"
    assert result.publication_reference is None
    completed = client.get(f"/api/v1/runs/{requested_id}").json()
    persisted = assert_worker_evidence(executions[0], completed, has_candidate=False)
    assert persisted.complete and persisted.escalation_reason == "NO_FEASIBLE_SUPPLIER"
    assert persisted.candidate is None
    assert client.get("/api/v1/deliveries").json() == fixed_before
    assert client.get("/api/v1/plan-history").json() == plans_before


def test_worker_preserves_policy_violation_escalation(
    client, database_url, recorded, monkeypatch
):
    emergency = recorded["EMERGENCY"]
    updated = client.post(
        f"/api/v1/deliveries/{emergency['id']}/update",
        json={
            "expected_quantity": "2",
            "expected_at": RECEIPT,
            "effective_at": ISSUE,
        },
    )
    assert updated.status_code == 200, updated.text
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            table = db.contingency_policy_versions
            row = (
                session.execute(select(table).where(table.c.version == 5))
                .mappings()
                .one()
            )
            payload = deepcopy(row["payload"])
            payload["new_order_budget_sgd"] = "10"
            session.execute(
                update(table).where(table.c.id == row["id"]).values(payload=payload)
            )
            session.commit()
    finally:
        engine.dispose()
    fixed_before = client.get("/api/v1/deliveries").json()
    plans_before = client.get("/api/v1/plan-history").json()
    requested_id = queue_worker_run(client)
    forbid_model_construction(monkeypatch)
    executions = capture_worker_execution(monkeypatch)

    result = run_worker(database_url)

    assert result.run_id == requested_id
    assert result.outcome is AgentOutcome.ESCALATE
    assert result.failure_classification == "POLICY_VIOLATION"
    completed = client.get(f"/api/v1/runs/{requested_id}").json()
    persisted = assert_worker_evidence(executions[0], completed, has_candidate=False)
    assert persisted.complete and persisted.escalation_reason == "POLICY_VIOLATION"
    assert persisted.candidate is None
    assert client.get("/api/v1/deliveries").json() == fixed_before
    assert client.get("/api/v1/plan-history").json() == plans_before


def test_worker_escalates_incomplete_frozen_evidence_without_candidate(
    client, database_url, recorded, monkeypatch
):
    plans_before = client.get("/api/v1/plan-history").json()
    deliveries_before = client.get("/api/v1/deliveries").json()
    requested_id = queue_worker_run(client, RECEIPT)
    forbid_model_construction(monkeypatch)
    executions = capture_worker_execution(monkeypatch)

    result = run_worker(database_url)

    assert result.run_id == requested_id
    assert result.outcome is AgentOutcome.ESCALATE
    assert result.failure_classification in {
        "MISSING_REQUIRED_DATA",
        "CALCULATION_INCOMPLETE",
    }
    completed = client.get(f"/api/v1/runs/{requested_id}").json()
    persisted = assert_worker_evidence(executions[0], completed, has_candidate=False)
    assert not persisted.complete
    assert persisted.outcome == "ESCALATE"
    assert persisted.escalation_reason in {
        "MISSING_REQUIRED_DATA",
        "CALCULATION_INCOMPLETE",
    }
    assert persisted.candidate is None
    assert client.get("/api/v1/deliveries").json() == deliveries_before
    assert client.get("/api/v1/plan-history").json() == plans_before


def test_worker_rejects_state_change_after_post_purchase_claim(
    client, database_url, recorded, monkeypatch
):
    requested_id = queue_worker_run(client)
    forbid_model_construction(monkeypatch)
    persist = worker.persist_post_purchase_result

    def persist_then_change_state(session, run_id):
        result = persist(session, run_id)
        manager(client)
        response = client.patch(
            "/api/v1/supplier-offers/market-chicken",
            json={
                "effective_at": "2026-02-16T10:00:00+08:00",
                "current_status": "UNAVAILABLE",
            },
        )
        assert response.status_code == 200, response.text
        return result

    monkeypatch.setattr(
        worker, "persist_post_purchase_result", persist_then_change_state
    )
    plans_before = client.get("/api/v1/plan-history").json()
    deliveries_before = client.get("/api/v1/deliveries").json()

    result = run_worker(database_url)

    assert result.run_id == requested_id
    assert result.outcome is None
    assert result.publication_status == "STALE_REJECTED"
    assert result.failure_classification == "STATE_REVISION_STALE"
    stale = client.get(f"/api/v1/runs/{requested_id}").json()
    assert stale["status"] == "FAILED"
    assert stale["failure_reason"] == "STATE_REVISION_STALE"
    assert stale["plan_version_id"] is None
    assert client.get("/api/v1/plan-history").json() == plans_before
    assert client.get("/api/v1/deliveries").json() == deliveries_before


@pytest.mark.parametrize(
    "cancel,quantity,addition,cash", [(False, "2", "2", "11"), (True, "4", "4", "15")]
)
def test_short_or_cancelled_only_remaining_addition(
    client, recorded, cancel, quantity, addition, cash
):
    emergency = recorded["EMERGENCY"]
    response = client.post(
        f"/api/v1/deliveries/{emergency['id']}/update",
        json={
            "expected_quantity": quantity,
            "expected_at": RECEIPT,
            "expected_expiry_date": "2026-02-17",
            "effective_at": ISSUE,
            "cancel_remainder": cancel,
        },
    )
    assert response.status_code == 200, response.text
    fixed_before = client.get("/api/v1/deliveries").json()
    run, _ = claim(client)
    result = calculate(client, run)
    assert result.outcome == "REVISE_PLAN" and result.complete
    assert result.candidate and len(result.candidate.lines) == 1
    assert result.candidate.lines[0].quantity == Decimal(addition)
    assert result.candidate.new_purchase_cash_cost == Decimal(cash)
    tampered = result.candidate.model_copy(deep=True)
    tampered.lines[0].quantity += 1
    response = client.post(
        f"/api/v1/runs/{run['id']}/complete",
        json={
            "outcome": "REVISE_PLAN",
            "candidate": tampered.model_dump(mode="json"),
        },
    )
    assert response.status_code == 409
    completed = complete(client, run, result)
    plan = client.get(f"/api/v1/plans/{completed['plan_version_id']}").json()
    assert plan["status"] == "PENDING_APPROVAL"
    assert Decimal(plan["lines"][0]["quantity"]) == Decimal(addition)
    assert client.get("/api/v1/deliveries").json() == fixed_before


def test_late_supply_and_missed_new_slot_escalate(client, recorded):
    emergency = recorded["EMERGENCY"]
    response = client.post(
        f"/api/v1/deliveries/{emergency['id']}/update",
        json={
            "expected_quantity": "4",
            "expected_at": "2026-02-17T09:00:00+08:00",
            "expected_expiry_date": "2026-02-17",
            "effective_at": ISSUE,
        },
    )
    assert response.status_code == 200
    zero_coverage(client)
    run, _ = claim(client, RECEIPT)
    result = calculate(client, run)
    assert result.complete and result.outcome == "ESCALATE"
    assert result.escalation_reason == "NO_FEASIBLE_SUPPLIER"
    assert result.candidate is None and result.numerical_result
    assert result.numerical_result["reason"] == "NO_TIMELY_SUPPLY_IN_DOMAIN"
    assert (
        client.post(
            f"/api/v1/runs/{run['id']}/complete", json={"outcome": "KEEP_CURRENT_PLAN"}
        ).status_code
        == 409
    )
    complete(client, run, result)


def test_missing_coverage_is_incomplete_not_keep(client, recorded):
    manager(client)
    client.post("/api/v1/assessments", json={"as_of": RECEIPT})
    agent(client)
    run = client.post("/api/v1/runs/claim").json()
    result = calculate(client, run)
    assert not result.complete and result.outcome == "ESCALATE"
    assert result.escalation_reason == "MISSING_REQUIRED_DATA"
    assert "OPENING_COVERAGE_INCOMPLETE" in result.findings
    assert result.candidate is None
    complete(client, run, result)


def test_new_revision_blocks_calculation_and_completion(client, recorded):
    run, _ = claim(client)
    result = calculate(client, run)
    manager(client)
    emergency = recorded["EMERGENCY"]
    assert (
        client.post(
            f"/api/v1/deliveries/{emergency['id']}/update",
            json={
                "expected_quantity": "2",
                "expected_at": RECEIPT,
                "effective_at": ISSUE,
            },
        ).status_code
        == 200
    )
    agent(client)
    path = f"/api/v1/runs/{run['id']}/post-purchase-contingency-result"
    assert client.put(path).status_code == 409
    assert (
        client.get(path).json()["id"] == result.id
    )  # historical evidence remains readable
    response = client.post(
        f"/api/v1/runs/{run['id']}/complete", json={"outcome": "KEEP_CURRENT_PLAN"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "STATE_REVISION_STALE"


def test_capture_knowledge_and_result_tamper_guards(client, database_url, recorded):
    run, _ = claim(client)
    calculate(client, run)
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            snapshot = deepcopy(run["snapshot"])
            snapshot["known_at"] = "2026-01-01T00:00:00+08:00"
            unavailable = freeze_post_purchase_input(
                session, snapshot, run["id"], run["input_revision"]
            )
            assert unavailable and not unavailable["complete"]
            assert "AUTHORITY_NOT_KNOWN_AT_CAPTURE" in unavailable["findings"]
            saved = planning.get_run(session, run["id"])
            raw = deepcopy(saved.snapshot)
            raw["post_purchase_contingency_result"]["complete"] = False
            session.execute(
                update(db.planning_runs)
                .where(db.planning_runs.c.id == run["id"])
                .values(snapshot=raw)
            )
            session.commit()
            with pytest.raises(ApiError) as error:
                read_post_purchase_result(session, run["id"])
            assert error.value.detail.code == "STATE_REVISION_STALE"
    finally:
        engine.dispose()


def test_manager_cannot_calculate_agent_result(client, recorded):
    run, _ = claim(client)
    manager(client)
    path = f"/api/v1/runs/{run['id']}/post-purchase-contingency-result"
    assert client.put(path).status_code == 403


@pytest.mark.parametrize(
    "field,value,reason,complete_search",
    [
        ("work_limit", 1, "CALCULATION_INCOMPLETE", False),
        ("new_order_budget_sgd", "10", "POLICY_VIOLATION", True),
    ],
)
def test_search_limit_and_budget_are_not_supplier_failure(
    client, database_url, recorded, field, value, reason, complete_search
):
    emergency = recorded["EMERGENCY"]
    assert (
        client.post(
            f"/api/v1/deliveries/{emergency['id']}/update",
            json={
                "expected_quantity": "2",
                "expected_at": RECEIPT,
                "effective_at": ISSUE,
            },
        ).status_code
        == 200
    )
    # Deliberately inject a restrictive persisted test policy before capture.
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            table = db.contingency_policy_versions
            row = (
                session.execute(select(table).where(table.c.version == 5))
                .mappings()
                .one()
            )
            payload = deepcopy(row["payload"])
            payload[field] = value
            session.execute(
                update(table).where(table.c.id == row["id"]).values(payload=payload)
            )
            session.commit()
    finally:
        engine.dispose()
    run, _ = claim(client)
    result = calculate(client, run)
    assert result.outcome == "ESCALATE" and result.escalation_reason == reason
    assert result.complete is complete_search and result.candidate is None
    assert result.numerical_result is not None
    assert result.numerical_result["reason"] == (
        "SEARCH_LIMIT_REACHED"
        if field == "work_limit"
        else "POLICY_CONSTRAINT_INFEASIBLE"
    )
    complete(client, run, result)


def test_unsupported_clock_has_explicit_incomplete_result(client, recorded):
    manager(client)
    assert (
        client.post(
            "/api/v1/assessments", json={"as_of": "2026-02-16T10:30:00+08:00"}
        ).status_code
        == 202
    )
    agent(client)
    run = client.post("/api/v1/runs/claim").json()
    result = calculate(client, run)
    assert not result.complete and result.outcome == "ESCALATE"
    assert result.escalation_reason == "CALCULATION_INCOMPLETE"
    assert "UNSUPPORTED_POST_PURCHASE_CLOCK" in result.findings
    assert result.candidate is result.numerical_result is None
    complete(client, run, result)


@pytest.mark.parametrize(
    "remainder,expected_outstanding,complete_search,reason",
    [
        ("EXPECTED", "2", False, "MISSING_REQUIRED_DATA"),
        ("CANCELLED", "0", True, "NO_FEASIBLE_SUPPLIER"),
    ],
)
def test_partial_receipt_counts_only_unreceived_remainder(
    client, recorded, remainder, expected_outstanding, complete_search, reason
):
    zero_coverage(client)
    emergency = recorded["EMERGENCY"]
    response = client.post(
        f"/api/v1/deliveries/{emergency['id']}/receive",
        json={
            "request_id": "post-purchase-partial",
            "quantity": "2",
            "received_at": RECEIPT,
            "expiry_date": "2026-02-17",
            "remainder": remainder,
        },
    )
    assert response.status_code == 200, response.text
    assert Decimal(response.json()["outstanding_quantity"]) == Decimal(
        expected_outstanding
    )
    fixed = client.get("/api/v1/deliveries").json()
    run, frozen = claim(client, RECEIPT)
    assert frozen.case is not None and frozen.case.opening_lots is not None
    assert (
        sum(
            l.quantity
            for l in frozen.case.opening_lots
            if l.ingredient_id == "vegetables"
        )
        == 8
    )
    projection = frozen.case.commitment_projection
    assert projection is not None
    assert sum(
        x.delivery.outstanding_quantity for x in projection.supplies
    ) == 4 + Decimal(expected_outstanding)
    result = calculate(client, run)
    assert result.complete is complete_search and result.outcome == "ESCALATE"
    assert result.candidate is None and result.escalation_reason == reason
    if remainder == "EXPECTED":
        # At the opening instant it is overdue, not guaranteed physical stock.
        assert any(x.startswith("OVERDUE_EXPECTED_SUPPLY:") for x in result.findings)
    complete(client, run, result)
    assert client.get("/api/v1/deliveries").json() == fixed
