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
        assert set(response.json()) == {
            "policy",
            "domain",
            "forecast_input",
            "activity_semantics",
            "commitment_projection",
        }
        assert len(response.json()["domain"]["offers"]) == 24
        frozen = client.get("/api/v1/manager/runs/run-1/procurement-evidence")
        assert frozen.status_code == 200
        assert frozen.json() == response.json()
        assert "private_marker" not in frozen.text
        historical = contract.model_dump(mode="json")
        historical.pop("activity_semantics")
        monkeypatch.setattr(
            planning,
            "get_run",
            lambda *_: SimpleNamespace(snapshot={"procurement_contract": historical}),
        )
        historical_response = client.get(
            "/api/v1/manager/runs/run-1/procurement-evidence"
        )
        assert historical_response.status_code == 200
        assert historical_response.json()["activity_semantics"] is None
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


def test_manager_assessment_empty_states_and_access(monkeypatch):
    from src import (
        inventory_adjustment_contracts,
        planning,
        sales_materiality_contracts,
    )
    from src.errors import ApiError

    monkeypatch.setattr(planning, "get_run", Mock(return_value=SimpleNamespace()))
    readers = [
        (
            sales_materiality_contracts,
            "sales-materiality",
            "MATERIALITY_ASSESSMENT_NOT_FOUND",
        ),
        (
            inventory_adjustment_contracts,
            "inventory-adjustment",
            "INVENTORY_ADJUSTMENT_ASSESSMENT_NOT_FOUND",
        ),
    ]
    app = create_app(Settings(database_url="sqlite://"))
    app.dependency_overrides[get_session] = lambda: Mock()
    app.dependency_overrides[auth.authenticate] = lambda: Identity(
        role="manager", username="manager"
    )
    with TestClient(app) as client:
        for module, path, code in readers:
            read = Mock(side_effect=ApiError(404, code, "No saved result"))
            monkeypatch.setattr(module, "read_assessment", read)
            url = f"/api/v1/manager/runs/run-1/{path}"
            response = client.get(url)
            assert response.status_code == 200
            assert response.json() is None
            read.side_effect = ApiError(409, "INVALID_EVIDENCE", "Evidence mismatch")
            assert client.get(url).status_code == 409
            app.dependency_overrides[auth.authenticate] = lambda: Identity(
                role="agent", username="agent"
            )
            assert client.get(url).status_code == 403
            app.dependency_overrides[auth.authenticate] = lambda: Identity(
                role="manager", username="manager"
            )
        monkeypatch.setattr(
            planning,
            "get_run",
            Mock(side_effect=ApiError(404, "NOT_FOUND", "Unknown run")),
        )
        for _, path, _ in readers:
            assert client.get(f"/api/v1/manager/runs/missing/{path}").status_code == 404
