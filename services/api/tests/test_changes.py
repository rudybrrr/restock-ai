import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text


def sign_in(client: TestClient) -> None:
    client.headers["Origin"] = "https://frontend.example"
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "manager", "password": "test-manager-password"},
        ).status_code
        == 200
    )


def promotion() -> dict:
    return {
        "revision": 1,
        "name": "CNY special",
        "start_date": "2026-02-17",
        "end_date": "2026-02-18",
        "menu_item_ids": ["chicken-rice"],
        "demand_multiplier": "1.5",
        "effective_at": "2026-02-16T08:00:00+08:00",
    }


def test_promotion_and_supplier_events_coalesce_and_freeze_inputs(
    client: TestClient,
) -> None:
    sign_in(client)
    for method, path in [
        ("PUT", "/api/v1/promotions/cny"),
        ("PATCH", "/api/v1/supplier-offers/fresh-chicken"),
    ]:
        preflight = client.options(
            path,
            headers={
                "Origin": "https://frontend.example",
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        assert preflight.status_code == 200, preflight.text
    response = client.put("/api/v1/promotions/cny", json=promotion())
    assert response.status_code == 200, response.text
    assert client.put("/api/v1/promotions/cny", json=promotion()).status_code == 200
    assert (
        client.put(
            "/api/v1/promotions/cny", json={**promotion(), "name": "conflicting retry"}
        ).status_code
        == 409
    )
    supplier = client.patch(
        "/api/v1/supplier-offers/fresh-chicken",
        json={
            "available_quantity": "2",
            "unit_price": "5.50",
            "effective_at": "2026-02-16T09:00:00+08:00",
        },
    )
    assert supplier.status_code == 200, supplier.text
    events = client.get("/api/v1/events")
    assert events.status_code == 200, events.text
    assert {event["type"] for event in events.json()} == {
        "PROMOTION_CREATED",
        "SUPPLIER_AVAILABILITY_CHANGED",
        "SUPPLIER_PRICE_CHANGED",
    }
    client.headers["Authorization"] = "Bearer test-agent-token"
    claimed = client.post("/api/v1/runs/claim")
    assert claimed.status_code == 200, claimed.text
    run = claimed.json()
    assert run["trigger"] == "PROMOTION_CREATED"
    assert run["trigger_event_id"] in {event["id"] for event in events.json()}
    promotion_event = run["snapshot"]["promotions"][0]
    assert promotion_event["type"] == "PROMOTION_CREATED"
    assert promotion_event["payload"]["name"] == "CNY special"
    assert promotion_event["id"] in run["snapshot"]["trigger_event_ids"]
    assert len(client.get(f"/api/v1/runs/{run['id']}/triggers").json()) == 3
    assert (
        client.patch(
            "/api/v1/supplier-offers/fresh-chicken",
            json={
                "available_quantity": "3",
                "effective_at": "2026-02-16T10:00:00+08:00",
            },
        ).status_code
        == 403
    )
    assert client.put("/api/v1/promotions/other", json=promotion()).status_code == 403


@pytest.mark.usefixtures("reject_audit_write")
def test_promotion_audit_failure_rolls_back_fact_and_queue(client: TestClient) -> None:
    sign_in(client)
    assert client.put("/api/v1/promotions/cny", json=promotion()).status_code == 500
    assert client.get("/api/v1/promotions").json() == []
    client.headers["Authorization"] = "Bearer test-agent-token"
    assert client.post("/api/v1/runs/claim").json()["error"]["code"] == "NO_QUEUED_RUN"


def test_assessment_write_failure_rolls_back_promotion_and_event(
    client: TestClient, database_url: str
) -> None:
    sign_in(client)
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE assessment_requests ADD CONSTRAINT unavailable CHECK (false) NOT VALID"
            )
        )
    engine.dispose()
    assert client.put("/api/v1/promotions/cny", json=promotion()).status_code == 500
    assert client.get("/api/v1/promotions").json() == []
    assert client.get("/api/v1/events").json() == []


def test_supplier_unknown_and_unchanged_values_are_preserved(
    client: TestClient,
) -> None:
    sign_in(client)
    body = {"unit_price": None, "effective_at": "2026-02-16T09:00:00+08:00"}
    result = client.patch("/api/v1/supplier-offers/fresh-chicken", json=body)
    assert result.status_code == 200, result.text
    assert result.json()["unit_price"] is None
    assert (
        client.patch("/api/v1/supplier-offers/fresh-chicken", json=body).status_code
        == 200
    )
    assert len(client.get("/api/v1/events").json()) == 1
    assert (
        client.patch(
            "/api/v1/supplier-offers/fresh-chicken",
            json={**body, "effective_at": "2026-02-16T08:00:00+08:00"},
        ).status_code
        == 409
    )
    assert (
        client.patch(
            "/api/v1/supplier-offers/fresh-chicken",
            json={**body, "available_quantity": -1},
        ).status_code
        == 422
    )
