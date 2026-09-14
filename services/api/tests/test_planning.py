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
    decision_url = f"/api/v1/plans/{version.json()['id']}/decision"
    decision = {
        "decision": "APPROVED",
        "plan_id": version.json()["plan_id"],
        "plan_version": version.json()["version"],
    }
    assert client.post(decision_url, json=decision).status_code == 403
    del client.headers["Authorization"]
    assert (
        client.post(decision_url, json={**decision, "plan_version": 999}).status_code
        == 409
    )
    approved = client.post(decision_url, json=decision)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED"
    assert client.post(decision_url, json=decision).status_code == 200
    assert (
        client.post(decision_url, json={**decision, "decision": "REJECTED"}).status_code
        == 409
    )
    events = client.get("/api/v1/events")
    assert events.status_code == 200, events.text
    assert (
        len([event for event in events.json() if event["type"] == "PLAN_APPROVED"]) == 1
    )
    lines = client.get(f"/api/v1/plans/{version.json()['id']}/lines")
    assert lines.status_code == 200, lines.text
    source = lines.json()[0]
    purchase = client.post(
        "/api/v1/deliveries",
        json={
            "supplier_id": source["supplier_id"],
            "ingredient_id": source["ingredient_id"],
            "kind": "NORMAL",
            "expected_quantity": "2.000",
            "expected_at": source["arrival_at"],
            "ordered_at": "2026-02-15T22:00:00+08:00",
            "source_plan_line_id": source["id"],
            "cycle_date": "2026-02-15",
        },
    )
    assert purchase.status_code == 201, purchase.text
    assert purchase.json()["source_plan_line_id"] == source["id"]
    assert purchase.json()["outstanding_quantity"] == "2.000"
    assert (
        client.get(f"/api/v1/plans/{version.json()['id']}/lines").json() == lines.json()
    )
    cycles = client.get(
        "/api/v1/order-cycles", params={"start": "2026-02-15", "end": "2026-02-15"}
    )
    assert all(row["status"] == "OPEN" for row in cycles.json())


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
    from datetime import datetime

    assert datetime.fromisoformat(second.json()["as_of"]) == datetime.fromisoformat(
        "2026-02-16T09:00:00+08:00"
    )


def test_completed_escalation_is_persisted_and_retry_cannot_change_it(
    client: TestClient,
) -> None:
    sign_in(client)
    client.post("/api/v1/assessments", json={"as_of": "2026-02-15T22:00:00+08:00"})
    client.headers["Authorization"] = "Bearer test-agent-token"
    run = client.post("/api/v1/runs/claim").json()
    url = f"/api/v1/runs/{run['id']}/complete"
    result = {"outcome": "ESCALATE", "escalation_reason": "NO_FEASIBLE_SUPPLIER"}
    completed = client.post(url, json=result)
    assert completed.status_code == 200, completed.text
    assert (
        completed.json()["snapshot"]["completion"]["escalation_reason"]
        == "NO_FEASIBLE_SUPPLIER"
    )
    assert client.post(url, json=result).status_code == 200
    assert client.post(url, json={"outcome": "KEEP_CURRENT_PLAN"}).status_code == 409


def test_newer_request_waits_for_active_attempt_and_replaces_stale_work(
    client: TestClient,
) -> None:
    sign_in(client)
    client.post("/api/v1/assessments", json={"as_of": "2026-02-15T22:00:00+08:00"})
    client.headers["Authorization"] = "Bearer test-agent-token"
    running = client.post("/api/v1/runs/claim").json()
    del client.headers["Authorization"]
    pending = client.post(
        "/api/v1/assessments", json={"as_of": "2026-02-16T08:00:00+08:00"}
    )
    assert pending.status_code == 202, pending.text
    assert pending.json()["id"] != running["id"]
    assert (
        client.post(
            "/api/v1/assessments", json={"as_of": "2026-02-16T09:00:00+08:00"}
        ).json()["id"]
        == pending.json()["id"]
    )
    client.headers["Authorization"] = "Bearer test-agent-token"
    assert client.post("/api/v1/runs/claim").status_code == 409
    completion = client.post(
        f"/api/v1/runs/{running['id']}/complete",
        json={"outcome": "ESCALATE", "escalation_reason": "MISSING_REQUIRED_DATA"},
    )
    assert completion.status_code == 409, completion.text
    assert completion.json()["error"]["code"] == "STATE_REVISION_STALE"
    claimed = client.post("/api/v1/runs/claim")
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["id"] == pending.json()["id"]


def test_expired_run_does_not_block_a_new_assessment(
    client: TestClient, database_url: str
) -> None:
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import create_engine, update

    from src import database as db

    sign_in(client)
    client.post("/api/v1/assessments", json={"as_of": "2026-02-15T22:00:00+08:00"})
    client.headers["Authorization"] = "Bearer test-agent-token"
    run = client.post("/api/v1/runs/claim").json()
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            update(db.planning_runs)
            .where(db.planning_runs.c.id == run["id"])
            .values(deadline_at=datetime.now(UTC) - timedelta(minutes=1))
        )
    engine.dispose()
    del client.headers["Authorization"]
    requested = client.post(
        "/api/v1/assessments", json={"as_of": "2026-02-16T22:00:00+08:00"}
    )
    assert requested.status_code == 202, requested.text
    assert requested.json()["id"] != run["id"]
    assert client.get(f"/api/v1/runs/{run['id']}").json()["status"] == "FAILED"


