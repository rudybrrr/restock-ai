# Bounded contingency numerical contract — version 1

Aniq, 22 September 2026. Related to [issue #11](https://github.com/rudybrrr/restock-ai/issues/11).
This freezes **implemented numerical semantics**, not an activated Backend policy.
Backend `ProcurementPolicyPayload.emergency_mode` remains `NORMAL_ONLY`.
Budget, safety, storage, horizon, prices, capacity and shipment identities must be
supplied from authorised versioned inputs; none of this fixture's values are defaults.

## Authority and scope

Approved ML v2 §§7, 8.1–8.6, 10 and T05–08/T11/T13/T16–20, amended by v3
§§3, 5–8, govern this bounded cash increment. V3 replaces the historical catalogue,
disables actionable search-limit incumbents, and leaves full economic OPEN-02 open.
Chun Yang's [22 September handoff](https://github.com/rudybrrr/restock-ai/issues/11#issuecomment-5773646848)
requests the residual-horizon/additional-only policy before Backend activation.
Main inspected: `843efe59b8217d7ba23c15ff02fd5ad978a7720a`.

Reuse `ForecastVersion`, canonical catalogue/recipes, `ExpectedSupply`/`Delivery`,
`OrderingOpportunity`, `PurchaseCandidate`, `Cash`, `project_multiday` and the
existing FEFO depletion kernel. The normal `procurement.py` strategy and
`COMPLETE_PRUNED_DOMAIN_V1` guards are unchanged. No adapter, API, persistence,
historical replay, actual order placement, worker or frontend changes belong here.

| Explicit numerical tag | Frozen meaning |
|---|---|
| `BOUNDED_CONTINGENCY_CASH_V1` | Additional purchases placed at operational issue time; fixed commitments immutable; per-ingredient protected and assessment windows supplied. |
| `CONTINGENCY_CARTESIAN_V1` | Complete finite pack-grid enumeration, including all splits; interrupted incumbent diagnostic only. |
| `EXPLICIT_NEW_SHIPMENT_ONCE_V1` | One delivery charge per explicit new shipment; exclusive monetary emergency charge once if any selected line is EMERGENCY. |
| `CASH_SLICE_V1` | New acquisition + delivery + exclusive emergency SGD, exactly once. |
| `FEFO_EXPIRY_RECEIVED_LOT_ID_V1` | Existing expiry/receipt-time/lot-ID order; projected identities use semantic opportunity facts and shipment ID, not arbitrary opportunity ID. |
| `EXPIRY_ARRIVAL_PLUS_SHELF_LIFE_MINUS_ONE_V1` | Expected usable-through date is arrival date + shelf-life days − 1; unusable at following Singapore midnight. |
| `SUPPLIER_ID_THEN_INGREDIENT_ID_V1` | Equal cash uses lexicographic supplier/ingredient/order/arrival/kind/offer/shipment/quantity/unit tuples. No reliability or arbitrary opportunity-ID preference. |
| `CONTEXT_ONLY` | Historical on-time rate never affects feasibility or ranking. |
| `SERVICE_END_SAFETY_RECEIPT_STORAGE_V1` | Reused projection constraint policy: safety after protected service; storage at opening and movement/receipt boundaries, including assessment. |

The caller resolves each protected window. This module does not promote
`coverage.py`'s fixture OPEN-at-decision convention into a production cadence rule.
Assessment cannot truncate protection or omit an outstanding delayed arrival.
Forecast coverage through assessment is mandatory, with later shortages labelled
ASSESSMENT rather than extending every ingredient's purchase guarantee. Storage
breaches anywhere in assessment reject a candidate. Expiry quantities and remaining
terminal exposure are diagnostic, without invented waste penalty or terminal credit.
After-assessment consequences remain unassessed, not certified safe.

## Exact call boundary

```python
from src.contingency import (
    ContingencyInputs, ContingencyCandidate, ContingencyResult,
    ContingencyValidation, search_contingency, validate_contingency,
)

# p: ContingencyInputs, entirely caller-resolved immutable frozen facts
result: ContingencyResult = search_contingency(p)
# Supplied candidate can originate outside search; no optimiser rerun here.
validation: ContingencyValidation = validate_contingency(p, candidate)
```

Typed fixture candidate (not Backend JSON):

```python
from decimal import Decimal
from src.procurement import Cash, PurchaseCandidate, PurchaseLine

candidate = ContingencyCandidate(PurchaseCandidate(
    lines=(PurchaseLine("rescue", Decimal("4"), "kg"),),
    claimed_cash=Cash(Decimal("8"), Decimal("3"), Decimal("4"), Decimal("15")),
))
# With the complete fixture request: validation.complete=True, feasible=True;
# recomputed cash=Cash(8,3,4,15), one Addition, one ShipmentCharge, and projected
# vegetables closing4 after the fixed original remainder arrives the next day.
```

These dataclasses/TypedDicts are internal Python arguments, **not a new public
transport schema**. `candidate` is `ContingencyCandidate(purchase: PurchaseCandidate,
claimed_additions: tuple[Addition,...] | None)`. Optional claimed cash and additions
are recomputed and compared, not trusted. Production callers must perform independent
validation on exactly the frozen request used for search, then Backend freshness checks.

| Required input | Existing field/function and mapping responsibility |
|---|---|
| `inventory: MultiDayInputs` | Exact `project_multiday` arguments; no second inventory model. Chun Yang resolves the bundle, Rudy maps it. |
| `inventory.coverage` | `CoverageResult` with operational issue, separate known-at, captured revision, all ingredient windows and their evidence, explicit maximum horizon. Existing first-slice `policy.target_date/horizon_end` is insufficient for arbitrary residual windows. |
| `inventory.forecasts` | Existing dated `ForecastVersion`, residual future buckets, complete profiles and catalogue/recipe/history/model/policy/context refs. Reuse Demand's frozen remainder; actual portions already reflected in estimated opening are never consumed again. Promotion APPLIED stays applied once. |
| Catalogue, recipes, recipe manifest | Existing `MenuItem`, `Ingredient`, `RecipeItem` and captured catalogue/recipe artifacts; same five dishes/eight ingredients and base units. Authoritative completeness must not be inferred merely from received rows. |
| Opening + manifest | `EstimatedInventoryLot`, complete per-ingredient lot coverage, explicit zero versus missing, same cutoff. Backend frozen inventory seam exists; source-selection correctness is still Backend's responsibility. |
| Fixed supplies + manifest | `commitment_projection` → existing `ExpectedSupply(Delivery,expiry_date,expiry_evidence,projected_lot_id)`; all received/cancelled/outstanding quantities and actual receipt links retained. `inventory_tools._commitment_supplies` is the existing mapping seam. |
| Evidence + safety/storage/assessment | Snapshot/opening/supply/catalogue/recipe/constraints `SourceEvidence`, all ingredient vectors and assessment endpoints; each availability/revision checked. No guessed unlimited storage or zero safety. |
| `suppliers`, `offers`, `approved_offer_manifest` | Canonical `Supplier`/`SupplierOffer`; complete `(offer_id,supplier_id,ingredient_id)` approval triples. Reuse frozen offer revisions, never mutable rereads. All required fields retained under their canonical names. |
| `opportunities`, `opportunity_manifest` | Existing `OrderingOpportunity` plus complete manifest and domain evidence. `None` unknown; empty list explicitly none. New placement must equal issue time; feasible arrivals and expiry supported by frozen terms. No future capacity renewal. |
| `shipment_groups` | Opportunity ID → explicit **new** shipment ID. Backend must supply this versioned relationship; first-slice supplier/arrival inference cannot distinguish two same-time shipments. |
| `max_packs` | Each opportunity exactly `floor(offer.available_quantity / offer.pack_size)`; smaller arbitrary bounds are rejected. Capacity shared across all new selections using that offer. Do not subtract old commitments again. |
| `budget`, `policies`, `work_limit` | Explicit nonnegative Decimal incremental SGD budget; all seven `POLICIES` tags; positive work limit. Existing policy transport cannot activate these tags without Chun Yang's versioned mapping. |
| `evidence`, `offer_evidence` | Required categories exported as `EVIDENCE`: approvals, domain, budget, shipments and all seven policy categories; each offer and opportunity expiry needs capture-bound available evidence. Domain refs attest to completeness but cannot manufacture it. |

Offer fields required: `unit_price`, `available_quantity`, `moq`, `pack_size`,
`lead_time_minutes`, tagged `order_cutoff`, `feasible_delivery_at`, `current_status`,
`shelf_life_days_on_arrival`, `delivery_fee_sgd`, `emergency_fee_sgd`, `observed_at`
and canonical identities/currency. A null required field is incomplete. Empty listed
slots or zero available quantity are known exclusions. Reliability is optional context.

Cutoff/lead equality is allowed. Latest placement is the minimum of arrival minus
lead time and that order day's explicit cutoff. Arrivals at bucket start can serve
it; at bucket end cannot backfill it. Mid-bucket arrival is unsupported/incomplete.
The engine neither delays fulfilment of earlier unmet demand nor cancels an old order.

## Cash and result semantics

Every selected line receives an `Addition` with opportunity/offer/supplier/ingredient,
unit/quantity, shipment identity, order/arrival/latest placement, expiry and kind.
Fixed commitments never become Addition rows. Multiple lines sharing one shipment
must have the same supplier/order/arrival/delivery-fee/emergency-fee terms; conflicting
declarations are incomplete. Separate shipment IDs incur separate fees even when
supplier and arrival match. NORMAL-only groups have zero emergency charge; mixed
groups pay it once. This charge is exclusive **money**, not a reliability score.
No existing fee is recharged or used to infer free consolidation with an old order.

`ContingencyValidation` returns `complete`, nullable `feasible`, findings, concrete
violations, exact `Cash`, resolved additions, `ShipmentCharge` rows and projection.
Line-level invalidity may prevent projection; budget failure still retains the
timed projection for diagnosis. Missing required facts yield feasible/cash unavailable.
Structural contradictions (unknown references, negative input, arbitrary bounds)
raise `ValueError`; an adapter must not turn that into supplier impossibility.

`ContingencyResult` echoes coverage, assessment endpoints, policy/source refs,
status/reason, work/evaluation/domain counts, candidate/validation, exclusion evidence,
overlapping rejection counts, diagnostic incumbent and `NoPurchase`.
`NoPurchase` uses exactly the original stock/forecasts/fixed commitments; its projection
contains timed shortages/safety/storage/expiry and fixed receipt effects. It is always
diagnostic (`actionable=False`). Dish lost sales/portions and full economic score remain
`None`: aggregate ingredient deficits do not identify whole-dish fulfilment.

| Result | Required consumer mapping (Rudy; Backend persists evidence) |
|---|---|
| `OPTIMAL_IN_DOMAIN` + independently feasible | Eligible for fresh Backend validation/publication, never automatic approval/order. Empty additions are valid numerical output, not automatic KEEP_CURRENT_PLAN. |
| `INFEASIBLE_IN_DOMAIN / NO_TIMELY_SUPPLY_IN_DOMAIN` | Every grid point checked; none covers protected demand with valid supply lines even before budget/storage/safety. Map to `NO_FEASIBLE_SUPPLIER` **within declared domain**, carrying exclusions and timed unmet evidence. |
| `INFEASIBLE_IN_DOMAIN / POLICY_CONSTRAINT_INFEASIBLE` | At least one valid-supply candidate covers demand, but all fail budget/storage/safety. Map to policy/shortage escalation with actual violations; do not call it a supplier failure. |
| `INCOMPLETE / INPUT_OR_SCOPE_INCOMPLETE` | Preserve findings: missing data → `MISSING_REQUIRED_DATA`; unsupported policy/timing/size → `CALCULATION_INCOMPLETE` or agreed policy mapping. Never safe/no-risk or a candidate. |
| `INCOMPLETE / SEARCH_LIMIT_REACHED` | `CALCULATION_INCOMPLETE` with SEARCH_LIMIT_REACHED detail; incumbent diagnostic only. Distinct from Coordinator CALL_LIMIT_REACHED. |
| Invalid supplied candidate | Reject with exact violations; no publication. |
| Unexpected execution exception | Actual `TOOL_FAILURE`; do not fabricate completed numerical output. |

**Required adapter correction:** `decision_engine_adapter.run_first_slice_engine`
currently maps every `INFEASIBLE_IN_DOMAIN` to `NO_FEASIBLE_SUPPLIER` (line 200 at
the inspected base). It also constructs first-slice groups from supplier/arrival.
Neither mapping can be copied unchanged for contingency. This task leaves that
Rudy-owned adapter and Backend's `planning_schemas.Candidate` untouched. In particular,
its default economic fields must not present unavailable full economic costs as
calculated zero; persist the cash scope and unavailable diagnostic fields explicitly.

## Search guarantee and support limits

Every 0..max-packs allocation for each opportunity is enumerated using an O(n)
mixed-radix counter, without materialising Cartesian pools. Zero, below-MOQ and
over-shared-capacity combinations are counted and rejected, not arbitrarily pruned.
No early success stops the required enumeration. The exact minimum cash and semantic
tie result is optimal only within the supplied finite opportunity domain, not every
possible supplier/arrival, renewal, continuation or economic policy.

Construction charges one unit per counted input row plus the baseline calculation;
each candidate charges `1 + number_of_opportunities`. `work_used`, `evaluated`, and
`domain_size` are distinct. Technical support caps: 32 opportunities, 10,000 counted
input rows, configured maximum horizon at most 31 days, work limit 1..1,000,000.
These caps reject unsupported scope rather than truncate data or domain. They are
not business defaults or a measured latency guarantee. See `_prepare` for counted
rows (offers/opportunities, lots/ingredients/recipes, supplies/receipts, profiles/buckets).
Calling the standalone validator also needs sufficient preparation work allowance.

All projected quantities/money remain exact Decimal with rational intermediates.
Serialize as decimal strings; no float conversion or premature pack/cent rounding.
Hypothetical Delivery uses the existing three-decimal physical purchase boundary;
unsupported purchase precision returns incomplete, never rounded. Backend must retain
finer projected quantities separately from observed-stock storage.

## Independently calculated acceptance example

`tests/fixtures/contingency_v1.json` is synthetic; it was not emitted by Backend.
Operational opening: **16 February 2026 10:00 SGT**. Separate known-at: **22 September
2026 10:00 SGT**, capture `synthetic-contingency-capture-1`. Explicit version-1 source
refs, full catalogue/recipe/opening/supply manifests; these are fixture identities.
All ingredients protect to 16 February 12:00; vegetables assess through 17 February
12:00 to retain the delayed original. No implied seven-day or production calendar.

Remaining forecast: 70 tofu bowls at 11:00–11:30, 30 at 11:30–12:00; other dishes
explicit zero. Next-day assessment demand explicit zero. Canonical recipes give
vegetables/rice **7 then 3 kg**, tofu **10.5 then 4.5 kg**, other ingredients zero.
Opening vegetables6, rice20, tofu20; other five ingredients explicitly zero.
Safety0, storage30 per ingredient/base unit, budgetS$30 are fixture-only inputs.

Original `fresh` delivery:10 ordered,6 received and present once in opening,
0 cancelled,4 outstanding arriving **17 February 09:00**, supported expiry20 Feb.
New `market-vegetables` emergency: capacity6, pack/MOQ1, S$2/kg, one-hour lead,
arrival16 Feb11:00, expiry17 Feb; one new shipment, deliveryS$3, exclusive emergencyS$4.

| Alternative | New additions/cash | Vegetables and first shortage |
|---|---|---|
| Rescue | 4 kg; acquisition8 + delivery3 + emergency4 = **S$15** | 6+4−7=3 after first bucket; 3−3=0 after second; original4 later → assessment close4. No protected shortage. |
| No new purchase | S$0, diagnostic | First bucket allocates6/unmet1; second allocates0/unmet3. First shortage16 Feb11:00–11:30. Original4 next day remains, close4; it does not erase unmet4. |
| Original arrives on time16 Feb11:00 | Empty additions, **S$0** | 6+4=10 allocated exactly once, close0. |
| Original remainder cancelled | Rescue4, **S$15** | Cancellation removes only4; opening6 unchanged; close0. |
| All new slots miss first bucket | No candidate, completed domain proof | `NO_TIMELY_SUPPLY_IN_DOMAIN`, precise earlier shortage retained. |
| BudgetS$14 | No candidate, completed policy infeasibility | Timely4kg exists but costs15; `POLICY_CONSTRAINT_INFEASIBLE`. |
| Missing original expiry | Incomplete, no candidate | Missing expiry evidence, possible earlier verified risk retained. |
| Work limit55 stops after allocations0..4 of0..6 | Incomplete, no actionable candidate | S$15 incumbent diagnostic only; two required allocations still unexamined. Complete fixture needs59 work units:45 construction/baseline +7×2 candidate units. |

Pack3/MOQ3 instead gives6kg, cash12+3+4=**S$19**, two extra kg caused by packs;
later original remains4. If rescue expires at midnight, FEFO determines which lot's
surplus expires; no aggregate subtraction guesses its identity. Two suppliers with
2kg capacity each require a2+2 split: acquisition8 + two delivery fees6 + two
emergency charges8 = **S$22**. Two different ingredients in one new shipment pay
one delivery/emergency charge, tested independently.

## Acceptance and activation boundary

`tests/test_contingency.py` checks all 23 requested numerical groups: on-time/partial/
short/cancelled/delayed and previously recorded commitments; supplier splits and
shared offer capacity; supplier proof versus budget/storage/safety; missing refs/
coverage/expiry/policy; interrupted incumbent; shared/distinct shipment charges;
sunk old fees; no backfill; late storage/expiry; expiry boundary/equal-expiry FEFO;
ID-order and reliability invariance; candidate tampering; normal-reduction rejection;
elapsed actual exclusion; no-action risk; next-day protection. Additional checks
cover exact conservation, no mutation, malformed quantities and ambient precision.

The external-purchase story is **numerically verified only**: recommendation4kg;
approval changes no input; subsequently supplied separate external EMERGENCY
Delivery4kg prevents duplicate recommendations; it has no receipt yet. The existing
Backend `POST /deliveries` and `POST /deliveries/{id}/receive` support recording
facts, but this task does not activate a contingency plan through them.

**Chun Yang:** map/persist/select the new policy, residual multi-day forecasts and
per-ingredient windows, full domain, explicit new-shipment grouping, constraints,
commitment expiry/revisions and lossless evidence under the captured clocks. Keep
NORMAL_ONLY until that mapping is implemented; retain existing normal policy.
Bind candidate/validation/no-action artifacts and enforce freshness, approval,
additional-only source-line quantities and external emergency recording.

**Rudy:** consume those exact frozen artifacts without defaults/mutable rereads;
invoke both functions, preserve reason/completeness/scope, use the discriminating
mapping above, persist resolvable evidence, and route normal versus contingency by
the selected policy. Neither an empty addition nor a diagnostic incumbent permits
an automatic KEEP/approval. Normal worker/live-provider readiness is separate.

**Still pending for #11:** activated-policy Backend/Agent/API acceptance of on-time
no duplicate, partial/late/cancelled rescue, typed escalation, fresh pending-plan
publication/approval, separate external emergency recording, re-assessment and
later actual receipt. These numerical fixtures do not close issue #11 or #16.
Full economic scoring/continuation/terminal policy and real-world accuracy remain
outside this increment. No full synthetic training calendar is approved here.

## Reproduce

From `services/api` with locked dependencies (`uv sync --locked`):

```powershell
$env:RESTOCK_TEST_TMP = Join-Path $env:TEMP 'restock-contingency-tests'
uv run python -m pytest -q tests/test_contingency.py
uv run python -m ruff check .
uv run python -m pyright
uv run python -m ruff format --check src/contingency.py tests/test_contingency.py
```

RESTOCK_TEST_TMP must be an absolute writable directory **outside the repository**
for synthetic-history regressions. Full Backend verification additionally needs
isolated disposable PostgreSQL and `TEST_DATABASE_URL`, as documented in API README.
Fresh execution results are recorded in ML_NUMERICAL_FUNCTIONS.md / ML_HANDOVER.md.
