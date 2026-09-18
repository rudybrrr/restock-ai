"""Approved policy contract and independent synthetic exposure/threshold oracles."""

import copy
import json
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from test_materiality import (
    batches,
    codes,
    run,
    set_expected,
    set_stock,
)
from test_materiality import (
    case as case,  # noqa: PLC0414
)
from test_procurement import reference as reference  # noqa: PLC0414

from src.forecasting import DailySalesObservation, seasonal_baseline
from src.materiality import (
    SALES_MATERIALITY_V1,
    SalesThresholdPolicy,
    resolve_sales_threshold_policy,
)
from src.procurement_contract_schemas import ForecastInputArtifact, ProcurementContract
from src.procurement_contracts import first_slice_seed_rows, freeze_operational_activity
from src.service_buckets import allocate_service_buckets

D = Decimal
FIXTURE = Path(__file__).parent / "fixtures/sales_threshold_policy_v1.json"


@pytest.fixture
def proposal(case):
    raw = json.loads(FIXTURE.read_text())
    assert raw["status"] == "APPROVED_DEMO_POLICY_SYNTHETIC_EVIDENCE_ONLY"
    case["threshold_policy"] = SalesThresholdPolicy(
        raw["version"],
        raw["rule"],
        D(raw["absolute_floor"]),
        D(raw["relative_threshold"]),
        D(raw["minimum_expected_portions"]),
        raw["minimum_complete_buckets"],
        case["threshold_policy"].evidence,
    )
    return case


def actual_baseline(proposal):
    """Restore canonical four-Monday history, replacing the old 150/dish override."""
    c = proposal["contract"]
    row = first_slice_seed_rows(c.known_at - timedelta(hours=1))["forecast_inputs"][0]
    artifact = ForecastInputArtifact.model_validate(row)
    proposal["contract"] = c.model_copy(update={"forecast_input": artifact})
    proposal["issued_input"] = artifact.model_copy(deep=True)
    history = [
        DailySalesObservation(
            r.service_date,
            r.available_at,
            r.revision,
            r.portions,
            r.promotion,
            r.censored,
        )
        for r in artifact.payload.history
    ]
    forecast = seasonal_baseline(
        history,
        proposal["issued_catalogue"].menu_items,
        issue_time=c.policy.payload.issue_time,
        target_date=c.policy.payload.target_date,
    )
    daily = {dish: value.expected_portions for dish, value in forecast.items()}
    # Independent oracle: the approved four identical Monday observations.
    assert daily == {
        "chicken-rice": D(100),
        "fried-rice": D(60),
        "chicken-noodles": D(80),
        "tofu-bowl": D(40),
        "vegetable-noodles": D(40),
    }
    assert all(value is not None for value in daily.values())
    issued = proposal["issued_forecast"]
    proposal["issued_forecast"] = replace(
        issued,
        buckets=allocate_service_buckets(
            {k: v for k, v in daily.items() if v is not None},
            proposal["issued_catalogue"].menu_items,
            target_date=issued.target_date,
            profile=issued.profile,
        ),
    )


