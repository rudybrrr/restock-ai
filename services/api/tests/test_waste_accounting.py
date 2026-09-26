"""Independent waste/count oracles; proposed fixture semantics, no database."""

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal, localcontext

import pytest

from src.inventory_projection import SourceEvidence
from src.schemas import Ingredient, InventoryLot
from src.waste_accounting import (
    WASTE_POLICY,
    WasteRevision,
    apply_waste_at,
    select_waste_effects,
)

D = Decimal


def clock(hour=12, day=16):
    return datetime.fromisoformat(f"2026-02-{day:02}T{hour:02}:00:00+08:00")


@pytest.fixture
def inputs():
    return {
        "lots": [
            InventoryLot(
                id="received-chicken",
                ingredient_id="chicken",
                unit="kg",
                received_at=clock(8),
                expiry_date=date(2026, 2, 16),
                initial_quantity=D(10),
                quantity=D(10),
                counted_at=clock(8),
            )
        ],
        "ingredients": [
            Ingredient(
                id="chicken",
                name="Chicken",
                unit="kg",
                interval_days=1,
                starting_date=date(2026, 2, 15),
            )
        ],
        "as_of": clock(20),
        "known_at": clock(21),
        "captured_revision": "synthetic-state-1",
        "observation_manifest": ["spill-1"],
        "evidence": {
            name: SourceEvidence(
                f"synthetic-{name}",
                clock(20),
                "synthetic-state-1",
            )
            for name in ("waste", "counts", "lots", "catalogue")
        },
        "policy": WASTE_POLICY,
    }


@pytest.fixture
def revision():
    return WasteRevision(
        observation_id="spill-1",
        revision_id="spill-1-r1",
        revision=1,
        replaces_revision_id=None,
        lot_id="received-chicken",
        ingredient_id="chicken",
        unit="kg",
        quantity=D("2.125"),
        observed_at=clock(12),
        recorded_at=clock(13),
        actor="synthetic-manager",
        reversed=False,
    )


def apply(selection, usable="10", expired="0", applied=()):
    return apply_waste_at(
        selection,
        at=clock(12),
        usable_before={"received-chicken": D(usable)},
        expired_before={"received-chicken": D(expired)},
        already_applied_revision_ids=applied,
    )


def test_exact_deduction_and_idempotent_retry(inputs, revision):
    result = select_waste_effects([revision, revision], **inputs)
    assert result.complete and result.effects is not None
    assert len(result.effects) == 1  # repeated transport row is not another spill
    first = apply(result)
    assert first.complete and first.lots is not None
    assert first.lots[0].usable_after == D("7.875")  # 10 - 2.125
    assert first.lots[0].expired_after == 0
    retry = apply(result, "7.875", applied=first.applied_revision_ids)
    assert retry.complete and retry.lots is not None
    assert retry.lots[0].usable_after == D("7.875")
    assert retry.lots[0].usable_deducted == 0
    assert revision.quantity == D("2.125")
    assert inputs["lots"][0].quantity == 10


def test_late_correction_replays_original_time_without_double_deduction(
    inputs, revision
):
    correction = replace(
        revision,
        revision=2,
        revision_id="spill-1-r2",
        replaces_revision_id=revision.revision_id,
        quantity=D("1.25"),
        recorded_at=clock(22),
    )
    earlier = select_waste_effects([correction, revision], **inputs)
    first = apply(earlier)
    assert first.lots is not None
    assert first.lots[0].usable_after == D("7.875")
    inputs["known_at"] = clock(23)
    later = select_waste_effects([correction, revision], **inputs)
    corrected = apply(later)
    assert corrected.lots is not None and later.effects is not None
    assert corrected.lots[0].usable_after == D("8.75")  # 10 - replacement 1.25
    assert later.effects[0].observed_at == clock(12)
    with pytest.raises(ValueError, match="Superseded.*replay"):
        apply(later, "7.875", applied=(revision.revision_id,))


def test_reversal_keeps_evidence_and_has_no_effect(inputs, revision):
    reversal = replace(
        revision,
        revision=2,
        revision_id="spill-1-r2",
        replaces_revision_id=revision.revision_id,
        reversed=True,
        recorded_at=clock(14),
    )
    selected = select_waste_effects([revision, reversal], **inputs)
    assert selected.effects is not None
    assert selected.effects[0].disposition == "REVERSED"
    assert selected.effects[0].recorded_quantity == D("2.125")
    assert selected.effects[0].effective_quantity == 0
    result = apply_waste_at(
        selected,
        at=clock(12),
        usable_before={},
        expired_before={},
        already_applied_revision_ids=(),
    )
    assert result.complete and result.lots == ()


