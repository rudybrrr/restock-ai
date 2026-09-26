# Aniq numerical handback — verified numerical scope

26 September 2026. Publication branch `feat/ml-economics-main`, based directly on
main `8be6496514fc3e82dae831c35e4f64ec18eb408a`. The user has authorised publishing
and merging this numerical slice. It does not activate production policies.

Development originated on `feat/ml-frontend-handoff` at integration
`50a78e07d5e03e21ad4bd572848a405a0abbe7a0`. Only the sixteen ML files were copied
to the main-based publication branch; the integration branch's seventeen extra
Agent/UI commits are excluded. Earlier checkpoints below describe development
history. Current merge validation is recorded at the end of this document.

## Implementation note, before edits

The user's new scope makes waste entry and full economics mandatory product
requirements. The user's later explicit instruction establishes priority
**v5 > v3 > v2**: higher-numbered plans supersede conflicting lower-numbered
requirements; compatible lower-plan detail still applies. Neither mandatory
scope nor this precedence instruction freezes explicitly unresolved
terminal valuation, continuation, or a Backend waste lifecycle.

Implement independent numerical support in the existing API `src` layout:

- `waste_accounting.py`: explicit proposed revision policy, visibility selection,
  count-boundary classification and a single-event-time deduction helper. Reuse
  canonical lot/ingredient types and exact quantity/time primitives. Do not add
  another historical inventory replayer or change Backend runtime behaviour.
- Full economic scoring/search: reuse forecast, recipe, coverage, projection and
  procurement kernels. Complete multi-day scoring and continuation remain required;
  the waste helper alone is not completion of this task.
- Focused independent tests and this concrete handback, with existing shared and
  local documentation updated at verified checkpoints.

Waste fixtures explicitly propose replacement revisions, reversal as zero effective
deduction, count absorption at equal timestamps, and separate expired disposal.
CY must confirm/persist the lifecycle. Tests must cover late revisions, retries,
corrections, reversals, count resets, quantity limits, units and expiry without
assuming gaps or unexplained count differences are waste. Economic fixtures must
explicitly supply policies rather than activating them as production defaults.

The existing `sales.estimated_inventory` replays sales then physical counts at
equal times. Its count resets must be preserved. Waste support must eventually be
inserted chronologically by CY: subtracting all waste from a final balance would
change intervening FEFO allocations and is incorrect. No new manager endpoint is
claimed or prescribed here.

## Current requirement mapping

| Ethan requirement | Existing source / new numerical work | Status and next owner |
| --- | --- | --- |
| Forecast method and eligible historical output | `forecasting.seasonal_baseline` → `DishForecast`; `service_buckets.allocate_service_buckets` → `ProjectedDemandBucket`; `promotion_forecasting.ForecastVersion` | Numerical functions available; CY must expose a selected immutable manager artifact retaining baseline method/eligibility metadata |
| Run-bound forecast evidence | `sales_materiality_contracts.read_assessment(session, run_id)` → `SalesMaterialityAssessment.engine_request.issued_forecast` | Persisted for sales-materiality assessments; not a general forecast catalogue or manager forecast feed |
| Manager sales evidence | `GET /api/v1/manager/runs/{run_id}/sales-materiality` → `SalesMaterialityDisplay` | Available, but deliberately omits `engine_request` and therefore the forecast buckets. Do not give the browser an Agent token or claim this route exposes those buckets |
| Ingredient requirements | `requirements.calculate_requirements` | Available for every ingredient, explicit zero included; CY persists selected calculated values, Ethan displays strings |
| Timed projected balances and shortages | `inventory_projection.project_inventory`; `coverage.calculate_coverage`; `multiday_projection.project_multiday` | Available pure results; CY must persist/read the selected result and recommendation basis |
| Waste numerical accounting | New `waste_accounting.select_waste_effects` / `apply_waste_at` | Tested proposed semantics, not an approved lifecycle or manager integration |
| Full economic objective | New `economic_ledger.score_ledger`, `economic_rollout.rollout_economics`, `economic_continuation.continue_routine`, `economic_search.search_economics` / `validate_economic_candidate` | Local policy-explicit numerical implementation, including frozen supply validation, continuation, finite search and independent candidate checks; numerical audit complete, production policy not frozen |
| Stored economic result and Agent consumption | No full-economic publication path established by this work | CY owns authority/read boundary; Rudy owns consumption after the complete numerical output exists |
| Connected waste and economic demonstration | Not yet available | Numerical handback ready; requires policy agreement, CY/Rudy/Ethan integration and actual connected acceptance |

### Forecast selection and values