def at_cutoff(proposal, clock):
    """Explicit synthetic counted stock and integer POS rows at a fresh cutoff."""
    cutoff = datetime.fromisoformat("2026-02-16T" + clock + ":00+08:00")
    c = proposal["contract"].model_copy(update={"as_of": cutoff}, deep=True)
    inv = proposal["risk"].inventory
    inv["as_of"] = cutoff
    inv["buckets"] = tuple(
        b for b in proposal["issued_forecast"].buckets if b.start >= cutoff
    )
    inv["opening_lots"] = [
        lot.model_copy(
            update={"as_of": cutoff, "counted_at": cutoff, "coverage_start": cutoff}
        )
        for lot in inv["opening_lots"]
    ]
    state = c.frozen_state
    assert state is not None
    state["inventory"] = [lot.model_dump(mode="json") for lot in inv["opening_lots"]]
    # Nearest integer cumulative POS values keep each dish within half a portion
    # of expectation. These are INPUTS; all expected assertions below are literal.
    cumulative = {d.id: D(0) for d in proposal["issued_catalogue"].menu_items}
    prior = dict.fromkeys(cumulative, 0)
    rows = []
    for i, b in enumerate(proposal["issued_forecast"].buckets):
        if b.end > cutoff:
            continue
        cumulative = {d: cumulative[d] + b.expected_portions[d] for d in cumulative}
        total = {d: round(q) for d, q in cumulative.items()}
        rows.append(
            {
                "id": f"proposal-{i}-r1",
                "source": "synthetic-proposal",
                "batch_id": f"proposal-{i}",
                "period_start": b.start.isoformat(),
                "period_end": b.end.isoformat(),
                "sales": {d: total[d] - prior[d] for d in total},
                "revision": 1,
                "active": True,
                "recorded_at": (c.known_at - timedelta(minutes=2)).isoformat(),
            }
        )
        prior = total
    state["sales_batches"] = rows
    proposal["contract"] = ProcurementContract.model_validate(
        freeze_operational_activity(c.model_dump(mode="json"), state)
    )


@pytest.mark.parametrize(
    ("dish", "before", "first", "previous", "expected"),
    [
        ("chicken-rice", "12:00", "12:30", "13.333334", "20.000001"),
        ("fried-rice", "13:00", "13:30", "16", "20"),
        # 32 lunch portions: floor six to 5.333333, give the two residual
        # micro-portions to buckets 1/2; first three = 16.000001, four = 21.333334.
        ("chicken-noodles", "12:30", "13:00", "16.000001", "21.333334"),
        ("tofu-bowl", "17:30", "18:00", "19", "22"),
        ("vegetable-noodles", "17:30", "18:00", "19", "22"),
    ],
)
def test_first_assessable_under_actual_baseline(
    proposal, dish, before, first, previous, expected
):
    actual_baseline(proposal)
    for clock, quantity, adequate in [
        (before, previous, False),
        (first, expected, True),
    ]:
        at_cutoff(proposal, clock)
        result = run(proposal)
        row = next(r for r in result.sales if r.dish_id == dish)
        assert row.expected == D(quantity)
        assert row.adequate_exposure is adequate
        assert row.material is (False if adequate else None)


@pytest.mark.parametrize(("actual", "material"), [(26, False), (27, True), (17, True)])
def test_whole_result_not_just_one_dish(proposal, actual, material):
    actual_baseline(proposal)
    at_cutoff(proposal, "18:00")
    rows = batches(proposal)
    rows[-1]["sales"]["tofu-bowl"] = actual - sum(
        r["sales"]["tofu-bowl"] for r in rows[:-1]
    )
    # A negative correction belongs in a previous positive batch, not negative sales.
    if rows[-1]["sales"]["tofu-bowl"] < 0:
        rows[-1]["sales"]["tofu-bowl"] = 0
        rows[-2]["sales"]["tofu-bowl"] -= 2
    result = run(proposal)
    assert result.complete and result.material_change is material
    assert result.inventory_feasible is True
    assert all(r.adequate_exposure for r in result.sales)
    tofu = next(r for r in result.sales if r.dish_id == "tofu-bowl")
    assert (tofu.expected, tofu.observed, tofu.threshold) == (D(22), D(actual), D(5))
    assert result.remainder is not None
    assert (
        sum(b.expected_portions["tofu-bowl"] for b in result.remainder.future_buckets)
        == 18
    )
    assert result.threshold_policy_version == "SALES_MATERIALITY_V1"


def test_sparse_dishes_prevent_aggregate_nonmaterial(proposal):
    actual_baseline(proposal)
    at_cutoff(proposal, "17:30")
    result = run(proposal)
    assert not result.complete and result.material_change is None
    assert {f.source for f in result.findings if f.code == "INSUFFICIENT_EXPOSURE"} == {
        "tofu-bowl",
        "vegetable-noodles",
    }


