from fastapi.testclient import TestClient


def test_submission_rolls_back_when_audit_storage_fails(
    client: TestClient, reject_audit_write: None
) -> None:
    sign_in(client)
    before = client.get("/api/v1/inventory").json()
    path = "/api/v1/daily-updates/2026-02-16"
    body = {
        "cutoff": "2026-02-16T22:00:00+08:00",
        "counts": {lot["id"]: "3" for lot in before},
        "sales": {dish["id"]: 0 for dish in client.get("/api/v1/menu-items").json()},
    }
    client.post(path + "/draft", json=body)
    assert client.post(path + "/submit").status_code == 500
    assert client.get("/api/v1/inventory").json() == before
    assert client.get(path).json()["revisions"] == []
    assert client.get(path).json()["draft"] == body
    assert client.get("/api/v1/events").json() == []


def test_invalid_daily_data_leaves_baseline_and_history_unchanged(
    client: TestClient,
) -> None:
    sign_in(client)
    path = "/api/v1/daily-updates/2026-02-16"
    before = client.get("/api/v1/inventory").json()
    draft = {
        "cutoff": "2026-02-16T22:00:00+08:00",
        "counts": {lot["id"]: "2" for lot in before},
        "sales": {dish["id"]: 0 for dish in client.get("/api/v1/menu-items").json()},
    }
    draft["counts"]["unknown"] = "1"
    assert client.post(path + "/draft", json=draft).status_code == 200
    assert client.post(path + "/submit").status_code == 422
    assert client.get("/api/v1/inventory").json() == before
    assert client.get("/api/v1/events").json() == []
    assert client.get("/api/v1/audit").json() == []
    assert client.get(path).json()["revisions"] == []
    assert (
        client.post(
            path + "/draft", json={**draft, "cutoff": "2026-02-17T22:00:00+08:00"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            path + "/draft", json={**draft, "counts": {"chicken-01": "-1"}}
        ).status_code
        == 422
    )
    assert client.get(path).json()["draft"]["counts"]["unknown"] == "1"
    client.headers["Authorization"] = "Bearer test-agent-token"
    assert client.post(path + "/draft", json=draft).status_code == 403
    assert client.post(path + "/submit").status_code == 403


def sign_in(client: TestClient) -> None:
    client.headers["Origin"] = "https://frontend.example"
    assert (
        client.post(
            "/api/v1/auth/login",
            json={
                "username": "manager",
                "password": "test-manager-password",
            },
        ).status_code
        == 200
    )


def test_closing_submission_preserves_draft_and_records_zero(
    client: TestClient,
) -> None:
    sign_in(client)
    day = "/api/v1/daily-updates/2026-02-16"
    draft = {"cutoff": "2026-02-16T22:00:00+08:00", "counts": {}, "sales": {}}
    assert client.post(day + "/draft", json=draft).status_code == 200
    assert client.post(day + "/submit").status_code == 422
    assert client.get(day).json()["draft"]["counts"] == {}
    assert client.get(day).json()["revisions"] == []
    lots = client.get("/api/v1/inventory").json()
    dishes = client.get("/api/v1/menu-items").json()
    draft["counts"] = {lot["id"]: "0" for lot in lots}
    draft["sales"] = {dish["id"]: 0 for dish in dishes}
    draft["counts"][lots[0]["id"]] = "7.5"
    draft["sales"][dishes[0]["id"]] = 100
    assert client.post(day + "/draft", json=draft).status_code == 200
    result = client.post(day + "/submit")
    assert result.status_code == 200, result.text
    assert result.json()["revision"] == 1
    inventory = client.get("/api/v1/inventory").json()
    assert inventory[0]["quantity"] == "7.500"
    assert inventory[0]["provenance"] == "PHYSICAL"
    assert inventory[1]["quantity"] == "0.000"
    draft["counts"][lots[0]["id"]] = "8"
    client.post(day + "/draft", json=draft)
    assert client.post(day + "/submit").json()["revision"] == 2
    history = client.get(day).json()["revisions"]
    assert [r["counts"][lots[0]["id"]] for r in history] == ["7.5", "8"]
    assert client.get("/api/v1/inventory").json()[0]["quantity"] == "8.000"
    events = client.get("/api/v1/events").json()
    assert [e["type"] for e in events] == [
        "DAILY_UPDATE_SUBMITTED",
        "DAILY_UPDATE_CORRECTED",
    ]
    assert events[0]["payload"]["replaces_revision_id"] is None
    assert events[1]["payload"]["replaces_revision_id"] == history[0]["id"]
    queued = client.post("/api/v1/assessments", json={"as_of": draft["cutoff"]})
    triggers = client.get(f"/api/v1/runs/{queued.json()['id']}/triggers").json()
    assert len(triggers) == 2
    assert len(client.get("/api/v1/audit").json()) == 2