`seasonal_baseline(history, menu_items, *, issue_time, target_date)` returns one
`DishForecast` per dish: `expected_portions`, `method`, `eligible_days`,
`matching_weekdays`, `used_history`, `coverage_flags`. It selects the latest final
daily revision visible at issue time, excludes promotional/censored observations,
uses four matching weekdays or the eligible-day fallback when at least seven
exist, otherwise returns `None` with `manual_required`. Missing is not zero.
Fractional demand uses 28-significant-digit Decimal arithmetic, not rounded orders.

The independently tested four-Monday v3 synthetic fixture produces 100 chicken
rice, 60 fried rice, 80 chicken noodles, 40 tofu bowls and 40 vegetable noodles.
Canonical recipe requirements are chicken24.600kg, rice20.000kg, noodles18.000kg,
eggs60pieces, tofu6.000kg, vegetables11.800kg, oil1.000litres, soy-sauce1.800litres.
These are synthetic numerical examples, not claims of retrieved persisted runs.

The explicit dated allocator produces Singapore half-open service buckets
`[start,end)` from a supplied profile; examples use six lunch buckets with40%
and eight dinner buckets with60%. `ForecastVersion` carries reference, base
reference, as_of, known_at, target_date, profile, immutable buckets, source
evidence, promotion revisions and elapsed observed coverage. Its reference is
caller-supplied, not proof that the pure kernel persisted anything. Source
evidence must resolve model/catalogue/recipe/history/profile/policy revisions.
The baseline `DishForecast` metadata is not all present in `ForecastVersion`;
CY must retain it when freezing a display artifact rather than reconstructing
eligibility from newer history. No new public schema/version has been frozen here.

CY's smallest addition is a manager-safe read of an immutable stored forecast
result selected by exact run/artifact reference, with method/eligibility metadata,
captured revision, clocks and original catalogue/recipe/model references. Bind a
plan to that exact reference. A date selector must resolve a particular version,
not silently replace an old plan's result with today's inference. No endpoint
name or real evidence ID is invented by this proposal. A genuine database response
has not been retrieved in this task; the field mapping above is code inspection.

Concrete **proposed manager display example**, built from the independently tested
synthetic v3 fixture (not emitted by Backend; names below are illustrative fields,
not a new approved transport schema):

```json
{
  "artifact_reference": "synthetic:v3-four-mondays-display-example",
  "run_reference": null,
  "plan_reference": null,
  "issue_time": "2026-02-15T22:00:00+08:00",
  "knowledge_cutoff": "2026-02-15T22:00:00+08:00",
  "operational_cutoff": "2026-02-15T22:00:00+08:00",
  "target_date": "2026-02-16",
  "timezone": "Asia/Singapore",
  "captured_revision": "synthetic-example-only",
  "catalogue_recipe_reference": "tests/fixtures/seasonal_baseline_v3.json",
  "method": "weekday_mean",
  "eligible_matching_days": 4,
  "expected_portions": {
    "chicken-rice": "100", "fried-rice": "60", "chicken-noodles": "80",
    "tofu-bowl": "40", "vegetable-noodles": "40"
  },
  "provenance": "PROJECTED",
  "availability": "SYNTHETIC_NUMERICAL_EXAMPLE_NOT_PERSISTED"
}
```

The actual baseline method tag is `weekday_mean`, not an invented model version.
There is no published forecast transport-schema version to supply here. For a live
artifact CY must replace these synthetic references with frozen catalogue/recipe,
method implementation and artifact revisions, and persist per-dish flags/history
and bucket data. A missing value is JSON `null`, not an omitted dish or numeric0.
The example's null run/plan links deliberately claim no persisted assessment.

### Projection meanings

One-day `InventoryProjection` uses `complete=False` with numerical fields `None`
for unsupported/missing evidence. Multi-day `MultiDayProjection` preserves each
ingredient's `verified_until`, verified `projection` prefix, movements and breaches
even when a later interval is unresolved. Display that prefix as bounded evidence;
never label subsequent unknown stock as zero. Protection ends differ by ingredient;
the common economic horizon is separate from those purchasing windows.

`BucketProjection` opening is usable stock after arrivals/expiry at bucket start,
and closing is after that interval's allocated demand. Its arrival/expiry columns
are not a full timeline: use multi-day `DatedBalance` movements for dated arrivals
and expiry. There, `closing = opening + admitted - allocated - expired`; allocation
is displayed at bucket end and arrivals/expiry at their actual boundary. Shortage
intervals come from bucket requirements/unmet quantities, not guessed from that
point-in-time line. Mid-bucket arrivals are explicitly unsupported. Expiry is next
Singapore midnight after expiry_date. FEFO uses expiry, receipt time, then the
explicit actual/projected lot identity. Do not compare namespaced provenance keys
as if they were Backend lot-ID ties.