@pytest.mark.parametrize("count_hour", [12, 18])
def test_equal_or_later_physical_count_absorbs_waste(inputs, revision, count_hour):
    inputs["lots"][0] = inputs["lots"][0].model_copy(
        update={"counted_at": clock(count_hour), "quantity": D("6.5")}
    )
    selected = select_waste_effects([revision], **inputs)
    assert selected.effects is not None
    assert selected.effects[0].disposition == "ABSORBED_BY_COUNT"
    assert selected.effects[0].effective_quantity == 0
    # Latest count remains 6.5; not 6.5 - 2.125, and not inferred waste of 3.5.
    assert inputs["lots"][0].quantity == D("6.5")


def test_late_correction_before_closing_count_stays_absorbed(inputs, revision):
    inputs["lots"][0] = inputs["lots"][0].model_copy(
        update={"counted_at": clock(18), "quantity": D(6)}
    )
    correction = replace(
        revision,
        revision=2,
        revision_id="r2",
        replaces_revision_id=revision.revision_id,
        quantity=D(3),
        recorded_at=clock(21),
    )
    selected = select_waste_effects([correction, revision], **inputs)
    assert selected.effects is not None
    assert selected.effects[0].effective_quantity == 0
    assert selected.effects[0].recorded_quantity == 3


def test_expired_disposal_at_midnight_is_not_second_usable_loss(inputs, revision):
    inputs.update(as_of=clock(2, 17), known_at=clock(3, 17))
    revision = replace(revision, observed_at=clock(0, 17), recorded_at=clock(1, 17))
    selected = select_waste_effects([revision], **inputs)
    assert selected.effects is not None
    assert selected.effects[0].disposition == "DISPOSE_EXPIRED"
    result = apply_waste_at(
        selected,
        at=clock(0, 17),
        usable_before={"received-chicken": D(0)},
        expired_before={"received-chicken": D(4)},
        already_applied_revision_ids=(),
    )
    assert result.complete and result.lots is not None
    assert result.lots[0].usable_after == 0
    assert result.lots[0].usable_deducted == 0
    assert result.lots[0].expired_after == D("1.875")


def test_expired_zero_usable_does_not_prove_disposal_capacity(inputs, revision):
    inputs.update(as_of=clock(2, 17), known_at=clock(3, 17))
    revision = replace(revision, observed_at=clock(0, 17), recorded_at=clock(1, 17))
    selected = select_waste_effects([revision], **inputs)
    result = apply_waste_at(
        selected,
        at=clock(0, 17),
        usable_before={"received-chicken": D(0)},
        expired_before={},
        already_applied_revision_ids=(),
    )
    assert not result.complete and result.lots is None
    assert result.findings[0].code == "MISSING_EVENT_BALANCE"


def test_two_events_share_one_available_balance_atomically(inputs, revision):
    other = replace(revision, observation_id="spill-2", revision_id="spill-2-r1")
    inputs["observation_manifest"] = ["spill-1", "spill-2"]
    selected = select_waste_effects([revision, other], **inputs)
    result = apply(selected, "4")  # 2.125 + 2.125 > 4
    assert not result.complete and result.lots is None
    assert result.applied_revision_ids is None
    assert result.findings[0].code == "WASTE_EXCEEDS_EVENT_BALANCE"


def test_distinct_events_on_same_lot_conserve_fractional_quantity(inputs, revision):
    other = replace(
        revision,
        observation_id="spill-2",
        revision_id="spill-2-r1",
        quantity=D("0.375"),
    )
    inputs["observation_manifest"] = ["spill-1", "spill-2"]
    selected = select_waste_effects([other, revision], **inputs)
    result = apply(selected)
    assert result.lots is not None
    assert result.lots[0].usable_after == D("7.5")
    assert result.lots[0].usable_deducted == D("2.5")


def test_explicit_no_waste_is_not_missing_and_discrepancy_not_inferred(inputs):
    missing = select_waste_effects([], **inputs)
    assert not missing.complete and missing.effects is None
    inputs["observation_manifest"] = []
    inputs["lots"][0] = inputs["lots"][0].model_copy(update={"quantity": D(5)})
    zero = select_waste_effects([], **inputs)
    assert zero.complete and zero.effects == ()  # 10 received - 5 count is not waste