def test_missing_interval_and_risk_do_not_certify_nonmaterial(proposal):
    actual_baseline(proposal)
    at_cutoff(proposal, "18:00")
    assert run(proposal).material_change is False
    assert run(proposal, risk=None).material_change is None
    batches(proposal).pop()
    result = run(proposal)
    assert result.material_change is None and not result.complete
    assert result.remainder is None and "MISSING_SALES_INTERVALS" in codes(result)


@pytest.mark.parametrize(
    ("expected", "adequate"),
    [
        ("19.999999", False),
        ("20", True),
        ("20.000001", True),
    ],
)
def test_exact_exposure_boundary(proposal, expected, adequate):
    set_expected(proposal, expected)
    result = run(proposal)
    row = next(r for r in result.sales if r.dish_id == "chicken-rice")
    assert row.expected == D(expected) and row.adequate_exposure is adequate
    assert result.material_change is (False if adequate else None)


def test_bucket_minimum_is_separate_from_expected_quantity(proposal):
    # Explicit high-demand sensitivity, not the actual first-slice baseline.
    issued = proposal["issued_forecast"]
    proposal["issued_forecast"] = replace(
        issued,
        buckets=allocate_service_buckets(
            {d.id: D(300) for d in proposal["issued_catalogue"].menu_items},
            proposal["issued_catalogue"].menu_items,
            target_date=issued.target_date,
            profile=issued.profile,
        ),
    )
    at_cutoff(proposal, "11:30")
    result = run(proposal)
    assert all(r.expected == 20 and r.adequate_exposure is False for r in result.sales)
    assert result.material_change is None
    at_cutoff(proposal, "12:00")
    result = run(proposal)
    assert result.complete and result.material_change is False
    assert all(r.expected == 40 and r.adequate_exposure is True for r in result.sales)


def test_proposal_zero_expectation_and_known_risk(proposal):
    set_expected(proposal, "0")
    for row in batches(proposal):
        row["sales"]["chicken-rice"] = 0
    result = run(proposal)
    row = next(r for r in result.sales if r.dish_id == "chicken-rice")
    assert (row.expected, row.observed, row.adequate_exposure, row.material) == (
        0,
        0,
        False,
        None,
    )
    assert result.material_change is None
    set_stock(proposal, D(0))
    result = run(proposal)
    assert result.material_change is True and not result.complete
    assert result.first_stockout_interval is not None


def test_explicit_identity_evidence_and_immutability(proposal):
    policy = proposal["threshold_policy"]
    before = copy.deepcopy(proposal["contract"].model_dump())
    first = run(proposal)
    assert first == run(proposal)
    assert proposal["contract"].model_dump() == before
    assert policy.evidence.reference in first.evidence_refs
    with pytest.raises(FrozenInstanceError):
        policy.minimum_complete_buckets = 1
    assert run(proposal, threshold_policy=None).material_change is None
    assert (
        run(proposal, threshold_policy=replace(policy, evidence=None)).material_change
        is None
    )


def resolve(case, policy):
    return resolve_sales_threshold_policy(
        policy,
        known_at=case["contract"].known_at,
        captured_revision=case["contract"].captured_state_revision,
    )


