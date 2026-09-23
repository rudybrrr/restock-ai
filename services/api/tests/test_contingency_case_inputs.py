"""Versioned first-case numerical inputs stay explicit and non-activated."""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from test_daily import sign_in

from src import database as db

CASE = "/api/v1/contingency-case-inputs/BOUNDED_CONTINGENCY_20260216_CASE_V1/versions/1"
CASE_V2 = CASE.replace("/versions/1", "/versions/2")


def test_agent_reads_complete_first_case_domain_and_residual_forecast(
    client: TestClient,
) -> None:
    assert client.get(CASE).status_code == 401
    client.headers["Authorization"] = "Bearer test-agent-token"
    response = client.get(CASE)
    assert response.status_code == 200, response.text
    artifact = response.json()
    assert artifact["policy_version_id"] == "policy:BOUNDED_CONTINGENCY_CASH_V1_DEMO:1"
    case = artifact["payload"]
    assert case["source_kind"] == "EXPLICIT_SYNTHETIC_INTEGRATION_FIXTURE"
    assert case["as_of"] == "2026-02-16T10:00:00+08:00"
    assert case["domain_id"] == "BOUNDED_CONTINGENCY_20260216_DOMAIN_V1"
    assert case["forecast_method"] == "EXPLICIT_RESIDUAL_DEMO_V1"
    assert len(case["forecasts"]) == 2
    today, tomorrow = case["forecasts"]
    assert today["target_date"] == "2026-02-16"
    assert [
        bucket["expected_portions"]["tofu-bowl"] for bucket in today["buckets"]
    ] == [
        "70",
        "30",
    ]
    assert tomorrow["target_date"] == "2026-02-17"
    assert all(
        all(value == "0" for value in bucket["expected_portions"].values())
        for bucket in tomorrow["buckets"]
    )
    assert case["opening_expected"]["vegetables"] == "6"
    assert case["fixed_supply_expected"] == {
        **case["fixed_supply_expected"],
        "supplier_id": "fresh",
        "ingredient_id": "vegetables",
        "expected_quantity": "10",
        "received_quantity": "6",
        "outstanding_quantity": "4",
    }
    assert case["approved_offer_manifest"] == [
        ["market-vegetables", "market", "vegetables"]
    ]
    assert len(case["offers"]) == 1
    assert case["offers"][0]["offer"]["unit_price"] == "2"
    assert case["offers"][0]["offer"]["available_quantity"] == "6"
    assert len(case["opportunities"]) == 1
    assert case["opportunities"][0]["kind"] == "EMERGENCY"
    assert case["opportunities"][0]["shipment_group_id"] == "new-rescue-shipment"
    assert case["opportunity_manifest"] == ["rescue"]


def test_version_two_binds_complete_catalogue_and_policy(
    client: TestClient,
) -> None:
    client.headers["Authorization"] = "Bearer test-agent-token"
    response = client.get(CASE_V2)
    assert response.status_code == 200, response.text
    artifact = response.json()
    assert artifact["version"] == 2
    assert artifact["policy_version_id"] == "policy:BOUNDED_CONTINGENCY_CASH_V1_DEMO:2"
    case = artifact["payload"]
    assert len(case["catalogue_menu_items"]) == 5
    assert len(case["catalogue_ingredients"]) == 8
    assert len(case["catalogue_recipes"]) == 16
    assert len(case["catalogue_suppliers"]) == 3
    assert len(case["recipe_manifest"]) == 16
    assert len(case["catalogue_sha256"]) == 64
    assert [
        row["quantity"]
        for row in case["catalogue_recipes"]
        if row["menu_item_id"] == "tofu-bowl" and row["ingredient_id"] == "vegetables"
    ] == ["0.100"]
    policy = client.get(
        "/api/v1/contingency-policies/BOUNDED_CONTINGENCY_CASH_V1_DEMO/versions/2"
    )
    assert policy.status_code == 200, policy.text
    assert policy.json()["payload"]["activation_state"] == "STAGED"
    assert policy.json()["payload"]["approved_domain_id"] == case["domain_id"]
    assert policy.json()["payload"]["forecast_artifact_id"] == artifact["id"]


def test_versioned_recipe_change_without_new_digest_fails_closed(
    client: TestClient, database_url: str
) -> None:
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            payload = connection.execute(
                select(db.contingency_case_inputs.c.payload).where(
                    db.contingency_case_inputs.c.version == 2
                )
            ).scalar_one()
            payload["catalogue_recipes"][0]["quantity"] = "0.999"
            connection.execute(
                update(db.contingency_case_inputs)
                .where(db.contingency_case_inputs.c.version == 2)
                .values(payload=payload)
            )
    finally:
        engine.dispose()
    client.headers["Authorization"] = "Bearer test-agent-token"
    response = client.get(CASE_V2)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MISSING_REQUIRED_DATA"
    del client.headers["Authorization"]
    sign_in(client)
    requested = client.post(
        "/api/v1/assessments", json={"as_of": "2026-02-16T10:00:00+08:00"}
    )
    assert requested.status_code == 202, requested.text
    client.headers["Authorization"] = "Bearer test-agent-token"
    claimed = client.post("/api/v1/runs/claim")
    assert claimed.status_code == 200, claimed.text
    snapshot = claimed.json()["snapshot"]
    assert snapshot["staged_contingency_case"]["status"] == "UNAVAILABLE"
    diagnostic = client.get(
        f"/api/v1/runs/{claimed.json()['id']}/staged-contingency-diagnostic"
    )
    assert diagnostic.status_code == 409
    assert diagnostic.json()["error"]["code"] == "MISSING_REQUIRED_DATA"
    assert (
        snapshot["procurement_contract"]["policy"]["payload"]["emergency_mode"]
        == "NORMAL_ONLY"
    )


def test_unknown_case_input_version_fails_closed(client: TestClient) -> None:
    client.headers["Authorization"] = "Bearer test-agent-token"
    response = client.get(CASE.replace("/versions/1", "/versions/3"))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MISSING_REQUIRED_DATA"


def test_incomplete_new_shipment_domain_fails_closed(
    client: TestClient, database_url: str
) -> None:
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            payload = connection.execute(
                select(db.contingency_case_inputs.c.payload).where(
                    db.contingency_case_inputs.c.version == 1
                )
            ).scalar_one()
            payload["opportunities"][0]["shipment_group_id"] = None
            connection.execute(
                update(db.contingency_case_inputs)
                .where(db.contingency_case_inputs.c.version == 1)
                .values(payload=payload)
            )
    finally:
        engine.dispose()
    client.headers["Authorization"] = "Bearer test-agent-token"
    response = client.get(CASE)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MISSING_REQUIRED_DATA"
