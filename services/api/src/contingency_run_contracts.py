"""Bind the staged numerical case to one immutable Backend run, without activation."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)
from sqlalchemy.orm import Session

from src.contingency_case_contracts import FIRST_CASE_ID, read_case_input
from src.contingency_case_schemas import ContingencyCaseInputVersion, catalogue_sha256
from src.contingency_policy_contracts import read_policy_version_by_id
from src.contingency_policy_schemas import ContingencyPolicyVersion
from src.errors import ApiError
from src.procurement_contract_schemas import FrozenCommitmentProjection
from src.schemas import (
    EstimatedInventoryLot,
    Ingredient,
    MenuItem,
    RecipeItem,
    Supplier,
)

CASE_ISSUE = datetime.fromisoformat("2026-02-16T10:00:00+08:00")


class StagedContingencyCase(BaseModel):
    """Frozen first-case evidence; never an activated procurement selection."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["STAGED_MATCH", "STAGED_MISMATCH", "UNAVAILABLE"]
    run_id: str
    as_of: AwareDatetime
    known_at: AwareDatetime
    captured_state_revision: str
    findings: list[str] = Field(default_factory=list)
    reason: str | None = None
    policy: ContingencyPolicyVersion | None = None
    case_input: ContingencyCaseInputVersion | None = None
    opening_lots: list[EstimatedInventoryLot] | None = None
    commitment_projection: FrozenCommitmentProjection | None = None

    @model_validator(mode="after")
    def complete_match(self) -> "StagedContingencyCase":
        if self.status == "UNAVAILABLE":
            if self.reason is None:
                raise ValueError("Unavailable staged case needs a reason")
        elif (
            self.policy is None or self.case_input is None or self.opening_lots is None
        ):
            raise ValueError("Staged case needs policy, case and opening evidence")
        if self.status == "STAGED_MATCH" and (
            self.findings or self.commitment_projection is None
        ):
            raise ValueError("A matched staged case must carry complete fixed supply")
        return self


