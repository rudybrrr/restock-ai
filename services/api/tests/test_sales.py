from datetime import date, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, update

from src import database as db


def sign_in(client: TestClient) -> None:
    client.headers["Origin"] = "https://frontend.example"
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"username": "manager", "password": "test-manager-password"},
        ).status_code
        == 200
    )


def test_sales_batch_updates_an_estimate_without_mutating_physical_counts(
    client: TestClient,
) -> None:
    sign_in(client)
    body = {
        "source": "simulator",
        "batch_id": "morning-001",
        "period_start": "2026-02-15T22:00:00+08:00",
        "period_end": "2026-02-16T01:00:00+08:00",
        "sales": {"chicken-rice": 10},
    }
    accepted = client.post("/api/v1/sales-batches", json=body)
    assert accepted.status_code == 201, accepted.text
    assert (
        client.post("/api/v1/sales-batches", json=body).json()["id"]
        == accepted.json()["id"]
    )
    estimate = client.get(
        "/api/v1/inventory/estimated", params={"as_of": body["period_end"]}
    )
    assert estimate.status_code == 200, estimate.text
    chicken = {
        lot["id"]: lot for lot in estimate.json() if lot["ingredient_id"] == "chicken"
    }
    assert chicken["chicken-01"]["quantity"] == "10.500"
    assert chicken["chicken-02"]["quantity"] == "5.000"
    assert chicken["chicken-01"]["provenance"] == "ESTIMATED"
    assert chicken["chicken-01"]["coverage_complete"] is True
    physical = {lot["id"]: lot for lot in client.get("/api/v1/inventory").json()}
    assert physical["chicken-01"]["quantity"] == "12.000"
    events = client.get("/api/v1/events").json()
    assert len(events) == 1
    assert events[0]["type"] == "SALES_UPDATED"
    assert events[0]["payload"]["effective_at"] == body["period_end"]
    client.headers["Authorization"] = "Bearer test-agent-token"
    run = client.post("/api/v1/runs/claim")
    assert run.status_code == 200, run.text
    snapshot = run.json()["snapshot"]
    assert run.json()["trigger"] == "SALES_UPDATED"
    assert snapshot["sales_batches"][0]["id"] == accepted.json()["id"]
    semantics = snapshot["procurement_contract"]["activity_semantics"]
    assert semantics["baseline_history_mode"] == ("VERSIONED_FORECAST_INPUT_IMMUTABLE")
    assert semantics["intraday_sales_mode"] == (
        "INVENTORY_ESTIMATE_AND_REASSESSMENT_ONLY"
    )
    assert semantics["closing_sales_mode"] == ("LATEST_DAILY_REVISION_AUTHORITATIVE")


def test_equal_expiry_lots_use_receipt_time_before_lot_id(
    client: TestClient, database_url: str
) -> None:
    """Historical replay follows FEFO_EXPIRY_RECEIVED_LOT_ID_V1."""
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                update(db.inventory_lots)
                .where(db.inventory_lots.c.id == "chicken-01")
                .values(
                    received_at=datetime.fromisoformat("2026-02-15T12:00:00+08:00"),
                    expiry_date=date(2026, 2, 20),
                )
            )
            connection.execute(
                update(db.inventory_lots)
                .where(db.inventory_lots.c.id == "chicken-02")
                .values(
                    received_at=datetime.fromisoformat("2026-02-15T08:00:00+08:00"),
                    expiry_date=date(2026, 2, 20),
                )
            )
    finally:
        engine.dispose()

    sign_in(client)
    response = client.post(
        "/api/v1/sales-batches",
        json={
            "source": "simulator",
            "batch_id": "equal-expiry-receipt-order",
            "period_start": "2026-02-15T22:00:00+08:00",
            "period_end": "2026-02-16T01:00:00+08:00",
            "sales": {"chicken-rice": 10},
        },
    )
    assert response.status_code == 201, response.text

    estimate = client.get(
        "/api/v1/inventory/estimated",
        params={"as_of": "2026-02-16T01:00:00+08:00"},
    )
    assert estimate.status_code == 200, estimate.text
    chicken = {
        lot["id"]: lot for lot in estimate.json() if lot["ingredient_id"] == "chicken"
    }
    assert chicken["chicken-02"]["quantity"] == "3.500"
    assert chicken["chicken-01"]["quantity"] == "12.000"


def test_sales_correction_replaces_an_interval_and_overlaps_are_rejected(
    client: TestClient,
) -> None:
    sign_in(client)
    first = {
        "source": "simulator",
        "batch_id": "one",
        "period_start": "2026-02-15T22:00:00+08:00",
        "period_end": "2026-02-16T01:00:00+08:00",
        "sales": {"chicken-rice": 10},
    }
    original = client.post("/api/v1/sales-batches", json=first).json()
    overlapping = {
        **first,
        "batch_id": "overlap",
        "period_start": "2026-02-16T00:00:00+08:00",
    }
    assert client.post("/api/v1/sales-batches", json=overlapping).status_code == 409
    correction = {
        **first,
        "sales": {"chicken-rice": 4},
        "replaces_id": original["id"],
    }
    corrected = client.post("/api/v1/sales-batches", json=correction)
    assert corrected.status_code == 201
    assert (
        client.post("/api/v1/sales-batches", json=correction).json()["id"]
        == corrected.json()["id"]
    )
    estimate = client.get(
        "/api/v1/inventory/estimated", params={"as_of": first["period_end"]}
    ).json()
    chicken = next(lot for lot in estimate if lot["id"] == "chicken-01")
    assert chicken["quantity"] == "11.400"


