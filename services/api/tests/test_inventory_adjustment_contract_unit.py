from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.inventory_adjustment_contracts import context_from_run
from src.inventory_adjustment_schemas import InventoryAdjustmentResult
from src.planning_schemas import PlanningRun


def test_context_uses_only_revision_bound_adjustments_that_triggered_the_run():
    now = datetime(2026, 9, 18, tzinfo=UTC)
    event = {
        "id": "adjustment-event-1",
        "type": "INVENTORY_ADJUSTED",
        "timestamp": now,
        "source": "manager",
        "payload": {
            "revision_id": "daily-revision-2",
            "replaces_revision_id": "daily-revision-1",
            "day": date(2026, 2, 16).isoformat(),
            "effective_at": "2026-02-16T21:00:00+08:00",
            "adjustments": [
                {
                    "lot_id": "chicken-01",
                    "ingredient_id": "chicken",
                    "unit": "kg",
                    "previous_quantity": "12",
                    "corrected_quantity": "12.5",
                    "delta": "0.5",
                }
            ],
        },
    }
    run = PlanningRun.model_validate(
        {
            "id": "run-1",
            "status": "RUNNING",
            "trigger": "INVENTORY_ADJUSTED",
            "trigger_event_id": event["id"],
            "as_of": "2026-02-16T21:00:00+08:00",
            "input_revision": 7,
            "snapshot": {
                "known_at": now.isoformat(),
                "inventory_snapshot_id": "run-1:inventory",
                "trigger_event_ids": [event["id"]],
                "inventory_adjustments": [
                    event,
                    {**event, "id": "unrelated-adjustment"},
                ],
                "inventory": [
                    {
                        "id": "chicken-01",
                        "ingredient_id": "chicken",
                        "unit": "kg",
                        "received_at": "2026-02-15T08:00:00+08:00",
                        "expiry_date": "2026-02-20",
                        "initial_quantity": "20",
                        "counted_at": "2026-02-16T21:00:00+08:00",
                        "quantity": "12.5",
                        "provenance": "ESTIMATED",
                        "as_of": "2026-02-16T21:00:00+08:00",
                        "coverage_start": "2026-02-16T21:00:00+08:00",
                        "coverage_complete": True,
                        "unallocated_consumption": "0",
                        "status": "ACTIVE",
                    }
                ],
            },
            "created_at": now,
            "claimed_at": now,
        }
    )

    context = context_from_run(run)

    assert context.captured_state_revision == "7"
    assert context.snapshot_reference == "run:run-1:snapshot:7"
    assert context.inventory_snapshot_reference == "run-1:inventory"
    assert context.required_evidence_refs == [
        "run:run-1:snapshot:7",
        "run-1:inventory",
        "event:adjustment-event-1",
    ]
    assert context.assessed_lot_ids == ["chicken-01"]
    assert context.assessed_ingredient_ids == ["chicken"]
    assert [item.id for item in context.adjustment_events] == ["adjustment-event-1"]
    assert context.inventory[0].quantity == Decimal("12.5")


def test_non_material_result_requires_complete_feasible_inventory():
    base = {
        "material_change": False,
        "complete": True,
        "inventory_feasible": True,
        "assessed_lot_ids": ["chicken-01"],
        "assessed_ingredient_ids": ["chicken"],
        "findings": [],
        "evidence_refs": ["snapshot"],
        "required_follow_up": [],
        "run_id": "run-1",
        "snapshot_reference": "snapshot",
        "inventory_snapshot_reference": "inventory",
        "captured_state_revision": "7",
        "as_of": "2026-02-16T21:00:00+08:00",
        "known_at": "2026-09-18T18:00:00+08:00",
        "adjustment_event_ids": ["adjustment-event-1"],
        "plan_id": None,
        "plan_version_reference": None,
    }
    assert InventoryAdjustmentResult.model_validate(base).material_change is False
    with pytest.raises(ValidationError, match="complete feasible"):
        InventoryAdjustmentResult.model_validate({**base, "inventory_feasible": None})