def test_revisions_keep_identity_but_new_normal_plans_get_a_new_identity(
    client: TestClient,
) -> None:
    sign_in(client)

    def publish(revises_plan_id: str | None = None) -> dict:
        client.headers.pop("Authorization", None)
        requested = client.post(
            "/api/v1/assessments",
            json={
                "as_of": "2026-02-15T22:00:00+08:00",
                "revises_plan_id": revises_plan_id,
            },
        )
        assert requested.status_code == 202, requested.text
        client.headers["Authorization"] = "Bearer test-agent-token"
        run = client.post("/api/v1/runs/claim").json()
        candidate = client.post(
            f"/api/v1/runs/{run['id']}/tools/optimise",
            json={"dish_quantities": {"chicken-rice": 200}},
        )
        assert candidate.status_code == 200, candidate.text
        completed = client.post(
            f"/api/v1/runs/{run['id']}/complete",
            json={"outcome": "REVISE_PLAN", "candidate": candidate.json()},
        )
        assert completed.status_code == 200, completed.text
        return client.get(f"/api/v1/plans/{completed.json()['plan_version_id']}").json()

    first = publish()
    second = publish(first["plan_id"])
    assert first["plan_id"] == second["plan_id"]
    assert (first["version"], second["version"]) == (1, 2)
    assert client.get(f"/api/v1/plans/{first['id']}").json()["status"] == "SUPERSEDED"
    third = publish()
    assert third["plan_id"] != first["plan_id"]
    assert third["version"] == 1


def test_missing_engine_is_explicit_and_does_not_publish_a_fake_plan(
    client: TestClient,
) -> None:
    from typing import cast

    from fastapi import FastAPI

    cast(FastAPI, client.app).state.settings.enable_development_calculator = False
    sign_in(client)
    client.post("/api/v1/assessments", json={"as_of": "2026-02-15T22:00:00+08:00"})
    client.headers["Authorization"] = "Bearer test-agent-token"
    run = client.post("/api/v1/runs/claim").json()
    result = client.post(
        f"/api/v1/runs/{run['id']}/tools/optimise",
        json={"dish_quantities": {"chicken-rice": 200}},
    )
    assert result.status_code == 503, result.text
    assert result.json()["error"]["code"] == "DECISION_ENGINE_NOT_CONNECTED"
    assert client.get("/api/v1/plan-history").json() == []


def test_no_purchase_outcome_requires_a_calculated_empty_result(
    client: TestClient,
) -> None:
    sign_in(client)
    client.post("/api/v1/assessments", json={"as_of": "2026-02-15T22:00:00+08:00"})
    client.headers["Authorization"] = "Bearer test-agent-token"
    run = client.post("/api/v1/runs/claim").json()
    url = f"/api/v1/runs/{run['id']}/complete"
    assert client.post(url, json={"outcome": "KEEP_CURRENT_PLAN"}).status_code == 409
    calculated = client.post(
        f"/api/v1/runs/{run['id']}/tools/optimise",
        json={"dish_quantities": {"chicken-rice": 1}},
    )
    assert calculated.status_code == 200, calculated.text
    assert calculated.json()["lines"] == []
    completed = client.post(url, json={"outcome": "KEEP_CURRENT_PLAN"})
    assert completed.status_code == 200, completed.text
    assert completed.json()["plan_version_id"] is None


def test_concurrent_requests_and_completions_do_not_duplicate_work(
    client: TestClient,
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    sign_in(client)

    def request():
        return client.post(
            "/api/v1/assessments", json={"as_of": "2026-02-15T22:00:00+08:00"}
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: request(), range(2)))
    assert all(response.status_code == 202 for response in responses)
    assert responses[0].json()["id"] == responses[1].json()["id"]
    client.headers["Authorization"] = "Bearer test-agent-token"
    run = client.post("/api/v1/runs/claim").json()
    candidate = client.post(
        f"/api/v1/runs/{run['id']}/tools/optimise",
        json={"dish_quantities": {"chicken-rice": 200}},
    )
    assert candidate.status_code == 200, candidate.text
    assert candidate.json()["calculation_mode"] == "DEVELOPMENT_FIXTURE"

    def complete():
        return client.post(
            f"/api/v1/runs/{run['id']}/complete",
            json={"outcome": "REVISE_PLAN", "candidate": candidate.json()},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        completions = list(pool.map(lambda _: complete(), range(2)))
    assert all(response.status_code == 200 for response in completions)
    assert (
        completions[0].json()["plan_version_id"]
        == completions[1].json()["plan_version_id"]
    )
    assert len(client.get("/api/v1/plan-history").json()) == 1


def test_exact_pending_version_cannot_be_approved_after_state_changes(
    client: TestClient,
) -> None:
    sign_in(client)
    client.post("/api/v1/assessments", json={"as_of": "2026-02-15T22:00:00+08:00"})
    client.headers["Authorization"] = "Bearer test-agent-token"
    run = client.post("/api/v1/runs/claim").json()
    candidate = client.post(
        f"/api/v1/runs/{run['id']}/tools/optimise",
        json={"dish_quantities": {"chicken-rice": 200}},
    ).json()
    completed = client.post(
        f"/api/v1/runs/{run['id']}/complete",
        json={"outcome": "REVISE_PLAN", "candidate": candidate},
    )
    plan = client.get(f"/api/v1/plans/{completed.json()['plan_version_id']}").json()

    client.headers.pop("Authorization", None)
    sign_in(client)
    changed = client.post(
        "/api/v1/assessments", json={"as_of": "2026-02-16T08:00:00+08:00"}
    )
    assert changed.status_code == 202, changed.text
    rejected = client.post(
        f"/api/v1/plans/{plan['id']}/decision",
        json={
            "plan_id": plan["plan_id"],
            "plan_version": plan["version"],
            "decision": "APPROVED",
        },
    )

    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["error"]["code"] == "PLAN_VERSION_STALE"
    assert client.get(f"/api/v1/plans/{plan['id']}").json()["status"] == "PENDING_APPROVAL"
