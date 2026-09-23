from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, update

from src import database as db

ISSUE_TIME = "2026-02-15T22:00:00+08:00"
ARRIVAL_TIME = "2026-02-16T08:00:00+08:00"


def instant(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value)
    assert timestamp.utcoffset() is not None
    return timestamp


def sign_in(client: TestClient) -> None:
    client.headers["Origin"] = "https://frontend.example"
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "manager", "password": "test-manager-password"},
        ).status_code
        == 200
    )


def agent(client: TestClient) -> None:
    client.headers["Authorization"] = "Bearer test-agent-token"


def test_manager_policy_display_preserves_role_boundaries(client: TestClient) -> None:
    listing = "/api/v1/manager/procurement-policies"
    display = listing + "/CASH_SLICE_V1/versions/1"
    assert client.get(listing).status_code == 401
    assert client.get(display).status_code == 401
    agent(client)
    assert client.get(listing).status_code == 403
    assert client.get(display).status_code == 403
    canonical = client.get(
        "/api/v1/procurement-policies/CASH_SLICE_V1/versions/1"
    ).json()
    del client.headers["Authorization"]
    sign_in(client)
    assert (
        client.get("/api/v1/procurement-policies/CASH_SLICE_V1/versions/1").status_code
        == 403
    )
    versions = client.get(listing)
    assert versions.status_code == 200
    assert versions.json()[0]["id"] == canonical["policy"]["id"]
    response = client.get(display)
    assert response.status_code == 200
    assert response.json() == {
        key: canonical[key]
        for key in (
            "policy",
            "domain",
            "forecast_input",
            "activity_semantics",
            "commitment_projection",
        )
    }
    assert "frozen_state" not in response.json()
    assert client.get(listing + "/MISSING/versions/1").status_code == 409


def test_first_slice_policy_endpoint_exposes_complete_immutable_domain(
    client: TestClient,
) -> None:
    endpoint = "/api/v1/procurement-policies/CASH_SLICE_V1/versions/1"
    assert client.get(endpoint).status_code == 401
    agent(client)
    response = client.get(endpoint)
    assert response.status_code == 200, response.text
    contract = response.json()
    assert contract["policy"]["policy_id"] == "CASH_SLICE_V1"
    assert contract["policy"]["version"] == 1
    assert contract["policy"]["payload"] == {
        **contract["policy"]["payload"],
        "objective_policy": "CASH_SLICE_V1",
        "new_order_budget_sgd": "100.000",
        "fee_policy": "SUPPLIER_ARRIVAL_ONCE_V1",
        "fee_grouping": "SUPPLIER_ID_AND_ARRIVAL_AT",
        "reliability_mode": "CONTEXT_ONLY",
        "emergency_mode": "NORMAL_ONLY",
        "fefo_policy": "FEFO_EXPIRY_RECEIVED_LOT_ID_V1",
        "new_supply_expiry_policy": "EXPIRY_ARRIVAL_PLUS_SHELF_LIFE_MINUS_ONE_V1",
        "tie_break_policy": "SUPPLIER_ID_THEN_INGREDIENT_ID_V1",
        "search_policy": "COMPLETE_PRUNED_DOMAIN_V1",
    }
    domain = contract["domain"]
    assert domain["domain_id"] == "CASH_SLICE_20260216_DOMAIN_V1"
    assert len(domain["offers"]) == len(domain["opportunities"]) == 24
    assert {row["supplier_id"] for row in domain["offers"]} == {
        "fresh",
        "pantry",
        "market",
    }
    assert {row["ingredient_id"] for row in domain["offers"]} == {
        "chicken",
        "rice",
        "noodles",
        "eggs",
        "tofu",
        "vegetables",
        "oil",
        "soy-sauce",
    }
    assert all(row["source_revision"] for row in domain["offers"])
    assert all(
        row["kind"] == "NORMAL"
        and instant(row["ordered_at"]) == instant(ISSUE_TIME)
        and instant(row["arrival_at"]) == instant(ARRIVAL_TIME)
        and row["expiry_date"] == "2026-02-20"
        for row in domain["opportunities"]
    )
    forecast_input = contract["forecast_input"]
    assert forecast_input["artifact_id"] == "CASH_SLICE_20260216_HISTORY_V1"
    assert forecast_input["version"] == 1
    assert forecast_input["policy_version_id"] == contract["policy"]["id"]
    assert instant(forecast_input["recorded_at"]) <= instant(contract["known_at"])
    assert forecast_input["payload"]["forecast_method"] == "SEASONAL_BASELINE_V1"
    assert forecast_input["payload"]["target_date"] == "2026-02-16"
    assert len(forecast_input["payload"]["history"]) == 4
    assert {row["service_date"] for row in forecast_input["payload"]["history"]} == {
        "2026-01-19",
        "2026-01-26",
        "2026-02-02",
        "2026-02-09",
    }
    assert all(
        row["portions"]
        == {
            "chicken-rice": 100,
            "fried-rice": 60,
            "chicken-noodles": 80,
            "tofu-bowl": 40,
            "vegetable-noodles": 40,
        }
        for row in forecast_input["payload"]["history"]
    )


def test_explicit_new_shipment_identity_is_preserved_in_frozen_domain(
    client: TestClient, database_url: str
) -> None:
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                update(db.procurement_domain_opportunities)
                .where(
                    db.procurement_domain_opportunities.c.offer_id
                    == "market-vegetables"
                )
                .values(shipment_group_id="demo-new-shipment")
            )
    finally:
        engine.dispose()
    sign_in(client)
    requested = client.post("/api/v1/assessments", json={"as_of": ISSUE_TIME})
    assert requested.status_code == 202, requested.text
    run_id = requested.json()["id"]
    agent(client)
    assert client.post("/api/v1/runs/claim").status_code == 200
    frozen = client.get(f"/api/v1/runs/{run_id}/procurement-contract")
    assert frozen.status_code == 200, frozen.text
    opportunity = next(
        row
        for row in frozen.json()["domain"]["opportunities"]
        if row["offer_id"] == "market-vegetables"
    )
    assert opportunity["shipment_group_id"] == "demo-new-shipment"