Actual receipt quantity is already represented in received stock; only reconciled
`Delivery.outstanding_quantity` enters expected supply. A with-recommendation
projection adds that specific candidate's hypothetical lines with separate IDs;
approval alone never turns them into receipts. Persist the basis and exact plan
version along with the projection. Storage/safety/shortage breaches retain their
protected-versus-later-assessment scope. Budget comes from candidate validation,
not inventory arithmetic. None of these pure types authorises a manager response
or certifies freshness against a database by itself.

Projection display oracle from existing `tests/fixtures/inventory_projection_v1.json`:
16 February2026, existing commitments only, vegetables2.000kg at10:00 SGT; tofu-bowl
recipe uses0.100kg vegetables per portion, with15 then10 projected portions.

| Service interval SGT | Opening usable kg | Expected arrivals kg | Required kg | Allocated kg | Closing usable kg | Unmet kg |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 11:00–11:30 | 2.000 | 0.000 | 1.500 | 1.500 | 0.500 | 0.000 |
| 11:30–12:00 | 0.500 | 0.000 | 1.000 | 0.500 | 0.000 | 0.500 |

First shortage is exactly `[11:30,12:00)`, with no expiry in those intervals.
The fixture supplies all eight ingredients, with explicit ample other stock.
It deliberately separates February operational time from September synthetic
recording/knowledge time; it is a retrospective test, not a forecast known in
February. Arrival-at-start/end and late-supply tests verify that a later receipt
cannot remove this earlier shortage. `test_missing_later_data_retains_known_shortage`
and `test_unresolved_later_supply_retains_verified_earlier_shortage` preserve a known
prefix when later data becomes unavailable. Any recommendation-inclusive display
must state the exact candidate/plan revision and retain the fixed-only baseline;
it must not relabel the new line as an observed receipt.

## Waste helper and Backend handback

Internal fixture policy: `PROPOSED_WASTE_REPLACEMENT_REPLAY_V1`. This is deliberately
named proposed. `select_waste_effects` takes explicit received physical lots,
canonical ingredients, observation revision chains, a complete visible observation
manifest, as_of/known_at/captured_revision and evidence for waste/counts/lots/catalogue.
`WasteRevision` records observation and revision identity, replacement link, lot,
ingredient/unit, positive Decimal quantity, observed and recorded clocks, actor,
and explicit reversal status. Identical repeated rows deduplicate; conflicting
identities or changing lot/time across replacements fail. Missing revision chains,
policy or provenance produce incomplete selection with no effects.

The latest visible replacement controls the original observation time. A reversal
retains the recorded positive quantity as evidence but has zero effective disposal.
At or before the supplied latest physical count, disposal is already absorbed.
After expiry, recorded disposal reduces only explicitly supplied expired remainder,
not already-zero usable inventory. A missing expired balance is unknown. No count
discrepancy becomes waste automatically.

`apply_waste_at` handles one exact event timestamp and explicit pre-event usable
and expired balances. It is a helper for an authoritative replayer, not that
replayer. It returns immutable per-lot before/deduction/after rows and applied
revision IDs; overdraw is incomplete and atomic (no partial applied IDs). A retry
of the same revisions does not deduct again. Passing a superseded applied revision
requires replay from counts. Do not apply a replacement atop the old deduction.
Do not subtract every selected observation from the final estimate: CY must replay
sales, waste and resets chronologically, with agreed within-batch timing boundaries.

Independent references:10kg minus2.125kg gives7.875kg; replacement1.25kg replayed
from10kg gives8.75kg; a subsequent6.5kg physical count remains6.5kg. Disposal2.125kg
from4kg expired remainder leaves1.875kg expired and0 usable. A corrected estimate
must feed the existing projection/materiality calculation; waste magnitude alone
is not a new materiality threshold, and incomplete sales coverage cannot become
complete because a waste record exists.

CY still needs accepted lifecycle decisions, append-only persistence, manager
authentication, idempotency key/content conflicts, concurrent revision checks,
positive quantity and event-time balance validation, explicit eligibility for
expired disposal, replay ordering/splits, list/history reads and run invalidation.
Rudy must consume resulting authoritative revision-bound risk/materiality evidence.
Ethan must wire actual writes/errors/retries only after those boundaries exist.
None is implemented or verified by these helper tests.

## Economic accounting checkpoint

`score_ledger(assets, service, shipments, ingredients, menu_items, *, manifests,
clocks, evidence, ledger_policy, terminal_policy, money_policy, provenance)` is
shorthand here for the explicitly named asset/service/shipment manifest arguments
in the function. `AssetFlow` conserves quantity across allocated, expired, usable
terminal and recoverable incoming terminal amounts. `DishService` holds required
and served portions and declared paid-equivalent net price/other variable cost.
Existing `contingency.ShipmentCharge` represents each new shipment once. This
does not trust a claimed optimiser cost, but it also does not yet validate the
chronological generation of those rows or certify supplier feasibility.

