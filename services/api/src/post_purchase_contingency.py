"""Bounded post-purchase Backend contract. No Agent/model or Delivery writes."""

from datetime import datetime
from decimal import Decimal
from typing import Literal, cast

from pydantic import AwareDatetime, BaseModel, ConfigDict, JsonValue, ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src import database as db
from src.agent_contracts import EscalationReason, PlanCostScope
from src.contingency import search_contingency, validate_contingency
from src.contingency_artifacts import _jsonable, _sha256
from src.contingency_case_contracts import FIRST_CASE_ID, read_case_input
from src.contingency_case_schemas import catalogue_sha256
from src.contingency_policy_contracts import read_policy_version_by_id
from src.contingency_run_contracts import CASE_ISSUE, StagedContingencyCase
from src.contingency_stage_adapter import _approved_kind, inputs_from_frozen_case
from src.errors import ApiError
from src.operations import lock_inventory
from src.planning_schemas import Candidate, PlanLine, PlanningRun
from src.schemas import (
    EstimatedInventoryLot,
    Ingredient,
    MenuItem,
    RecipeItem,
    Supplier,
)

INPUT_KEY = "post_purchase_contingency_input"
RESULT_KEY = "post_purchase_contingency_result"
RULE = "POST_PURCHASE_FIXED_SUPPLY_V1"
RECEIPT_ISSUE = datetime.fromisoformat("2026-02-16T11:00:00+08:00")


class PostPurchaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["POST_PURCHASE_FIXED_SUPPLY_V1"] = RULE
    run_id: str
    as_of: AwareDatetime
    known_at: AwareDatetime
    captured_state_revision: str
    complete: bool
    findings: list[str]
    fixed_delivery_ids: list[str]
    source_plan_version_id: str | None
    case: StagedContingencyCase | None


class PostPurchaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["POST_PURCHASE_FIXED_SUPPLY_V1"] = RULE
    id: str
    input_sha256: str
    run_id: str
    as_of: AwareDatetime
    known_at: AwareDatetime
    captured_state_revision: str
    complete: bool
    outcome: Literal["KEEP_CURRENT_PLAN", "REVISE_PLAN", "ESCALATE"]
    escalation_reason: EscalationReason | None
    findings: list[str]
    fixed_delivery_ids: list[str]
    candidate: Candidate | None
    candidate_reference: str | None
    numerical_result: dict[str, JsonValue] | None
    independent_validation: dict[str, JsonValue] | None


