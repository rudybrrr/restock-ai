from fastapi.testclient import TestClient


def sign_in(client: TestClient) -> None:
    client.headers["Origin"] = "https://frontend.example"
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "manager", "password": "test-manager-password"},
        ).status_code
        == 200
    )


def test_agent_claims_a_frozen_run_and_publishes_a_calculated_plan(
    client: TestClient,
) -> None:
    sign_in(client)
    requested = client.post(
        "/api/v1/assessments", json={"as_of": "2026-02-15T22:00:00+08:00"}
    )
    assert requested.status_code == 202, requested.text
    run = requested.json()
    assert run["status"] == "QUEUED"
    client.headers["Authorization"] = "Bearer test-agent-token"
    claimed = client.post("/api/v1/runs/claim")
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["id"] == run["id"]
    run = claimed.json()
    candidate = client.post(
        f"/api/v1/runs/{run['id']}/tools/optimise",
        json={"dish_quantities": {"chicken-rice": 200}},
    )
    assert candidate.status_code == 200, candidate.text
    proposal = candidate.json()
    assert proposal["lines"]
    completed = client.post(
        f"/api/v1/runs/{run['id']}/complete",
        json={"outcome": "REVISE_PLAN", "candidate": proposal},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "SUCCEEDED"
    version = client.get(f"/api/v1/plans/{completed.json()['plan_version_id']}")
    assert version.status_code == 200, version.text
    assert version.json()["status"] == "PENDING_APPROVAL"
    assert version.json()["forecast_id"] == run["snapshot"]["forecast_id"]


def test_assessment_requests_coalesce_until_the_agent_completes(
    client: TestClient,
) -> None:
    sign_in(client)
    first = client.post(
        "/api/v1/assessments", json={"as_of": "2026-02-16T08:00:00+08:00"}
    )
    second = client.post(
        "/api/v1/assessments", json={"as_of": "2026-02-16T09:00:00+08:00"}
    )
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
