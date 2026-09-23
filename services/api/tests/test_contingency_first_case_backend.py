"""Public-API proof of the Backend facts for the staged supplier-delay case."""

from datetime import datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from test_daily import sign_in

from src.procurement_contract_schemas import FrozenCommitmentProjection

CASE = "/api/v1/contingency-case-inputs/BOUNDED_CONTINGENCY_20260216_CASE_V1/versions/1"
ISSUE = "2026-02-16T10:00:00+08:00"


def test_first_case_stock_and_delayed_commitment_are_frozen_once(
    client: TestClient,
) -> None:
    sign_in(client)
    delivery = client.post(
        "/api/v1/deliveries",
        json={
            "supplier_id": "fresh",
            "ingredient_id": "vegetables",
            "kind": "NORMAL",
            "expected_quantity": "10",
            "ordered_at": "2026-02-15T10:00:00+08:00",
            "expected_at": "2026-02-16T11:00:00+08:00",
        },
    )
    assert delivery.status_code == 201, delivery.text
    delivery_id = delivery.json()["id"]

    counts = {lot["id"]: "0" for lot in client.get("/api/v1/inventory").json()}
    counts["rice-01"] = "20"
    counts["tofu-01"] = "20"
    draft = client.post(
        "/api/v1/daily-updates/2026-02-15/draft",
        json={
            "cutoff": "2026-02-15T22:00:00+08:00",
            "counts": counts,
            "sales": {
                dish["id"]: 0 for dish in client.get("/api/v1/menu-items").json()
            },
        },
    )
    assert draft.status_code == 200, draft.text
    closing = client.post("/api/v1/daily-updates/2026-02-15/submit")
    assert closing.status_code == 200, closing.text

    receipt = client.post(
        f"/api/v1/deliveries/{delivery_id}/receive",
        json={
            "request_id": "first-case-six-kilos",
            "quantity": "6",
            "received_at": "2026-02-16T09:00:00+08:00",
            "expiry_date": "2026-02-20",
            "remainder": "EXPECTED",
        },
    )
    assert receipt.status_code == 200, receipt.text
    receipt_lot_id = receipt.json()["receipts"][0]["lot_id"]
    delayed = client.post(
        f"/api/v1/deliveries/{delivery_id}/update",
        json={
            "expected_quantity": "10",
            "expected_at": "2026-02-17T09:00:00+08:00",
            "expected_expiry_date": "2026-02-20",
            "effective_at": "2026-02-16T09:30:00+08:00",
        },
    )
    assert delayed.status_code == 200, delayed.text

    # The simulator explicitly reports no sales since the physical count.
    # Split at the receipt so the new lot has complete post-receipt coverage too.
    for batch_id, start, end in (
        ("before-receipt", "2026-02-15T22:00:00+08:00", "2026-02-16T09:00:00+08:00"),
        ("after-receipt", "2026-02-16T09:00:00+08:00", ISSUE),
    ):
        batch = client.post(
            "/api/v1/sales-batches",
            json={
                "source": "first-case-simulator",
                "batch_id": batch_id,
                "period_start": start,
                "period_end": end,
                "sales": {},
            },
        )
        assert batch.status_code == 201, batch.text

    requested = client.post("/api/v1/assessments", json={"as_of": ISSUE})
    assert requested.status_code == 202, requested.text
    client.headers["Authorization"] = "Bearer test-agent-token"
    case_response = client.get(CASE)
    assert case_response.status_code == 200, case_response.text
    case = case_response.json()["payload"]
    claimed = client.post("/api/v1/runs/claim")
    assert claimed.status_code == 200, claimed.text
    run = claimed.json()
    snapshot = run["snapshot"]
    assert datetime.fromisoformat(snapshot["as_of"]) == datetime.fromisoformat(ISSUE)
    assert datetime.fromisoformat(snapshot["known_at"]) >= datetime.fromisoformat(
        case_response.json()["recorded_at"]
    )
    assert (
        str(run["input_revision"])
        == snapshot["procurement_contract"]["captured_state_revision"]
    )

    opening = {ingredient: Decimal(0) for ingredient in case["ingredient_ids"]}
    for lot in snapshot["inventory"]:
        if lot["status"] == "ACTIVE":
            assert lot["coverage_complete"] is True
            opening[lot["ingredient_id"]] += Decimal(lot["quantity"])
    assert opening == {
        ingredient: Decimal(quantity)
        for ingredient, quantity in case["opening_expected"].items()
    }
    tofu_recipe = {
        row["ingredient_id"]: Decimal(row["quantity"])
        for row in snapshot["recipes"]
        if row["menu_item_id"] == "tofu-bowl"
    }
    assert tofu_recipe == {
        "tofu": Decimal("0.150"),
        "rice": Decimal("0.100"),
        "vegetables": Decimal("0.100"),
    }
    vegetable_demand = [
        Decimal(bucket["expected_portions"]["tofu-bowl"]) * tofu_recipe["vegetables"]
        for bucket in case["forecasts"][0]["buckets"]
    ]
    assert vegetable_demand == [Decimal(7), Decimal(3)]
    assert sum(vegetable_demand) - opening["vegetables"] == Decimal(4)
    received_lot = next(
        lot for lot in snapshot["inventory"] if lot["id"] == receipt_lot_id
    )
    assert Decimal(received_lot["quantity"]) == Decimal(6)
    assert (
        received_lot["expiry_date"]
        == case["fixed_supply_expected"]["received_expiry_date"]
    )

    assert len(snapshot["commitments"]) == 1
    fixed = snapshot["commitments"][0]
    expected = case["fixed_supply_expected"]
    for field in ("supplier_id", "ingredient_id", "kind"):
        assert fixed[field] == expected[field]
    for field in ("ordered_at", "expected_at"):
        assert datetime.fromisoformat(fixed[field]) == datetime.fromisoformat(
            expected[field]
        )
    for field in (
        "expected_quantity",
        "received_quantity",
        "cancelled_quantity",
        "outstanding_quantity",
    ):
        assert Decimal(fixed[field]) == Decimal(expected[field])
    assert fixed["receipts"][0]["lot_id"] == receipt_lot_id
    projection = snapshot["procurement_contract"]["commitment_projection"]
    assert projection["complete"] is True
    assert projection["supply_manifest"] == [delivery_id]
    assert len(projection["supplies"]) == 1
    assert projection["supplies"][0]["delivery"]["id"] == delivery_id
    assert projection["supplies"][0]["expiry_date"] == "2026-02-20"
    assert projection["supplies"][0]["expiry_evidence"]["reference"] == (
        f"delivery:{delivery_id}:expected_expiry_date"
    )
    assert (
        projection["supplies"][0]["expiry_evidence"]["captured_revision"]
        == (fixed["terms_event_id"])
    )
    assert datetime.fromisoformat(
        projection["supplies"][0]["expiry_evidence"]["available_at"]
    ) <= datetime.fromisoformat(snapshot["known_at"])
    assert (
        snapshot["procurement_contract"]["policy"]["payload"]["emergency_mode"]
        == "NORMAL_ONLY"
    )
    assert "contingency_contract" not in snapshot
    staged = snapshot["staged_contingency_case"]
    assert staged["status"] == "STAGED_MATCH", staged["findings"]
    assert staged["findings"] == []
    assert staged["policy"]["id"] == "policy:BOUNDED_CONTINGENCY_CASH_V1_DEMO:2"
    assert staged["case_input"]["id"] == (
        "case-input:BOUNDED_CONTINGENCY_20260216_CASE_V1:2"
    )
    assert staged["run_id"] == run["id"]
    assert datetime.fromisoformat(staged["known_at"]) == datetime.fromisoformat(
        snapshot["known_at"]
    )
    assert staged["captured_state_revision"] == str(run["input_revision"])
    assert staged["opening_lots"] == snapshot["inventory"]
    assert FrozenCommitmentProjection.model_validate(
        staged["commitment_projection"]
    ) == FrozenCommitmentProjection.model_validate(projection)
    read_back = client.get(f"/api/v1/runs/{run['id']}/staged-contingency-case")
    assert read_back.status_code == 200, read_back.text
    assert read_back.json() == staged
