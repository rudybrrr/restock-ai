"""Persistence and freshness boundary for sales-materiality engine calls."""

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import insert, or_, select, update
from sqlalchemy.orm import Session

from src import database as db
from src.errors import ApiError
from src.history_dataset import Catalogue
from src.operations import lock_inventory
from src.procurement_contract_schemas import ProcurementContract
from src.sales_materiality_schemas import (
    SalesMaterialityAssessment,
    SalesMaterialityContext,
    SalesMaterialityEngineRequest,
    SalesMaterialityRequestCreate,
    SalesMaterialityResultWrite,
    SalesThresholdPolicyInput,
)
from src.sales_threshold_schemas import (
    FrozenSalesThresholdPolicy,
    MaterialityEvidence,
    SalesThresholdPolicyVersion,
)

POLICY_VERSION = "SALES_MATERIALITY_V1"
POLICY_ID = "sales-threshold-policy:SALES_MATERIALITY_V1"
POLICY_SOURCE_REVISION = "ANIQ_APPROVED_SALES_MATERIALITY_20260918_V1"


def seed_policy(recorded_at: datetime) -> dict:
    return {
        "id": POLICY_ID,
        "version": POLICY_VERSION,
        "effective_at": datetime.fromisoformat("2026-02-15T22:00:00+08:00"),
        "expires_at": datetime.fromisoformat("2026-02-16T21:00:00+08:00"),
        "recorded_at": recorded_at,
        "source_revision": POLICY_SOURCE_REVISION,
        "payload": {
            "version": POLICY_VERSION,
            "rule": "V2_DEMO_ABSOLUTE_OR_RELATIVE_V1",
            "absolute_floor": "5",
            "relative_threshold": "0.2",
            "minimum_expected_portions": "20",
            "minimum_complete_buckets": 2,
            "scope": (
                "ONE_SINGAPORE_SERVICE_DAY_PER_DISH_CUMULATIVE_COMPLETE_HALF_HOURS"
            ),
        },
    }


