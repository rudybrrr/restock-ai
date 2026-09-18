from datetime import date, datetime
from decimal import Decimal

from src.inventory_tools import _commitment_supplies
from src.operations_schemas import Delivery
from src.procurement_contract_schemas import (
    FrozenCommitmentProjection,
    FrozenExpectedSupply,
    FrozenSourceEvidence,
)


def delivery(delivery_id: str, *, received: str, cancelled: str, outstanding: str) -> Delivery:
    return Delivery.model_validate(
        {
            "id": delivery_id,
            "supplier_id": "fresh",
            "ingredient_id": "chicken",
            "kind": "NORMAL",
            "expected_quantity": "10.000",
            "ordered_at": "2026-02-15T22:00:00+08:00",
            "expected_at": "2026-02-16T08:00:00+08:00",
            "source_validation": "MANUAL",
            "received_quantity": received,
            "cancelled_quantity": cancelled,
            "outstanding_quantity": outstanding,
            "receipts": [],
        }
    )


def test_commitment_adapter_preserves_partial_receipt_and_cancelled_remainder() -> None:
    partial = delivery("delivery-partial", received="6.000", cancelled="0.000", outstanding="4.000")
    cancelled = delivery("delivery-cancelled", received="6.000", cancelled="4.000", outstanding="0.000")
    projection = FrozenCommitmentProjection(
        as_of=datetime.fromisoformat("2026-02-15T22:00:00+08:00"),
        known_at=datetime.fromisoformat("2026-02-15T22:01:00+08:00"),
        captured_state_revision="7",
        expiry_policy="EXPIRY_ARRIVAL_PLUS_SHELF_LIFE_MINUS_ONE_V1",
        complete=True,
        findings=[],
        supply_manifest=[partial.id, cancelled.id],
        supplies=[
            FrozenExpectedSupply(
                delivery=partial,
                expiry_date=date(2026, 2, 18),
                expiry_evidence=FrozenSourceEvidence(
                    reference="offer-1:shelf_life_days_on_arrival",
                    available_at=datetime.fromisoformat("2026-02-15T22:01:00+08:00"),
                    captured_revision="offer-rev-1",
                ),
                projected_lot_id="projected-delivery:delivery-partial",
            ),
            FrozenExpectedSupply(delivery=cancelled, expiry_date=None, expiry_evidence=None, projected_lot_id=None),
        ],
    )

    supplies, manifest = _commitment_supplies(projection)

    assert manifest == [partial.id, cancelled.id]
    assert [item.delivery.id for item in supplies] == [partial.id, cancelled.id]
    assert supplies[0].delivery.received_quantity == Decimal("6.000")
    assert supplies[0].delivery.outstanding_quantity == Decimal("4.000")
    assert supplies[1].delivery.cancelled_quantity == Decimal("4.000")
    assert supplies[1].delivery.outstanding_quantity == Decimal("0.000")
