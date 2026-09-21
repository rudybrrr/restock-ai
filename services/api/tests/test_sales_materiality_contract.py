from fastapi.testclient import TestClient


def sign_in(client: TestClient) -> None:
    client.headers["Origin"] = "https://frontend.example"
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "manager", "password": "test-manager-password"},
    )
    assert response.status_code == 200, response.text


def use_agent(client: TestClient) -> None:
    client.headers["Authorization"] = "Bearer test-agent-token"


def claim_sales_run(client: TestClient) -> dict:
    sign_in(client)
    sales = client.post(
        "/api/v1/sales-batches",
        json={
            "source": "simulator",
            "batch_id": "materiality-contract-001",
            "period_start": "2026-02-15T22:00:00+08:00",
            "period_end": "2026-02-16T01:00:00+08:00",
            "sales": {"chicken-rice": 10},
        },
    )
    assert sales.status_code == 201, sales.text
    use_agent(client)
    claimed = client.post("/api/v1/runs/claim")
    assert claimed.status_code == 200, claimed.text
    return claimed.json()


def request_body(context: dict) -> dict:
    return {
        "request_id": "materiality-request-001",
        "captured_state_revision": context["captured_state_revision"],
        "as_of": context["as_of"],
        "known_at": context["known_at"],
        "issued_forecast_reference": "forecast:demo:v1",
        "issued_forecast": {
            "reference": "forecast:demo:v1",
            "as_of": context["as_of"],
            "known_at": context["known_at"],
            "target_date": "2026-02-16",
            "profile": [],
            "sources": [],
            "buckets": [],
            "promotion_state": "EXCLUDED",
            "base_reference": "forecast:base:v1",
        },
        "plan_reference": None,
        "safety_reference": "safety:demo:v1",
        "risk": None,
    }


def incomplete_result(context: dict) -> dict:
    return {
        "material_change": None,
        "complete": False,
        "feasible_under_observed_state": None,
        "inventory_feasible": None,
        "assessed_scope": [],
        "sales": [],
        "projection": None,
        "safety_breaches": [],
        "first_stockout_interval": None,
        "first_safety_breach_at": None,
        "first_risk_at": None,
        "affected_ids": [],
        "compared_intervals": [],
        "missing_intervals": [],
        "remainder": None,
        "daily_history": None,
        "findings": [{"code": "MISSING_EVIDENCE", "source": "sales"}],
        "material_findings": [],
        "evidence_refs": [
            context["snapshot_reference"],
            context["policy"]["evidence"]["reference"],
            context["forecast_input_reference"],
            "forecast:demo:v1",
        ],
        "required_follow_up": ["RESOLVE_INCOMPLETE_EVIDENCE"],
        "run_id": context["run_id"],
        "snapshot_reference": context["snapshot_reference"],
        "as_of": context["as_of"],
        "known_at": context["known_at"],
        "captured_state_revision": context["captured_state_revision"],
        "forecast_reference": "forecast:demo:v1",
        "forecast_input_reference": context["forecast_input_reference"],
        "threshold_policy_version": "SALES_MATERIALITY_V1",
        "coverage_through": "2026-02-16T21:00:00+08:00",
        "limitations": ["REFERENCES_REQUIRE_CALLER_PERSISTENCE"],
    }


def complete_safe_result(context: dict) -> dict:
    result = incomplete_result(context)
    result.update(
        {
            "material_change": True,
            "complete": True,
            "feasible_under_observed_state": True,
            "inventory_feasible": True,
            "assessed_scope": ["SALES_DEVIATION", "PHYSICAL_SHORTAGE", "SAFETY_STOCK"],
            "findings": [],
            "material_findings": [
                {"code": "SALES_THRESHOLD_REACHED", "source": "chicken-rice"}
            ],
            "required_follow_up": [],
        }
    )
    return result