def freeze_post_purchase_input(
    session: Session, snapshot: dict, run_id: str, revision: int
) -> dict | None:
    """Select two explicit fixture clocks; mismatches never fall back to normal."""
    commitments = snapshot["commitments"]
    emergency = [r for r in commitments if r["kind"] == "EMERGENCY"]
    if not any(
        row["supplier_id"] == "market"
        and row["ingredient_id"] == "vegetables"
        and datetime.fromisoformat(row["ordered_at"]) == CASE_ISSUE
        for row in emergency
    ):
        return None
    as_of = datetime.fromisoformat(snapshot["as_of"])
    known_at = datetime.fromisoformat(snapshot["known_at"])
    findings: set[str] = set()
    frozen = None
    source_version = None
    if as_of not in (CASE_ISSUE, RECEIPT_ISSUE):
        findings.add("UNSUPPORTED_POST_PURCHASE_CLOCK")
    if len(commitments) != 2 or len(emergency) != 1:
        findings.add("UNSUPPORTED_FIXED_SUPPLY_SET")
    if not findings:
        try:
            case = read_case_input(
                session, FIRST_CASE_ID, 5 if as_of == CASE_ISSUE else 6
            )
            policy = read_policy_version_by_id(session, case.policy_version_id)
            if case.effective_at > as_of or policy.effective_at > as_of:
                findings.add("AUTHORITY_NOT_EFFECTIVE_AT_OPENING")
            if case.recorded_at > known_at or policy.recorded_at > known_at:
                findings.add("AUTHORITY_NOT_KNOWN_AT_CAPTURE")
            if (
                case.source_revision != f"{RULE}:{case.version}"
                or policy.payload.activation_state != "ACTIVE"
            ):
                findings.add("POST_PURCHASE_AUTHORITY_MISMATCH")
            payload = case.payload
            catalogue = catalogue_sha256(
                [MenuItem.model_validate(x) for x in snapshot["menu_items"]],
                [Ingredient.model_validate(x) for x in snapshot["ingredients"]],
                [RecipeItem.model_validate(x) for x in snapshot["recipes"]],
                [Supplier.model_validate(x) for x in snapshot["suppliers"]],
            )
            if catalogue != payload.catalogue_sha256:
                findings.add("CATALOGUE_MISMATCH")
            if snapshot["promotions"]:
                findings.add("UNSUPPORTED_PROMOTION_CONTEXT")
            original = next(r for r in commitments if r["kind"] == "NORMAL")
            expected = payload.fixed_supply_expected
            for key in ("supplier_id", "ingredient_id", "kind"):
                if original[key] != getattr(expected, key):
                    findings.add("ORIGINAL_COMMITMENT_MISMATCH")
            for key in ("ordered_at", "expected_at"):
                if datetime.fromisoformat(original[key]) != getattr(expected, key):
                    findings.add("ORIGINAL_COMMITMENT_MISMATCH")
            for key in (
                "expected_quantity",
                "received_quantity",
                "cancelled_quantity",
                "outstanding_quantity",
            ):
                if Decimal(original[key]) != getattr(expected, key):
                    findings.add("ORIGINAL_COMMITMENT_MISMATCH")
            if (
                original.get("expected_expiry_date")
                != expected.received_expiry_date.isoformat()
            ):
                findings.add("ORIGINAL_EXPIRY_MISMATCH")
            rescue = emergency[0]
            line = (
                session.execute(
                    select(db.purchase_plan_lines).where(
                        db.purchase_plan_lines.c.id == rescue.get("source_plan_line_id")
                    )
                )
                .mappings()
                .one_or_none()
            )
            if line is None or rescue.get("source_validation") != "APPROVED_ALLOCATION":
                findings.add("MISSING_APPROVED_PURCHASE_LINEAGE")
            else:
                source_version = line["plan_version_id"]
                parent = (
                    session.execute(
                        select(db.plan_versions).where(
                            db.plan_versions.c.id == source_version
                        )
                    )
                    .mappings()
                    .one()
                )
                parent_run = (
                    session.execute(
                        select(db.planning_runs).where(
                            db.planning_runs.c.id == parent["run_id"]
                        )
                    )
                    .mappings()
                    .one()
                )
                latest_active = session.execute(
                    select(db.plan_versions.c.id)
                    .where(
                        db.plan_versions.c.status.in_(("PENDING_APPROVAL", "APPROVED"))
                    )
                    .order_by(db.plan_versions.c.created_at.desc())
                    .limit(1)
                ).scalar_one_or_none()
                if latest_active is not None and latest_active != source_version:
                    findings.add("UNSUPPORTED_NEWER_PLAN")
                parent_case = parent_run["snapshot"].get("active_contingency_case", {})
                original_ids = (
                    parent_run["snapshot"]
                    .get("decision_engine_artifacts", {})
                    .get("fixed_supply_ids")
                )
                if (
                    parent_case.get("status") != "ACTIVE_MATCH"
                    or parent_case.get("case_input", {}).get("id")
                    != f"case-input:{FIRST_CASE_ID}:4"
                    or original_ids != [original["id"]]
                    or parent["created_at"] > known_at
                    or line["kind"] != "EMERGENCY"
                    or line["quantity"] != Decimal(4)
                ):
                    findings.add("PARENT_FIRST_CASE_MISMATCH")
            if (
                rescue["supplier_id"] != "market"
                or rescue["ingredient_id"] != "vegetables"
                or datetime.fromisoformat(rescue["ordered_at"]) != CASE_ISSUE
                or Decimal(rescue["expected_quantity"]) > 4
            ):
                findings.add("EMERGENCY_PURCHASE_OUTSIDE_RULE")
            lots = [
                EstimatedInventoryLot.model_validate(x) for x in snapshot["inventory"]
            ]
            expected_opening = dict(payload.opening_expected)
            expected_opening["vegetables"] += Decimal(rescue["received_quantity"])
            opening = dict.fromkeys(payload.ingredient_ids, Decimal(0))
            if {lot.ingredient_id for lot in lots} != set(opening):
                findings.add("OPENING_MANIFEST_INCOMPLETE")
            for lot in lots:
                if lot.status == "ACTIVE":
                    if (
                        not lot.coverage_complete
                        or lot.unallocated_consumption
                        or lot.as_of != as_of
                    ):
                        findings.add("OPENING_COVERAGE_INCOMPLETE")
                    if lot.ingredient_id in opening:
                        opening[lot.ingredient_id] += lot.quantity
            if opening != expected_opening:
                findings.add("OPENING_OUTSIDE_BOUNDED_CASE")
            for fixed in commitments:
                for receipt in fixed["receipts"]:
                    lot = next((x for x in lots if x.id == receipt["lot_id"]), None)
                    if (
                        lot is None
                        or lot.quantity != Decimal(receipt["quantity"])
                        or lot.ingredient_id != fixed["ingredient_id"]
                        or lot.expiry_date.isoformat() != receipt["expiry_date"]
                    ):
                        findings.add("RECEIPT_OPENING_MISMATCH")
            projection = snapshot.get("procurement_contract", {}).get(
                "commitment_projection"
            )
            if (
                projection is None
                or not projection["complete"]
                or sorted(projection["supply_manifest"])
                != sorted(x["id"] for x in commitments)
            ):
                findings.add("FIXED_SUPPLY_COVERAGE_INCOMPLETE")
            if not findings:
                frozen = StagedContingencyCase(
                    status="ACTIVE_MATCH",
                    run_id=run_id,
                    as_of=as_of,
                    known_at=known_at,
                    captured_state_revision=str(revision),
                    policy=policy,
                    case_input=case,
                    opening_lots=lots,
                    commitment_projection=projection,
                )
        except ApiError as error:
            findings.add(
                "POST_PURCHASE_EVIDENCE_UNAVAILABLE:"
                + error.detail.code
                + ":"
                + error.detail.message
            )
        except (ValidationError, KeyError, ValueError, StopIteration):
            findings.add("POST_PURCHASE_EVIDENCE_UNAVAILABLE")
    return PostPurchaseInput(
        run_id=run_id,
        as_of=as_of,
        known_at=known_at,
        captured_state_revision=str(revision),
        complete=not findings,
        findings=sorted(findings),
        fixed_delivery_ids=sorted(x["id"] for x in commitments),
        source_plan_version_id=source_version,
        case=frozen,
    ).model_dump(mode="json")


