import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from test_daily import sign_in


def test_purchase_rolls_back_when_audit_storage_fails(
    client: TestClient, reject_audit_write: None
) -> None:
    sign_in(client)
    body = {
        "supplier_id": client.get("/api/v1/suppliers").json()[0]["id"],
        "ingredient_id": "chicken",
        "kind": "NORMAL",
        "expected_quantity": "10",
        "ordered_at": "2026-02-16T08:00:00+08:00",
        "expected_at": "2026-02-16T10:00:00+08:00",
    }
    with pytest.raises(IntegrityError):
        client.post("/api/v1/deliveries", json=body)
    assert client.get("/api/v1/deliveries").json() == []
    assert client.get("/api/v1/events").json() == []
    assert len(client.get("/api/v1/inventory").json()) == 9


def test_delivery_changes_cancellation_and_permissions(client: TestClient) -> None:
    sign_in(client)
    body = {
        "supplier_id": client.get("/api/v1/suppliers").json()[0]["id"],
        "ingredient_id": "chicken",
        "kind": "NORMAL",
        "expected_quantity": "10",
        "ordered_at": "2026-02-16T08:00:00+08:00",
        "expected_at": "2026-02-16T10:00:00+08:00",
    }
    assert (
        client.post(
            "/api/v1/deliveries", json={**body, "supplier_id": "unknown"}
        ).status_code
        == 422
    )
    result = client.post("/api/v1/deliveries", json=body)
    path = "/api/v1/deliveries/" + result.json()["id"]
    change = {
        "expected_quantity": "8",
        "expected_at": "2026-02-17T10:00:00+08:00",
        "effective_at": "2026-02-16T09:00:00+08:00",
    }
    result = client.post(path + "/update", json=change)
    assert result.status_code == 200
    assert result.json()["outstanding_quantity"] == "8.000"
    assert client.get("/api/v1/events").json()[-1]["type"] == "DELIVERY_SHORT"
    result = client.post(path + "/update", json={**change, "cancel_remainder": True})
    assert result.json()["cancelled_quantity"] == "8.000"
    assert result.json()["outstanding_quantity"] == "0.000"
    assert client.post(path + "/update", json=change).status_code == 409
    client.headers["Authorization"] = "Bearer test-agent-token"
    assert client.get(path).status_code == 200
    assert client.post("/api/v1/deliveries", json=body).status_code == 403
    assert client.post(path + "/update", json=change).status_code == 403
    receipt = {
        "request_id": "denied",
        "quantity": "1",
        "received_at": body["expected_at"],
        "expiry_date": "2026-02-20",
        "remainder": "EXPECTED",
    }
    assert client.post(path + "/receive", json=receipt).status_code == 403
    del client.headers["Authorization"]
    del client.headers["Origin"]
    assert client.post("/api/v1/deliveries", json=body).status_code == 403


def test_partial_receipts_retry_and_closing_reconciliation(client: TestClient) -> None:
    sign_in(client)
    supplier = client.get("/api/v1/suppliers").json()[0]["id"]
    body = {
        "supplier_id": supplier,
        "ingredient_id": "chicken",
        "kind": "EMERGENCY",
        "expected_quantity": "10",
        "expected_at": "2026-02-16T10:00:00+08:00",
        "ordered_at": "2026-02-16T08:00:00+08:00",
    }
    result = client.post("/api/v1/deliveries", json=body)
    assert result.status_code == 201, result.text
    path = "/api/v1/deliveries/" + result.json()["id"]
    assert len(client.get("/api/v1/inventory").json()) == 9
    receipt = {
        "request_id": "first-receipt",
        "quantity": "4",
        "received_at": "2026-02-16T10:00:00+08:00",
        "expiry_date": "2026-02-19",
        "remainder": "EXPECTED",
    }
    received = client.post(path + "/receive", json=receipt)
    assert received.status_code == 200, received.text
    assert received.json()["outstanding_quantity"] == "6.000"
    assert client.post(path + "/receive", json=receipt).json() == received.json()
    assert (
        client.post(path + "/receive", json={**receipt, "quantity": "5"}).status_code
        == 409
    )
    second = {
        **receipt,
        "request_id": "second-receipt",
        "quantity": "2",
        "expiry_date": "2026-02-20",
        "remainder": "CANCELLED",
    }
    result = client.post(path + "/receive", json=second)
    assert result.status_code == 200
    assert result.json()["received_quantity"] == "6.000"
    assert result.json()["cancelled_quantity"] == "4.000"
    assert result.json()["outstanding_quantity"] == "0.000"
    assert len(result.json()["receipts"]) == 2
    inventory = client.get("/api/v1/inventory").json()
    assert len(inventory) == 11
    day = "/api/v1/daily-updates/2026-02-16"
    draft = {
        "cutoff": "2026-02-16T22:00:00+08:00",
        "counts": {lot["id"]: "1" for lot in inventory},
        "sales": {dish["id"]: 0 for dish in client.get("/api/v1/menu-items").json()},
    }
    client.post(day + "/draft", json=draft)
    assert client.post(day + "/submit").status_code == 200
    assert all(
        lot["quantity"] == "1.000" for lot in client.get("/api/v1/inventory").json()
    )
    assert client.get(path).json()["received_quantity"] == "6.000"
    assert client.post(path + "/receive", json=receipt).status_code == 200
    assert len(client.get("/api/v1/inventory").json()) == 11
    assert [e["type"] for e in client.get("/api/v1/events").json()] == [
        "EXTERNAL_ORDER_RECORDED",
        "DELIVERY_RECEIVED",
        "DELIVERY_RECEIVED",
        "DELIVERY_CANCELLED",
        "DAILY_UPDATE_SUBMITTED",
    ]
