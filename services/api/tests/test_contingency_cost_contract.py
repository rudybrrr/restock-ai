"""Cash-only contingency plans must not claim unavailable economic estimates."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.agent_contracts import (
    EvidenceCategory,
    EvidenceRef,
    EvidenceSource,
    PlanCostScope,
    PlanStatus,
    PurchasePlanLine,
)
from src.agent_contracts import (
    PurchasePlanVersion as CanonicalPlanVersion,
)
from src.manager_evidence import _plan_reference
from src.planning import _same_candidate
from src.planning_schemas import Candidate, PlanLine, PurchasePlanVersion

NOW = datetime(2026, 2, 16, 11, tzinfo=UTC)


def _cash_only_candidate() -> dict:
    return Candidate(
        calculation_mode="CONTINGENCY_ENGINE",
        forecast_id="forecast:residual",
        inventory_snapshot_id="inventory:frozen",
        lines=[
            PlanLine(
                ingredient_id="vegetables",
                supplier_id="market",
                offer_id="market-vegetables",
                opportunity_id="rescue",
                shipment_group_id="new-rescue-shipment",
                quantity=Decimal(4),
                unit_price=Decimal(2),
                arrival_at=NOW,
            )
        ],
        total_purchase_cost=Decimal(8),
        expected_waste_cost=None,
        expected_stockout_cost=None,
        delivery_cost=Decimal(3),
        emergency_penalty=Decimal(4),
        total_expected_cost=None,
        cost_scope=PlanCostScope.NEW_PURCHASE_CASH_ONLY,
        new_purchase_cash_cost=Decimal(15),
    ).model_dump()


def _ref(category: EvidenceCategory) -> EvidenceRef:
    return EvidenceRef(
        category=category,
        source=EvidenceSource.BACKEND,
        reference_id=category.value,
        version=1,
    )


def test_contingency_cash_scope_survives_canonical_publication() -> None:
    candidate = Candidate.model_validate(_cash_only_candidate())
    plan = CanonicalPlanVersion(
        id="version:rescue",
        plan_id="plan:rescue",
        version=1,
        status=PlanStatus.PENDING_APPROVAL,
        forecast_ref=_ref(EvidenceCategory.FORECAST_RESULT),
        inventory_snapshot_ref=_ref(EvidenceCategory.INVENTORY_SNAPSHOT),
        candidate_result_ref=_ref(EvidenceCategory.CANDIDATE_RESULT),
        created_at=NOW,
        trigger_id="event:delay",
        state_revision="12",
        lines=[
            PurchasePlanLine(
                ingredient_id="vegetables",
                supplier_id="market",
                offer_id="market-vegetables",
                opportunity_id="rescue",
                shipment_group_id="new-rescue-shipment",
                quantity=Decimal(4),
                unit="kg",
                unit_price=Decimal(2),
                delivery_at=NOW,
            )
        ],
        total_purchase_cost=candidate.total_purchase_cost,
        expected_waste_cost=candidate.expected_waste_cost,
        expected_stockout_cost=candidate.expected_stockout_cost,
        delivery_cost=candidate.delivery_cost,
        emergency_penalty=candidate.emergency_penalty,
        total_expected_cost=candidate.total_expected_cost,
        cost_scope=candidate.cost_scope,
        new_purchase_cash_cost=candidate.new_purchase_cash_cost,
        approval_reason="MANAGER_APPROVAL_REQUIRED",
    )
    assert plan.new_purchase_cash_cost == Decimal(15)
    assert plan.total_expected_cost is None
    manager_reference = _plan_reference(
        PurchasePlanVersion(
            **candidate.model_dump(),
            id=plan.id,
            plan_id=plan.plan_id,
            version=plan.version,
            status=plan.status,
            run_id="run:delay",
            created_at=NOW,
        )
    )
    assert manager_reference.total_expected_cost is None
    assert manager_reference.new_purchase_cash_cost == "15"
    with pytest.raises(ValidationError):
        CanonicalPlanVersion.model_validate(
            {**plan.model_dump(), "expected_waste_cost": Decimal(0)}
        )


@pytest.mark.parametrize(
    "change",
    [
        {"expected_waste_cost": Decimal(0)},
        {"expected_stockout_cost": Decimal(0)},
        {"total_expected_cost": Decimal(15)},
        {"new_purchase_cash_cost": Decimal(14)},
        {"new_purchase_cash_cost": None},
        {"calculation_mode": "ENGINE"},
        {"total_purchase_cost": Decimal(-1), "delivery_cost": Decimal(12)},
    ],
)
def test_cash_only_candidate_rejects_false_or_missing_cost_claims(change: dict) -> None:
    with pytest.raises(ValidationError):
        Candidate.model_validate({**_cash_only_candidate(), **change})


def test_stored_legacy_candidate_without_new_fields_still_matches() -> None:
    raw = {
        **_cash_only_candidate(),
        "calculation_mode": "ENGINE",
        "expected_waste_cost": Decimal(0),
        "expected_stockout_cost": Decimal(0),
        "total_expected_cost": Decimal(15),
    }
    raw.pop("cost_scope")
    raw.pop("new_purchase_cash_cost")
    assert _same_candidate(raw, Candidate.model_validate(raw))
