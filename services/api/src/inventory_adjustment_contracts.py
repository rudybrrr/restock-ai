"""Frozen context and immutable result for inventory-count corrections."""

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src import database as db
from src.errors import ApiError
from src.inventory_adjustment_schemas import (
    InventoryAdjustmentAssessment,
    InventoryAdjustmentContext,
    InventoryAdjustmentResult,
    InventoryAdjustmentResultWrite,
)
from src.operations import lock_inventory
from src.operations_schemas import InventoryAdjustmentEvent
from src.planning_schemas import PlanningRun


def _canonical_hash(value: dict) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def required_for_run(session: Session, run_id: str) -> bool:
    return (
        session.execute(
            select(db.assessment_requests.c.event_id)
            .join(db.events, db.events.c.id == db.assessment_requests.c.event_id)
            .where(
                db.assessment_requests.c.run_id == run_id,
                db.events.c.type == "INVENTORY_ADJUSTED",
            )
            .limit(1)
        ).first()
        is not None
    )


def context_from_run(run: PlanningRun) -> InventoryAdjustmentContext:
    snapshot = run.snapshot
    trigger_ids = set(snapshot.get("trigger_event_ids", []))
    events = [
        InventoryAdjustmentEvent.model_validate(item)
        for item in snapshot.get("inventory_adjustments", [])
        if item.get("id") in trigger_ids
    ]
    if not events:
        raise ApiError(
            409,
            "INVENTORY_ADJUSTMENT_NOT_REQUIRED",
            "Run has no frozen inventory-adjustment trigger",
        )
    revision = str(run.input_revision)
    if snapshot.get("captured_state_revision") not in (None, revision):
        raise ApiError(
            409,
            "CAPTURED_REVISION_MISMATCH",
            "Frozen snapshot does not match the run input revision",
        )
    snapshot_reference = f"run:{run.id}:snapshot:{revision}"
    contract_reference = (
        f"run:{run.id}:procurement-contract"
        if snapshot.get("procurement_contract") is not None
        else None
    )
    required_evidence_refs = [
        snapshot_reference,
        snapshot["inventory_snapshot_id"],
        *(f"event:{event.id}" for event in events),
    ]
    assessed_lot_ids = sorted(
        {item.lot_id for event in events for item in event.payload.adjustments}
    )
    assessed_ingredient_ids = sorted(
        {item.ingredient_id for event in events for item in event.payload.adjustments}
    )
    return InventoryAdjustmentContext(
        run_id=run.id,
        as_of=run.as_of,
        known_at=datetime.fromisoformat(snapshot["known_at"]),
        captured_state_revision=revision,
        snapshot_reference=snapshot_reference,
        inventory_snapshot_reference=snapshot["inventory_snapshot_id"],
        procurement_contract_reference=contract_reference,
        plan_id=snapshot.get("revises_plan_id"),
        plan_version_reference=snapshot.get("plan_version_reference"),
        required_evidence_refs=required_evidence_refs,
        assessed_lot_ids=assessed_lot_ids,
        assessed_ingredient_ids=assessed_ingredient_ids,
        adjustment_events=events,
        inventory=snapshot["inventory"],
    )


def _saved(run: PlanningRun) -> InventoryAdjustmentAssessment | None:
    raw = run.snapshot.get("inventory_adjustment_assessment")
    return (
        InventoryAdjustmentAssessment.model_validate(raw) if raw is not None else None
    )


def read_assessment(session: Session, run_id: str) -> InventoryAdjustmentAssessment:
    from src import planning

    assessment = _saved(planning.get_run(session, run_id))
    if assessment is None:
        raise ApiError(
            404,
            "INVENTORY_ADJUSTMENT_ASSESSMENT_NOT_FOUND",
            "Inventory-adjustment assessment does not exist",
        )
    return assessment


def save_result(
    session: Session,
    run_id: str,
    body: InventoryAdjustmentResultWrite,
) -> InventoryAdjustmentAssessment:
    from src import planning

    lock_inventory(session)
    run = planning.get_run(session, run_id)
    payload = body.result.model_dump(mode="json")
    result_hash = _canonical_hash(payload)
    existing = _saved(run)
    if existing is not None:
        if existing.result_sha256 != result_hash:
            raise ApiError(
                409,
                "INVENTORY_ADJUSTMENT_RESULT_CONFLICT",
                "Inventory-adjustment result is already immutable",
            )
        return existing
    if run.status != "RUNNING":
        raise ApiError(
            409,
            "RUN_NOT_RUNNING",
            "Inventory adjustment can only be assessed for a running attempt",
        )
    if planning.state_revision(session) != run.input_revision:
        raise ApiError(
            409,
            "STALE_RUN_INPUT",
            "Operational inputs changed after this run was claimed",
        )
    context = context_from_run(run)
    result = body.result
    event_ids = [event.id for event in context.adjustment_events]
    if (
        result.run_id != run_id
        or result.snapshot_reference != context.snapshot_reference
        or result.inventory_snapshot_reference != context.inventory_snapshot_reference
        or result.captured_state_revision != context.captured_state_revision
        or result.as_of != context.as_of
        or result.known_at != context.known_at
        or result.adjustment_event_ids != event_ids
        or result.plan_id != context.plan_id
        or result.plan_version_reference != context.plan_version_reference
        or result.assessed_lot_ids != context.assessed_lot_ids
        or result.assessed_ingredient_ids != context.assessed_ingredient_ids
    ):
        raise ApiError(
            409,
            "INVENTORY_ADJUSTMENT_CONTEXT_MISMATCH",
            "Result does not match the exact frozen correction context",
        )
    if not set(context.required_evidence_refs) <= set(result.evidence_refs):
        raise ApiError(
            409,
            "INVENTORY_ADJUSTMENT_EVIDENCE_INCOMPLETE",
            "Result omits required correction evidence",
        )
    completed_at = datetime.now(UTC)
    assessment = InventoryAdjustmentAssessment(
        result_reference=f"inventory-adjustment-result:{run_id}",
        result_sha256=result_hash,
        result=result,
        completed_at=completed_at,
    )
    session.execute(
        update(db.planning_runs)
        .where(db.planning_runs.c.id == run_id)
        .values(
            snapshot={
                **run.snapshot,
                "inventory_adjustment_assessment": assessment.model_dump(mode="json"),
            }
        )
    )
    session.commit()
    return assessment


def result_for_completion(
    session: Session, run_id: str
) -> InventoryAdjustmentResult | None:
    if not required_for_run(session, run_id):
        return None
    try:
        return read_assessment(session, run_id).result
    except ApiError as error:
        raise ApiError(
            409,
            "MATERIALITY_RESULT_REQUIRED",
            "Inventory-adjustment runs require a persisted materiality result",
        ) from error
