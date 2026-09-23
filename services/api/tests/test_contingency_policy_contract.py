"""The first contingency policy is explicit demo evidence, not a live default."""

from fastapi.testclient import TestClient

POLICY = "/api/v1/contingency-policies/BOUNDED_CONTINGENCY_CASH_V1_DEMO/versions/1"


def test_agent_reads_staged_version_without_activating_normal_runs(
    client: TestClient,
) -> None:
    assert client.get(POLICY).status_code == 401
    client.headers["Origin"] = "https://frontend.example"
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "manager", "password": "test-manager-password"},
        ).status_code
        == 200
    )
    assert client.get(POLICY).status_code == 403
    client.headers["Authorization"] = "Bearer test-agent-token"
    response = client.get(POLICY)
    assert response.status_code == 200, response.text
    version = response.json()
    assert version["policy_id"] == "BOUNDED_CONTINGENCY_CASH_V1_DEMO"
    assert version["version"] == 1
    policy = version["payload"]
    assert policy["source_kind"] == "EXPLICIT_SYNTHETIC_INTEGRATION_FIXTURE"
    assert policy["activation_state"] == "STAGED"
    assert policy["objective_policy"] == "BOUNDED_CONTINGENCY_CASH_V1"
    assert policy["search_policy"] == "CONTINGENCY_CARTESIAN_V1"
    assert policy["fee_policy"] == "EXPLICIT_NEW_SHIPMENT_ONCE_V1"
    assert policy["new_order_budget_sgd"] == "30"
    assert policy["work_limit"] == 10000
    assert policy["approved_domain_id"] is None
    assert policy["forecast_artifact_id"] is None
    assert (
        set(policy["safety_stock"])
        == set(policy["storage_limits"])
        == {
            "chicken",
            "rice",
            "noodles",
            "eggs",
            "tofu",
            "vegetables",
            "oil",
            "soy-sauce",
        }
    )
    assert all(value == "0" for value in policy["safety_stock"].values())
    assert all(value == "30" for value in policy["storage_limits"].values())
    assert all(
        value == "2026-02-16T12:00:00+08:00"
        for value in policy["protected_end"].values()
    )
    assert policy["assessment_end"]["vegetables"] == "2026-02-17T12:00:00+08:00"
    assert all(
        value == "2026-02-16T12:00:00+08:00"
        for key, value in policy["assessment_end"].items()
        if key != "vegetables"
    )

    del client.headers["Authorization"]
    requested = client.post(
        "/api/v1/assessments", json={"as_of": "2026-02-16T10:00:00+08:00"}
    )
    assert requested.status_code == 202, requested.text
    client.headers["Authorization"] = "Bearer test-agent-token"
    claimed = client.post("/api/v1/runs/claim")
    assert claimed.status_code == 200, claimed.text
    snapshot = claimed.json()["snapshot"]
    assert "contingency_contract" not in snapshot
    assert snapshot["procurement_contract"]["policy"]["payload"]["emergency_mode"] == (
        "NORMAL_ONLY"
    )


def test_unknown_contingency_policy_is_not_synthesised(client: TestClient) -> None:
    client.headers["Authorization"] = "Bearer test-agent-token"
    response = client.get(
        "/api/v1/contingency-policies/BOUNDED_CONTINGENCY_CASH_V1_DEMO/versions/2"
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "MISSING_REQUIRED_DATA"