The proposed `PROPOSED_OPERATING_COST_LEDGER_V1` uses opening recognised assets +
new acquisition + delivery + exclusive emergency fees + incremental disposal +
unmet contribution, less explicitly selected terminal credit. Acquisition-valued
expiry and gross lost sales are descriptive columns, not duplicate addends.
`ZERO_TERMINAL_V1` and `BOOK_TERMINAL_V1` are separately selectable fixture policies;
both totals are reported. `SGD_HALF_EVEN_FINAL_V1` rounds only the final primary
comparison to cents and retains exact component Decimals. Future recoverable
incoming credit must be explicitly evidenced; leftover usable stock is not waste.

V5 §28 requires waste/stockout/cost economics, but does not freeze disposal rates
or terminal valuation. Treating its waste term as incremental disposal rather than
charging acquisition twice is a proposed accounting interpretation using compatible
v2 detail, requiring confirmation. V5 §35 permits, rather than requires, a reliability
penalty; no weight is specified. V3's CONTEXT_ONLY is retained absent an explicit
new policy. Mandatory scope does not make either a production default.

Complete accounting example (isolated chicken terms; other ingredients constant):
10kg atSGD1 with5kg expired and disposalSGD1/kg costsSGD15;5kg atSGD2.20 all used
costsSGD11. Acquisition-valued expirySGD5 is not added again. With usable leftovers,
10kg atSGD1.20 costsSGD12 under zero credit andSGD6 with5kg book credit; this reverses
its comparison withSGD11. No guaranteed future consumption is claimed.

Incomplete example: omit valuation evidence or the terminal policy and
`EconomicLedger.complete=False`, `components=None`; there is no cash-only fallback.
Complete ledger arithmetic is not full economic optimisation, a feasible candidate,
a completed search, or a connected demo. Those remain outstanding in this task.

## Verification at this checkpoint

- New waste37 + ledger23 tests: **60 passed**. Independent arithmetic; no database.
- Numerical regressions including forecasting, requirements, buckets, projection,
  synthetic history, multi-day coverage, procurement, contingency, materiality,
  promotion, physical day/seven-day scenarios: initial run712 passed/43 failed.
  All43 were synthetic-history output-isolation failures because test temporary
  paths defaulted inside the repository; no application behaviour was changed.
  Synthetic-history rerun with an external temporary root: **68 passed**, including
  configuration/profile semantic checks. The runs cover778 distinct passing cases
  after correcting the harness path; this is not one combined778-test execution.
- Whole-API Ruff and Pyright pass (0 errors/warnings); four changed Python files
  pass formatting; tracked diff check passes. Two existing dependency deprecation
  warnings. No PostgreSQL, browser, gateway or deployment check run: shared runtime
  and persistence are unchanged.

From `services/api` in this worktree, reuse the prepared Python3.12 environment:

```powershell
$env:RESTOCK_TEST_TMP = Join-Path $env:TEMP 'restock-ml-handoff-tests'
.venv/Scripts/python.exe -m pytest -q tests/test_waste_accounting.py tests/test_economic_ledger.py
.venv/Scripts/python.exe -m pytest -q tests/test_synthetic_history.py
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m pyright
.venv/Scripts/python.exe -m ruff format --check src/waste_accounting.py src/economic_ledger.py tests/test_waste_accounting.py tests/test_economic_ledger.py
git diff --check
```

## Chronological economic rollout checkpoint

`economic_rollout.rollout_economics(RolloutInputs)` executes the common 21-date
trajectory using canonical five-dish/eight-ingredient recipes. It validates frozen
forecasts, opening coverage and fixed receipt/cancellation reconciliation through
`project_multiday`, then calculates stock-constrained served dish portions in
stable dish-ID order. Unserved dishes consume none of their ingredients. This is
expected fractional service, not observed consumption or physical whole orders.

`RolloutInputs` supplies existing `MultiDayInputs`, exact horizon end, `AssetTerms`
for each opening/outstanding resource, `DishTerms` for each bucket/dish (including
zeros), optional `HypotheticalPurchase` values reusing `contingency.Addition`,
separate new `ShipmentCharge` values, evidence/policies and a work limit. Fixed
deliveries remain in inventory; hypothetical current/later purchases are separate.
This entry point does not choose continuation purchases or validate supplier offers.

`EconomicRollout` returns the ledger, conserved `AssetFlow` and `DishService` rows,
expected movements, breaches, warnings and the unchanged fixed-only projection.
`RolloutContext` retains clocks, revision, policies, forecast references, fixed
supply IDs and evidence even for incomplete calculations. A complete calculation
can still have shortages or storage/safety breaches; it does not certify a candidate.

