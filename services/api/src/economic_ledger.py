"""Exact projected/realised ledger algebra, not a rollout or procurement search.

Internal policy-explicit inputs. Callers must construct/validate the chronological
stock and service ledger independently. This function verifies conservation and
accounting, not supplier feasibility, source-query completeness or optimality.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from fractions import Fraction
from itertools import pairwise
from typing import Literal

from src.contingency import ShipmentCharge
from src.coverage import evidence_findings
from src.inventory_projection import Finding, SourceEvidence, _aware, _id, _quantity
from src.procurement import _decimal
from src.schemas import Ingredient, MenuItem

LEDGER_POLICY = "PROPOSED_OPERATING_COST_LEDGER_V1"
MONEY_POLICY = "SGD_HALF_EVEN_FINAL_V1"
TERMINAL_POLICIES = frozenset({"ZERO_TERMINAL_V1", "BOOK_TERMINAL_V1"})


@dataclass(frozen=True)
class AssetFlow:
    """One valued resource, including recoverable fixed incoming assets once.

    quantity = allocated + expired + ending_usable + ending_incoming. Incoming
    book credit requires explicit recoverability evidence, not a guessed future
    receipt. For partially received commitments the opening received lot and the
    remaining incoming resource are separate, disjoint quantities. Cancelled
    unrecoverable assets must not be represented as recoverable incoming.
    """

    reference: str
    ingredient_id: str
    unit: str
    origin: Literal["OPENING", "FIXED_COMMITMENT", "NEW_PURCHASE", "CONTINUATION"]
    quantity: Decimal
    allocated: Decimal
    expired: Decimal
    ending_usable: Decimal
    ending_incoming: Decimal
    unit_cost: Decimal
    incremental_disposal_rate: Decimal


@dataclass(frozen=True)
class DishService:
    """Expected served portions or independently measured outcomes, never mixed.

    effective_net_price is already paid-equivalent per served portion (including
    declared free/promotion portions). It is not full menu price multiplied by
    all free portions. Required/served values use the same fulfilment convention.
    """

    start: datetime
    end: datetime
    menu_item_id: str
    required: Decimal
    served: Decimal
    effective_net_price: Decimal
    noningredient_variable_cost: Decimal


@dataclass(frozen=True)
class EconomicComponents:
    opening_assets: Decimal
    acquisition: Decimal
    delivery: Decimal
    emergency_extra: Decimal
    disposal_incremental: Decimal
    unmet_contribution: Decimal
    terminal_usable_book: Decimal
    terminal_incoming_book: Decimal
    expired_book: Decimal
    gross_lost_sales: Decimal
    zero_terminal_total: Decimal
    book_terminal_total: Decimal
    primary_total: Decimal
    primary_sgd: Decimal


@dataclass(frozen=True)
class EconomicLedger:
    complete: bool
    findings: tuple[Finding, ...]
    components: EconomicComponents | None
    expired_quantities: tuple[tuple[str, Decimal], ...] | None
    ending_usable_quantities: tuple[tuple[str, Decimal], ...] | None
    unmet_portions: tuple[tuple[str, Decimal], ...] | None
    start: datetime
    end: datetime
    known_at: datetime
    captured_revision: str
    terminal_policy: str | None
    provenance: str
    # Feasibility/search certification intentionally absent from a ledger total.


def score_ledger(
    assets: Sequence[AssetFlow],
    service: Sequence[DishService],
    shipments: Sequence[ShipmentCharge],
    ingredients: Sequence[Ingredient],
    menu_items: Sequence[MenuItem],
    *,
    asset_manifest: Sequence[str],
    service_manifest: Sequence[tuple[datetime, datetime, str]],
    shipment_manifest: Sequence[str],
    start: datetime,
    end: datetime,
    known_at: datetime,
    captured_revision: str,
    evidence: Mapping[str, SourceEvidence],
    ledger_policy: str | None,
    terminal_policy: str | None,
    money_policy: str | None,
    provenance: Literal["PROJECTED", "REALISED"],
) -> EconomicLedger:
    """Recompute both terminal valuations from one conserved component ledger.

    V5's waste component is explicitly incremental disposal cost here; expired
    acquisition value is reported but not charged twice. This is a proposed
    policy interpretation requiring confirmation, not an activated Backend rule.
    Missing required policy/evidence/manifest rows returns no monetary totals.
    Structural contradictions raise ValueError, including double shipment charges.
    """
    start, end, known_at = _aware(start), _aware(end), _aware(known_at)
    if end <= start:
        raise ValueError("Economic scoring horizon must be positive")
    _id(captured_revision)
    if provenance not in ("PROJECTED", "REALISED"):
        raise ValueError("Explicit projected or realised provenance required")
    findings: set[Finding] = set()
    for name, valid in (
        ("ledger", ledger_policy == LEDGER_POLICY),
        ("terminal", terminal_policy in TERMINAL_POLICIES),
        ("money", money_policy == MONEY_POLICY),
    ):
        if not valid:
            findings.add(Finding("ECONOMIC_POLICY_UNRESOLVED", name))
    sources = {"assets", "service", "shipments", "valuation", "policy", "catalogue"}
    if set(evidence) - sources:
        raise ValueError("Unknown economic evidence source")
    for source in sources:
        findings.update(
            evidence_findings(
                source,
                evidence.get(source),
                known_at,
                captured_revision,
            )
        )
    units = {i.id: i.unit for i in ingredients}
    dishes = {m.id for m in menu_items}
    if (
        not units
        or len(units) != len(ingredients)
        or not dishes
        or len(dishes) != len(menu_items)
    ):
        raise ValueError("Unique nonempty catalogue required")
    for identifier in (*units, *dishes):
        _id(identifier)
    if any(unit not in ("kg", "litres", "pieces") for unit in units.values()):
        raise ValueError("Unsupported ingredient unit")
    asset_ids = [a.reference for a in assets]
    service_ids = [(_aware(s.start), _aware(s.end), s.menu_item_id) for s in service]
    shipment_ids = [s.shipment_group_id for s in shipments]
    for name, actual, manifest in (
        ("assets", asset_ids, list(asset_manifest)),
        (
            "service",
            service_ids,
            [(_aware(a), _aware(b), d) for a, b, d in service_manifest],
        ),
        ("shipments", shipment_ids, list(shipment_manifest)),
    ):
        if len(set(actual)) != len(actual) or len(set(manifest)) != len(manifest):
            raise ValueError(f"Duplicate economic {name} identity")
        if set(actual) != set(manifest):
            findings.add(Finding("ECONOMIC_COVERAGE_MISMATCH", name))
    amounts = {
        name: Fraction(0)
        for name in (
            "opening",
            "acquisition",
            "delivery",
            "emergency",
            "disposal",
            "unmet",
            "usable",
            "incoming",
            "expired",
            "lost_sales",
        )
    }
    expired = {i: Fraction(0) for i in units}
    usable = {i: Fraction(0) for i in units}
    unmet = {d: Fraction(0) for d in dishes}
    for asset in assets:
        _id(asset.reference)
        if asset.ingredient_id not in units or asset.unit != units[asset.ingredient_id]:
            raise ValueError("Economic asset ingredient/unit mismatch")
        if asset.origin not in (
            "OPENING",
            "FIXED_COMMITMENT",
            "NEW_PURCHASE",
            "CONTINUATION",
        ):
            raise ValueError("Unknown economic asset origin")
        for value in (
            asset.quantity,
            asset.allocated,
            asset.expired,
            asset.ending_usable,
            asset.ending_incoming,
            asset.unit_cost,
            asset.incremental_disposal_rate,
        ):
            _quantity(value)
        if Fraction(asset.quantity) != sum(
            map(
                Fraction,
                (
                    asset.allocated,
                    asset.expired,
                    asset.ending_usable,
                    asset.ending_incoming,
                ),
            )
        ):
            raise ValueError("Economic asset quantities do not conserve")
        cost = Fraction(asset.unit_cost)
        key = (
            "opening"
            if asset.origin in ("OPENING", "FIXED_COMMITMENT")
            else "acquisition"
        )
        amounts[key] += Fraction(asset.quantity) * cost
        amounts["disposal"] += Fraction(asset.expired) * Fraction(
            asset.incremental_disposal_rate
        )
        amounts["expired"] += Fraction(asset.expired) * cost
        amounts["usable"] += Fraction(asset.ending_usable) * cost
        amounts["incoming"] += Fraction(asset.ending_incoming) * cost
        expired[asset.ingredient_id] += Fraction(asset.expired)
        usable[asset.ingredient_id] += Fraction(asset.ending_usable)
    for row in service:
        if (
            row.menu_item_id not in dishes
            or not start <= _aware(row.start) < _aware(row.end) <= end
        ):
            raise ValueError("Service outside economic horizon/catalogue")
        for value in (
            row.required,
            row.served,
            row.effective_net_price,
            row.noningredient_variable_cost,
        ):
            _quantity(value)
        if row.served > row.required:
            raise ValueError("Served portions exceed required portions")
        missing = Fraction(row.required) - Fraction(row.served)
        unmet[row.menu_item_id] += missing
        amounts["lost_sales"] += missing * Fraction(row.effective_net_price)
        amounts["unmet"] += missing * (
            Fraction(row.effective_net_price)
            - Fraction(row.noningredient_variable_cost)
        )
    for dish in dishes:
        intervals = sorted(
            (_aware(r.start), _aware(r.end)) for r in service if r.menu_item_id == dish
        )
        if any(a[1] > b[0] for a, b in pairwise(intervals)):
            raise ValueError("Overlapping dish service intervals")
    for shipment in shipments:
        _id(shipment.shipment_group_id)
        _id(shipment.supplier_id)
        _aware(shipment.arrival_at)
        _quantity(shipment.delivery)
        _quantity(shipment.emergency)
        amounts["delivery"] += Fraction(shipment.delivery)
        amounts["emergency"] += Fraction(shipment.emergency)
    components = None
    if not findings:
        zero = sum(
            (
                amounts[k]
                for k in (
                    "opening",
                    "acquisition",
                    "delivery",
                    "emergency",
                    "disposal",
                    "unmet",
                )
            ),
            Fraction(0),
        )
        book = zero - amounts["usable"] - amounts["incoming"]
        primary = _decimal(zero if terminal_policy == "ZERO_TERMINAL_V1" else book)
        with localcontext(
            Context(
                prec=max(
                    28, len(primary.as_tuple().digits) + abs(primary.adjusted()) + 3
                )
            )
        ):
            rounded = primary.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        components = EconomicComponents(
            _decimal(amounts["opening"]),
            _decimal(amounts["acquisition"]),
            _decimal(amounts["delivery"]),
            _decimal(amounts["emergency"]),
            _decimal(amounts["disposal"]),
            _decimal(amounts["unmet"]),
            _decimal(amounts["usable"]),
            _decimal(amounts["incoming"]),
            _decimal(amounts["expired"]),
            _decimal(amounts["lost_sales"]),
            _decimal(zero),
            _decimal(book),
            primary,
            rounded,
        )
    return EconomicLedger(
        not findings,
        tuple(sorted(findings)),
        components,
        None
        if findings
        else tuple((i, _decimal(q)) for i, q in sorted(expired.items())),
        None
        if findings
        else tuple((i, _decimal(q)) for i, q in sorted(usable.items())),
        None if findings else tuple((d, _decimal(q)) for d, q in sorted(unmet.items())),
        start,
        end,
        known_at,
        captured_revision,
        terminal_policy,
        provenance,
    )
