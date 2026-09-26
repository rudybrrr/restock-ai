"""Pure proposed waste semantics; no persistence, endpoint or historical replay.

Select the frozen replacement revision once, then let the authoritative replayer
apply effects at their observed times. A correction requires replay, not a second
deduction from an already adjusted estimate. Caller-supplied evidence is checked
for consistency; this module cannot certify the source query that produced it.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Context, Decimal, localcontext
from typing import Literal

from src.inventory_projection import (
    Finding,
    SourceEvidence,
    _aware,
    _expiry,
    _id,
    _precision,
    _quantity,
)
from src.schemas import Ingredient, InventoryLot

WASTE_POLICY = "PROPOSED_WASTE_REPLACEMENT_REPLAY_V1"
ZERO = Decimal(0)


@dataclass(frozen=True)
class WasteRevision:
    """Internal numerical fixture record, not a canonical manager write schema.

    quantity is positive even on a reversal, which retains the replaced record's
    quantity as evidence but has zero effective disposal/deduction. Reinstatement
    is a later non-reversed replacement. Identity/lot/time cannot be corrected in
    place: reverse the old observation and record a separate new observation.
    """

    observation_id: str
    revision_id: str
    revision: int
    replaces_revision_id: str | None
    lot_id: str
    ingredient_id: str
    unit: str
    quantity: Decimal
    observed_at: datetime
    recorded_at: datetime
    actor: str
    reversed: bool


@dataclass(frozen=True)
class WasteEffect:
    observation_id: str
    revision_id: str
    lot_id: str
    ingredient_id: str
    unit: str
    observed_at: datetime
    recorded_at: datetime
    recorded_quantity: Decimal
    effective_quantity: Decimal
    disposition: Literal[
        "DEDUCT_USABLE", "DISPOSE_EXPIRED", "ABSORBED_BY_COUNT", "REVERSED"
    ]


@dataclass(frozen=True)
class WasteSelection:
    as_of: datetime
    known_at: datetime
    captured_revision: str
    policy: str | None
    complete: bool
    findings: tuple[Finding, ...]
    effects: tuple[WasteEffect, ...] | None
    evidence: tuple[tuple[str, SourceEvidence], ...]


def select_waste_effects(
    revisions: Sequence[WasteRevision],
    lots: Sequence[InventoryLot],
    ingredients: Sequence[Ingredient],
    *,
    as_of: datetime,
    known_at: datetime,
    captured_revision: str,
    observation_manifest: Sequence[str],
    evidence: Mapping[str, SourceEvidence],
    policy: str | None,
) -> WasteSelection:
    """Select known revisions and classify effects relative to frozen counts.

    observation_manifest explicitly declares all effective observations visible
    in this input scope (empty means known none). Each selected chain must start
    at revision 1. Lots contain the caller's latest known physical count through
    as_of, not an estimate already reduced by waste. A count at observed_at absorbs
    the disposal; its quantity is never reduced again. An expired disposal remains
    measured evidence but does not deduct from usable stock a second time.

    Missing policy/evidence/coverage returns incomplete with effects=None.
    Contradictory identities, revisions, units and quantities raise ValueError.
    """
    as_of, known_at = _aware(as_of), _aware(known_at)
    _id(captured_revision)
    findings: set[Finding] = set()
    if policy != WASTE_POLICY:
        findings.add(Finding("WASTE_POLICY_UNRESOLVED", "policy"))
    expected_sources = {"waste", "counts", "lots", "catalogue"}
    if set(evidence) - expected_sources:
        raise ValueError("Unknown waste evidence source")
    for name in sorted(expected_sources):
        source = evidence.get(name)
        if source is None or not source.reference or not source.reference.strip():
            findings.add(Finding("MISSING_EVIDENCE", name))
        elif source.available_at is None:
            findings.add(Finding("MISSING_AVAILABILITY", name))
        elif _aware(source.available_at) > known_at:
            findings.add(Finding("EVIDENCE_NOT_YET_AVAILABLE", name))
        if source is not None and source.captured_revision != captured_revision:
            findings.add(Finding("CAPTURED_REVISION_MISMATCH", name))

    units = {i.id: i.unit for i in ingredients}
    if not units or len(units) != len(ingredients):
        raise ValueError("Unique nonempty ingredient catalogue required")
    for ingredient, unit in units.items():
        _id(ingredient)
        if unit not in ("kg", "litres", "pieces"):
            raise ValueError("Unsupported ingredient unit")
    lot_by_id = {lot.id: lot for lot in lots}
    if len(lot_by_id) != len(lots):
        raise ValueError("Duplicate received lot")
    for lot in lots:
        _id(lot.id)
        if lot.ingredient_id not in units or lot.unit != units[lot.ingredient_id]:
            raise ValueError("Unknown ingredient or incompatible lot unit")
        _quantity(lot.quantity)
        _quantity(lot.initial_quantity)
        if not _aware(lot.received_at) <= _aware(lot.counted_at) <= as_of:
            raise ValueError("Inconsistent received lot/count times")
        if _expiry(lot.expiry_date) <= _aware(lot.received_at):
            raise ValueError("Lot expired before receipt")
        if lot.provenance != "PHYSICAL":
            raise ValueError("Physical count inputs required")

    if len(set(observation_manifest)) != len(observation_manifest):
        raise ValueError("Duplicate observation manifest identity")
    for identifier in observation_manifest:
        _id(identifier)
    # Rows not yet recorded cannot affect this frozen selection, including their
    # corrections. Operational-future records are also excluded, never backdated.
    visible: dict[str, WasteRevision] = {}
    for row in revisions:
        recorded, observed = _aware(row.recorded_at), _aware(row.observed_at)
        if recorded > known_at or observed > as_of:
            continue
        if recorded < observed:
            raise ValueError("Waste cannot be recorded before it was observed")
        for identifier in (row.observation_id, row.revision_id, row.lot_id, row.actor):
            _id(identifier)
        _quantity(row.quantity)
        if row.quantity == 0 or type(row.reversed) is not bool:
            raise ValueError("Positive waste quantity and explicit reversal required")
        if type(row.revision) is not int or row.revision < 1:
            raise ValueError("Positive integer waste revision required")
        if row.revision_id in visible and visible[row.revision_id] != row:
            raise ValueError("Conflicting duplicate waste revision")
        visible[row.revision_id] = row

    chains: dict[str, list[WasteRevision]] = {}
    for row in visible.values():
        chains.setdefault(row.observation_id, []).append(row)
    if set(chains) != set(observation_manifest):
        findings.add(Finding("WASTE_COVERAGE_MISMATCH", "waste"))
    effects: list[WasteEffect] = []
    for observation, chain in sorted(chains.items()):
        chain.sort(key=lambda r: r.revision)
        previous: WasteRevision | None = None
        for row in chain:
            if previous is not None:
                if row.revision == previous.revision:
                    raise ValueError("Conflicting waste revision number")
                if (
                    row.lot_id,
                    row.ingredient_id,
                    row.unit,
                    _aware(row.observed_at),
                ) != (
                    previous.lot_id,
                    previous.ingredient_id,
                    previous.unit,
                    _aware(previous.observed_at),
                ):
                    raise ValueError("Waste replacement changes observation identity")
                if _aware(row.recorded_at) < _aware(previous.recorded_at):
                    raise ValueError("Waste revision recording times go backwards")
                if (
                    row.revision != previous.revision + 1
                    or row.replaces_revision_id != previous.revision_id
                ):
                    findings.add(Finding("MISSING_WASTE_REVISION_CHAIN", observation))
                if row.reversed and row.quantity != previous.quantity:
                    raise ValueError("Reversal must retain the replaced quantity")
            elif row.revision != 1 or row.replaces_revision_id is not None:
                findings.add(Finding("MISSING_WASTE_REVISION_CHAIN", observation))
            elif row.reversed:
                raise ValueError("First waste revision cannot be a reversal")
            previous = row
        selected = chain[-1]
        lot = lot_by_id.get(selected.lot_id)
        if lot is None:
            raise ValueError("Waste must reference a known received lot")
        if selected.ingredient_id != lot.ingredient_id or selected.unit != lot.unit:
            raise ValueError("Waste ingredient/unit does not match received lot")
        if _aware(selected.observed_at) < _aware(lot.received_at):
            raise ValueError("Waste was observed before receipt")
        disposition = (
            "REVERSED"
            if selected.reversed
            else "ABSORBED_BY_COUNT"
            if _aware(selected.observed_at) <= _aware(lot.counted_at)
            else "DISPOSE_EXPIRED"
            if _aware(selected.observed_at) >= _expiry(lot.expiry_date)
            else "DEDUCT_USABLE"
        )
        effects.append(
            WasteEffect(
                observation,
                selected.revision_id,
                selected.lot_id,
                selected.ingredient_id,
                selected.unit,
                _aware(selected.observed_at),
                _aware(selected.recorded_at),
                selected.quantity,
                ZERO
                if disposition in ("REVERSED", "ABSORBED_BY_COUNT")
                else selected.quantity,
                disposition,
            )
        )
    return WasteSelection(
        as_of,
        known_at,
        captured_revision,
        policy,
        not findings,
        tuple(sorted(findings)),
        None
        if findings
        else tuple(sorted(effects, key=lambda e: (e.observed_at, e.observation_id))),
        tuple(sorted(evidence.items())),
    )


@dataclass(frozen=True)
class WasteLotDeduction:
    lot_id: str
    usable_before: Decimal
    usable_deducted: Decimal
    usable_after: Decimal
    expired_before: Decimal
    expired_disposed: Decimal
    expired_after: Decimal


@dataclass(frozen=True)
class WasteApplication:
    at: datetime
    complete: bool
    findings: tuple[Finding, ...]
    lots: tuple[WasteLotDeduction, ...] | None
    applied_revision_ids: tuple[str, ...] | None


def apply_waste_at(
    selection: WasteSelection,
    *,
    at: datetime,
    usable_before: Mapping[str, Decimal],
    expired_before: Mapping[str, Decimal],
    already_applied_revision_ids: Sequence[str],
) -> WasteApplication:
    """Deduct one timestamp atomically from explicit, already replayed balances.

    Caller handles sales/receipts/count resets chronologically. Both maps must
    cover precisely the lots with active deductions at this timestamp, even if
    all corresponding revisions were already applied (idempotent retry). Expired
    physical remainder is separate from usable stock; never infer it from zero
    usable stock. A replacement cannot be applied atop a superseded deduction:
    rebuild from the count using select_waste_effects at the new knowledge cutoff.
    """
    at = _aware(at)
    if at > selection.as_of:
        raise ValueError("Waste application exceeds frozen operational cutoff")
    if not selection.complete or selection.effects is None:
        return WasteApplication(at, False, selection.findings, None, None)
    if selection.policy != WASTE_POLICY or selection.findings:
        raise ValueError("Contradictory waste selection certification")
    if len({e.observation_id for e in selection.effects}) != len(selection.effects):
        raise ValueError("Duplicate selected waste observation")
    if len({e.revision_id for e in selection.effects}) != len(selection.effects):
        raise ValueError("Duplicate selected waste revision")
    for effect in selection.effects:
        _quantity(effect.recorded_quantity)
        _quantity(effect.effective_quantity)
        if effect.recorded_quantity == 0:
            raise ValueError("Positive recorded waste quantity required")
        if (
            not _aware(effect.observed_at)
            <= _aware(effect.recorded_at)
            <= selection.known_at
        ):
            raise ValueError("Waste effect outside frozen knowledge")
        if effect.observed_at > selection.as_of:
            raise ValueError("Waste effect outside frozen operational cutoff")
        if effect.disposition in ("REVERSED", "ABSORBED_BY_COUNT"):
            if effect.effective_quantity != 0:
                raise ValueError("Absorbed/reversed waste must not deduct stock")
        elif effect.disposition in ("DEDUCT_USABLE", "DISPOSE_EXPIRED"):
            if effect.effective_quantity != effect.recorded_quantity:
                raise ValueError("Effective waste differs from selected observation")
        else:
            raise ValueError("Unknown waste effect disposition")
    applied = set(already_applied_revision_ids)
    if len(applied) != len(already_applied_revision_ids):
        raise ValueError("Duplicate applied revision identity")
    selected_ids = {e.revision_id for e in selection.effects}
    if applied - selected_ids:
        raise ValueError("Superseded or unknown waste revision: replay from counts")
    if any(e.revision_id in applied and e.observed_at > at for e in selection.effects):
        raise ValueError("Future waste marked already applied")
    effects = [
        e
        for e in selection.effects
        if e.observed_at == at and e.disposition in ("DEDUCT_USABLE", "DISPOSE_EXPIRED")
    ]
    lots = {e.lot_id for e in effects}
    if set(usable_before) != lots or set(expired_before) != lots:
        return WasteApplication(
            at, False, (Finding("MISSING_EVENT_BALANCE", "waste"),), None, None
        )
    values = [*usable_before.values(), *expired_before.values()]
    for q in values:
        _quantity(q)
    values.extend(e.effective_quantity for e in effects)
    with localcontext(Context(prec=_precision(values))):
        rows = []
        findings: set[Finding] = set()
        for lot_id in sorted(lots):
            usable = sum(
                (
                    e.effective_quantity
                    for e in effects
                    if e.lot_id == lot_id
                    and e.disposition == "DEDUCT_USABLE"
                    and e.revision_id not in applied
                ),
                ZERO,
            )
            expired = sum(
                (
                    e.effective_quantity
                    for e in effects
                    if e.lot_id == lot_id
                    and e.disposition == "DISPOSE_EXPIRED"
                    and e.revision_id not in applied
                ),
                ZERO,
            )
            if usable > usable_before[lot_id] or expired > expired_before[lot_id]:
                findings.add(Finding("WASTE_EXCEEDS_EVENT_BALANCE", lot_id))
            rows.append(
                WasteLotDeduction(
                    lot_id,
                    usable_before[lot_id],
                    usable,
                    usable_before[lot_id] - usable,
                    expired_before[lot_id],
                    expired,
                    expired_before[lot_id] - expired,
                )
            )
        if findings:
            return WasteApplication(at, False, tuple(sorted(findings)), None, None)
    return WasteApplication(
        at,
        True,
        (),
        tuple(rows),
        tuple(sorted(applied | {e.revision_id for e in effects})),
    )