def test_future_observation_not_selected(inputs, revision):
    future = replace(revision, observed_at=clock(22), recorded_at=clock(23))
    inputs["known_at"] = clock(23)
    inputs["observation_manifest"] = []
    assert select_waste_effects([future], **inputs).effects == ()


@pytest.mark.parametrize(
    "field,value,message",
    [
        ("quantity", D(0), "Positive waste"),
        ("quantity", D(-1), "nonnegative"),
        ("quantity", D("NaN"), "nonnegative"),
        ("quantity", D("Infinity"), "nonnegative"),
        ("unit", "litres", "ingredient/unit"),
        ("ingredient_id", "rice", "ingredient/unit"),
        ("lot_id", "outstanding-delivery", "known received lot"),
        ("observed_at", clock(7), "before receipt"),
        ("recorded_at", clock(11), "recorded before"),
        ("revision", True, "integer"),
        ("actor", "", "identities"),
        ("reversed", True, "First waste"),
    ],
)
def test_malformed_observation_rejected(inputs, revision, field, value, message):
    with pytest.raises(ValueError, match=message):
        select_waste_effects([replace(revision, **{field: value})], **inputs)


def test_revision_gap_is_incomplete(inputs, revision):
    gap = replace(revision, revision=3, revision_id="r3", replaces_revision_id="r2")
    result = select_waste_effects([revision, gap], **inputs)
    assert not result.complete and result.effects is None
    assert result.findings[0].code == "MISSING_WASTE_REVISION_CHAIN"


@pytest.mark.parametrize(
    "change",
    [
        {"unit": "litres"},
        {"lot_id": "another-lot"},
        {"observed_at": clock(11)},
        {"ingredient_id": "rice"},
    ],
)
def test_correction_must_preserve_identity(inputs, revision, change):
    altered = replace(
        revision,
        revision=2,
        revision_id="r2",
        replaces_revision_id=revision.revision_id,
        **change,
    )
    with pytest.raises(ValueError, match="changes observation identity"):
        select_waste_effects([revision, altered], **inputs)


def test_conflicting_duplicate_is_not_idempotent_retry(inputs, revision):
    with pytest.raises(ValueError, match="Conflicting duplicate"):
        select_waste_effects([revision, replace(revision, quantity=D(1))], **inputs)


@pytest.mark.parametrize(
    "problem,expected",
    [
        ("policy", "WASTE_POLICY_UNRESOLVED"),
        ("missing", "MISSING_EVIDENCE"),
        ("late", "EVIDENCE_NOT_YET_AVAILABLE"),
        ("revision", "CAPTURED_REVISION_MISMATCH"),
    ],
)
def test_missing_authority_is_incomplete(inputs, revision, problem, expected):
    if problem == "policy":
        inputs["policy"] = None
    elif problem == "missing":
        inputs["evidence"].pop("waste")
    elif problem == "late":
        inputs["evidence"]["waste"] = SourceEvidence(
            "fixture", clock(23), "synthetic-state-1"
        )
    else:
        inputs["evidence"]["waste"] = SourceEvidence(
            "fixture", clock(20), "other-revision"
        )
    result = select_waste_effects([revision], **inputs)
    assert not result.complete and result.effects is None
    assert expected in {f.code for f in result.findings}
    assert apply(result).lots is None


def test_deterministic_immutable_and_independent_decimal_context(inputs, revision):
    expected = select_waste_effects([revision], **inputs)
    with localcontext() as ctx:
        ctx.prec = 2
        repeated = select_waste_effects([revision], **inputs)
        result = apply(repeated)
        assert result.lots is not None
        assert result.lots[0].usable_after == D("7.875")
    assert expected == repeated
    assert inputs["lots"][0].quantity == 10


def test_modified_effect_cannot_claim_zero_or_negative_deduction(inputs, revision):
    selected = select_waste_effects([revision], **inputs)
    assert selected.effects is not None
    for quantity in (D(0), D(-1)):
        tampered = replace(
            selected,
            effects=(
                replace(
                    selected.effects[0],
                    effective_quantity=quantity,
                ),
            ),
        )
        with pytest.raises(ValueError):
            apply(tampered)


def test_replaying_earlier_boundary_cannot_skip_future_applied_waste(inputs, revision):
    selected = select_waste_effects([revision], **inputs)
    with pytest.raises(ValueError, match="Future waste"):
        apply_waste_at(
            selected,
            at=clock(11),
            usable_before={},
            expired_before={},
            already_applied_revision_ids=(revision.revision_id,),
        )