`COMMON_21_CALENDAR_DAYS_V1` counts today only when the dated profile has remaining
service. After closing, include the next 21 dates; zero demand during a declared
service period still counts. `scoring_end(issue, has_remaining_service=...)` makes
this explicit. Including today's closed remainder can require the existing
projector's explicit elapsed-day support span to be 22; that does not lengthen any
actual protection window. Full forecast coverage and a common end remain required.

`FRACTIONAL_STABLE_DISH_28DP_DOWN_V1` keeps terminating ratios exact. Recurring
constrained fractions such as 2/3 round down to 28 places; residual stock/unmet
portions stay visible with `FRACTIONAL_REPRESENTATION_RESIDUAL`. Required demand is
unchanged. Hypothetical FEFO identities are explicitly
`hypothetical:<opportunity_id>`, not claims about future persisted lot IDs.

Arrivals at bucket start can serve it; arrivals at bucket end cannot repair it;
mid-bucket arrivals remain incomplete. Terminal expiry precedes credit. Evidenced
fixed supply arriving after the horizon remains incoming, not usable or consumed.
The original projector's `DELAYED_COMMITMENT_BEYOND_ASSESSMENT` finding is retained
as a warning with that unchanged projection. The bounded ledger may separately
complete with explicit expiry/lot identity and valuation evidence; it does not
certify consequences after the common cutoff. No future outcomes or refitted
forecasts enter this calculation.

Synthetic fixture: `tests/fixtures/economic_rollout_v1.json`, 16 February 00:00
through 9 March 00:00 SGT. Ten chicken-rice portions/day, all other dishes explicit
zero. Supplied protection spans are 1/14/3/3/2/1/7/7 days, separate from scoring.
Opening 3 kg chicken expires after day 1; 1.5 kg serves ten portions and 1.5 kg
expires. Other ingredients are sufficient or zero-demand. Their zero book costs
isolate this comparison and are fixture assumptions, not production defaults.

- No additions: 210 required, 10 served, 200 unmet. Opening SGD6 + disposal
  SGD1.50 + unmet contribution SGD1,600 = **SGD1,607.50**.
- 30 kg at SGD2 arriving day 2 at 10:00: 210 served; opening6 + acquisition60
  + disposal1.50 = **SGD67.50**.
- Same supply at 11:30, after service: 200 served, ten unmet. Zero-credit score
  **SGD147.50**, book sensitivity **SGD144.50** with 1.5 kg usable beyond the
  horizon. The earlier shortage remains visible.
- Missing costs/provenance, unsupported timing or exhausted work returns no total;
  retained movements are diagnostic only.

Verification: combined relevant numerical suite **799 passed**, two existing
dependency warnings (58.87s). After the isolated after-closing horizon correction
and two added cases, the final new waste/ledger/rollout group is **83 passed**
(4.33s), including all 23 rollout tests. The 799-test run predates that correction;
existing modules were unchanged. Whole-API Ruff/Pyright pass. No DB/model/UI run.

