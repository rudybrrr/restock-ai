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