def test_estimate_marks_a_gap_in_sales_coverage_incomplete(client: TestClient) -> None:
    sign_in(client)
    assert (
        client.post(
            "/api/v1/sales-batches",
            json={
                "source": "simulator",
                "batch_id": "after-gap",
                "period_start": "2026-02-16T02:00:00+08:00",
                "period_end": "2026-02-16T03:00:00+08:00",
                "sales": {},
            },
        ).status_code
        == 201
    )
    response = client.get(
        "/api/v1/inventory/estimated",
        params={"as_of": "2026-02-16T03:00:00+08:00"},
    )
    assert response.status_code == 200
    assert response.json()[0]["coverage_complete"] is False


def test_receipt_does_not_restore_pre_receipt_consumption(client: TestClient) -> None:
    sign_in(client)
    batch = {
        "source": "simulator",
        "batch_id": "before-receipt",
        "period_start": "2026-02-15T22:00:00+08:00",
        "period_end": "2026-02-16T01:00:00+08:00",
        "sales": {"chicken-rice": 10},
    }
    assert client.post("/api/v1/sales-batches", json=batch).status_code == 201
    delivery = client.post(
        "/api/v1/deliveries",
        json={
            "supplier_id": client.get("/api/v1/suppliers").json()[0]["id"],
            "ingredient_id": "chicken",
            "kind": "NORMAL",
            "expected_quantity": "4",
            "ordered_at": "2026-02-16T01:00:00+08:00",
            "expected_at": "2026-02-16T02:00:00+08:00",
        },
    ).json()
    receipt = client.post(
        "/api/v1/deliveries/" + delivery["id"] + "/receive",
        json={
            "request_id": "receipt",
            "quantity": "4",
            "received_at": "2026-02-16T02:00:00+08:00",
            "expiry_date": "2026-02-20",
            "remainder": "EXPECTED",
        },
    )
    assert receipt.status_code == 200, receipt.text
    rows = client.get(
        "/api/v1/inventory/estimated", params={"as_of": "2026-02-16T02:00:00+08:00"}
    ).json()
    assert (
        next(row for row in rows if row["id"] == "chicken-01")["quantity"] == "10.500"
    )
    assert (
        sum(float(row["quantity"]) for row in rows if row["ingredient_id"] == "chicken")
        == 19.5
    )


def test_expiry_does_not_reallocate_past_sales_to_later_batch(
    client: TestClient,
) -> None:
    sign_in(client)
    response = client.post(
        "/api/v1/sales-batches",
        json={
            "source": "simulator",
            "batch_id": "before-expiry",
            "period_start": "2026-02-15T22:00:00+08:00",
            "period_end": "2026-02-16T01:00:00+08:00",
            "sales": {"chicken-rice": 10},
        },
    )
    assert response.status_code == 201, response.text
    rows = client.get(
        "/api/v1/inventory/estimated", params={"as_of": "2026-02-19T01:00:00+08:00"}
    ).json()
    assert next(row for row in rows if row["id"] == "chicken-01")["status"] == "EXPIRED"
    assert next(row for row in rows if row["id"] == "chicken-02")["quantity"] == "5.000"


def test_same_identity_correction_retry_is_idempotent(client: TestClient) -> None:
    sign_in(client)
    batch = {
        "source": "simulator",
        "batch_id": "same-identity",
        "period_start": "2026-02-15T22:00:00+08:00",
        "period_end": "2026-02-16T01:00:00+08:00",
        "sales": {"chicken-rice": 10},
    }
    original = client.post("/api/v1/sales-batches", json=batch).json()
    correction = {**batch, "sales": {"chicken-rice": 4}, "replaces_id": original["id"]}
    accepted = client.post("/api/v1/sales-batches", json=correction)
    assert accepted.status_code == 201, accepted.text
    retry = client.post("/api/v1/sales-batches", json=correction)
    assert retry.status_code == 201, retry.text
    assert retry.json()["id"] == accepted.json()["id"]


def test_batch_crossing_expiry_boundary_is_rejected(client: TestClient) -> None:
    sign_in(client)
    response = client.post(
        "/api/v1/sales-batches",
        json={
            "source": "simulator",
            "batch_id": "expiry-split",
            "period_start": "2026-02-17T22:00:00+08:00",
            "period_end": "2026-02-18T01:00:00+08:00",
            "sales": {"chicken-rice": 10},
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "UNSUPPORTED_EXPIRY_SPLIT"