Reproduce this component from `services/api`:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_economic_rollout.py tests/test_economic_ledger.py tests/test_waste_accounting.py
```

This historical rollout checkpoint preceded the continuation/search implementation
below. An explicit hypothetical purchase list alone was not automatic continuation
or full optimisation.

## Frozen supply, continuation and economic search

These are local numerical interfaces, not new canonical Backend transport or an
approved production policy. The original v5/v3/v2 files remain unchanged.

`economic_supply.EconomicSupply` supplies issue/horizon/knowledge clocks, revision,
canonical ingredients/suppliers/offers, approved-offer and opportunity manifests,
explicit `CapacityWindow` rows, opportunity-to-window and shipment-group mappings,
disposal rates and frozen source evidence. A window's quantity is remaining NEW
capacity, shared across all allocations in that window. Recorded commitments are
not subtracted again. Windows for one offer cannot overlap or exceed its frozen
quantity; renewal cannot silently clear `UNAVAILABLE` status. Empty domains differ
from unavailable ones. Unknown price/expiry/fee/policy evidence prevents completion,
even if the affected alternative is not selected.

`validate_economic_supply(inputs, PurchaseCandidate)` independently resolves
canonical `Addition`, `HypotheticalPurchase`, `ShipmentCharge` and `Cash` values.
It checks approval, pack/MOQ, capacity, deadlines, lead time, delivery slots,
shelf-life expiry and claims. It separately returns immediate cash and total
hypothetical cash. Its feasibility certifies supply terms only, not stock or the
economic plan. It does not call either search.

`economic_continuation.ContinuationInputs` combines the fixed-only `RolloutInputs`
with that supply domain, explicit local decision times for every ingredient,
complete anchored `RoutineOccasion` rows, a shared incremental cash budget,
policy/evidence, deterministic work limit and explicit host timeout. Each occasion
declares its opportunities and next feasible ordinary receipt; that boundary is
cross-checked against the supplied later domain and capped only for hypothetical
future protection. Normal current protection is never shortened. The calendar uses
canonical `starting_date` and `interval_days`, not an ad hoc daily reset.

`continue_routine(inputs, current_purchase)` uses the same issued forecast
throughout. It takes the candidate's coupled-dish projected prefix, then checks
raw recipe demand independently for the ingredient being replenished. Another
ingredient's stockout cannot reduce this planning demand. It considers at most
three suppliers and two slots each, tests single-offer pack quantities and chooses
the lowest incremental landed cash, then stable opportunity ID/quantity. Shared
fees, capacity, stock expiry, storage, safety and the remaining budget apply.
FEFO depletion is shared with the rollout; no Backend replay/helper was changed.

The routine rule deliberately does not solve a recursive split optimisation.
If no single-offer continuation covers a gap, it records
`CONTINUATION_HEURISTIC_SHORTAGE`; it does not claim suppliers are impossible.
This is a fully modelled later risk when inputs/calculation are complete, and the
ledger charges its unmet portions. Future lines remain `actionable=false`, separate
from the current recommendation and all recorded deliveries.

`economic_search.EconomicSearchInputs` adds an explicit current-ingredient
authorisation manifest, search/objective/tie versions, work limit, score limit
(at most 32 current finalists plus diagnostic no-action) and host timeout.
`search_economics(inputs)` exhaustively enumerates the declared current capacity's
pack lattice, including zero and split purchases. It performs no unproved quantity
pruning. Large domains that cannot fit the work allowance return incomplete rather
than being allocated in memory or labelled supplier failure.

`validate_economic_candidate(inputs, EconomicCandidate)` is callable independently.
It does not call `search_economics`; it resolves terms again, checks each actual
ingredient protection window against raw demand before any continuation, recomputes
the common policy trajectory/ledger, checks future storage, and rejects altered
cash, continuation-line or component claims. Dish unmet demand and physical
ingredient shortage are separate: a chicken shortage does not falsely label
sufficient rice/soy sauce short. The coupled rollout alone cannot certify a long
ingredient window using sales suppressed by another ingredient's stockout.

The result separates `complete`/`feasible` validation from `search_complete` and
`optimal_in_domain`. `OK` requires complete enumeration and independent checks.
`INFEASIBLE / NO_FEASIBLE_CANDIDATE_IN_DOMAIN` proves only that explicit finite
domain, with concrete rejection counts such as budget or shortage. Work, host-time
or score-cap exhaustion is `INCOMPLETE / SEARCH_LIMIT_REACHED`; an incumbent is
diagnostic only. There is no cash-only fallback. A fully completed search claims
optimality only over current actions under the fixed greedy continuation, not all
possible future ordering strategies. Deadline expiry is polled between bounded
numerical batches; it is not process preemption or a latency guarantee.

Public search and independent-validation results always retain `EconomicContext`,
including incomplete results: rollout clocks/revision and forecast/fixed-supply
references, policy tags, current authorised ingredients, offer/window/occasion
source evidence, declared budget and work/score/host limits. The nested selected
validation uses the parent request context; decreasing internal timeout allowances
do not become nondeterministic policy metadata. These are source declarations, not
a replacement for CY persisting/hashing the complete canonical request and result.

Proposed fixture policy versions: `PROJECTED_OPERATING_COST_V2`,
`EXHAUSTIVE_CURRENT_GREEDY_ROUTINE_V1`, `GREEDY_ROUTINE_CONTINUATION_V1`,
`STABLE_OFFER_CONTINUATION_V1`, `EXPLICIT_NEW_SHIPMENT_ONCE_V1`, and
`ECONOMIC_CENTS_WASTE_CASH_SHIPMENTS_SUPPLIERS_IDS_V1`. Ties use rounded primary
SGD cents, expired book value, immediate cash, current shipment/supplier count,
then stable canonical line identities. Ledger/terminal/fulfilment policies remain
explicit. V5 permits a reliability penalty but does not supply its weight; the
implemented explicit `CONTEXT_ONLY` contract remains invariant to rate-only edits.

### Independent worked cases

Same 21-date canonical fixture as above. Current protection for chicken is one
day; it does not force a 21-day initial order. With opening3kg and daily future
1.5kg purchases at SGD2/kg (zero fixture fees), twenty routine purchases cost60.
Opening6 + initial disposal1.50 + purchases60 = **SGD67.50**, all210 portions served.
One30kg fixed outstanding delivery instead yields no routine purchases and the
same score: its60 valuation is opening assets, not a new acquisition.

For the economic search fixture, set opening chicken to explicit zero:

| Current choice | Current cash | Expired current chicken/removal | Future ordinary cash | Full zero-terminal score |
| --- | ---: | ---: | ---: | ---: |
| No purchase (diagnostic) | 0 | 0 | 60 | 140, including ten unmet portions ×8 |
| A: 3kg at1/kg, expires after day1 | 3 | 1.5kg /1.50 | 60 | 64.50 |
| B: 1.5kg at2.50/kg, expires after day1 | 3.75 | 0 | 60 | **63.75** |
| Both | 6.75 | 3kg /3 | 60 | 69.75 |

Four combinations are exhaustively checked. B wins despite greater immediate
cash. Acquisition-valued expired stock is not charged a second time. A separate
two-supplier fixture requires0.75kg at1 plus0.75kg at2; neither alone suffices,
and the combined current2.25 plus future60 gives **SGD62.25**.

Terminal sensitivity keeps all21 forecast dates but makes later demand explicit
zero: A3kg at1.40 with documented post-horizon expiry scores4.20 under zero credit
and2.10 under book credit; B1.5kg at2.50 scores3.75 under either. This demonstrates
the policy-dependent ranking without selecting the favourable valuation afterward.

Incomplete example: a score limit of2 permits no-action and the first feasible
current candidate, but leaves required alternatives unscored. Return
`INCOMPLETE / SEARCH_LIMIT_REACHED`, `candidate=None`, `optimal_in_domain=false`,
and the feasible incumbent only in `diagnostic_incumbent`. Missing opening costs
similarly returns `MISSING_ASSET_VALUATION`, never a cash recommendation.

### Integration handback and remaining gates

CY must confirm the economic/waste policies, supply authoritative frozen offer
windows, ordinary calendars, prices/disposal costs, demand economics, approvals,
budget/storage/safety, and catalogue/recipe/revision evidence. Persist the exact
request alongside the validated result and source references; the numerical
evidence checks cannot prove correct source selection. Provide manager-safe reads
of the frozen result, not current recomputations. No endpoint or persisted result
for this new full-economic engine is claimed as existing.

Rudy must consume the complete validated current candidate separately from
non-actionable no-action/continuation diagnostics. Incomplete, infeasible and
heuristic future risk are different states; neither incomplete totals nor an
incumbent may become an approvable plan. Existing orders remain immutable. The
Agent must not reproduce arithmetic, create future orders or claim numerical
tests prove a connected assessment. Ethan renders the selected persisted values
as Decimal strings, preserving zero versus unavailable and projected versus actual.

Before live publication: owner policy agreement, CY persistence/freshness/manager
reads and waste lifecycle, Rudy result mapping, Ethan screens/forms, then isolated
API/PostgreSQL and browser acceptance of the connected workflow. Publishing these numerical modules does not implement or authorise those other
owners' connections, activate a policy, or verify a live product workflow.

Reproduce the new components from `services/api`:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_economic_supply.py tests/test_economic_continuation.py tests/test_economic_search.py tests/test_economic_rollout.py
```