def test_approved_definition_and_decimal_transport(proposal):
    definition = SALES_MATERIALITY_V1
    assert (
        definition.version,
        definition.rule,
        definition.absolute_floor,
        definition.relative_threshold,
        definition.minimum_expected_portions,
        definition.minimum_complete_buckets,
        definition.evidence,
    ) == (
        "SALES_MATERIALITY_V1",
        "V2_DEMO_ABSOLUTE_OR_RELATIVE_V1",
        D("5"),
        D("0.2"),
        D("20"),
        2,
        None,
    )
    # A definition in code is not a selected/persisted policy for a run.
    assert not resolve(proposal, definition).complete
    supplied = proposal["threshold_policy"]
    result = resolve(proposal, supplied)
    assert result.complete and result.policy == supplied and result.findings == ()
    assert resolve(
        proposal,
        replace(
            supplied, absolute_floor=D("5.000"), minimum_expected_portions=D("20.000")
        ),
    ).complete
    for target, attribute, value in (
        (definition, "absolute_floor", D(6)),
        (result, "policy", None),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(target, attribute, value)


@pytest.mark.parametrize(
    "version",
    [
        "EXPLICIT_TEST_EXPOSURE_20_V1",
        "PROPOSED_SALES_MATERIALITY_V1",
        "SALES_MATERIALITY_V2",
        "sales_materiality_v1",
    ],
)
def test_unknown_and_fixture_versions_never_resolve_or_certify(proposal, version):
    policy = replace(proposal["threshold_policy"], version=version)
    resolution = resolve(proposal, policy)
    assert not resolution.complete and resolution.policy is None
    assert {f.code for f in resolution.findings} == {"UNSUPPORTED_SALES_POLICY_VERSION"}
    result = run(proposal, threshold_policy=policy)
    assert result.material_change is None and not result.complete
    assert "UNSUPPORTED_SALES_POLICY_VERSION" in codes(result)
    assert result.threshold_policy_version == version  # supplied identity, not approval
    set_stock(proposal, D(0))
    result = run(proposal, threshold_policy=policy)
    assert result.material_change is True and not result.complete


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rule", "DIFFERENT_RULE"),
        ("absolute_floor", D(6)),
        ("relative_threshold", D("0.3")),
        ("minimum_expected_portions", D(0)),
        ("minimum_expected_portions", D(21)),
        ("minimum_complete_buckets", 1),
        ("minimum_complete_buckets", 3),
    ],
)
def test_frozen_version_conflicts_cannot_bypass_resolver(proposal, field, value):
    policy = replace(proposal["threshold_policy"], **{field: value})
    resolution = resolve(proposal, policy)
    assert not resolution.complete and resolution.policy is None
    assert "SALES_POLICY_VERSION_CONFLICT" in {f.code for f in resolution.findings}
    result = run(proposal, threshold_policy=policy)
    assert result.material_change is None and not result.complete
    assert "SALES_POLICY_VERSION_CONFLICT" in codes(result)


@pytest.mark.parametrize(
    "missing",
    [
        "policy",
        "version",
        "rule",
        "absolute_floor",
        "relative_threshold",
        "minimum_expected_portions",
        "minimum_complete_buckets",
        "evidence",
    ],
)
def test_missing_selection_is_explicitly_incomplete(proposal, missing):
    supplied = proposal["threshold_policy"]
    policy = None if missing == "policy" else replace(supplied, **{missing: None})
    resolution = resolve(proposal, policy)
    assert not resolution.complete and resolution.policy is None
    assert resolution.findings
    assert run(proposal, threshold_policy=policy).material_change is None


@pytest.mark.parametrize("kind", ["missing_ref", "missing_time", "late", "capture"])
def test_policy_evidence_is_bound_to_frozen_run(proposal, kind):
    supplied = proposal["threshold_policy"]
    evidence = supplied.evidence
    assert evidence is not None
    changes = {
        "missing_ref": {"reference": None},
        "missing_time": {"available_at": None},
        "late": {
            "available_at": proposal["contract"].known_at + timedelta(microseconds=1)
        },
        "capture": {"captured_revision": "another-capture"},
    }
    resolution = resolve(
        proposal, replace(supplied, evidence=replace(evidence, **changes[kind]))
    )
    assert not resolution.complete and resolution.policy is None
    assert resolution.findings
    # Exact knowledge cutoff is visible; equivalent UTC instant has same meaning.
    from datetime import UTC

    assert resolve(
        proposal,
        replace(
            supplied,
            evidence=replace(
                evidence,
                available_at=proposal["contract"].known_at.astimezone(UTC),
            ),
        ),
    ).complete


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("absolute_floor", 5.0),
        ("relative_threshold", D("NaN")),
        ("minimum_expected_portions", D("-1")),
        ("minimum_complete_buckets", True),
        ("minimum_complete_buckets", D(2)),
    ],
)
def test_malformed_transport_is_not_coerced(proposal, field, value):
    with pytest.raises((TypeError, ValueError)):
        resolve(proposal, replace(proposal["threshold_policy"], **{field: value}))