def select_post_purchase_input(run: PlanningRun) -> PostPurchaseInput | None:
    raw = run.snapshot.get(INPUT_KEY)
    if raw is None:
        return None
    result = PostPurchaseInput.model_validate(raw)
    if (
        result.run_id != run.id
        or result.as_of != run.as_of
        or result.known_at != datetime.fromisoformat(run.snapshot["known_at"])
        or result.captured_state_revision != str(run.input_revision)
    ):
        raise ApiError(
            409, "STATE_REVISION_STALE", "Post-purchase input does not match run"
        )
    return result


def _result_id(body: dict) -> str:
    return "post-purchase:" + _sha256(
        _jsonable({k: v for k, v in body.items() if k != "id"})
    )


def read_post_purchase_result(session: Session, run_id: str) -> PostPurchaseResult:
    from src import planning

    run = planning.get_run(session, run_id)
    frozen = select_post_purchase_input(run)
    raw = run.snapshot.get(RESULT_KEY)
    if frozen is None or raw is None:
        raise ApiError(
            409, "MISSING_REQUIRED_DATA", "Post-purchase result not calculated"
        )
    result = PostPurchaseResult.model_validate(raw)
    if (
        result.input_sha256 != _sha256(_jsonable(frozen))
        or result.id != _result_id(result.model_dump(mode="json"))
        or result.run_id != run.id
        or result.captured_state_revision != str(run.input_revision)
        or result.as_of != frozen.as_of
        or result.known_at != frozen.known_at
    ):
        raise ApiError(
            409, "STATE_REVISION_STALE", "Post-purchase result identity mismatch"
        )
    return result