Verification: combined numerical regression **861 passed** in204.65s, including
the corrected synthetic-history profile validation. Then two additional
adversarial regressions reproduced missing SGD validation and a zero-capacity
future window being treated as a feasible receipt boundary. Both are corrected;
all **62 supply/continuation/search tests passed** in165.89s on the final code.
Do not describe this as a fresh863-test combined run. Two existing dependency
deprecation warnings; whole-API Ruff/Pyright pass, all12 new Python files format
clean, tracked/untracked whitespace checks pass. No DB, browser or model run.
Earlier799/83 counts above are historical. Final audit and subsequent verification
are recorded below; those earlier checks are not newly rerun results.


## Final requirement audit — 26 September 2026

**Aniq's authorised independent numerical implementation and handback are complete
locally. Production contract agreement and connected product completion are not.**
The mandatory manager waste workflow and connected full-economic demo remain open
product requirements. No owner approval is inferred from silence.

| Requested scope | Delivered evidence | Boundary / remaining owner |
| --- | --- | --- |
| Source precedence and preservation | v5 > v3 > v2 applied; original plan hashes unchanged; current integration/main/frontend refs inspected | Explicit unresolved policy proposals remain proposals |
| Exact forecast/read mapping | Existing callable/result fields, manager-read omission, synthetic four-Monday display example above | CY freezes and exposes manager-safe artifact; Ethan renders it |
| Timed projection handback | Existing one-/multi-day functions, verified-prefix semantics, explicit two-bucket balance/shortage oracle, fixed versus candidate supply basis | CY persists exact basis/version; no general manager projection feed claimed |
| Waste numerical contribution | `test_waste_accounting.py`: 37 passing cases for revision visibility, replacement/reversal, retries, counts, expiry, quantity conservation and immutability | Proposed lifecycle requires agreement and CY replay/persistence; Rudy triggers reassessment; Ethan supplies entry/history UI |
| Full economic components | `test_economic_ledger.py`: 23 passing cases, independent acquisition/disposal/contribution/terminal identities and final-cent rounding | Terminal/primary-objective policy not activated as production default |
| Common 21-date physical scoring | `test_economic_rollout.py`: 23 passing cases, canonical recipe coupling, FEFO/expiry, fixed partial receipts/cancellation, late supply, storage/safety and horizon boundaries | Forecast arithmetic is projected, not a second observed-history replayer or real outcome evidence |
| Explicit future supply and continuation | `test_economic_supply.py`: 28; `test_economic_continuation.py`: 20. Capacity renewal, fee grouping, calendars, raw ingredient protection, shared budget, deadlines, known heuristic limitations | Future single-offer greedy policy can miss a feasible split; it reports heuristic shortage, not supplier impossibility. No future line is an order |
| Search, independent validation and evidence | `test_economic_search.py`: 15. Four-choice exhaustive oracle, split oracle, tamper rejection without invoking search, terminal sensitivity, ties, reliability invariance, work limits and evidence context | Optimal only in the declared current domain under supplied continuation. Large/unfinished search has no actionable incumbent |
| Regression and isolation | Earlier 861-test combined numerical regression plus final 146-test new-module run; current static/format/whitespace checks | No shared runtime change: no PostgreSQL, live model, browser or deployment verification performed |
| Concrete owner handback | Callable inputs/outputs, proposed policies, worked and incomplete examples, manager read gaps and owners in this document | CY/Rudy/Ethan integration and connected acceptance remain necessary |

