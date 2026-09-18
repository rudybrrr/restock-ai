from datetime import UTC, datetime
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_changes import promotion
from test_daily import sign_in

from src.planning import _snapshot


def snapshot(client: TestClient, at: str, known_at: str | None = None) -> dict:
    assert isinstance(client.app, FastAPI)
    with Session(client.app.state.engine) as session:
        return _snapshot(
            session,
            datetime.fromisoformat(at),
            "replay",
            datetime.fromisoformat(known_at) if known_at else None,
        )


def test_supplier_and_promotion_history_survives_later_revisions(
    client: TestClient,
) -> None:
    sign_in(client)
    at = "2026-02-16T08:00:00+08:00"
    assert client.put("/api/v1/promotions/cny", json=promotion()).status_code == 200
    original = snapshot(client, at)
    old_price = next(
        row["unit_price"] for row in original["offers"] if row["id"] == "fresh-chicken"
    )
    change_at = "2026-02-16T09:00:00+08:00"
    changed = client.patch(
        "/api/v1/supplier-offers/fresh-chicken",
        json={"unit_price": "99", "effective_at": change_at},
    )
    assert changed.status_code == 200, changed.text
    revised = {
        **promotion(),
        "revision": 2,
        "demand_multiplier": "2",
        "effective_at": change_at,
    }
    assert client.put("/api/v1/promotions/cny", json=revised).status_code == 200
    earlier = snapshot(client, at)
    assert (
        next(
            row["unit_price"]
            for row in earlier["offers"]
            if row["id"] == "fresh-chicken"
        )
        == old_price
    )
    assert earlier["promotions"][0]["revision"] == 1
    later = snapshot(client, change_at)
    assert (
        Decimal(
            next(
                row["unit_price"]
                for row in later["offers"]
                if row["id"] == "fresh-chicken"
            )
        )
        == 99
    )
    assert later["promotions"][0]["revision"] == 2
    assert later["offer_version_ids"] != original["offer_version_ids"]
    assert snapshot(client, at, original["known_at"]) == original
    # A newly recorded observation at the SAME effective instant also respects
    # the real knowledge cutoff when replaying a saved assessment.
    assert (
        client.patch(
            "/api/v1/supplier-offers/fresh-chicken",
            json={"unit_price": "100", "effective_at": change_at},
        ).status_code
        == 200
    )
    assert snapshot(client, change_at, later["known_at"]) == later
    assert (
        client.put(
            "/api/v1/promotions/cny",
            json={**revised, "revision": 3, "effective_at": at},
        ).status_code
        == 409
    )
    client.headers["Authorization"] = "Bearer test-agent-token"
    run = client.post("/api/v1/runs/claim")
    assert run.status_code == 200, run.text
    frozen = run.json()["snapshot"]
    assert frozen["known_at"]
    assert client.get(f"/api/v1/runs/{run.json()['id']}").json()["snapshot"] == frozen


