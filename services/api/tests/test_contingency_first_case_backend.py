"""Public-API proof of the Backend facts for the staged supplier-delay case."""

from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from test_daily import sign_in
from test_decision_engine_adapter import EngineScript

from src.agent_contracts import AgentOutcome
from src.assessment_worker import _FullPlanningRouteClassifier
from src.backend_control_plane import run_backend_coordinator
from src.contingency_artifacts import StagedContingencyArtifact, _verify_artifact
from src.decision_engine_adapter import BackendProcurementTools
from src.errors import ApiError
from src.planning_schemas import PlanningRun
from src.procurement_contract_schemas import FrozenCommitmentProjection

CASE = "/api/v1/contingency-case-inputs/BOUNDED_CONTINGENCY_20260216_CASE_V1/versions/3"
ISSUE = "2026-02-16T10:00:00+08:00"


def test_first_case_stock_and_delayed_commitment_are_frozen_once(
    client: TestClient,
    database_url: str,
) -> None:
    sign_in(client)
    delivery = client.post(
        "/api/v1/deliveries",
        json={
            "supplier_id": "fresh",
            "ingredient_id": "vegetables",
            "kind": "NORMAL",
            "expected_quantity": "10",
            "ordered_at": "2026-02-15T10:00:00+08:00",
            "expected_at": "2026-02-16T11:00:00+08:00",
        },
    )
    assert delivery.status_code == 201, delivery.text
    delivery_id = delivery.json()["id"]

    counts = {lot["id"]: "0" for lot in client.get("/api/v1/inventory").json()}
    counts["rice-01"] = "20"
    counts["tofu-01"] = "20"
    draft = client.post(
        "/api/v1/daily-updates/2026-02-15/draft",
        json={
            "cutoff": "2026-02-15T22:00:00+08:00",
            "counts": counts,
            "sales": {
                dish["id"]: 0 for dish in client.get("/api/v1/menu-items").json()
            },
        },
    )
    assert draft.status_code == 200, draft.text
    closing = client.post("/api/v1/daily-updates/2026-02-15/submit")
    assert closing.status_code == 200, closing.text

    receipt = client.post(
        f"/api/v1/deliveries/{delivery_id}/receive",
        json={
            "request_id": "first-case-six-kilos",
            "quantity": "6",
            "received_at": "2026-02-16T09:00:00+08:00",
            "expiry_date": "2026-02-20",
            "remainder": "EXPECTED",
        },
    )
    assert receipt.status_code == 200, receipt.text
    receipt_lot_id = receipt.json()["receipts"][0]["lot_id"]

    # The simulator explicitly reports no sales since the physical count.
    # Split at the receipt so the new lot has complete post-receipt coverage too.
    for batch_id, start, end in (
        ("before-receipt", "2026-02-15T22:00:00+08:00", "2026-02-16T09:00:00+08:00"),
        ("after-receipt", "2026-02-16T09:00:00+08:00", ISSUE),
    ):
        batch = client.post(
            "/api/v1/sales-batches",
            json={
                "source": "first-case-simulator",
                "batch_id": batch_id,
                "period_start": start,
                "period_end": end,
                "sales": {},
            },
        )
        assert batch.status_code == 201, batch.text

    delayed = client.post(
        f"/api/v1/deliveries/{delivery_id}/update",
        json={
            "expected_quantity": "10",
            "expected_at": "2026-02-17T09:00:00+08:00",
            "expected_expiry_date": "2026-02-20",
            "effective_at": "2026-02-16T09:30:00+08:00",
        },
    )
    assert delayed.status_code == 200, delayed.text

    requested = client.post("/api/v1/assessments", json={"as_of": ISSUE})
    assert requested.status_code == 202, requested.text
    client.headers["Authorization"] = "Bearer test-agent-token"
    case_response = client.get(CASE)
    assert case_response.status_code == 200, case_response.text
    case = case_response.json()["payload"]
    claimed = client.post("/api/v1/runs/claim")
    assert claimed.status_code == 200, claimed.text
    run = claimed.json()
    snapshot = run["snapshot"]
    assert datetime.fromisoformat(snapshot["as_of"]) == datetime.fromisoformat(ISSUE)
    assert datetime.fromisoformat(snapshot["known_at"]) >= datetime.fromisoformat(
        case_response.json()["recorded_at"]
    )
    assert (
        str(run["input_revision"])
        == snapshot["procurement_contract"]["captured_state_revision"]
    )

    opening = {ingredient: Decimal(0) for ingredient in case["ingredient_ids"]}
    for lot in snapshot["inventory"]:
        if lot["status"] == "ACTIVE":
            assert lot["coverage_complete"] is True
            opening[lot["ingredient_id"]] += Decimal(lot["quantity"])
    assert opening == {
        ingredient: Decimal(quantity)
        for ingredient, quantity in case["opening_expected"].items()
    }
    tofu_recipe = {
        row["ingredient_id"]: Decimal(row["quantity"])
        for row in snapshot["recipes"]
        if row["menu_item_id"] == "tofu-bowl"
    }
    assert tofu_recipe == {
        "tofu": Decimal("0.150"),
        "rice": Decimal("0.100"),
        "vegetables": Decimal("0.100"),
    }
    vegetable_demand = [
        Decimal(bucket["expected_portions"]["tofu-bowl"]) * tofu_recipe["vegetables"]
        for bucket in case["forecasts"][0]["buckets"]
    ]
    assert vegetable_demand == [Decimal(7), Decimal(3)]
    assert sum(vegetable_demand) - opening["vegetables"] == Decimal(4)
    received_lot = next(
        lot for lot in snapshot["inventory"] if lot["id"] == receipt_lot_id
    )
    assert Decimal(received_lot["quantity"]) == Decimal(6)
    assert (
        received_lot["expiry_date"]
        == case["fixed_supply_expected"]["received_expiry_date"]
    )

    assert len(snapshot["commitments"]) == 1
    fixed = snapshot["commitments"][0]
    expected = case["fixed_supply_expected"]
    for field in ("supplier_id", "ingredient_id", "kind"):
        assert fixed[field] == expected[field]
    for field in ("ordered_at", "expected_at"):
        assert datetime.fromisoformat(fixed[field]) == datetime.fromisoformat(
            expected[field]
        )
    for field in (
        "expected_quantity",
        "received_quantity",
        "cancelled_quantity",
        "outstanding_quantity",
    ):
        assert Decimal(fixed[field]) == Decimal(expected[field])
    assert fixed["receipts"][0]["lot_id"] == receipt_lot_id
    projection = snapshot["procurement_contract"]["commitment_projection"]
    assert projection["complete"] is True
    assert projection["supply_manifest"] == [delivery_id]
    assert len(projection["supplies"]) == 1
    assert projection["supplies"][0]["delivery"]["id"] == delivery_id
    assert projection["supplies"][0]["expiry_date"] == "2026-02-20"
    assert projection["supplies"][0]["expiry_evidence"]["reference"] == (
        f"delivery:{delivery_id}:expected_expiry_date"
    )
    assert (
        projection["supplies"][0]["expiry_evidence"]["captured_revision"]
        == (fixed["terms_event_id"])
    )
    assert datetime.fromisoformat(
        projection["supplies"][0]["expiry_evidence"]["available_at"]
    ) <= datetime.fromisoformat(snapshot["known_at"])
    assert (
        snapshot["procurement_contract"]["policy"]["payload"]["emergency_mode"]
        == "NORMAL_ONLY"
    )
    assert "contingency_contract" not in snapshot
    staged = snapshot["staged_contingency_case"]
    assert staged["status"] == "STAGED_MATCH", staged["findings"]
    assert staged["findings"] == []
    assert staged["policy"]["id"] == "policy:BOUNDED_CONTINGENCY_CASH_V1_DEMO:3"
    assert staged["case_input"]["id"] == (
        "case-input:BOUNDED_CONTINGENCY_20260216_CASE_V1:3"
    )
    assert staged["case_input"]["payload"]["offer_authority"] == (
        "APPROVED_SYNTHETIC_DEMO_QUOTE"
    )
    assert staged["run_id"] == run["id"]
    assert datetime.fromisoformat(staged["known_at"]) == datetime.fromisoformat(
        snapshot["known_at"]
    )
    assert staged["captured_state_revision"] == str(run["input_revision"])
    assert staged["opening_lots"] == snapshot["inventory"]
    assert FrozenCommitmentProjection.model_validate(
        staged["commitment_projection"]
    ) == FrozenCommitmentProjection.model_validate(projection)
    read_back = client.get(f"/api/v1/runs/{run['id']}/staged-contingency-case")
    assert read_back.status_code == 200, read_back.text
    assert read_back.json() == staged
    diagnostic = client.get(f"/api/v1/runs/{run['id']}/staged-contingency-diagnostic")
    assert diagnostic.status_code == 200, diagnostic.text
    result = diagnostic.json()
    assert result["status"] == "STAGED_DIAGNOSTIC"
    assert result["actionable"] is False
    assert result["offer_authority"] == "APPROVED_SYNTHETIC_DEMO_QUOTE"
    assert result["offer_approval_reference"] == "DEMO_QUOTE_DECISION_2026_09_24"
    assert result["run_id"] == run["id"]
    assert result["captured_state_revision"] == str(run["input_revision"])
    assert result["findings"] == []
    assert result["search_status"] == "OPTIMAL_IN_DOMAIN", result
    assert result["search_complete"] is True
    assert result["validation_complete"] is True
    assert result["validation_feasible"] is True
    assert result["candidate_lines"] == [
        {
            "opportunity_id": "rescue",
            "offer_id": "market-vegetables",
            "supplier_id": "market",
            "ingredient_id": "vegetables",
            "shipment_group_id": "new-rescue-shipment",
            "quantity": "4",
            "unit": "kg",
            "unit_price": "2",
            "ordered_at": ISSUE,
            "arrival_at": "2026-02-16T11:00:00+08:00",
            "expiry_date": "2026-02-17",
            "kind": "EMERGENCY",
        }
    ]
    assert result["fixed_supply_ids"] == [delivery_id]
    assert Decimal(result["cash_acquisition_sgd"]) == Decimal(8)
    assert Decimal(result["cash_delivery_sgd"]) == Decimal(3)
    assert Decimal(result["cash_emergency_sgd"]) == Decimal(4)
    assert Decimal(result["cash_total_sgd"]) == Decimal(15)
    artifact_path = f"/api/v1/runs/{run['id']}/staged-contingency-artifact"
    assert client.get(artifact_path).status_code == 409
    saved = client.put(artifact_path)
    assert saved.status_code == 200, saved.text
    artifact = saved.json()
    assert artifact["status"] == "STAGED_DIAGNOSTIC"
    assert artifact["actionable"] is False
    assert artifact["captured_state_revision"] == str(run["input_revision"])
    assert artifact["diagnostic"] == result
    assert artifact["result"]["status"] == "OPTIMAL_IN_DOMAIN"
    assert artifact["independent_validation"]["complete"] is True
    assert artifact["independent_validation"]["feasible"] is True
    assert artifact["independent_validation"]["cash"]["total"] == "15"
    assert artifact["result"]["no_purchase"]["fixed_supply_ids"] == [delivery_id]
    repeated = client.put(artifact_path)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json() == artifact
    assert client.get(artifact_path).json() == artifact
    unchanged = client.get(f"/api/v1/runs/{run['id']}")
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["status"] == "RUNNING"
    assert unchanged.json()["plan_version_id"] is None
    assert unchanged.json()["snapshot"]["staged_contingency_artifact"]["id"] == artifact["id"]
    assert "calculated_candidate" not in unchanged.json()["snapshot"]
    tampered = StagedContingencyArtifact.model_validate(
        {**artifact, "result": {**artifact["result"], "status": "INCOMPLETE"}}
    )
    with pytest.raises(ApiError) as error:
        _verify_artifact(PlanningRun.model_validate(unchanged.json()), tampered)
    assert error.value.detail.code == "STATE_REVISION_STALE"
    assert client.get("/api/v1/plan-history").json() == []

    active = snapshot["active_contingency_case"]
    assert active["status"] == "ACTIVE_MATCH"
    assert active["case_input"]["id"].endswith(":4")
    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            execution = run_backend_coordinator(
                session,
                run["id"],
                EngineScript(),
                BackendProcurementTools(session),
                manual_classifier=_FullPlanningRouteClassifier(),
            )
            assert execution.completion.outcome is AgentOutcome.REVISE_PLAN
            assert execution.publication_result is not None
            plan = execution.publication_result.created_plan_version
            assert plan is not None
            assert plan.status.value == "PENDING_APPROVAL"
            assert plan.cost_scope.value == "NEW_PURCHASE_CASH_ONLY"
            assert plan.new_purchase_cash_cost == Decimal(15)
            assert plan.total_expected_cost is None
            assert len(plan.lines) == 1
            assert plan.lines[0].kind == "EMERGENCY"
            assert plan.lines[0].quantity == Decimal(4)
            plan_id = plan.id
            version = plan.version
            logical_plan_id = plan.plan_id
    finally:
        engine.dispose()

    client.headers.pop("Authorization", None)
    approved = client.post(
        f"/api/v1/plans/{plan_id}/decision",
        json={"plan_id": logical_plan_id, "plan_version": version, "decision": "APPROVED"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED"
    lines = client.get(f"/api/v1/plans/{plan_id}/lines")
    assert lines.status_code == 200, lines.text
    assert len(lines.json()) == 1
    line = lines.json()[0]
    assert line["kind"] == "EMERGENCY"
    assert line["expiry_date"] == "2026-02-17"
    purchase = client.post(
        "/api/v1/deliveries",
        json={
            "supplier_id": line["supplier_id"],
            "ingredient_id": line["ingredient_id"],
            "kind": line["kind"],
            "expected_quantity": line["quantity"],
            "ordered_at": line["ordered_at"],
            "expected_at": line["arrival_at"],
            "expected_expiry_date": line["expiry_date"],
            "source_plan_line_id": line["id"],
        },
    )
    assert purchase.status_code == 201, purchase.text
    assert purchase.json()["source_plan_line_id"] == line["id"]
    assert client.get(f"/api/v1/plans/{plan_id}/lines").json()[0][
        "uncommitted_quantity"
    ] == "0.000"