def read_policy(session: Session, version: str) -> SalesThresholdPolicyVersion:
    row = (
        session.execute(
            select(db.sales_threshold_policy_versions).where(
                db.sales_threshold_policy_versions.c.version == version
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ApiError(404, "POLICY_NOT_FOUND", "Sales threshold policy does not exist")
    return SalesThresholdPolicyVersion.model_validate(row)


def select_frozen_policy(
    session: Session,
    as_of: datetime,
    known_at: datetime,
    captured_state_revision: str,
) -> FrozenSalesThresholdPolicy | None:
    row = (
        session.execute(
            select(db.sales_threshold_policy_versions)
            .where(
                db.sales_threshold_policy_versions.c.effective_at <= as_of,
                db.sales_threshold_policy_versions.c.expires_at >= as_of,
                db.sales_threshold_policy_versions.c.recorded_at <= known_at,
            )
            .order_by(db.sales_threshold_policy_versions.c.recorded_at.desc())
            .limit(1)
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    policy = SalesThresholdPolicyVersion.model_validate(row)
    return FrozenSalesThresholdPolicy(
        **policy.model_dump(),
        evidence=MaterialityEvidence(
            reference=policy.id,
            available_at=policy.recorded_at,
            captured_revision=captured_state_revision,
        ),
    )


def context_from_contract(contract: ProcurementContract) -> SalesMaterialityContext:
    if contract.run_id is None or contract.sales_threshold_policy is None:
        raise ApiError(
            409,
            "MISSING_REQUIRED_DATA",
            "Run has no frozen sales threshold policy",
        )
    snapshot_reference = (
        f"run:{contract.run_id}:snapshot:{contract.captured_state_revision}"
    )
    return SalesMaterialityContext(
        run_id=contract.run_id,
        as_of=contract.as_of,
        known_at=contract.known_at,
        captured_state_revision=contract.captured_state_revision,
        procurement_contract_reference=f"run:{contract.run_id}:procurement-contract",
        snapshot_reference=snapshot_reference,
        snapshot_evidence=MaterialityEvidence(
            reference=snapshot_reference,
            available_at=contract.known_at,
            captured_revision=contract.captured_state_revision,
        ),
        forecast_input_reference=contract.forecast_input.id,
        policy=contract.sales_threshold_policy,
    )


def _canonical_hash(value: dict) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _assessment(row) -> SalesMaterialityAssessment:
    public_fields = {
        key: value
        for key, value in row.items()
        if key not in {"request_payload", "result_payload"}
    }
    return SalesMaterialityAssessment.model_validate(
        {
            **public_fields,
            "engine_request": row["request_payload"],
            "result": row["result_payload"],
        }
    )


def read_assessment(session: Session, run_id: str) -> SalesMaterialityAssessment:
    row = (
        session.execute(
            select(db.sales_materiality_assessments).where(
                db.sales_materiality_assessments.c.run_id == run_id
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ApiError(
            404,
            "MATERIALITY_ASSESSMENT_NOT_FOUND",
            "Sales materiality assessment does not exist",
        )
    return _assessment(row)


def required_for_run(session: Session, run_id: str) -> bool:
    return (
        session.execute(
            select(db.assessment_requests.c.event_id)
            .join(db.events, db.events.c.id == db.assessment_requests.c.event_id)
            .where(
                db.assessment_requests.c.run_id == run_id,
                db.events.c.type == "SALES_UPDATED",
            )
            .limit(1)
        ).first()
        is not None
    )


def result_for_completion(session: Session, run_id: str):
    if not required_for_run(session, run_id):
        return None
    try:
        assessment = read_assessment(session, run_id)
    except ApiError as error:
        raise ApiError(
            409,
            "MATERIALITY_RESULT_REQUIRED",
            "Sales-triggered runs require a persisted materiality result",
        ) from error
    if assessment.result is None:
        raise ApiError(
            409,
            "MATERIALITY_RESULT_REQUIRED",
            "Sales-triggered runs require a persisted materiality result",
        )
    return assessment.result


def _running_contract(
    session: Session, run_id: str
) -> tuple[dict, ProcurementContract]:
    from src import planning

    run = planning.get_run(session, run_id)
    if run.status != "RUNNING":
        raise ApiError(
            409,
            "RUN_NOT_RUNNING",
            "Sales materiality can only be recorded for a running assessment",
        )
    if planning.state_revision(session) != run.input_revision:
        raise ApiError(
            409,
            "STALE_RUN_INPUT",
            "Operational inputs changed after this run was claimed",
        )
    raw = run.snapshot.get("procurement_contract")
    if raw is None:
        raise ApiError(
            409,
            "MISSING_REQUIRED_DATA",
            "Run has no frozen procurement contract",
        )
    contract = ProcurementContract.model_validate(raw)
    if contract.captured_state_revision != str(run.input_revision):
        raise ApiError(
            409,
            "CAPTURED_REVISION_MISMATCH",
            "Frozen contract does not match the run input revision",
        )
    return run.model_dump(mode="python"), contract


def _engine_request(
    contract: ProcurementContract, body: SalesMaterialityRequestCreate
) -> SalesMaterialityEngineRequest:
    context = context_from_contract(contract)
    if (
        body.captured_state_revision != context.captured_state_revision
        or body.as_of != context.as_of
        or body.known_at != context.known_at
    ):
        raise ApiError(
            409,
            "MATERIALITY_CONTEXT_MISMATCH",
            "Request clocks and revision must match the frozen run",
        )
    if body.issued_forecast.reference != body.issued_forecast_reference:
        raise ApiError(
            422,
            "INVALID_FORECAST_REFERENCE",
            "Issued forecast payload must carry its declared immutable reference",
        )
    state = contract.frozen_state or {}
    if any(name not in state for name in ("menu_items", "ingredients", "recipes")):
        raise ApiError(
            409,
            "MISSING_REQUIRED_DATA",
            "Frozen run has no complete catalogue",
        )
    try:
        catalogue = Catalogue.model_validate(
            {
                "menu_items": state["menu_items"],
                "ingredients": state["ingredients"],
                "recipes": state["recipes"],
            }
        )
    except (TypeError, ValueError) as error:
        raise ApiError(
            409,
            "MISSING_REQUIRED_DATA",
            "Frozen run catalogue is invalid",
        ) from error
    return SalesMaterialityEngineRequest(
        contract_reference=context.procurement_contract_reference,
        contract=contract,
        issued_forecast_reference=body.issued_forecast_reference,
        issued_forecast=body.issued_forecast,
        issued_input=contract.forecast_input,
        issued_catalogue=catalogue,
        snapshot_evidence=context.snapshot_evidence,
        threshold_policy=SalesThresholdPolicyInput(
            **context.policy.payload.model_dump(),
            evidence=context.policy.evidence,
        ),
        plan_reference=body.plan_reference,
        safety_reference=body.safety_reference,
        risk=body.risk,
    )


def create_request(
    session: Session, run_id: str, body: SalesMaterialityRequestCreate
) -> SalesMaterialityAssessment:
    lock_inventory(session)
    existing_rows = (
        session.execute(
            select(db.sales_materiality_assessments).where(
                or_(
                    db.sales_materiality_assessments.c.run_id == run_id,
                    db.sales_materiality_assessments.c.id == body.request_id,
                )
            )
        )
        .mappings()
        .all()
    )
    if len(existing_rows) > 1:
        raise ApiError(
            409,
            "MATERIALITY_REQUEST_CONFLICT",
            "Request identity and run already belong to different exchanges",
        )
    existing = existing_rows[0] if existing_rows else None
    if existing is not None:
        if existing["run_id"] != run_id or existing["id"] != body.request_id:
            raise ApiError(
                409,
                "MATERIALITY_REQUEST_CONFLICT",
                "Request identity already belongs to a different run",
            )
        from src import planning

        saved_run = planning.get_run(session, run_id)
        raw = saved_run.snapshot.get("procurement_contract")
        if raw is None:
            raise ApiError(409, "MISSING_REQUIRED_DATA", "Run has no frozen contract")
        request_hash = _canonical_hash(
            _engine_request(ProcurementContract.model_validate(raw), body).model_dump(
                mode="json"
            )
        )
        if existing["request_sha256"] != request_hash:
            raise ApiError(
                409,
                "MATERIALITY_REQUEST_CONFLICT",
                "Run already has a different immutable materiality request",
            )
        return _assessment(existing)
    run, contract = _running_contract(session, run_id)
    context = context_from_contract(contract)
    payload = _engine_request(contract, body).model_dump(mode="json")
    request_hash = _canonical_hash(payload)
    now = datetime.now(UTC)
    row = {
        "id": body.request_id,
        "run_id": run_id,
        "policy_version_id": context.policy.id,
        "captured_state_revision": context.captured_state_revision,
        "as_of": context.as_of,
        "known_at": context.known_at,
        "request_reference": f"sales-materiality-request:{body.request_id}",
        "request_sha256": request_hash,
        "request_payload": payload,
        "created_at": now,
    }
    session.execute(insert(db.sales_materiality_assessments).values(**row))
    session.execute(
        update(db.planning_runs)
        .where(db.planning_runs.c.id == run_id)
        .values(
            snapshot={
                **run["snapshot"],
                "sales_materiality_request_ref": row["request_reference"],
            }
        )
    )
    session.commit()
    return read_assessment(session, run_id)


def save_result(
    session: Session,
    run_id: str,
    request_id: str,
    body: SalesMaterialityResultWrite,
) -> SalesMaterialityAssessment:
    lock_inventory(session)
    assessment = read_assessment(session, run_id)
    if assessment.id != request_id:
        raise ApiError(
            404,
            "MATERIALITY_ASSESSMENT_NOT_FOUND",
            "Sales materiality request does not exist",
        )
    if body.request_reference != assessment.request_reference:
        raise ApiError(
            409,
            "MATERIALITY_REQUEST_MISMATCH",
            "Result must identify the exact persisted request",
        )
    result = body.result
    payload = result.model_dump(mode="json")
    result_hash = _canonical_hash(payload)
    if assessment.result is not None:
        if assessment.result_sha256 != result_hash:
            raise ApiError(
                409,
                "MATERIALITY_RESULT_CONFLICT",
                "Materiality result is already immutable",
            )
        return assessment
    run, contract = _running_contract(session, run_id)
    context = context_from_contract(contract)
    if (
        result.run_id != run_id
        or result.snapshot_reference != context.snapshot_reference
        or result.as_of != context.as_of
        or result.known_at != context.known_at
        or result.captured_state_revision != context.captured_state_revision
        or result.forecast_reference
        != assessment.engine_request.issued_forecast_reference
        or result.forecast_input_reference != context.forecast_input_reference
        or result.threshold_policy_version != context.policy.version
        or result.coverage_through != contract.policy.payload.horizon_end
    ):
        raise ApiError(
            409,
            "MATERIALITY_RESULT_CONTEXT_MISMATCH",
            "Result does not match the exact frozen request context",
        )
    required_refs = {
        context.snapshot_reference,
        context.policy.evidence.reference,
        context.forecast_input_reference,
        assessment.engine_request.issued_forecast_reference,
    }
    if not required_refs <= set(result.evidence_refs):
        raise ApiError(
            409,
            "MATERIALITY_EVIDENCE_INCOMPLETE",
            "Result omits required immutable request evidence",
        )
    result_reference = f"sales-materiality-result:{request_id}"
    completed_at = datetime.now(UTC)
    session.execute(
        update(db.sales_materiality_assessments)
        .where(db.sales_materiality_assessments.c.id == request_id)
        .values(
            result_reference=result_reference,
            result_sha256=result_hash,
            result_payload=payload,
            completed_at=completed_at,
        )
    )
    session.execute(
        update(db.planning_runs)
        .where(db.planning_runs.c.id == run_id)
        .values(
            snapshot={
                **run["snapshot"],
                "sales_materiality_request_ref": assessment.request_reference,
                "sales_materiality_result_ref": result_reference,
            }
        )
    )
    session.commit()
    return read_assessment(session, run_id)