def freeze_staged_case(
    session: Session, snapshot: dict, run_id: str, captured_state_revision: int
) -> dict | None:
    """Report exact first-case matching; STAGED data never selects an Agent policy."""
    as_of = datetime.fromisoformat(snapshot["as_of"])
    if as_of != CASE_ISSUE:
        return None
    known_at = datetime.fromisoformat(snapshot["known_at"])
    try:
        case = read_case_input(session, FIRST_CASE_ID, 3)
        policy = read_policy_version_by_id(session, case.policy_version_id)
    except ApiError as error:
        return StagedContingencyCase.model_validate(
            {
                "status": "UNAVAILABLE",
                "reason": error.detail.code,
                "run_id": run_id,
                "as_of": snapshot["as_of"],
                "known_at": snapshot["known_at"],
                "captured_state_revision": str(captured_state_revision),
            }
        ).model_dump(mode="json")
    if case.recorded_at > known_at or policy.recorded_at > known_at:
        return StagedContingencyCase.model_validate(
            {
                "status": "UNAVAILABLE",
                "reason": "CASE_NOT_KNOWN_AT_CAPTURE",
                "run_id": run_id,
                "as_of": snapshot["as_of"],
                "known_at": snapshot["known_at"],
                "captured_state_revision": str(captured_state_revision),
            }
        ).model_dump(mode="json")

    payload = case.payload
    findings: set[str] = set()
    if (
        policy.payload.activation_state != "STAGED"
        or policy.payload.approved_domain_id != payload.domain_id
        or policy.payload.forecast_artifact_id != case.id
    ):
        findings.add("POLICY_REFERENCE_MISMATCH")
    if payload.offer_authority != "APPROVED_SYNTHETIC_DEMO_QUOTE":
        findings.add("OFFER_AUTHORITY_MISSING")
    try:
        menu = [MenuItem.model_validate(row) for row in snapshot["menu_items"]]
        ingredients = [
            Ingredient.model_validate(row) for row in snapshot["ingredients"]
        ]
        recipes = [RecipeItem.model_validate(row) for row in snapshot["recipes"]]
        suppliers = [Supplier.model_validate(row) for row in snapshot["suppliers"]]
        catalogue_matches = (
            payload.catalogue_sha256 is not None
            and catalogue_sha256(menu, ingredients, recipes, suppliers)
            == payload.catalogue_sha256
        )
    except (KeyError, ValidationError, ValueError):
        catalogue_matches = False
    if not catalogue_matches:
        findings.add("CATALOGUE_MISMATCH")

    opening = {ingredient: Decimal(0) for ingredient in payload.ingredient_ids}
    try:
        lots = [
            EstimatedInventoryLot.model_validate(row) for row in snapshot["inventory"]
        ]
    except (KeyError, ValidationError):
        lots = []
        findings.add("OPENING_COVERAGE_INCOMPLETE")
    for lot in lots:
        if lot.ingredient_id not in opening:
            findings.add("CATALOGUE_MISMATCH")
            continue
        if lot.status == "ACTIVE":
            if not lot.coverage_complete or lot.unallocated_consumption:
                findings.add("OPENING_COVERAGE_INCOMPLETE")
            opening[lot.ingredient_id] += lot.quantity
    if opening != payload.opening_expected:
        findings.add("OPENING_MISMATCH")

    commitments = snapshot["commitments"]
    projection = snapshot.get("procurement_contract", {}).get("commitment_projection")
    if len(commitments) != 1 or projection is None:
        findings.add("FIXED_SUPPLY_MISMATCH")
    else:
        fixed = commitments[0]
        expected = payload.fixed_supply_expected
        if (
            fixed["supplier_id"] != expected.supplier_id
            or fixed["ingredient_id"] != expected.ingredient_id
            or fixed["kind"] != expected.kind
            or datetime.fromisoformat(fixed["ordered_at"]) != expected.ordered_at
            or datetime.fromisoformat(fixed["expected_at"]) != expected.expected_at
            or fixed.get("expected_expiry_date")
            != expected.received_expiry_date.isoformat()
            or any(
                Decimal(fixed[field]) != getattr(expected, field)
                for field in (
                    "expected_quantity",
                    "received_quantity",
                    "cancelled_quantity",
                    "outstanding_quantity",
                )
            )
        ):
            findings.add("FIXED_SUPPLY_MISMATCH")
        receipts = fixed["receipts"]
        if len(receipts) != 1:
            findings.add("RECEIPT_MISMATCH")
        else:
            receipt = receipts[0]
            received_lot = next(
                (lot for lot in lots if lot.id == receipt["lot_id"]), None
            )
            if (
                Decimal(receipt["quantity"]) != expected.received_quantity
                or receipt["expiry_date"] != expected.received_expiry_date.isoformat()
                or received_lot is None
                or received_lot.ingredient_id != expected.ingredient_id
                or received_lot.quantity != expected.received_quantity
                or received_lot.expiry_date != expected.received_expiry_date
            ):
                findings.add("RECEIPT_MISMATCH")
        supplies = projection["supplies"]
        if (
            not projection["complete"]
            or projection["supply_manifest"] != [fixed["id"]]
            or len(supplies) != 1
            or supplies[0]["delivery"]["id"] != fixed["id"]
            or supplies[0]["expiry_date"] != expected.received_expiry_date.isoformat()
            or supplies[0]["expiry_evidence"] is None
            or supplies[0]["expiry_evidence"]["reference"]
            != f"delivery:{fixed['id']}:expected_expiry_date"
            or supplies[0]["expiry_evidence"]["captured_revision"]
            != fixed.get("terms_event_id")
        ):
            findings.add("FIXED_SUPPLY_PROJECTION_MISMATCH")

    return StagedContingencyCase.model_validate(
        {
            "status": "STAGED_MATCH" if not findings else "STAGED_MISMATCH",
            "findings": sorted(findings),
            "run_id": run_id,
            "as_of": snapshot["as_of"],
            "known_at": snapshot["known_at"],
            "captured_state_revision": str(captured_state_revision),
            "policy": policy.model_dump(mode="json"),
            "case_input": case.model_dump(mode="json"),
            "opening_lots": [lot.model_dump(mode="json") for lot in lots],
            "commitment_projection": projection,
        }
    ).model_dump(mode="json")
