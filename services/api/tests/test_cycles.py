import pytest
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


def test_cycle_decision_keeps_anchor_and_does_not_create_supply(
    client: TestClient,
) -> None:
    sign_in(client)
    url = "/api/v1/order-cycles/rice/2026-02-15/decision"
    response = client.post(url, json={"status": "SKIPPED", "note": "Enough stock"})
    assert response.status_code == 200, response.text
    assert response.json()["actor"] == "manager"
    assert (
        client.post(url, json={"status": "SKIPPED", "note": "Enough stock"}).json()
        == response.json()
    )
    assert client.post(url, json={"status": "ORDERED"}).status_code == 409
    result = client.get(
        "/api/v1/order-cycles", params={"start": "2026-02-15", "end": "2026-03-15"}
    )
    assert result.status_code == 200, result.text
    rice = [row for row in result.json() if row["ingredient_id"] == "rice"]
    assert [(row["scheduled_date"], row["status"]) for row in rice] == [
        ("2026-02-15", "SKIPPED"),
        ("2026-03-01", "OPEN"),
        ("2026-03-15", "OPEN"),
    ]
    assert client.get("/api/v1/deliveries").json() == []
    events = client.get("/api/v1/events")
    assert events.status_code == 200, events.text
    assert (
        len(
            [event for event in events.json() if event["type"] == "ORDER_CYCLE_UPDATED"]
        )
        == 1
    )
    client.headers["Authorization"] = "Bearer test-agent-token"
    assert (
        client.post(
            "/api/v1/order-cycles/rice/2026-03-01/decision", json={"status": "ORDERED"}
        ).status_code
        == 403
    )


@pytest.mark.parametrize("day", ["2026-02-14", "2026-02-16"])
def test_cycle_rejects_dates_off_the_anchor(client: TestClient, day: str) -> None:
    sign_in(client)
    response = client.post(
        f"/api/v1/order-cycles/rice/{day}/decision", json={"status": "ORDERED"}
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "NOT_AN_ORDERING_DATE"


@pytest.mark.usefixtures("reject_audit_write")
def test_cycle_decision_and_audit_are_atomic(client: TestClient) -> None:
    sign_in(client)
    response = client.post(
        "/api/v1/order-cycles/rice/2026-02-15/decision", json={"status": "ORDERED"}
    )
    assert response.status_code == 500, response.text
    result = client.get(
        "/api/v1/order-cycles", params={"start": "2026-02-15", "end": "2026-02-15"}
    )
    assert all(row["status"] == "OPEN" for row in result.json())