def test_agent_reads_the_exact_contract_frozen_with_run_context(
    client: TestClient,
) -> None:
    sign_in(client)
    requested = client.post("/api/v1/assessments", json={"as_of": ISSUE_TIME})
    assert requested.status_code == 202, requested.text
    run_id = requested.json()["id"]
    manager_endpoint = f"/api/v1/manager/runs/{run_id}/procurement-evidence"
    assert client.get(manager_endpoint).status_code == 409
    agent(client)
    assert client.get(manager_endpoint).status_code == 403
    assert client.get(f"/api/v1/runs/{run_id}/procurement-contract").status_code == 409
    claimed = client.post("/api/v1/runs/claim")
    assert claimed.status_code == 200, claimed.text
    run = claimed.json()
    response = client.get(f"/api/v1/runs/{run_id}/procurement-contract")
    assert response.status_code == 200, response.text
    contract = response.json()
    assert contract["run_id"] == run_id
    assert instant(contract["as_of"]) == instant(ISSUE_TIME)
    assert instant(contract["known_at"]) == instant(run["snapshot"]["known_at"])
    assert contract["captured_state_revision"] == str(run["input_revision"])
    assert contract["policy"]["version"] == 1
    assert contract["domain"]["version"] == 1
    assert contract["forecast_input"]["version"] == 1
    assert instant(contract["forecast_input"]["effective_at"]) <= instant(
        contract["as_of"]
    )
    assert instant(contract["forecast_input"]["recorded_at"]) <= instant(
        contract["known_at"]
    )
    assert contract["frozen_state"]["commitments"] == []
    assert contract["frozen_state"]["sales_batches"] == []
    assert len(contract["frozen_state"]["inventory"]) == 9
    assert run["snapshot"]["procurement_contract"] == contract
    del client.headers["Authorization"]
    display = client.get(manager_endpoint)
    assert display.status_code == 200
    assert display.json() == {
        key: contract[key]
        for key in (
            "policy",
            "domain",
            "forecast_input",
            "activity_semantics",
            "commitment_projection",
        )
    }


def test_incomplete_domain_fails_closed_at_canonical_read_boundary(
    client: TestClient, database_url: str
) -> None:
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                delete(db.procurement_domain_opportunities).where(
                    db.procurement_domain_opportunities.c.offer_id == "market-oil"
                )
            )
    finally:
        engine.dispose()
    agent(client)
    response = client.get("/api/v1/procurement-policies/CASH_SLICE_V1/versions/1")
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "MISSING_REQUIRED_DATA"


def test_missing_forecast_input_fails_closed_at_canonical_read_boundary(
    client: TestClient, database_url: str
) -> None:
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(delete(db.procurement_forecast_inputs))
    finally:
        engine.dispose()
    agent(client)
    response = client.get("/api/v1/procurement-policies/CASH_SLICE_V1/versions/1")
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "MISSING_REQUIRED_DATA"


def test_run_does_not_capture_forecast_input_recorded_after_its_known_at(
    client: TestClient, database_url: str
) -> None:
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                update(db.procurement_forecast_inputs).values(
                    recorded_at=datetime.now(UTC) + timedelta(days=1)
                )
            )
    finally:
        engine.dispose()

    sign_in(client)
    requested = client.post("/api/v1/assessments", json={"as_of": ISSUE_TIME})
    assert requested.status_code == 202, requested.text
    agent(client)
    claimed = client.post("/api/v1/runs/claim")
    assert claimed.status_code == 200, claimed.text
    response = client.get(f"/api/v1/runs/{claimed.json()['id']}/procurement-contract")
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "MISSING_REQUIRED_DATA"


def test_first_slice_contract_freezes_nonempty_post_baseline_activity(
    client: TestClient,
) -> None:
    sign_in(client)
    activity = client.post(
        "/api/v1/sales-batches",
        json={
            "source": "simulator",
            "batch_id": "before-first-slice",
            "period_start": "2026-02-15T21:00:00+08:00",
            "period_end": "2026-02-15T21:30:00+08:00",
            "sales": {"chicken-rice": 1},
        },
    )
    assert activity.status_code == 201, activity.text
    requested = client.post("/api/v1/assessments", json={"as_of": ISSUE_TIME})
    assert requested.status_code == 202, requested.text
    agent(client)
    run = client.post("/api/v1/runs/claim")
    assert run.status_code == 200, run.text
    response = client.get(f"/api/v1/runs/{run.json()['id']}/procurement-contract")
    assert response.status_code == 200, response.text
    contract = response.json()
    assert contract["frozen_state"]["sales_batches"][0]["id"] == activity.json()["id"]
    assert contract["activity_semantics"]["intraday_sales_mode"] == (
        "INVENTORY_ESTIMATE_AND_REASSESSMENT_ONLY"
    )
    assert contract["commitment_projection"] == {
        "as_of": contract["as_of"],
        "known_at": contract["known_at"],
        "captured_state_revision": contract["captured_state_revision"],
        "expiry_policy": "EXPIRY_ARRIVAL_PLUS_SHELF_LIFE_MINUS_ONE_V1",
        "complete": True,
        "findings": [],
        "supply_manifest": [],
        "supplies": [],
    }
