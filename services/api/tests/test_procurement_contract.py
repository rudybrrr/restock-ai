from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete

from src import database as db

ISSUE_TIME = "2026-02-15T22:00:00+08:00"


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
        and datetime.fromisoformat(row["ordered_at"])
        == datetime.fromisoformat(ISSUE_TIME)
        and datetime.fromisoformat(row["arrival_at"])
        == datetime.fromisoformat("2026-02-16T08:00:00+08:00")
        and row["expiry_date"] == "2026-02-20"
        for row in domain["opportunities"]
    )


def test_agent_reads_the_exact_contract_frozen_with_run_context(
    client: TestClient,
) -> None:
    sign_in(client)
    requested = client.post("/api/v1/assessments", json={"as_of": ISSUE_TIME})
    assert requested.status_code == 202, requested.text
    run_id = requested.json()["id"]
    agent(client)
    assert client.get(f"/api/v1/runs/{run_id}/procurement-contract").status_code == 409
    claimed = client.post("/api/v1/runs/claim")
    assert claimed.status_code == 200, claimed.text
    run = claimed.json()
    response = client.get(f"/api/v1/runs/{run_id}/procurement-contract")
    assert response.status_code == 200, response.text
    contract = response.json()
    assert contract["run_id"] == run_id
    assert datetime.fromisoformat(contract["as_of"]) == datetime.fromisoformat(
        ISSUE_TIME
    )
    assert datetime.fromisoformat(contract["known_at"]) == datetime.fromisoformat(
        run["snapshot"]["known_at"]
    )
    assert contract["captured_state_revision"] == str(run["input_revision"])
    assert contract["policy"]["version"] == 1
    assert contract["domain"]["version"] == 1
    assert contract["frozen_state"]["commitments"] == []
    assert contract["frozen_state"]["sales_batches"] == []
    assert len(contract["frozen_state"]["inventory"]) == 9
    assert run["snapshot"]["procurement_contract"] == contract


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


def test_first_slice_contract_refuses_nonempty_post_baseline_activity(
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
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "MISSING_REQUIRED_DATA"
    assert run.json()["snapshot"]["procurement_contract_unavailable_reason"] == (
        "FIRST_SLICE_ACTIVITY_NOT_EMPTY"
    )