def persist_post_purchase_result(session: Session, run_id: str) -> PostPurchaseResult:
    """Compute from frozen facts, validate independently, then persist without ordering."""
    from src import planning

    lock_inventory(session)
    run = planning.get_run(session, run_id)
    if run.status != "RUNNING":
        raise ApiError(409, "RUN_NOT_RUNNING", "Only a claimed run can calculate")
    if planning.current_state_revision(session) != str(run.input_revision):
        raise ApiError(409, "STATE_REVISION_STALE", "Inputs changed after claim")
    frozen = select_post_purchase_input(run)
    if frozen is None:
        raise ApiError(409, "MISSING_REQUIRED_DATA", "No post-purchase input selected")
    if RESULT_KEY in run.snapshot:
        return read_post_purchase_result(session, run_id)
    numerical = validation = candidate = None
    complete = False
    outcome = "ESCALATE"
    reason = (
        EscalationReason.CALCULATION_INCOMPLETE
        if any(x.startswith("UNSUPPORTED") for x in frozen.findings)
        else EscalationReason.MISSING_REQUIRED_DATA
    )
    findings = list(frozen.findings)
    if frozen.complete and frozen.case is not None:
        inputs = inputs_from_frozen_case(run, frozen.case)
        numerical = search_contingency(inputs)
        complete = numerical.search_complete
        findings += [f"{x.code}:{x.source}" for x in numerical.findings]
        if numerical.status == "INFEASIBLE_IN_DOMAIN":
            reason = (
                EscalationReason.NO_FEASIBLE_SUPPLIER
                if numerical.reason == "NO_TIMELY_SUPPLY_IN_DOMAIN"
                else EscalationReason.POLICY_VIOLATION
            )
        elif numerical.status != "OPTIMAL_IN_DOMAIN" or numerical.candidate is None:
            reason = (
                EscalationReason.CALCULATION_INCOMPLETE
                if numerical.reason == "SEARCH_LIMIT_REACHED"
                or any("UNSUPPORTED" in x.code for x in numerical.findings)
                else EscalationReason.MISSING_REQUIRED_DATA
            )
        else:
            validation = validate_contingency(inputs, numerical.candidate)
            if (
                validation != numerical.validation
                or not validation.complete
                or not validation.feasible
                or validation.cash is None
            ):
                complete = False
                reason = EscalationReason.POLICY_VIOLATION
                findings.append("INDEPENDENT_VALIDATION_FAILED")
            else:
                outcome = "REVISE_PLAN" if validation.additions else "KEEP_CURRENT_PLAN"
                reason = None
                offers = {x.id: x for x in inputs.offers}
                assert frozen.case.case_input is not None
                candidate = Candidate(
                    calculation_mode="CONTINGENCY_ENGINE",
                    forecast_id=frozen.case.case_input.id,
                    inventory_snapshot_id=run.snapshot["inventory_snapshot_id"],
                    lines=[
                        PlanLine(
                            ingredient_id=x.ingredient_id,
                            supplier_id=x.supplier_id,
                            offer_id=x.offer_id,
                            opportunity_id=x.opportunity_id,
                            shipment_group_id=x.shipment_group_id,
                            quantity=x.quantity,
                            unit_price=cast(Decimal, offers[x.offer_id].unit_price),
                            arrival_at=x.arrival_at,
                            ordered_at=x.ordered_at,
                            expiry_date=x.expiry_date,
                            kind=_approved_kind(x.kind),
                        )
                        for x in validation.additions
                    ],
                    total_purchase_cost=validation.cash.acquisition,
                    delivery_cost=validation.cash.delivery,
                    emergency_penalty=validation.cash.emergency,
                    expected_waste_cost=None,
                    expected_stockout_cost=None,
                    total_expected_cost=None,
                    cost_scope=PlanCostScope.NEW_PURCHASE_CASH_ONLY,
                    new_purchase_cash_cost=validation.cash.total,
                )
    candidate_ref = (
        "candidate:" + _sha256(candidate.model_dump(mode="json")) if candidate else None
    )
    result = PostPurchaseResult(
        id="pending",
        input_sha256=_sha256(_jsonable(frozen)),
        run_id=run.id,
        as_of=frozen.as_of,
        known_at=frozen.known_at,
        captured_state_revision=str(run.input_revision),
        complete=complete,
        outcome=outcome,
        escalation_reason=reason,
        findings=findings,
        fixed_delivery_ids=frozen.fixed_delivery_ids,
        candidate=candidate,
        candidate_reference=candidate_ref,
        numerical_result=cast(dict[str, JsonValue], _jsonable(numerical))
        if numerical
        else None,
        independent_validation=cast(dict[str, JsonValue], _jsonable(validation))
        if validation
        else None,
    )
    result = result.model_copy(
        update={"id": _result_id(result.model_dump(mode="json"))}
    )
    snapshot = {**run.snapshot, RESULT_KEY: result.model_dump(mode="json")}
    if candidate is not None:
        snapshot["calculated_candidate"] = candidate.model_dump(mode="json")
        snapshot["decision_engine_artifacts"] = {
            "input": {
                "id": "engine-input:" + result.input_sha256,
                "case": _jsonable(frozen),
            },
            "candidate": {
                "id": candidate_ref,
                "candidate": candidate.model_dump(mode="json"),
            },
            "validation": {
                "id": result.id + ":validation",
                "candidate_id": candidate_ref,
                "complete": True,
                "feasible": True,
                "independent_result": result.independent_validation,
            },
            "search_result": result.numerical_result,
            "fixed_supply_ids": result.fixed_delivery_ids,
        }
    session.execute(
        update(db.planning_runs)
        .where(db.planning_runs.c.id == run.id)
        .values(snapshot=snapshot)
    )
    session.commit()
    return result


def result_for_completion(
    session: Session, run: PlanningRun
) -> PostPurchaseResult | None:
    if select_post_purchase_input(run) is None:
        return None
    return read_post_purchase_result(session, run.id)