def test_agent_round_trip_persists_exact_policy_request_result_and_gate(
    client: TestClient,
) -> None:
    run = claim_sales_run(client)
    run_id = run["id"]

    policy = client.get("/api/v1/sales-threshold-policies/SALES_MATERIALITY_V1")
    assert policy.status_code == 200, policy.text
    assert policy.json()["payload"] == {
        "version": "SALES_MATERIALITY_V1",
        "rule": "V2_DEMO_ABSOLUTE_OR_RELATIVE_V1",
        "absolute_floor": "5",
        "relative_threshold": "0.2",
        "minimum_expected_portions": "20",
        "minimum_complete_buckets": 2,
        "scope": "ONE_SINGAPORE_SERVICE_DAY_PER_DISH_CUMULATIVE_COMPLETE_HALF_HOURS",
    }

    context_response = client.get(f"/api/v1/runs/{run_id}/sales-materiality-context")
    assert context_response.status_code == 200, context_response.text
    context = context_response.json()
    assert context["supported"] is True
    assert context["captured_state_revision"] == str(run["input_revision"])
    assert context["policy"]["evidence"]["captured_revision"] == str(
        run["input_revision"]
    )

    body = request_body(context)
    created = client.post(
        f"/api/v1/runs/{run_id}/sales-materiality-requests", json=body
    )
    assert created.status_code == 201, created.text
    assessment = created.json()
    assert assessment["engine_request"]["threshold_policy"] == {
        **policy.json()["payload"],
        "evidence": context["policy"]["evidence"],
    }
    assert assessment["engine_request"]["contract"]["run_id"] == run_id
    assert len(assessment["engine_request"]["issued_catalogue"]["menu_items"]) == 5
    assert (
        assessment["engine_request"]["issued_input"]["id"]
        == context["forecast_input_reference"]
    )
    assert assessment["request_sha256"]
    assert (
        client.post(
            f"/api/v1/runs/{run_id}/sales-materiality-requests", json=body
        ).json()["request_sha256"]
        == assessment["request_sha256"]
    )

    result_write = {
        "request_reference": assessment["request_reference"],
        "result": incomplete_result(context),
    }
    saved = client.put(
        f"/api/v1/runs/{run_id}/sales-materiality-requests/{body['request_id']}/result",
        json=result_write,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["result_sha256"]
    manager_path = f"/api/v1/manager/runs/{run_id}/sales-materiality"
    assert client.get(manager_path).status_code == 403
    del client.headers["Authorization"]
    displayed = client.get(manager_path)
    assert displayed.status_code == 200
    assert displayed.json()["result"] == saved.json()["result"]
    assert "engine_request" not in displayed.json()
    assert displayed.json()["result"]["material_change"] is None
    use_agent(client)
    assert (
        client.put(
            f"/api/v1/runs/{run_id}/sales-materiality-requests/{body['request_id']}/result",
            json=result_write,
        ).json()["result_sha256"]
        == saved.json()["result_sha256"]
    )

    uncertified = client.post(
        f"/api/v1/runs/{run_id}/complete",
        json={"outcome": "KEEP_CURRENT_PLAN"},
    )
    assert uncertified.status_code == 409
    assert uncertified.json()["error"]["code"] == "UNCERTIFIED_OUTCOME"
    completed = client.post(
        f"/api/v1/runs/{run_id}/complete",
        json={
            "outcome": "ESCALATE",
            "escalation_reason": "CALCULATION_INCOMPLETE",
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "SUCCEEDED"
    assert (
        client.post(
            f"/api/v1/runs/{run_id}/sales-materiality-requests", json=body
        ).json()["request_sha256"]
        == assessment["request_sha256"]
    )
    assert (
        client.put(
            f"/api/v1/runs/{run_id}/sales-materiality-requests/{body['request_id']}/result",
            json=result_write,
        ).json()["result_sha256"]
        == saved.json()["result_sha256"]
    )


def test_manager_cannot_write_agent_materiality_contract(client: TestClient) -> None:
    run = claim_sales_run(client)
    run_id = run["id"]
    context = client.get(f"/api/v1/runs/{run_id}/sales-materiality-context").json()
    del client.headers["Authorization"]
    response = client.post(
        f"/api/v1/runs/{run_id}/sales-materiality-requests",
        json=request_body(context),
    )
    assert response.status_code == 403


def test_safe_material_sales_result_certifies_keep_current_plan(
    client: TestClient,
) -> None:
    run = claim_sales_run(client)
    run_id = run["id"]
    context = client.get(f"/api/v1/runs/{run_id}/sales-materiality-context").json()
    body = request_body(context)
    assessment = client.post(
        f"/api/v1/runs/{run_id}/sales-materiality-requests", json=body
    ).json()

    saved = client.put(
        f"/api/v1/runs/{run_id}/sales-materiality-requests/{body['request_id']}/result",
        json={
            "request_reference": assessment["request_reference"],
            "result": complete_safe_result(context),
        },
    )
    assert saved.status_code == 200, saved.text

    completed = client.post(
        f"/api/v1/runs/{run_id}/complete",
        json={"outcome": "KEEP_CURRENT_PLAN"},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "SUCCEEDED"
