"""Synthetic catalog has usable tradeoffs for the demo's supplier decisions."""

from datetime import date, datetime, timedelta
from decimal import Decimal


def test_seed_offers_support_alternatives_and_future_deliveries(client):
    client.headers["Authorization"] = "Bearer test-agent-token"
    response = client.get("/api/v1/supplier-offers")
    assert response.status_code == 200
    offers = response.json()
    for ingredient in client.get("/api/v1/ingredients").json():
        alternatives = {
            offer["supplier_id"]: offer
            for offer in offers
            if offer["ingredient_id"] == ingredient["id"]
        }
        fresh, pantry, market = (
            alternatives[key] for key in ("fresh", "pantry", "market")
        )
        assert (
            Decimal(pantry["unit_price"])
            < Decimal(fresh["unit_price"])
            < Decimal(market["unit_price"])
        )
        assert (
            market["lead_time_minutes"]
            < fresh["lead_time_minutes"]
            < pantry["lead_time_minutes"]
        )
        assert (
            Decimal(pantry["available_quantity"])
            > Decimal(fresh["available_quantity"])
            > Decimal(market["available_quantity"])
        )
        for offer in alternatives.values():
            slots = [
                datetime.fromisoformat(value) for value in offer["feasible_delivery_at"]
            ]
            observed = datetime.fromisoformat(offer["observed_at"])
            assert slots == sorted(set(slots))
            assert max(slots) >= observed + timedelta(days=28)
            assert any(
                slot >= observed + timedelta(minutes=offer["lead_time_minutes"])
                for slot in slots
            )
            assert Decimal(offer["available_quantity"]) >= Decimal(offer["moq"]) > 0
            assert Decimal(offer["moq"]) % Decimal(offer["pack_size"]) == 0
            assert 0 < Decimal(offer["recent_on_time_rate"]) <= 1
        # Urgent supply can arrive the same afternoon after a morning disruption.
        disruption = datetime.fromisoformat("2026-02-18T10:00:00+08:00")
        assert any(
            disruption + timedelta(minutes=market["lead_time_minutes"])
            <= datetime.fromisoformat(slot)
            < disruption.replace(hour=19)
            for slot in market["feasible_delivery_at"]
        )


def test_seed_preserves_batch_counts_with_distinct_synthetic_expiries(client):
    client.headers["Authorization"] = "Bearer test-agent-token"
    lots = {lot["id"]: lot for lot in client.get("/api/v1/inventory").json()}
    assert len(lots) == 9  # The fixture runs the non-overwriting seed twice.
    assert lots["chicken-01"]["expiry_date"] == "2026-02-18"
    assert lots["chicken-02"]["expiry_date"] == "2026-02-20"
    assert Decimal(lots["chicken-01"]["quantity"]) == 12
    assert Decimal(lots["chicken-02"]["quantity"]) == 5
    for ingredient in ("rice", "oil", "soy-sauce"):
        assert date.fromisoformat(lots[f"{ingredient}-01"]["expiry_date"]) > date(
            2026, 3, 15
        )
    offers = client.get("/api/v1/supplier-offers").json()
    shelf_lives = {
        offer["ingredient_id"]: offer["shelf_life_days_on_arrival"] for offer in offers
    }
    assert shelf_lives["vegetables"] < shelf_lives["eggs"] < shelf_lives["rice"]
