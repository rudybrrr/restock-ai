"""Read-boundary checks without a database; persistence is tested separately."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient

from src import auth, procurement_contracts
from src.config import Settings
from src.database import get_session
from src.main import create_app
from src.schemas import Identity


def test_manager_run_projection_preserves_structured_trace_without_private_payloads():
    from src.manager_evidence import build_manager_run_evidence
    from src.planning_schemas import PlanningRun, PurchasePlanVersion

    run = PlanningRun.model_validate(
        {
            "id": "run-1",
            "status": "SUCCEEDED",
            "trigger": "SUPPLIER_AVAILABILITY_CHANGED",
            "trigger_event_id": "event-1",
            "as_of": "2026-02-16T08:00:00+08:00",
            "input_revision": 12,
            "snapshot": {"known_at": "2026-02-16T08:00:00+08:00"},
            "outcome": "REQUEST_HUMAN_APPROVAL",
            "plan_version_id": "version-2",
            "created_at": "2026-02-16T08:00:01+08:00",
            "completed_at": "2026-02-16T08:00:03+08:00",
        }
    )
    plans = [
        PurchasePlanVersion.model_validate(
            {
                "id": "version-2",
                "plan_id": "plan-1",
                "version": 2,
                "status": "PENDING_APPROVAL",
                "calculation_mode": "ENGINE",
                "forecast_id": "forecast-2",
                "inventory_snapshot_id": "inventory-2",
                "run_id": "run-1",
                "lines": [],
                "total_purchase_cost": "10",
                "total_expected_cost": "10",
                "created_at": "2026-02-16T08:00:02+08:00",
            }
        ),
        PurchasePlanVersion.model_validate(
            {
                "id": "version-1",
                "plan_id": "plan-1",
                "version": 1,
                "status": "SUPERSEDED",
                "calculation_mode": "ENGINE",
                "forecast_id": "forecast-1",
                "inventory_snapshot_id": "inventory-1",
                "run_id": "old-run",
                "lines": [],
                "total_purchase_cost": "9",
                "total_expected_cost": "9",
                "created_at": "2026-02-16T07:00:02+08:00",
            }
        ),
    ]
    audits = [
        {
            "id": "audit-specialist",
            "event_id": "event-1",
            "actor": "COORDINATOR",
            "action": "SPECIALIST_CALLED",
            "timestamp": "2026-02-16T08:00:01+08:00",
            "payload": {
                "run_id": "run-1",
                "state_revision": "12",
                "specialist": "PROCUREMENT",
                "specialist_call_id": "run-1-TASK-1",
                "call_sequence": 1,
                "objective": "Investigate supplier impact.",
                "summary": "Called PROCUREMENT specialist.",
                "prompt": "must not appear",
            },
        },
        {
            "id": "audit-tool",
            "event_id": "event-1",
            "actor": "PROCUREMENT",
            "action": "TOOL_RESULT_RECORDED",
            "timestamp": "2026-02-16T08:00:02+08:00",
            "payload": {
                "run_id": "run-1",
                "state_revision": "12",
                "tool_call_id": "run-1-TASK-1-TOOL-1",
                "tool_name": "check_supplier_feasibility",
                "tool_succeeded": True,
                "summary": "Supplier evidence returned.",
                "scratchpad": "must not appear",
                "evidence_refs": [
                    {
                        "category": "SUPPLIER_STATE",
                        "source": "BACKEND",
                        "reference_id": "offer-1",
                        "state_revision": "12",
                    }
                ],
            },
        },
        {
            "id": "audit-validation",
            "event_id": "event-1",
            "actor": "BACKEND",
            "action": "VALIDATION_COMPLETED",
            "timestamp": "2026-02-16T08:00:02+08:00",
            "payload": {
                "run_id": "run-1",
                "state_revision": "12",
                "tool_succeeded": True,
                "summary": "Candidate is feasible.",
            },
        },
        {
            "id": "audit-stale",
            "event_id": "event-1",
            "actor": "manager",
            "action": "APPROVAL_RECORDED",
            "timestamp": "2026-02-16T08:00:04+08:00",
            "payload": {
                "run_id": "run-1",
                "plan_id": "plan-1",
                "plan_version": 1,
                "reason_codes": ["PLAN_VERSION_STALE"],
                "summary": "Approval of exact plan version 1 was rejected as stale.",
            },
        },
        {
            "id": "audit-complete",
            "event_id": "event-1",
            "actor": "COORDINATOR",
            "action": "RUN_COMPLETED",
            "timestamp": "2026-02-16T08:00:03+08:00",
            "payload": {
                "run_id": "run-1",
                "state_revision": "12",
                "final_outcome": "REQUEST_HUMAN_APPROVAL",
                "reason_codes": [],
                "summary": "A validated plan is ready for manager approval.",
                "frozen_state": {"private": "must not appear"},
            },
        },
    ]

    result = build_manager_run_evidence(run, plans, {"id": "event-1", "type": run.trigger, "source": "backend", "timestamp": run.as_of, "payload": {"secret": "hidden"}}, audits)
    dumped = result.model_dump_json()

    assert result.active_plan is not None
    assert result.active_plan.version == 2
    assert [plan.version for plan in result.plan_history] == [2, 1]
    assert result.routing.specialists == ["PROCUREMENT"]
    assert result.routing.tool_calls == ["check_supplier_feasibility"]
    assert result.validation[0].succeeded is True
    assert result.decision.summary == "A validated plan is ready for manager approval."
    assert result.approval.stale_attempts[0].reason_codes == ["PLAN_VERSION_STALE"]
    assert "prompt" not in dumped
    assert "scratchpad" not in dumped
    assert "frozen_state" not in dumped
    assert "secret" not in dumped


def test_manager_run_projection_surfaces_validation_result_tool_evidence():
    from src.manager_evidence import build_manager_run_evidence
    from src.planning_schemas import PlanningRun

    run = PlanningRun.model_validate(
        {
            "id": "run-1",
            "status": "SUCCEEDED",
            "trigger": "SUPPLIER_AVAILABILITY_CHANGED",
            "trigger_event_id": "event-1",
            "as_of": "2026-02-16T08:00:00+08:00",
            "input_revision": 12,
            "snapshot": {},
            "outcome": "REQUEST_HUMAN_APPROVAL",
            "created_at": "2026-02-16T08:00:01+08:00",
            "completed_at": "2026-02-16T08:00:03+08:00",
        }
    )
    result = build_manager_run_evidence(
        run,
        [],
        {"id": "event-1", "type": run.trigger, "source": "backend", "timestamp": run.as_of},
        [
            {
                "id": "audit-validation-tool",
                "event_id": "event-1",
                "actor": "PROCUREMENT",
                "action": "TOOL_RESULT_RECORDED",
                "timestamp": "2026-02-16T08:00:02+08:00",
                "payload": {
                    "tool_succeeded": True,
                    "summary": "validate_purchase_plan returned trusted evidence.",
                    "evidence_refs": [
                        {
                            "category": "VALIDATION_RESULT",
                            "source": "DECISION_ENGINE",
                            "reference_id": "validation:1",
                        }
                    ],
                },
            }
        ],
    )

    assert len(result.validation) == 1
    assert result.validation[0].succeeded is True
    assert result.validation[0].evidence_refs[0].reference_id == "validation:1"


def test_manager_run_evidence_route_is_manager_only_and_uses_projection(monkeypatch):
    from src import planning
    from src.planning_schemas import PlanningRun, PurchasePlanVersion

    run = PlanningRun.model_validate(
        {
            "id": "run-1",
            "status": "SUCCEEDED",
            "trigger": "MANUAL_REASSESSMENT_REQUESTED",
            "trigger_event_id": "event-1",
            "as_of": "2026-02-16T08:00:00+08:00",
            "input_revision": 12,
            "snapshot": {},
            "outcome": "KEEP_CURRENT_PLAN",
            "created_at": "2026-02-16T08:00:01+08:00",
            "completed_at": "2026-02-16T08:00:03+08:00",
        }
    )
    plan = PurchasePlanVersion.model_validate(
        {
            "id": "version-1",
            "plan_id": "plan-1",
            "version": 1,
            "status": "APPROVED",
            "calculation_mode": "ENGINE",
            "forecast_id": "forecast-1",
            "inventory_snapshot_id": "inventory-1",
            "run_id": "run-1",
            "lines": [],
            "total_purchase_cost": "0",
            "total_expected_cost": "0",
            "created_at": "2026-02-16T08:00:02+08:00",
        }
    )
    monkeypatch.setattr(planning, "get_run", lambda *_: run)
    monkeypatch.setattr(planning, "read_plan", lambda *_: plan)

    def execute(statement):
        text = str(statement)
        result = Mock()
        if "plan_versions.plan_id" in text or "plan_versions.run_id" in text:
            result.mappings.return_value.all.return_value = [{"id": "version-1"}]
        elif "events.id" in text:
            result.mappings.return_value.one_or_none.return_value = {
                "id": "event-1",
                "type": "MANUAL_REASSESSMENT_REQUESTED",
                "source": "manager",
                "timestamp": "2026-02-16T08:00:00+08:00",
                "payload": {"private": "not returned"},
            }
        else:
            result.mappings.return_value.all.return_value = []
        return result

    session = Mock()
    session.execute.side_effect = execute
    app = create_app(Settings(database_url="sqlite://"))
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[auth.authenticate] = lambda: Identity(
        role="manager", username="manager"
    )
    with TestClient(app) as client:
        response = client.get("/api/v1/manager/runs/run-1/evidence")
        assert response.status_code == 200, response.text
        assert response.json()["run_id"] == "run-1"
        assert response.json()["plan_history"][0]["version"] == 1
        assert "private" not in response.text

        app.dependency_overrides[auth.authenticate] = lambda: Identity(
            role="agent", username="agent"
        )
        assert client.get("/api/v1/manager/runs/run-1/evidence").status_code == 403


def test_operational_contract_exports_adapter_ready_fixed_commitments():
    rows = procurement_contracts.first_slice_seed_rows(
        datetime(2026, 2, 15, tzinfo=UTC)
    )
    contract = procurement_contracts._build(
        rows["policies"][0],
        rows["domains"][0],
        rows["forecast_inputs"][0],
        rows["offers"],
        rows["opportunities"],
    ).model_copy(
        update={
            "run_id": "run-1",
            "captured_state_revision": "12",
        }
    )
    commitment = {
        "id": "delivery-1",
        "supplier_id": "fresh",
        "ingredient_id": "chicken",
        "kind": "NORMAL",
        "expected_quantity": "10.000",
        "expected_at": "2026-02-16T08:00:00+08:00",
        "ordered_at": "2026-02-15T22:00:00+08:00",
        "received_quantity": "2.000",
        "cancelled_quantity": "3.000",
        "outstanding_quantity": "5.000",
        "receipts": [],
    }
    frozen = procurement_contracts.freeze_operational_activity(
        contract.model_dump(mode="json"),
        {"commitments": [commitment], "sales_batches": [{"id": "batch-1"}]},
    )
    assert frozen["frozen_state"]["sales_batches"] == [{"id": "batch-1"}]
    projection = frozen["commitment_projection"]
    assert projection["complete"] is True
    assert projection["supply_manifest"] == ["delivery-1"]
    supply = projection["supplies"][0]
    assert supply["delivery"]["outstanding_quantity"] == "5.000"
    assert supply["expiry_date"] == "2026-02-20"
    assert supply["projected_lot_id"] == "projected-delivery:delivery-1"
    assert supply["expiry_evidence"]["reference"] == (
        "fresh-chicken:shelf_life_days_on_arrival"
    )
    assert frozen["activity_semantics"]["reconciliation_mode"] == ("COMPARE_NEVER_ADD")


def test_manager_evidence_uses_canonical_contract_and_frozen_run(monkeypatch):
    rows = procurement_contracts.first_slice_seed_rows(
        datetime(2026, 2, 15, tzinfo=UTC)
    )
    contract = procurement_contracts._build(
        rows["policies"][0],
        rows["domains"][0],
        rows["forecast_inputs"][0],
        rows["offers"],
        rows["opportunities"],
    )
    contract.frozen_state = {"private_marker": "must not be returned"}
    read = Mock(return_value=contract)
    monkeypatch.setattr(procurement_contracts, "read_policy_contract", read)
    from src import planning

    monkeypatch.setattr(
        planning,
        "get_run",
        lambda *_: SimpleNamespace(
            snapshot={"procurement_contract": contract.model_dump(mode="json")}
        ),
    )
    app = create_app(Settings(database_url="sqlite://"))
    session = Mock()
    session.execute.return_value.mappings.return_value.all.return_value = rows[
        "policies"
    ]
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[auth.authenticate] = lambda: Identity(
        role="manager", username="manager"
    )
    with TestClient(app) as client:
        listing = "/api/v1/manager/procurement-policies"
        response = client.get(listing)
        assert response.status_code == 200
        assert response.json()[0]["policy_id"] == "CASH_SLICE_V1"
        response = client.get(listing + "/CASH_SLICE_V1/versions/1")
        assert response.status_code == 200, response.text
        read.assert_called_once_with(session, "CASH_SLICE_V1", 1)
        assert set(response.json()) == {"policy", "domain", "forecast_input"}
        assert len(response.json()["domain"]["offers"]) == 24
        frozen = client.get("/api/v1/manager/runs/run-1/procurement-evidence")
        assert frozen.status_code == 200
        assert frozen.json() == response.json()
        assert "private_marker" not in frozen.text
        monkeypatch.setattr(
            planning, "get_run", lambda *_: SimpleNamespace(snapshot={})
        )
        assert (
            client.get("/api/v1/manager/runs/run-1/procurement-evidence").status_code
            == 409
        )
        app.dependency_overrides[auth.authenticate] = lambda: Identity(
            role="agent", username="agent"
        )
        assert client.get(listing).status_code == 403
        assert client.get(listing + "/CASH_SLICE_V1/versions/1").status_code == 403
        assert (
            client.get("/api/v1/manager/runs/run-1/procurement-evidence").status_code
            == 403
        )
