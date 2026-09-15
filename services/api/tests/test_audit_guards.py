from datetime import date

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from test_daily import sign_in

from src.schemas import Ingredient


def test_ordering_interval_is_positive_in_schema_and_database(
    database_url: str,
) -> None:
    engine = create_engine(database_url)
    try:
        for invalid in (0, -1):
            with pytest.raises(ValidationError):
                Ingredient(
                    id="rice",
                    name="Rice",
                    unit="kg",
                    interval_days=invalid,
                    starting_date=date(2026, 2, 15),
                )
            with pytest.raises(IntegrityError), engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE ingredients SET interval_days = :value WHERE id = 'rice'"
                    ),
                    {"value": invalid},
                )
    finally:
        engine.dispose()


def test_complete_sparse_batches_and_strict_correction_identity(
    client: TestClient,
) -> None:
    sign_in(client)
    body = {
        "source": "simulator",
        "batch_id": "one",
        "period_start": "2026-02-15T22:00:00+08:00",
        "period_end": "2026-02-16T00:00:00+08:00",
        "sales": {},
    }
    original = client.post("/api/v1/sales-batches", json=body)
    assert original.status_code == 201, original.text
    inventory = client.get(
        "/api/v1/inventory/estimated", params={"as_of": body["period_end"]}
    ).json()
    assert all(row["coverage_complete"] for row in inventory)
    assert (
        next(row for row in inventory if row["id"] == "chicken-01")["quantity"]
        == "12.000"
    )
    correction = {
        **body,
        "replaces_id": original.json()["id"],
        "sales": {"chicken-rice": 1},
    }
    for changed in (
        {"source": "other"},
        {"batch_id": "other"},
        {"period_start": "2026-02-15T23:00:00+08:00"},
        {"period_end": "2026-02-16T01:00:00+08:00"},
    ):
        response = client.post("/api/v1/sales-batches", json={**correction, **changed})
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "SALES_CORRECTION_IDENTITY"
    accepted = client.post("/api/v1/sales-batches", json=correction)
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["revision"] == 2
    assert (
        client.post("/api/v1/sales-batches", json=correction).json()["id"]
        == accepted.json()["id"]
    )


@pytest.mark.parametrize("cancel_via_receipt", [False, True])
def test_public_cancellation_closes_all_remainder_and_cannot_be_reopened(
    client: TestClient, cancel_via_receipt: bool
) -> None:
    sign_in(client)
    created = client.post(
        "/api/v1/deliveries",
        json={
            "supplier_id": "fresh",
            "ingredient_id": "chicken",
            "kind": "NORMAL",
            "expected_quantity": "10",
            "ordered_at": "2026-02-16T08:00:00+08:00",
            "expected_at": "2026-02-16T10:00:00+08:00",
        },
    )
    assert created.status_code == 201, created.text
    path = "/api/v1/deliveries/" + created.json()["id"]
    received = client.post(
        path + "/receive",
        json={
            "request_id": "receipt",
            "quantity": "4",
            "received_at": "2026-02-16T10:00:00+08:00",
            "expiry_date": "2026-02-20",
            "remainder": "CANCELLED" if cancel_via_receipt else "EXPECTED",
        },
    )
    assert received.status_code == 200, received.text
    update = {
        "expected_quantity": "10",
        "expected_at": "2026-02-16T12:00:00+08:00",
        "effective_at": "2026-02-16T11:00:00+08:00",
        "cancel_remainder": True,
    }
    closed = (
        received if cancel_via_receipt else client.post(path + "/update", json=update)
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["cancelled_quantity"] == "6.000"
    assert closed.json()["outstanding_quantity"] == "0.000"
    reopened = client.post(path + "/update", json={**update, "cancel_remainder": False})
    assert reopened.status_code == 409, reopened.text
    assert reopened.json()["error"]["code"] == "DELIVERY_CLOSED"
    assert client.get(path).json()["cancelled_quantity"] == "6.000"