The final new-module run passed **146 tests in 145.42s**, with two existing
Starlette/httpx/anyio dependency deprecation warnings. It includes the latest
context-preservation checks and an actual feasible future-split case that the
single-offer continuation misses. Whole-API Ruff passed; whole-API Pyright reported
**0 errors and 0 warnings**. All twelve new Python files pass Ruff formatting;
tracked and untracked changes pass whitespace checks. The earlier **861-test**
combined regression remains a prior checkpoint, not a fresh combined run on these
last metadata/test edits. No existing runtime source has changed.

Reproduce the final focused run from `services/api`:

```powershell
.venv/Scripts/python.exe -m pytest -q tests/test_waste_accounting.py tests/test_economic_ledger.py tests/test_economic_rollout.py tests/test_economic_supply.py tests/test_economic_continuation.py tests/test_economic_search.py
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m pyright
```

Freshly inspected references: local/integration base
`50a78e07d5e03e21ad4bd572848a405a0abbe7a0`, main
`8be6496514fc3e82dae831c35e4f64ec18eb408a`, frontend branch
`2527896a87a8da17075257de57f29752ebb698a8`. Integration and the inspected frontend
branch have no API-file differences. The local feature is 17 commits ahead of
main and zero behind; no merge/rebase was performed. Original `restock-ai` is
clean; unrelated materiality-worktree changes remain untouched. Staging is empty.
At that development checkpoint all new numerical code, tests and documentation
were uncommitted; see the main-based publication record below for subsequent status.

Next smallest step: confirm the proposed waste lifecycle and primary economic /
terminal / continuation policy with their owners, then CY can implement the
smallest frozen manager-safe request/result boundary from this handback. Numerical
policy fixtures are reviewable now. Subsequent merge authorisation covers code
publication only; it does not settle policies or authorise that Backend adapter.


## Main-based publication — 26 September 2026

The selected implementation is on
[feat/ml-economics-main](https://github.com/rudybrrr/restock-ai/tree/feat/ml-economics-main),
based on main `8be6496514fc3e82dae831c35e4f64ec18eb408a`. Publication/merge status
is established by GitHub's commit and pull-request history, not a fabricated SHA
inside this source. The six numerical modules, six test modules and small fixture
are byte-identical to the verified development work; only these shared docs were
updated for publication. No existing runtime module or dependency changed.

The source/read mapping above also exists on this main base, but does not prove
successful runtime persistence. In particular, main does not yet include Rudy's
integration-branch sales-materiality serializer/worker repairs. This ML-only change
does not merge those repairs or claim their live acceptance. New economic and
waste helpers have no Backend/Agent call site or manager endpoint in this change.

Production primary-objective, terminal, continuation and waste lifecycle decisions
remain pending. Merging tested policy-explicit numerical code is not activation
of fixture assumptions and is not completion of the mandatory connected demo.

Merge verification on main base8be6496: **864 numerical tests passed in75.21s**,
with two existing dependency deprecation warnings. This fresh run includes all146
new-component cases plus forecasting, requirements, service buckets, one-day and
multi-day projection, synthetic history, procurement, contingency, materiality,
promotion forecasts and physical simulator/scenario regressions. Whole-API Ruff
passed, Pyright reported0errors/0warnings, and all12 new Python files passed Ruff
format checking. No production runtime/persistence code changed, so PostgreSQL,
frontend/browser, live gateway and deployment gates were not run or claimed.