def test_commitments_receipts_cancellations_and_cycles_obey_operational_cutoff(
    client: TestClient,
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
    original = snapshot(client, "2026-02-16T10:00:00+08:00")
    assert snapshot(client, "2026-02-16T07:00:00+08:00")["commitments"] == []
    changed = client.post(
        path + "/update",
        json={
            "expected_quantity": "8",
            "expected_at": "2026-02-16T12:00:00+08:00",
            "effective_at": "2026-02-16T11:00:00+08:00",
        },
    )
    assert changed.status_code == 200, changed.text
    # A late-recorded early receipt must not import the 11:00 revised terms.
    receipt = client.post(
        path + "/receive",
        json={
            "request_id": "late-slip",
            "remainder": "EXPECTED",
            "quantity": "2",
            "received_at": "2026-02-16T09:00:00+08:00",
            "expiry_date": "2026-02-20",
        },
    )
    assert receipt.status_code == 200, receipt.text
    backdated = client.post(
        path + "/update",
        json={
            "expected_quantity": "10",
            "expected_at": "2026-02-16T12:00:00+08:00",
            "effective_at": "2026-02-16T10:00:00+08:00",
        },
    )
    assert backdated.status_code == 409, backdated.text
    assert backdated.json()["error"]["code"] == "STALE_DELIVERY_UPDATE"
    backdated_cancel = client.post(
        path + "/receive",
        json={
            "request_id": "bad-cancellation",
            "quantity": "1",
            "remainder": "CANCELLED",
            "received_at": "2026-02-16T10:00:00+08:00",
            "expiry_date": "2026-02-20",
        },
    )
    assert backdated_cancel.status_code == 409, backdated_cancel.text
    second = client.post(
        path + "/receive",
        json={
            "request_id": "second-slip",
            "quantity": "4",
            "received_at": "2026-02-16T12:00:00+08:00",
            "expiry_date": "2026-02-20",
            "remainder": "CANCELLED",
        },
    )
    assert second.status_code == 200, second.text
    cycle = client.post(
        "/api/v1/order-cycles/rice/2026-02-15/decision",
        json={"status": "ORDERED", "effective_at": "2026-02-16T11:00:00+08:00"},
    )
    assert cycle.status_code == 200, cycle.text
    earlier = snapshot(client, "2026-02-16T10:00:00+08:00")
    commitment = earlier["commitments"][0]
    assert datetime.fromisoformat(commitment["expected_at"]) == datetime.fromisoformat(
        created.json()["expected_at"]
    )
    assert Decimal(commitment["received_quantity"]) == 2
    assert Decimal(commitment["outstanding_quantity"]) == 8
    assert Decimal(commitment["cancelled_quantity"]) == 0
    assert len(commitment["receipts"]) == 1
    future_lot = second.json()["receipts"][-1]["lot_id"]
    assert future_lot not in {lot["id"] for lot in earlier["inventory"]}
    assert earlier["cycle_decisions"] == []
    later = snapshot(client, "2026-02-16T12:00:00+08:00")
    assert Decimal(later["commitments"][0]["received_quantity"]) == 6
    assert Decimal(later["commitments"][0]["cancelled_quantity"]) == 2
    assert Decimal(later["commitments"][0]["outstanding_quantity"]) == 0
    projection = earlier["procurement_contract"]["commitment_projection"]
    assert projection["complete"] is True
    assert projection["supply_manifest"] == [created.json()["id"]]
    supply = projection["supplies"][0]
    assert Decimal(supply["delivery"]["outstanding_quantity"]) == 8
    assert supply["expiry_date"] == "2026-02-20"
    assert supply["projected_lot_id"] == ("projected-delivery:" + created.json()["id"])
    assert supply["expiry_evidence"]["captured_revision"]
    closed = later["procurement_contract"]["commitment_projection"]["supplies"][0]
    assert Decimal(closed["delivery"]["received_quantity"]) == 6
    assert Decimal(closed["delivery"]["cancelled_quantity"]) == 2
    assert Decimal(closed["delivery"]["outstanding_quantity"]) == 0
    assert closed["expiry_date"] is None
    assert closed["projected_lot_id"] is None
    assert len(later["cycle_decisions"]) == 1
    assert (
        snapshot(client, "2026-02-16T10:00:00+08:00", original["known_at"]) == original
    )


def test_later_sales_and_daily_corrections_do_not_change_known_snapshot(
    client: TestClient,
) -> None:
    sign_in(client)
    batch = {
        "source": "simulator",
        "batch_id": "one",
        "period_start": "2026-02-15T22:00:00+08:00",
        "period_end": "2026-02-16T00:00:00+08:00",
        "sales": {"chicken-rice": 10},
    }
    created = client.post("/api/v1/sales-batches", json=batch)
    assert created.status_code == 201, created.text
    before = snapshot(client, batch["period_end"])
    assert (
        client.post(
            "/api/v1/sales-batches",
            json={
                **batch,
                "replaces_id": created.json()["id"],
                "sales": {"chicken-rice": 20},
            },
        ).status_code
        == 201
    )
    assert snapshot(client, batch["period_end"], before["known_at"]) == before
    after = snapshot(client, batch["period_end"])
    assert after["sales_batches"][0]["revision"] == 2
    assert after["inventory"] != before["inventory"]
    path = "/api/v1/daily-updates/2026-02-16"
    body = {
        "cutoff": "2026-02-16T22:00:00+08:00",
        "counts": {row["id"]: "3" for row in client.get("/api/v1/inventory").json()},
        "sales": {row["id"]: 0 for row in client.get("/api/v1/menu-items").json()},
    }
    assert client.post(path + "/draft", json=body).status_code == 200
    assert client.post(path + "/submit").status_code == 200
    closing = snapshot(client, body["cutoff"])
    body["counts"]["chicken-01"] = "1"
    body["sales"]["chicken-rice"] = 100
    assert client.post(path + "/draft", json=body).status_code == 200
    assert client.post(path + "/submit").status_code == 200
    assert snapshot(client, body["cutoff"], closing["known_at"]) == closing
    revised = snapshot(client, body["cutoff"])
    assert len(revised["authoritative_daily_sales"]) == 1
    assert revised["authoritative_daily_sales"][0]["sales"]["chicken-rice"] == 100
    assert datetime.fromisoformat(revised["known_at"]) <= datetime.now(UTC)


def test_unknown_historical_baseline_cannot_be_certified(client: TestClient) -> None:
    sign_in(client)
    requested = client.post(
        "/api/v1/assessments", json={"as_of": "2026-02-14T22:00:00+08:00"}
    )
    assert requested.status_code == 202, requested.text
    client.headers["Authorization"] = "Bearer test-agent-token"
    claimed = client.post("/api/v1/runs/claim")
    assert claimed.status_code == 200, claimed.text
    run = claimed.json()
    assert run["snapshot"]["offers"] == []
    assert run["snapshot"]["missing_offer_history"]
    calculated = client.post(
        f"/api/v1/runs/{run['id']}/tools/optimise",
        json={"dish_quantities": {"chicken-rice": 200}},
    )
    assert calculated.status_code == 409, calculated.text
    assert calculated.json()["error"]["code"] == "MISSING_REQUIRED_DATA"
    assert client.get("/api/v1/plan-history").json() == []
