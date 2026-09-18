# ReStock numerical functions and development datasets

Latest addition: [promotion application and immutable comparison](#promotion-forecast-application-and-comparison--18-september-2026).
It adds the Demand numerical seam; the Pass 3E inventory/procurement contracts below
are unchanged.

## Pass 3E numerical compatibility — 17 September 2026

This section supersedes historical policy/waiting statements below. Governing
sources: approved v2 + v3, both supplied Pass 3E discussion/handoff documents,
and the explicit 16–17 September decisions in the implementation prompt.
Base: `86abb37cb12eaee8296c2418e88f2f7b9bdef0ba`; isolated branch
`feat/ml-pass3e-compatibility`. The original checkout is preserved.
[Chun Yang's confirmation](https://github.com/rudybrrr/restock-ai/issues/16#issuecomment-5700645096)
and current code establish that PR #20's policy/domain is merged. The fetched agent
branch remains `764a27b9f89be86a36dd3d8dcc95079f77314239`; unpublished work is unknown.

### Exact supported policies

| Identifier | Meaning |
|---|---|
| `FEFO_EXPIRY_RECEIVED_LOT_ID_V1` | Expiry, receipt/expected-availability instant, actual or explicitly projected lot identity; only arrived, unexpired stock |
| `EXPIRY_ARRIVAL_PLUS_SHELF_LIFE_MINUS_ONE_V1` | Singapore arrival date + shelf-life days − 1; usable through that day, excluded at next Singapore midnight; nonpositive shelf life cannot validate |
| `SUPPLIER_ID_THEN_INGREDIENT_ID_V1` | Cash first, then lexicographically sorted `(supplier_id, ingredient_id, normalized order instant, normalized arrival instant, kind, offer_id, Decimal quantity, unit)` line tuples; no fewer-lines or opportunity-ID preference |
| `COMPLETE_PRUNED_DOMAIN_V1` | Complete minimum-pack compositions under the guards/proof below; explicit incomplete result outside that scope |

Backend `CASH_SLICE_V1` and normal-only `SUPPLIER_ARRIVAL_ONCE_V1` are supported
directly: exact acquisition plus one fee per supplier/arrival; no emergency line,
commitment co-shipping credit, discounts, minimum-spend obligation or future value.
Reliability remains context-only. Legacy explicit emergency cash/tie and Cartesian
policies remain available for earlier fixtures. The old
`USABLE_THROUGH_ARRIVAL_DATE_PLUS_DAYS` tag is rejected, not reinterpreted. The
small procurement fixture/tests now supply corrected expiry; physical expiries
and the backend seed are unchanged.

### Callable inputs, evidence and identity

`search_procurement(ProcurementInputs)` and independent
`validate_candidate(inputs, PurchaseCandidate)` remain pure functions. New input
`search_policy` selects the method; omission preserves legacy
`COMPLETE_CARTESIAN_V1`, never implicit pruning. Bind the search tag to required
domain policy evidence and persist it with the request. The validator recomputes
cash, expiry, timed coverage, capacity, packs/MOQ, storage, budget and safety
without calling the optimiser or trusting its feasible flag.

| Backend source | Numerical mapping / required validation |
|---|---|
| `policy.payload` | Issue/target/end/profile, safety/storage/budget, objective/fee/expiry/tie/search tags; verify SGD, Singapore, 30-minute, NORMAL_ONLY and CONTEXT_ONLY before mapping; no missing-field defaults |
| `domain.offers[].offer` | Existing `SupplierOffer`; preserve every original capacity and source revision in offer evidence |
| `domain.opportunities[]` | `OrderingOpportunity` dates/kind/offer/expiry; ID remains evidence/line lookup, not ranking; `max_packs` is floor(original new capacity / pack) for each opportunity |
| Policy/domain IDs, versions, source revisions, clocks and capture | Resolvable `SourceEvidence`; original revision belongs in its reference, capture stamp identifies the same bundle. Syntactic checks cannot establish correct source selection |
| `frozen_state` | Existing inventory/catalogue/recipe/history models, complete authoritative manifests, and existing baseline/recipe/bucket kernels; verified empty activity/commitments are evidence, not inferred from absence |
| Fixed expected supply | Existing `Delivery` + supported expected expiry/evidence + explicit `ExpectedSupply.projected_lot_id` for shared FEFO; received quantities stay once in opening stock |
| Results | Persist request, exact result and separate validation. Preserve `domain_size`, `reduced_domain_size`, `evaluated`, `work_used`, `search_policy`, completion, optimality and cause evidence |

Provenance keys remain `opening:<actual-lot-id>` and `supply:<delivery-id>`; those
prefixes do **not** determine shared FEFO ties. Opening stock uses original lot
IDs/times. Fixed expected supply requires an explicit unique projected identity.
Candidate identity is `projected-purchase:` plus compact JSON of its normalized
semantic opportunity tuple `(supplier, ingredient, order, arrival, kind, offer)`.
This is hypothetical identity, not a future actual receipt ID. Renaming opaque
opportunity IDs does not change it. Identities must be unique across physical and
projected stock. Zero outstanding adds no lot. Legacy fixture FEFO tags preserve
their original namespaced order; they are not aliases of the shared tag.

### Proof, guards and honest completion

Keep all offers/opportunities/capacities in the input and evidence. Guards require
complete inputs, positive acquisition, nonnegative consistent shipment fees,
the exact normal cash/semantic tie policies, zero safety, empty commitments,
one normal opportunity per offer, unit pack/MOQ, available offers with valid
cutoff/lead/slot, a common pre-service arrival, and opening/new stock usable
throughout service. Only one-day upper storage/budget constraints apply; the
supported cash policy has no discounts, minimum-spend obligations or future rewards.

Derive `ceil(max(0, total requirement − usable opening))` using exact rational
arithmetic. Under these guards, remove excess packs from any feasible allocation
until this minimum remains. Every service prefix remains covered, MOQ one is
preserved, capacity only decreases, storage/budget cannot worsen, positive
acquisition falls and a nonnegative fixed shipment fee can only stay or disappear.
Thus an optimum exists among the retained minimum-pack compositions. Enumerate
every such supplier split within original capacities. This is exclusion by proof,
not a claim that all raw combinations were visited or a universal optimiser.

Outside the guards: `UNSUPPORTED_SEARCH_SCOPE`, no actionable candidate. Callers
may explicitly use supported Cartesian enumeration with an honest limit. Unknown
economic/fee policies remain incomplete rather than being ignored.
Generation uses iterative composition traversal; each ingredient, visited node,
created edge and evaluated complete candidate uses one work unit. Construction
as well as evaluation is bounded; no unbounded capacity pool is materialized.
`domain_size` always records the original Cartesian product;
`reduced_domain_size` is null until construction completes. Impossible capacity
can prove an empty reduced domain with `INSUFFICIENT_NEW_CAPACITY` evidence.
Budget/storage failures keep their own causes, not `NO_FEASIBLE_SUPPLIER`.

`SEARCH_LIMIT_REACHED` returns incomplete with null actionable candidate and
validation; an incumbent is diagnostic only. Unsupported scope, missing evidence,
interrupted work, completed infeasibility and tool failure remain distinct.
Rudy owns mapping to the existing Agent outcome vocabulary.

### Executed fixture, checks and limitations

`test_pass3e_numerical.py::full` reads actual backend `first_slice_seed_rows` and
canonical contract models without a DB. Explicit v3 nine-lot stock and four
Monday observations flow through baseline, bucket and recipe kernels. All 24
offers/opportunities retain capacity 200. Oracles appear only in assertions.
Current mutable seed has richer supplier terms and different lot expiries; this
fixture is not a claim about a populated database and does not overwrite it.

Raw domain `201**24`; chicken gap 7.6 → 8 packs (45 compositions), noodles gap 3 →
3 packs (10): **450 candidates, 748 total work units**. Fresh supplies chicken
**8 kg**, noodles **3 kg**: acquisition **SGD 55.50**, delivery **5**, emergency
**0**, total **60.50**. Independent validation passes. Small independent exhaustive
oracles vary gaps, capacity and prices. Tests also interrupt generation and stop
after a feasible incumbent, with no actionable incomplete result.

Fresh verification from `services/api`, prepared Python environment:

```powershell
python -m pytest -q tests/test_forecasting.py tests/test_requirements.py tests/test_service_buckets.py tests/test_inventory_projection.py tests/test_procurement.py tests/test_synthetic_history.py tests/test_pass3e_numerical.py
python -m ruff check .
python -m pyright
python -m ruff format --check src/procurement.py src/inventory_projection.py tests/test_procurement.py tests/test_pass3e_numerical.py
git diff --check
```

**367 passed**, including 34 new cases and synthetic service-profile regressions;
two existing dependency deprecation warnings. Ruff passed, Pyright zero
errors/warnings, four changed Python files formatted. A preliminary root-directory
Ruff invocation misclassified first-party imports; the API-directory run passed.

**Subsequent full-suite verification, 17 September:** Docker is available again.
On implementation commit `8aefe36b51d166c86f94c9eddc8eb45a570fad98`,
`python -m pytest -q` produced **426 passed, 2 failed, 2 warnings in 788.92 s**.
This includes all 367 numerical cases above. API-wide Ruff, Pyright (zero
errors/warnings) and formatting for the four changed Python files passed again.

Testing used a separate `postgres:18-alpine` container with tmpfs storage,
loopback-only ephemeral port and default server timezone UTC. `TEST_DATABASE_URL`
pointed only to this instance; repository fixtures created/migrated/seeded/dropped
their own disposable databases. Existing application data and stopped project
containers were untouched. No API/frontend service or hosted database was started.

The failures are in unchanged `tests/test_procurement_contract.py`:

- `test_first_slice_policy_endpoint_exposes_complete_immutable_domain`, line 69:
  exact opportunity timestamp strings differ from the expected Singapore offset.
- `test_agent_reads_the_exact_contract_frozen_with_run_context`, line 94:
  returned `2026-02-15T14:00:00Z` versus expected `2026-02-15T22:00:00+08:00`.

Both reproduce on an isolated archive of unchanged main
`86abb37cb12eaee8296c2418e88f2f7b9bdef0ba`: **2 failed, 2 warnings in 28.50 s**,
using the same environment and the following focused command:

```powershell
python -m pytest -q tests/test_procurement_contract.py::test_first_slice_policy_endpoint_exposes_complete_immutable_domain tests/test_procurement_contract.py::test_agent_reads_the_exact_contract_frozen_with_run_context
```

These are equivalent instants, but the full gate is not passing. Chun Yang owns
resolving the serialization/test expectation contract; this task does not change
backend code/tests or change the database timezone merely to hide the failures.
A separate read-only API diagnostic against a disposable seeded test database
confirmed all 24 opportunities have the expected kind, expiry and equivalent
order/arrival instants; their rendered timestamps use UTC. This is diagnostic
evidence, not a replacement passing test or a waived gate.
The earlier Docker-startup error and historical 394-test result are not current
evidence. On 17 September, Aniq relayed Chun Yang's acceptance of fixing the
Singapore timestamp issue later and explicitly authorized proceeding with
[PR #22](https://github.com/rudybrrr/restock-ai/pull/22). This replaces the earlier
hold for these two known failures only; their recorded results are unchanged.
The backend correction remains deferred. Normal GitHub protection checks still
apply, and this relayed decision is not a GitHub review approval. No source or
test changes were made to obtain this acceptance; the suite was not rerun for
this documentation-only decision update.

Subsequent backend status: PR #23 made those timestamp checks compare equivalent
aware instants. The later FEFO replay alignment passes the complete PostgreSQL
suite with **429 passed**, plus clean Ruff and Pyright checks.

Backend policy/domain v1 already registers these tags; no new activation is
requested. Chun Yang still owns source completeness. Historical replay now uses
the shared `(expiry, received_at, lot_id)` ordering, with a regression that reverses
receipt and lot-ID order. No shared replay helper was extracted. Nonempty
commitments need an explicit projected identity convention.
Rudy owns mapping the exact claimed-run contract and persisting/resolving input,
result and independent-validation evidence before backend freshness/publication.
No live adapter, genuine pending plan, full training dataset, multi-day economic
objective or end-to-end integration is claimed here.

## Earlier implementation record

The dated sections below retain fixture and source history. This Pass 3E section
overrides their earlier policy proposals, expiry convention and waiting instructions.

This revision includes baseline forecasting, recipe conversion, dated service
allocation, one-day inventory projection, reproducible development history and
one-day cash procurement with independent validation. Use [feat/forecasting](https://github.com/rudybrrr/restock-ai/tree/feat/forecasting)
and resolve its commit for a consistent source/test/documentation review. The earlier
foundation was published at e3c66b6; d298c65 was the feature branch before these
dataset/procurement additions. Neither historical commit contains these additions.
Implementation is based on approved v2 plus v3; production policies and #16 live
contracts remain unresolved. Verification records below identify their task scope.

The 15 September update incorporates main `411527d327114f29cf1dd5a46e6e76faeae2024b`
into feature revision `4f1d4c3de8c80d50c6c90012cb81ce5b3a2533ac`, preserving historical
selection and audit code. Read the [current integration boundary](#15-september-integration-boundary)
before using historical readiness statements below. In particular, PR #17 added
the backend corrections previously tracked as CY-001; the live ML export and
combined PostgreSQL verification remain separate acceptance work.

Fresh publication verification, 14 September 2026: **329 numerical tests passed**
(193 foundation + 68 dataset + 68 procurement), two existing dependency warnings,
10.97 seconds. API-wide Ruff and Pyright passed; all five added Python files passed
formatting. The portable 84-day development generation/validation commands below
also passed. Generated files remain outside Git. No database, Bedrock or end-to-end
checks were run. Earlier verification entries retain their historical task scope.

## Python inputs and outputs

`src.forecasting.seasonal_baseline(history, menu_items, *, issue_time,
target_date)` takes final daily submission revisions and the existing
`schemas.MenuItem` models. `DailySalesObservation` and `DishForecast` are local
Python values, not new backend request/response schemas or persisted evidence IDs.
The function performs no I/O and returns one `DishForecast` per catalogue dish.

- History quantities are nonnegative integer **served portions**, including free
  portions, not transactions. Missing dish observations remain missing.
- Every observation requires a positive revision, an aware availability timestamp
  and explicit boolean promotion/censoring metadata. These day-wide flags apply
  conservatively to every dish in that submission. A future adapter must provide
  observed provenance; it cannot default missing metadata to false.
- Only observations available at or before issue time are visible. Service dates
  must precede the target and cannot exceed the Singapore issue date. Target dates
  cannot precede the Singapore issue date. Equal availability/issue times are visible.
- The highest visible revision replaces the entire day's earlier vector before
  eligibility filtering. Identical retries count once; conflicting same-day,
  same-revision records are errors. Final totals are not added to intraday batches;
  batches are outside this function's input contract.
- Use the last four uncensored, non-promotional matching weekdays when available.
  Otherwise average **all supplied eligible days**, provided there are at least
  seven. V2 specifies the minimum but no fallback recency window; this implements
  its eligible-day mean without inventing a trailing-seven-day policy.
- Below that coverage, return `expected_portions=None`, `method=manual_required`
  and explicit flags. An independently supplied manual forecast would be a separate
  caller decision, never a guessed value. Four explicit zero Mondays yield zero.
- Results include method, eligible-day/matching-weekday counts, selected
  `(service_date, revision, available_at)` references and coverage/exclusion flags.
  Means use 28 significant Decimal digits, half-even. Expected portions stay
  fractional. This is a normal-day baseline: no invented promotion normalisation,
  holiday uplift or uncertainty calibration. Service allocation is a separate
  pure function described below, not inferred observed intraday consumption.

## Dated service-bucket allocation

`src.service_buckets.allocate_service_buckets(daily_forecast, menu_items, *,
target_date, profile)` accepts the complete Decimal daily forecast and existing
MenuItem catalogue. Compose it with `seasonal_baseline` only after checking that
every expected value is present. Unknown/missing dishes, None, non-finite or
negative quantities, floats and implicit conversions are rejected. No sparse
mode is provided for a supposedly complete daily service allocation.

The caller supplies dated `ServicePeriod(start, end, weight)` Python values.
Weights are finite nonnegative Decimals and must sum **exactly** to one, without
normalisation or tolerance. Each period's weight is spread evenly over its
half-hours. This represents 0.4/6 exactly in intermediate arithmetic, without
asking a fixture author to provide six rounded repeating Decimal weights.

Timestamps must be aware, align to half-hour boundaries and delimit positive
non-overlapping intervals on the explicit Singapore target date. Inputs using
other offsets are normalized to Singapore. End at the following midnight is
allowed; crossing beyond it is not. Intervals are `[start, end)`; adjacent
periods are allowed. Periods are sorted chronologically. Gaps create no buckets
and establish no observed zero-sales coverage. Zero-weight periods still produce
explicit zero-demand buckets.

The result is an immutable tuple of `ProjectedDemandBucket` values with aware
Singapore start/end timestamps, all-dish Decimal `expected_portions`, and fixed
`provenance="PROJECTED"`. Preserve the supplied profile alongside the result as
calculation evidence. These are local numerical records, not a new backend
transport contract. The caller associates the daily forecast with its correct
date/version; no database or issue-time history loader is added here.

Rounding policy, per dish:

1. Use a quantum of 0.000001 portions, or a finer power of ten when required to
   represent the original daily total exactly. Ignore representation-only trailing
   zeros. Zero totals use the default quantum.
2. Compute each ideal allocation using exact rational intermediates from Decimal
   inputs. Floor nonnegative allocations to quantum units (ROUND_DOWN semantics).
3. Give remaining units to buckets in descending fractional-remainder order,
   breaking ties by earliest chronological start. No last-bucket catch-all and
   no independent rounding that inflates the total.
4. Construct Decimal outputs exactly, independent of ambient Decimal precision
   and rounding. Every dish's mathematical sum equals its daily input; each
   bucket deviates from its ideal by less than one quantum. Extremely small
   totals can consequently leave most buckets at zero. A period's aggregate
   share is subject to bucket rounding; it is not separately forced to its weight.

For subsequent arithmetic on unusually large/high-precision outputs, callers
must use sufficient Decimal precision (as the existing recipe helper does) or
exact reference arithmetic. A low-precision caller's summation can itself round.
The function does not estimate service patterns from history, subtract actual
sales, scale an intraday remainder, replay inventory or certify demand accuracy.

The explicit synthetic profile in `tests/fixtures/service_profile_v2.json`
dates lunch 11:00-14:00 and dinner 17:00-21:00 on 16 February 2026, Singapore time,
with period weights 0.4 and 0.6. For 100 daily portions, the first four lunch
buckets contain 6.666667 each, the last two 6.666666, and all eight dinner buckets
7.500000. Lunch sums to 40, dinner to 60, and the day to 100. For 25.25 portions,
lunch is `[1.683334]*2 + [1.683333]*4` and dinner `[1.893750]*8`, summing to 25.25.

## Recipe conversion

`src.requirements.calculate_requirements(forecast, menu_items, ingredients,
recipes, *, sparse=False)` reuses `MenuItem`, `Ingredient` and `RecipeItem`.
Forecast values must be finite, nonnegative **Decimal** expected served portions.
The default requires every catalogue dish, with explicit zeros. `sparse=True`
declares omitted dishes out of scope with zero contribution; it is not a way to
hide `manual_required` or unknown demand in a supposedly complete forecast.

Recipe quantities must be finite positive Decimals, expressed directly in the
referenced ingredient's `kg`, `litres` or `pieces` base unit. RecipeItem has no
separate unit field. Unknown references, duplicate lines, unsupported units and
dishes without recipes are rejected, even for zero forecasts. A caller must supply
the complete resolved recipe version; the function cannot detect an individually
missing line without an authoritative recipe manifest. Every supplied ingredient
is returned as a Decimal total, including unused ingredients with explicit zero.
Nonnegative products and sums use sufficient Decimal precision for exact
aggregation; there is no database-scale quantisation, pack rounding or conversion.
Fractional expected eggs remain fractional.

`sum_recipe_usage` is the shared multiplication helper used by this validated
function and the two existing backend calculations in `planning.py` and `sales.py`.
Their established complete-batch/development-request omitted-as-zero semantics are
retained at that low-level seam. The changes only extract their multiplication;
they do not implement new inventory replay, procurement or publication behaviour.

## Correctness fixture and checks

`services/api/tests/fixtures/seasonal_baseline_v3.json` is an explicitly synthetic,
version-pinned test fixture. Its four Mondays are 19/26 January and 2/9 February
2026, each available at 22:00 Singapore time. Issue: 15 February 22:00; target:
16 February. All observations are explicitly non-promotional and uncensored.
The fixture is not loaded into the application database or provided as an answer
to runtime code. The seed-contract test compares its catalogue and recipes with
the current database seeded by the repository's existing test harness.

Independent oracle: dish forecasts `100, 60, 80, 40, 40` in the v3 dish order.
Chicken is `100*.150 + 80*.120 = 24.600 kg`; rice `10+6+4 = 20.000 kg`;
noodles `12+6 = 18.000 kg`; eggs `60 pieces`; tofu `6.000 kg`;
vegetables `3+4+4.8 = 11.800 kg`; oil `.6+.4 = 1.000 litres`;
soy sauce `1+.8 = 1.800 litres`. Oracles are independently specified and are not
inputs to either function. A varied `10,20,30,41` Monday series must yield `25.25`.

Run from `services/api` in the prepared environment:

```powershell
uv run pytest -q tests/test_forecasting.py tests/test_requirements.py
uv run pytest -q tests/test_service_buckets.py
uv run ruff check .
uv run pyright
# Existing repository gate; its fixtures create/drop disposable databases.
$env:TEST_DATABASE_URL='postgresql://<local-test-role>:<local-test-password>@127.0.0.1:5432/postgres'
uv run pytest -q
```

These tests establish numerical and boundary correctness for supplied inputs,
not real restaurant forecast quality, completed ML integration or backend
publication. The current backend history lacks the full eligibility/availability
contract needed for a trustworthy automatic loader. Further pure numerical work
can proceed with explicit fixtures; publication requires backend-owned versioned
history/snapshot transport and agreed result mapping. No fee, economic-policy or
agent-completion decision is a dependency of these two functions.

Verified locally on 13 September 2026: 59 focused tests passed (0.20 s), 107 full
backend tests passed (284.81 s), Ruff passed, Pyright reported zero errors/warnings,
and `git diff --check` passed. The two pytest warnings are existing Starlette/httpx
and anyio deprecations. No frontend, cloud or live-agent checks were rerun.

Subsequent service-allocation task, same branch/base: 50 new cases, **109 combined
numerical tests passed in 0.21 s**, and **157 full backend tests passed in 260.31 s**.
Ruff, Pyright (zero errors/warnings), formatting of the new Python files and
`git diff --check` passed. Existing implementation/test files were unchanged.
The same two dependency warnings remain. PostgreSQL was started temporarily for
the backend gate and stopped afterward; API/frontend remained stopped.

Combined numerical command:

```powershell
uv run pytest -q tests/test_forecasting.py tests/test_requirements.py tests/test_service_buckets.py
uv run ruff format --check src/service_buckets.py tests/test_service_buckets.py
```


## One-day inventory projection (issue #15)

`src.inventory_projection.project_inventory` is implemented in this revision. It
advances explicitly verified opening estimates through one declared Singapore
service day using the existing projected buckets, catalogue/recipe models and
`calculate_requirements`. It performs no I/O and does not call or modify
`sales.estimated_inventory`. There is no second observed-history replay,
shared-helper extraction, new HTTP payload, order recommendation or publication.

The function takes all inputs explicitly:

- `opening_lots`: existing `EstimatedInventoryLot` values at the same `as_of`,
  with aware receipt/count/coverage times, remaining quantity, expiry/status and
  explicit coverage. Initial quantity is receipt provenance, never extra stock.
- `opening_manifest`: every ingredient mapped to its complete expected lot IDs.
  An explicit empty list certifies no held lots in this fixture. Missing keys or
  missing listed lots do not certify zero. An expired retained lot has zero usable
  opening quantity; the projector cannot reconstruct its pre-opening expired
  remainder from the backend's zero estimate.
- `buckets`, existing menu/ingredient/recipe models, and a complete
  `recipe_manifest` of dish/ingredient pairs. Recipe quantities and units come
  from the supplied resolved version, not a second multiplication implementation.
  Unknown references, duplicate lines and missing recipes are rejected.
- `service_profile`: the existing dated ServicePeriod values, used through the
  allocator to validate the profile and declare the complete expected half-hour
  interval set. It is a coverage manifest here; the supplied bucket quantities
  remain authoritative projected inputs and are not reallocated or inferred.
  Every declared interval must have a bucket, including explicit zero demand.
- `supplies`: ExpectedSupply wraps the existing Delivery model, plus a supplied
  expected expiry date and SourceEvidence for that assumption. A complete
  `supply_manifest` lists the delivery IDs, including fully received/cancelled
  entries when supplied. Explicit empty inputs mean no commitments.
- `as_of`, `target_date`, inclusive `horizon_end`, `known_at`,
  `captured_revision`, `evidence` and `fixture_fefo`. Opening can be on the
  service day or the preceding setup day; the horizon ends within the target day
  or at its following midnight. The first projected interval cannot precede the
  opening cutoff.

SourceEvidence is a small internal Python value: reference, availability time and
captured revision. Evidence is required for snapshot, opening, supply, catalogue,
recipe, forecast and profile, plus expiry assumptions for positive remaining
supply. All must name the same captured revision and be available by `known_at`.
The knowledge clock is deliberately separate from operational `as_of`: September
fixture recording time is not compared blindly with February simulated service.
Later evidence is rejected as incomplete rather than silently dropped. A caller
must supply a correctly selected frozen set and truthful complete manifests;
these references are not resolved or persisted by this pure function. This does
**not** fix CY-001 or certify live snapshot provenance.

Actual receipt records must agree with linked opening lot identity, ingredient,
initial quantity, receipt time and expiry. Their effective times cannot exceed
opening as-of. Received totals must match receipts, and expected quantity must
equal received + cancelled + outstanding. The projector adds **only outstanding
quantity** at its expected arrival. Receipt IDs and lot links cannot be duplicated.
Remaining stock can be below the actual receipt amount because opening estimates
already include observed consumption. Fully cancelled/received entries add zero;
their irrelevant future expiry is not invented. Overdue unreceived supply is
incomplete, not stock on hand.

`fixture_fefo` has no default. It explicitly chooses `EXPIRY_RECEIVED_ID`
(expiry boundary, receipt/expected arrival, namespaced source key) or
`EXPIRY_ID` (expiry boundary, namespaced source key). These are **fixture-only
orderings**, with independent equal-expiry examples demonstrating their difference.
Namespaced keys keep `opening:<lot-id>` distinct from `supply:<delivery-id>`.
Neither option establishes shared backend agreement or equal-expiry parity.
Chun Yang's current expiry/ID ordering is unchanged; shared extraction is deferred.

Timing and arithmetic:

- Stock usable at bucket start may serve it; supply exactly at bucket end can
  serve only a subsequent bucket. A strictly interior arrival or opening cutoff
  returns incomplete. Sub-half-hour splits are outside this bounded slice.
- Bucket balances are after start-boundary arrivals/expiry and before end-boundary
  events. Whole-horizon balances include events in gaps and at the inclusive end.
  Stock expiring at the following Singapore midnight is removed even at the
  horizon cutoff. An arrival after the horizon is retained as a zero-admitted
  expected source and cannot serve this projection.
- Unmet demand is recorded in its original bucket. Later stock cannot backfill
  it. Allocated ingredient quantities do not prove whole-dish/customer fulfilment.
- Recipe multiplication remains shared. Projection addition/subtraction uses an
  isolated Decimal context sized from all input and derived quantities to retain
  exact sums. There is no float conversion, per-bucket scale rounding or residual
  loss, including fractional expected pieces. Downstream callers must also retain
  sufficient precision when summing; database serialization remains issue #16.

The immutable InventoryProjection contains copied evidence, boundaries, fixture
ordering and `provenance=PROJECTED`. On complete supplied fixtures it returns
bucket and horizon ingredient/lot balances (opening, admitted, allocated, expired,
closing), ingredient required/unmet quantities, dated expiry quantities, and first
shortage intervals. `complete=True` means a fully calculated conditional fixture,
not no shortage, guaranteed delivery, verified demand quality or live authority.
An empty first-shortage tuple means no shortage under those complete inputs.

Missing evidence, revision/availability mismatch, missing manifest/observed
coverage, positive historical deficit or unsupported timing returns
`complete=False` with sorted Finding(code, source) values. All numerical result
fields, including first shortages, are **None**, preventing incomplete from being
mistaken for zero/no risk. A repeated ingredient deficit across opening lots is
not summed; contradictory repeated values are rejected. Structural invalidity
raises ValueError (including Pydantic validation errors); wrong evidence object
types raise TypeError. No input models, collections or bucket values are mutated.

### Independent projection fixture and acceptance disposition

`tests/fixtures/inventory_projection_v1.json` references the existing v3
catalogue and supplies a complete dated opening/profile/forecast fixture.
Fifteen then ten tofu-bowl portions use the **current** 0.100 kg vegetable recipe:
requirements 1.500 then 1.000 kg. Opening 2.000 kg yields closing 0.500 then
0.000 kg, with 0.500 kg unmet at 11:30-12:00 on 16 February. An expected
0.500 kg at 11:30 removes that shortage; at 12:00 it leaves the earlier shortage
and closes with 0.500 kg. Other ingredient stock is explicitly ample.
No expected answer is passed to production code.

The full seasonal baseline -> 40/60 service allocation -> recipe -> projection
test independently checks all eight daily requirements: 24.600 kg chicken,
20.000 kg rice, 18.000 kg noodles, 60 eggs, 6.000 kg tofu, 11.800 kg vegetables,
1.000 litres oil and 1.800 litres soy sauce. Fraction-based reference cases test
different stock levels and arrival boundaries without using production arithmetic
as the oracle.

Mapping to the twelve acceptance bullets in [issue #15](https://github.com/rudybrrr/restock-ai/issues/15), in order:

| # | Disposition | Evidence / remaining boundary |
|---|---|---|
| 1 | Verified for explicit fixtures | Conservation assertions for every lot/ingredient, every bucket and horizon; independent Fraction grid, tiny fractional pieces and exact recipe composition. |
| 2 | Verified | Full current five-dish/eight-ingredient baseline/profile composition; zeros and shared recipes. |
| 3 | Verified fixture FEFO/expiry; shared parity deferred | Different-expiry and both explicit tie-policy oracles; expiry before service/in gaps/at horizon. Shared tie agreement is absent in refreshed #16 comments. |
| 4 | Verified | Complete zero vs missing manifest/lot/bucket/evidence, missing observed coverage and repeated/inconsistent historical deficits. |
| 5 | Verified bounded timing | Start/end/later arrivals, overdue and unsupported middle/cutoff cases. No automatic splitting or within-bucket prorating. |
| 6 | Verified | 10/6/4 and cancelled remainder oracles, receipt-opening consistency, duplicate and arithmetic rejection. |
| 7 | Verified | First- and second-bucket shortages persist after later sufficient arrivals. |
| 8 | Verified | Unknown IDs, unit mismatch, naive times, overlaps, negatives/non-finite/float inputs, manifests and unavailable/revision-mismatched evidence. |
| 9 | Verified | Inputs unchanged on success and incomplete return; repeated/order/timezone/low-precision-context results agree. |
| 10 | Verified | Independent 2 kg example, fractional grid, zero, FEFO and expiry oracles; full current catalogue arithmetic. |
| 11 | Not applicable to this implementation; extraction deferred | No shared helper or backend file changed. Backend tie/replay behaviour remains byte-identical to the pre-task worktree. |
| 12 | Verified for this bounded scope | This Python contract, test evidence and handover distinguish conditional numerical correctness from unresolved live/procurement/publication acceptance. |

The exact final validation commands/results are recorded in SESSION_STATE.
Fixture development is implemented; shared tie order/extraction, live authoritative
opening/supply provenance, and storage/agent mappings remain issue #16 work.
The next integration step is to agree and provide one frozen backend opening +
outstanding-supply example with these completeness, expiry and precision semantics,
then connect it through a thin adapter. Fees and procurement policies are later
purchasing dependencies, not retrospective blockers for this projector.

## Synthetic history and chronological datasets (14 September 2026)

`services/api/src/synthetic_history.py` implements a reproducible **fully supplied
development fixture**, with validation and observation-only readers in
`services/api/src/history_dataset.py`. These are local dataset formats, not a new
backend transport contract. Existing `MenuItem`, `Ingredient`, `RecipeItem`,
`calculate_requirements`, `allocate_service_buckets` and `DailySalesObservation`
are reused. No existing runtime module, database seed or API route changed.

### Authority and configuration

The source register identifies the complete approved sources under the materials
folder's `Working Directory/PLANS/`:

- `ReStock_ML_Decision_Engine_Plan_v2_Review_Reconciled.md`, especially §§5–6:
  chronological targets, distinct random streams, served-sales labels, publication
  visibility, atomic promotional pairs and evaluator isolation.
- `ReStock_ML_Decision_Engine_Plan_v3_Integration_Amendment.md`, especially §§3.1–3.3,
  5, 7–8: current catalogue/recipes, replacement calendar/hash freeze, existing
  contracts and deferred model comparison. Aniq explicitly confirms Ethan's
  approval of v2 together with v3; preparation-stage headers are historical.

No accepted replacement **full-history** range, simulation start and feature/model
catalogue pin was found in these sources or the later supplied handover decisions.
The old v2 February calendar and v3 four-Monday correctness fixture are not an
approved full dataset calendar. `tests/fixtures/history_development_v1.json` is an
explicit local development configuration, not the agreed training/test dataset.
The generator deliberately accepts only `purpose=DEVELOPMENT_FIXTURE` in version 1.

The current seed was checked read-only against the five dishes, eight ingredients
and sixteen recipes in `seasonal_baseline_v3.json`, including an AST-based test that
does not import or execute the seed. Catalogue/recipe source is main
`5827515ec48183ba908151fb0016b118cd801b1c`. Counterfactual use of these current recipes
throughout historical dates is a declared fixture assumption; ingredient
`starting_date` remains the backend's scheduling date, not evidence of historical
catalogue availability. Canonical JSON hashes (sorted existing model records;
recipe Decimal strings retain their declared scale) are:

- Catalogue: `0704fa2f1658e140d9cc5fd1f090f64d094d14403d698da97d5ea22ea8e0e3da`
- Recipes: `12a039e95453255236a9d49f7514e42188c63811ebe032e111662a16168098af`

Development history is **2025-09-01 through 2025-11-23**, Singapore time; declared
development simulation start is **2025-11-25T08:00:00+08:00**. No simulation is run.
Target partitions apply identically to all five dishes:

| Partition | Inclusive dates | Days | Daily revision rows | Batch rows | Truth rows | Ingredient rows |
|---|---|---:|---:|---:|---:|---:|
| Warm-up | 2025-09-01–2025-09-28 | 28 | 280 | 1960 | 140 | 224 |
| Train | 2025-09-29–2025-10-26 | 28 | 280 | 1960 | 140 | 224 |
| Validation | 2025-10-27–2025-11-09 | 14 | 140 | 980 | 70 | 112 |
| Test | 2025-11-10–2025-11-23 | 14 | 140 | 980 | 70 | 112 |
| Total | | 84 | 840 | 5880 | 420 | 672 |

There are two published BOGO events, one training and one validation event. CSV
counts exclude headers. Two daily revisions do not mean twice as many labels:
there are 420 dish/date labels including warm-up, 140/70/70 outside warm-up.

**Proposed full configuration, requiring Aniq/Ethan confirmation before generation:**
history 2024-02-16–2026-02-14; warm-up 2024-02-16–2024-03-14; training targets
2024-03-15–2025-08-14; validation 2025-08-15–2025-11-14; test
2025-11-15–2026-02-14; simulation start 2026-02-16T08:00:00+08:00; the two hashes
above as catalogue/recipe pins; historical namespace `restock/history/v1` with
demand/timing/error seeds 3001/3002/3003. This is a new proposal aligned with the
current setup date, not approval inferred from the one-day v3 fixture. Confirm
the fully supplied scope/assumptions too; it does not supply a physical benchmark.
No artifacts for that proposed full range were generated.

### Generation, visibility and validation semantics

- SHA-256 counter streams use independent demand, event-timing and observation-error
  seeds 17/23/31 under `restock/history-development/v1`. Separate development and
  held-out scenario namespaces are declared and must differ. Draws are keyed by
  logical date/dish/event identities, not traversal order. Modulo sampling's tiny
  bias is documented in code. Stable row IDs do not depend on random outcomes.
- Assumptions specify base transactions, Monday-first weekday factors, linear
  trend, bounded integer variation and published BOGO dates. Expected transaction
  counts use rational arithmetic and half-even integer rounding, floored at zero.
  All attempted transactions are served. A BOGO transaction is one paid plus one
  free portion in the same bucket, with recipe usage for both. There is no physical
  stock cap, stockout simulator, hidden-loss generation or receipt/count generation.
- The existing 40% lunch / 60% dinner allocator supplies fourteen half-hour weights,
  quantized by its documented exact-conservation rule. Independent timing draws
  distribute whole transactions among them; observed daily shares need not equal
  the expected 40/60 proportions exactly. Batches are synthetic observed interval
  totals, not projected demand. Coverage is only the declared service intervals;
  no observed zero is inferred for closures or unreported periods.
- `available_at` is the synthetic submission/recording time at which the observation
  becomes known; `effective_at` is its service cutoff. Initial daily reports are
  available at 22:00, with declared reporting error and 5% dish-level missingness.
  Every day has a full replacement correction at 22:00 the next day. Missing
  rows retain their dish identity and have blank quantities; observed zeros have
  explicit zero quantities. Each revision includes the complete five-dish manifest.
- Fixture prices are explicitly synthetic SGD 6 per paid transaction, not current
  backend menu prices. Money and ingredient quantities use decimal strings; floats,
  non-finite/negative quantities, invalid references and inconsistent accounting
  are rejected. Integer served/paid/free portions remain distinct from transactions.
- `load_forecast_inputs(observations, issue_time=...)` returns only available daily
  revisions and published promotion context, plus catalogue/recipe hashes. It
  never reads evaluator files or adds batches to daily totals. It cannot infer a
  missing final total from service batches. The existing baseline selects visible
  replacement revisions before applying its promotional/censored exclusions and
  sparse-history rules. Current baseline flags are day-wide: a promotion or censor
  flag on any dish conservatively excludes that day for every dish.
- `load_partition_targets(..., partition=..., known_at=...)` selects latest visible
  daily labels in one target-date partition, preserving missingness and eligibility
  flags. The caller must freeze `known_at` to the actual fitting/evaluation clock.
  Warm-up is separate; insufficient history still returns no forecast. No random
  row splits, feature matrix, multi-horizon origin/label joins, fitting or tuning
  are produced. Purging crossing-horizon training labels remains mandatory for a
  later feature builder; there are no such training records to purge in this task.
- `validate_observations` checks allowlisted files/columns, content hashes, catalogue
  pins, complete daily and interval manifests, chronology, revisions, explicit
  flags and sales/revenue identities. Offline `validate_dataset` additionally
  checks configuration/seeds, full-supply assumptions, final/batch/truth conservation,
  observation-error bounds and exact recipe/unit accounting. Isolated censoring
  tests exercise baseline eligibility; they do not claim simulated stockouts.

### Reproduce and inspect

From `services/api`, using the prepared environment (choose a **new** output root
on repeats; existing directories are rejected):

```powershell
$datasetRoot = Join-Path $env:TEMP 'restock-history-publication-v1'
.\.venv\Scripts\python.exe -m src.synthetic_history --config tests/fixtures/history_development_v1.json --catalogue-fixture tests/fixtures/seasonal_baseline_v3.json --observations "$datasetRoot\observations" --evaluator "$datasetRoot\evaluator"
.\.venv\Scripts\python.exe -m src.synthetic_history --validate-only --observations "$datasetRoot\observations" --evaluator "$datasetRoot\evaluator"
```

The original local commands generated `history-development-v1` and a separate
`history-development-v1-reproduction`; **all nine files had identical SHA-256 hashes**.
The portable commands above use a fresh temporary output root instead.
Both output directories must be separate/non-nested and outside the repository.
Outputs are intentionally outside Git, database seed paths and runtime mounts.

`observations/` contains catalogue JSON, daily/batch/promotion CSVs and an allowlisted
manifest. `evaluator/` contains configuration JSON, attempted-demand and recipe-usage
CSVs and its manifest. The evaluator manifest records generator/schema versions,
seeds/namespaces, timezone/ranges/partitions, catalogue/recipe hashes, output hashes
and the observation-manifest hash. Hidden parameters/seeds/truth are absent from
the observation reader result and public manifest. No nondeterministic run timestamp
enters reproducible content. These local manifests are not authoritative backend
snapshot references, and their integrity hashes do not certify real-world provenance.

Validation on 14 September: **257 numerical tests passed** (64 new dataset cases
plus the existing 193), two existing dependency deprecation warnings, 17.21 seconds.
Ruff passed across the API; Pyright reported zero errors/warnings; all three new
Python files passed formatting; `git diff --check` passed. The previous **241-test
backend run is historical and was not rerun**: shared runtime/configuration was
unchanged and this task prohibits database mutation. No services were started.

This verifies synthetic accounting, reproduction and leakage boundaries, not real
restaurant forecast accuracy. Physical fulfilment/replay, hidden losses, multi-horizon
features, XGBoost, procurement within the dataset generator, the forty-scenario benchmark and backend/agent
integration remain outside scope. Issue #16 mapping remains unresolved; PR #17's
historical-selection fixes supersede the former blanket CY-001 statement. The smallest
dataset follow-up is to confirm the full calendar/catalogue/assumption proposal;
the next live numerical connection still needs the agreed frozen opening/commitment
example and thin input adapter described above, with separate authorization.

### Service-profile consistency correction (14 September 2026)

Offline `validate_dataset` now expands the configured dated profile through the
existing `allocate_service_buckets` function and compares its ordered local-time
half-hour intervals with the parsed observation manifest. It raises
`Configured service intervals differ from observation manifest` on a mismatch.
The observation-only reader remains independent of evaluator configuration.
Equivalent reordered periods pass; sampled transaction shares are not checked
against profile weights. No second profile-expansion algorithm was introduced.

Before the fix, two regression cases on temporary 84-day fixtures reproduced
`DID NOT RAISE ValueError`: a lunch-only configuration and a shifted lunch window
with the same number of intervals. Both refresh the configuration hash and retain
all observation bytes, so their final rejection exercises semantic consistency.
Positive tests cover unchanged data, reordered periods and changed valid weights.

Final correction checks: **261 numerical tests passed** (68 dataset + 193 existing),
two existing dependency warnings, 10.99 seconds; API-wide Ruff and Pyright passed
(zero type errors/warnings; Pyright update notice only); both edited Python files
passed formatting; `git diff --check` passed. The supplied 84-day development
dataset passed `--validate-only`, and all nine artifact hashes remain unchanged.
Database tests were not rerun; no shared runtime/reader code, services or database
state changed. Earlier 257-test results and the existing review ZIP predate this
correction. Full-history configuration/assumption approval and live integration
remain unresolved; this change only corrects development-data validation.

## Pure one-day procurement cash search (14 September 2026)

`src.procurement.search_procurement(inputs)` and independently callable
`validate_candidate(inputs, candidate)` now implement the bounded cash slice.
These are local Python functions, independent of sessions, HTTP, OpenClaw and I/O.
They do not change `planning.optimise`, `planning._validate_candidate`, observed
inventory replay, canonical schemas, the seed or any backend/agent transport.
V2 §§7–8 and v3 §§4–6 govern the numerical methods; the user's current task
authorizes implementation with explicit fixture policies. The full-project review
Markdown named in the request was not found; it is not an approval dependency.

### Callable inputs and interpretation

`ProcurementInputs` holds the following explicit inputs. These dataclasses and the
`ProjectionInputs` TypedDict are internal argument bundles, not proposed endpoints.

| Input | Required semantics |
|---|---|
| `inventory` | Exactly the existing `project_inventory` arguments described above: complete catalogue/recipe/profile, projected dish buckets, verified opening estimates, fixed `ExpectedSupply`/receipt records, authoritative manifests, separate operational/knowledge clocks, capture revision, evidence and explicit fixture FEFO. |
| `issue_time` | Aware operational placement time equal to the opening `as_of`. Only new orders placed at this instant are supported. Future placement opportunities or unequal issue/opening return incomplete, not a silently changed order date. |
| `requirements` | Dated `DatedRequirement(start,end,quantities)` vectors, with every ingredient including zeros in its canonical base unit. Build with `calculate_requirements` on each projected dish bucket. Validation cross-checks every interval and exact quantity against the same recipe function; missing/mismatched vectors are incomplete. No demand-to-pack rounding occurs here. |
| `suppliers`, `offers`, `approved_offer_manifest` | Existing `Supplier`/`SupplierOffer` models and complete declared `(offer_id,supplier_id,ingredient_id)` approval triples for this supplied domain. Unknown references are rejected; missing approval coverage is incomplete. Each offer retains canonical field names, including `available_quantity` for **new commitments**. |
| `opportunities` | Explicit `OrderingOpportunity(id,offer_id,ordered_at,arrival_at,kind,expiry_date,expiry_evidence)`. `None` means unknown; an empty sequence means explicitly none. Their evidence must establish applicable ordering occasions; this function does not derive backend cycle state or add undeclared opportunities. |
| `safety`, `storage`, `budget` | Complete all-ingredient nonnegative Decimal vectors and a supplied nonnegative new-order SGD budget. Safety is required after every service bucket. Storage is checked at opening and receipt boundaries before subsequent consumption, including gaps; simultaneous arrivals aggregate. No unlimited/default values. |
| Four policy fields | Explicit strings listed below; unknown/missing values return `MISSING_OR_UNSUPPORTED_POLICY`. |
| `policy_evidence` | `SourceEvidence` for `approvals`, `opportunities`, `safety`, `storage`, `budget`, `domain`, `fee_policy`, `tie_policy`, `expiry_policy`, `cash_policy`. |
| `offer_evidence` | SourceEvidence keyed by every supplied offer ID. Required references/availability must be present, available by `known_at`, and bound to the common captured revision. Offer `observed_at` must also be no later than that knowledge clock. Operational and recording clocks are distinct, as in the projector. |
| `max_packs`, `work_limit` | One explicit nonnegative integer pack bound per opportunity, equal to `floor(available_quantity / pack_size)`. Positive integer work limit counts evaluated candidates, including rejected ones. Domain evidence declares the opportunity/offer scope. |

The caller must select correct frozen sources and establish approval/coverage.
Matching supplied manifests and evidence strings cannot prove those claims or fix
CY-001. Promotion/censoring/history visibility remains the existing forecast
component's responsibility. Missing forecast demand must never enter as zero.

### Supported fixture policies and timing

All are **explicit local fixture assumptions, not accepted production defaults**:

- `cash_policy=CASH_SLICE_V1_EXACT_SGD`: exact acquisition + delivery + exclusive
  emergency cash only. Products and sums use exact rational intermediates from
  Decimal inputs, converted losslessly to Decimal outputs independently of ambient
  Decimal precision. No cent quantization or demand rounding; no economic waste,
  stockout penalty, terminal credit, continuation value or reliability penalty.
- `fee_policy=SUPPLIER_ARRIVAL_ONCE_PLUS_EMERGENCY_ONCE`: group **new lines only**
  by supplier and normalized arrival instant; delivery fee once, plus the exclusive
  emergency fee once if any line in that group is emergency. Mixed groups follow
  that explicit rule. All potential lines in a group must agree on both fee values;
  conflicting values return incomplete. Separate arrivals incur separate fees.
  Fixed commitments incur no new cash here and are never merged with new lines to
  infer a fee waiver; production co-shipping rules still require agreement.
- `tie_policy=FEWER_LINES_THEN_STABLE_LINES`: minimize total cash, then positive
  line count, then lexicographically sorted `(opportunity_id, quantity, unit)` tuples.
  IDs must therefore be stable. This is not a physical FEFO policy or an economic
  surplus preference. Changing only valid `recent_on_time_rate` cannot change selection.
- `expiry_policy=USABLE_THROUGH_ARRIVAL_DATE_PLUS_DAYS`: the explicit expected expiry
  must equal Singapore arrival date plus supplied `shelf_life_days_on_arrival`.
  Zero means usable through the arrival day; stock expires at the next midnight.
  This day-count convention requires production confirmation; no future receipt
  expiry is borrowed. Each proposed opportunity requires its own expiry evidence.

Every positive opportunity allocation must satisfy its offer MOQ and pack multiple;
capacity is shared by all lines using that offer, across arrival times and kinds.
Existing commitments are **not subtracted from new capacity again**. Cutoff equality
and lead-time equality are allowed. `NONE` cutoff is known unrestricted; `UNKNOWN`
and null required supplier fields are incomplete. Empty delivery slots are known
unavailable, not unknown. Positive arrivals must be after opening. Inside-bucket
arrivals remain unsupported and return incomplete; start arrivals can serve that
bucket, end arrivals only later buckets. Later stock never erases earlier unmet demand.

Candidate validation adds only in-memory `proposed:<opportunity_id>` ExpectedSupply
records to a copied projector argument bundle, with no receipts and no persistence.
`proposed_supply_ids` distinguishes those hypothetical recommendations from fixed
external commitments in the returned projection. Opening remains ESTIMATED, demand
and balances PROJECTED, deliveries expected. Actual 10/6/4 receipt/cancellation
reconciliation is delegated to the unchanged projector, not implemented twice.

The temporary Delivery model retains its existing `Numeric(12,3)`-compatible
quantity limits. A proposed purchase that it cannot represent gives
`UNSUPPORTED_PURCHASE_PRECISION` with incomplete output, **never quantization**.
Projected ingredient consumption and cash retain their finer Decimal precision.
Orders spanning future placement dates, within-bucket proration, other fee/expiry/tie
policies, arbitrary fine-scale physical purchase quantities and multi-day protection
are outside this implementation. These limits do not establish shared contracts.

### Search, validation and completion

For each opportunity the search enumerates every integer pack count from zero to
its declared bound, inclusively. Bounds must match physical new capacity divided by
pack size; smaller arbitrary bounds are rejected. Their Cartesian product includes
all splits, with shared capacity and all other constraints checked independently.
Below-MOQ and over-shared-capacity combinations are counted and rejected rather
than silently removed from the claimed domain. No supplier shortlist is inferred.
Complete enumeration proves only the explicitly supplied domain, not omitted
offers, undeclared times, another horizon or production policy.

Enumeration uses mixed-radix indices without materializing large Cartesian pools.
There is no performance/scale guarantee beyond the supplied candidate work limit.

| Result | Meaning and consumer rule |
|---|---|
| `OPTIMAL_IN_DOMAIN` | Search complete, at least one feasible candidate, minimum cash/tie score within this exact domain. Returned candidate includes independently recomputed cash and validation/projection evidence. An empty line tuple is a verified no-purchase result. This does not authorize ordering or publication. |
| `INFEASIBLE_IN_DOMAIN` | Every declared combination evaluated and rejected. No candidate, `search_complete=True`, `optimal_in_domain=False`. `rejection_counts` distinguishes budget, storage, safety, timing, capacity, etc.; counts overlap across constraint categories. Do not label all causes NO_FEASIBLE_SUPPLIER. |
| `INCOMPLETE` | Missing evidence/policy, unsupported numerical scope or unfinished search. `candidate` and `validation` are None. Search-limit findings contain `SEARCH_LIMIT_REACHED` and evaluated/total counts; a `diagnostic_incumbent` may exist but must never be actionable. No infeasibility/optimality claim. |

`validate_candidate` does not invoke the search, trust a feasible flag or compare
only with its selected answer. It checks supplied lines, optional `claimed_cash`,
offer relationships, timing, shared capacity, cash, projection, storage and safety
directly. It returns `CandidateValidation(complete,feasible,findings,violations,cash,
projection,proposed_supply_ids)`. Missing evidence/unsupported scope has
`complete=False` and feasible/cash/projection None. Known violations have
`complete=True, feasible=False`; cash is diagnostic, and a timed projection is
included when line-level checks permit one. Violation evidence identifies the
offer/opportunity, constraint, or ingredient interval; storage includes the measured
peak and limit. Structural contradictions raise ValueError. Inputs are not mutated.

### Independent worked examples and verification

`tests/fixtures/procurement_v1.json` composes the existing five-dish catalogue,
recipes and 40/60 fourteen-bucket service profile for 16 February 2026. It uses
v3's daily forecast, opening quantities, zero safety, storage vector and S$100
budget. **Its only supplied offers are Fresh chicken/noodles, with new capacities
8/3**, not the current seed's 200 or all three suppliers. This explicit small-domain
fixture has 9×4=36 combinations; it does not prove a global all-supplier optimum.
It preserves v3's illustrative prices, 08:00 arrival, grouped S$5 delivery and S$12
exclusive emergency fee. No actual seed offer is changed.

Hand arithmetic: chicken `24.6−17=7.6 kg`, hence 8 one-kg packs; noodles `18−15=3 kg`.
Acquisition `8×4.50+3×6.50=55.50`; one group fee `5`; normal total **S$60.50**.
Projected chicken closes at 0.4 kg, noodles at zero, all ingredient demand is met.
Both lines emergency (or one emergency in the same group) gives S$72.50, not two
emergency fees or a second delivery fee. Expected values are assertions only.

The small two-bucket test uses 15 then 10 tofu bowls: vegetable requirements 1.5
then 1 kg, opening 2 kg. One-kg packs at S$9.50 plus S$5 delivery select **1 kg,
S$14.50**, closing 0.5 kg. With capacity 2 the complete domain is `{0,1,2}`.
Work limit 2 evaluates zero (shortage) and one (feasible), then returns **INCOMPLETE /
SEARCH_LIMIT_REACHED, 2/3**, candidate=None, with the S$14.50 incumbent diagnostic
only. Budget zero instead allows all three evaluations and proves domain
infeasibility, with budget and unmet-demand evidence rather than supplier failure.

Executed from `services/api` with the prepared environment:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_procurement.py tests/test_forecasting.py tests/test_requirements.py tests/test_service_buckets.py tests/test_inventory_projection.py tests/test_synthetic_history.py
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pyright
.\.venv\Scripts\python.exe -m ruff format --check src/procurement.py tests/test_procurement.py
git diff --check
```

**329 tests passed** (68 procurement + 261 existing numerical), two existing
Starlette/httpx and anyio deprecations, 29.08 seconds. API-wide Ruff passed; Pyright
reported zero errors/warnings (version-update notice only); both new Python files
passed formatting. The service-profile correction is included in this numerical
regression run. Database/frontend/agent/cloud tests were not run: no shared runtime
or integration seam changed and no services/database were started. The historical
241-test backend result is not a new test result. Synthetic checks do not measure
restaurant forecast accuracy, full economic optimality or live purchasing readiness.

### Remaining ownership and next step

- **Aniq:** this one-day numerical slice is complete for explicit fixtures. Next
  smallest useful numerical task is one frozen before/after disruption comparison
  using these same projector/search/validation results as materiality evidence,
  once exact materiality thresholds/comparison policy are supplied. Do not invent
  those thresholds. Multi-day protection/continuation, full economics, physical
  simulation and held-out evaluation remain later ML work; full-history calendar
  and assumptions are still unapproved.
- **Chun Yang:** supply provenance-correct frozen opening, complete catalogue and
  manifests, reconciled commitments/expiry, approved offers and applicable ordering
  opportunities; capture budget/storage/safety and accepted policy versions. Own
  preservation/verification of PR #17 historical selection, database adapters, immutable evidence persistence, freshness,
  completion/lifecycle and approval enforcement. Agree fee grouping/co-shipping,
  expiry day count, physical purchase precision and FEFO parity before live use.
- **Rudy:** consume referenced numerical results without recalculating them. Map
  SEARCH_LIMIT_REACHED to CALCULATION_INCOMPLETE, preserve nulls/findings and keep
  incumbents diagnostic. Distinguish known constraint infeasibility, missing data,
  unsupported scope and tool execution failure. Coordinate the backend's current
  embedded Candidate versus agent reference contracts before publication.

The next integration step remains one agreed immutable backend fixture and its
input mapping, now including supplier/policy/domain evidence, followed by a
backend-owned adapter. The supplied #16 proposal remains a proposal; this task did
not refresh or edit GitHub issue comments and infers no new teammate approval.
Live result publication still needs agreed evidence/precision/completion contracts
and backend/agent acceptance. No procurement optimiser is wired to the application.

## 15 September integration boundary

### Authority, merge and callable scope

The approved sources were read completely for this update, without editing them:

| Source | SHA-256 | Applicable direction |
| --- | --- | --- |
| `ReStock_ML_Decision_Engine_Plan_v2_Review_Reconciled.md` | `3e326b5e77d4feba6a14ed7ce410ddee3a3c023754a0fe3c79a4a62add4deeed` | Numerical ownership, independent validation, exact quantities, temporal coverage and interface semantics |
| `ReStock_ML_Decision_Engine_Plan_v3_Integration_Amendment.md` | `bcc2bc7548bace736facbc3775d4ef2f46ad7078262b82f50436526dbba62714` | Current catalogue; first one-day cash stage; context-only reliability; diagnostic incumbents; backend-owned canonical transport |

V3 overrides conflicting v2 examples and policies. The user's supplied approval
and 15 September integration request authorize this implementation update; dated
"planning only" text records the earlier document task. Full economic scoring,
continuation and held-out evaluation are not made complete or approved by this update.

`src.procurement.search_procurement(inputs: ProcurementInputs) -> ProcurementResult`
is the real bounded deterministic optimiser for the **first one-day cash stage**.
`src.procurement.validate_candidate(inputs: ProcurementInputs,
candidate: PurchaseCandidate) -> CandidateValidation` is the numerical validator
before backend freshness, publication and approval checks. No second optimiser,
backend route, persisted schema or agent adapter is introduced here.

Main's newer `sales_at(session, as_of, known_at)` replay is retained with
`RecipeItem` conversion and `sum_recipe_usage`. The main snapshot, historical fact
readers, recording-time filters, one-actionable-plan rule and audit tests are
preserved. `planning.optimise` remains the opt-in development calculator until
Chun Yang and Rudy connect the real engine; importing the helper does not wire it.

### Exact inputs and version support

The existing `ProcurementInputs` table above is the callable contract. Every call
uses one resolved immutable bundle, not separate live catalogue/offer queries.
Main's snapshot now supplies `as_of`, `known_at` and `offer_version_ids`; use those
facts and its frozen commitments rather than current-state fallback reads.
Complete menu/recipe/stock coverage, forecast/profile evidence, expected outstanding
supply expiry and manager policy still need the agreed backend export mapping.

| Version/context | Existing numerical support | Backend/agent responsibility |
| --- | --- | --- |
| Operational and knowledge time | `inventory.as_of`, `issue_time`, `target_date`, `horizon_end`, `inventory.known_at` | Bind to the same saved run and coverage; do not replace operational time with wall-clock time |
| Captured state | `inventory.captured_revision`; each `SourceEvidence.captured_revision` | Map integer `input_revision` losslessly to a string and resolve the actual frozen bundle; matching strings alone do not prove provenance |
| Recipe/catalogue/forecast/profile | Complete typed inputs and respective `inventory.evidence` entries | Resolve immutable versions and manifests; original source versions belong in the referenced artifact |
| Supplier revisions | `offer_evidence[offer_id]`, offer `observed_at` and approved-offer manifest | Retain main's selected `offer_version_ids` and all required evidence; no newer mutable offer substitution |
| Cash policy | `cash_policy=CASH_SLICE_V1_EXACT_SGD` plus `policy_evidence["cash_policy"]` | Mark the result as immediate cash, not projected operating cost or profit |
| Fee policy | `fee_policy=SUPPLIER_ARRIVAL_ONCE_PLUS_EMERGENCY_ONCE` plus its evidence | Freeze the explicit shipment mapping below; do not silently rename it `PER_LINE_V1` |
| Expiry and tie policies | Explicit supported strings plus their evidence | Preserve the day-count convention and stable opportunity IDs; unsupported versions return incomplete |
| Safety/storage/budget/domain | Explicit values and corresponding `policy_evidence` | Retain scope, version and source; no missing-to-zero or unlimited-capacity defaults |
| FEFO/reliability | Explicit `fixture_fefo`; reliability is context-only in this cash stage | Preserve backend historical tie semantics; do not claim tied FEFO parity. Rate-only changes cannot affect selection |
| Algorithm | Module and exact Git commit identify this implementation | Persist the producing revision with the result; there is no existing numerical `algorithm_version` field to pretend is echoed |

The four supported policy identifiers select semantics; their `SourceEvidence`
references identify the exact captured configuration. An unknown version is not
accepted simply because an adapter discards the version field. The engine supports
neither the full six-term economic ledger nor valuation/continuation policies yet.
For this cash stage, mark those terms unsupported/not applicable in the agreed
backend representation. Do not insert zero costs and claim they were evaluated.

### Artifact mapping for Chun Yang and Rudy

This table defines required information for the **proposed backend-owned mapping**,
not a second ML wire schema or new endpoint. Use existing run/artifact storage.

| Artifact or field | Mapping and consumer rule |
| --- | --- |
| Calculation request | Persist the resolved `ProcurementInputs`, run/snapshot identity, captured revision, exact algorithm revision and all referenced data/policy versions. Preserve manifests and declared search domain, not only selected lines |
| Calculation result | Persist the exact `ProcurementResult` alongside that request. It does not itself echo all request metadata, allocate a persistent ID or verify a resolver |
| Purchase lines | Resolve each `PurchaseLine.opportunity_id` through the captured `OrderingOpportunity` to its `offer_id`, supplier/ingredient, order/arrival times, kind and expiry. Preserve exact quantity/unit. Reject unknown/stale references |
| Money | Preserve `Cash.acquisition`, `delivery`, `emergency`, `total` separately. The ordinary and exclusive emergency fees are not duplicated per ingredient line |
| Validation | Persist the independently returned `CandidateValidation`: `complete`, nullable `feasible`, findings, violations, cash, projected balances and `proposed_supply_ids`. Keep hypothetical additions distinct from external commitments |
| References | Backend allocates a resolvable result reference; Rudy's `candidate_result_ref` must resolve to this saved calculation and its exact request. An in-memory string or generated run suffix is not proof of persistence |
| Decimal/time transport | JSON Decimal strings, aware ISO timestamps, nulls retained, integer counters retained. Do not round through JavaScript numbers or the physical-count scale. Tuple-keyed Python values need explicit canonical serialization, not guessed JSON object keys |

Only `OPTIMAL_IN_DOMAIN` with completed search, a returned candidate and a complete,
feasible independent validation can proceed to backend checks in this implementation.
An empty candidate is a no-purchase calculation, not a fictitious pending order.
`INFEASIBLE_IN_DOMAIN` requires full enumeration and cause-specific evidence;
budget/storage infeasibility must not automatically become `NO_FEASIBLE_SUPPLIER`.
For `INCOMPLETE`, preserve null candidate/validation and all findings. A
`diagnostic_incumbent` remains non-actionable even if `validate_candidate` passes.
Map search exhaustion to `ESCALATE / CALCULATION_INCOMPLETE`, detail
`SEARCH_LIMIT_REACHED`. Missing data, unsupported scope, genuine execution failure
and the coordinator's `CALL_LIMIT_REACHED` remain distinct as required by v3.
Main's completion schema still needs the backend/agent-owned vocabulary mapping.

### Fee proposal disposition

Chun Yang's `SHARED_INTEGRATION_CONTRACT.md` proposes explicit `shipment_group_id`
and `fee_policy_version` under `PER_SHIPMENT_V1`. The current kernel groups new
lines by **supplier and normalized arrival instant** and has no
`shipment_group_id` argument. These contracts are not interchangeable by renaming.

For the first connection, Aniq proposes accepting the existing kernel only where
the caller supplies and validates an explicit one-to-one mapping between each
`(supplier, arrival)` pair and one new shipment group. Every line in that group
must have the same ordinary/emergency fee terms. Persist this mapping and the
selected kernel fee-policy identifier with the request/result. Fees are charged
once per group, with one additional emergency charge when any line is emergency.
Fixed commitments are not included in these new groups and imply no fee waiver.

Two separately charged groups with the same supplier/arrival, fee consolidation
with old commitments, per-line fees or incompatible group terms are unsupported
by this kernel. The adapter must reject/return an explicit unsupported calculation
instead of silently coalescing those groups. A broader grouping policy requires
an agreed version and a subsequent numerical change with tests. This proposal
needs Chun Yang/Rudy confirmation in #16; publication of this branch is not agreement.

### Two- and three-supplier acceptance

`test_procurement.py::bounded_supplier_domain` retains the reference's five dishes,
eight ingredients and fourteen dated service buckets. Only chicken/noodles have
new offers in this explicitly supplied test domain. Their fixed needs are 7.6 kg
and 3 kg after opening stock; the other six ingredients are already covered.
Every supplied opportunity is enumerated without dropping any of its pack choices.

| Explicit fixture | Full combinations | Independently expected selection and cash |
| --- | ---: | --- |
| Two suppliers, Fresh/Pantry; chicken pack/capacity 4 kg each; noodles pack 1/capacity 2 kg each | `2*3*2*3 = 36` | Chicken 4 kg each at 4.50/5 gives 38; noodles Fresh 2 at 6.50 and Pantry 1 at 7 gives 20; two fees of 5. Total **S$68**, chicken closing 0.4 kg |
| Three suppliers, Fresh/Pantry/Market; chicken pack/capacity 3 kg each; noodles pack 1/capacity 2 kg each | `2*3*2*3*2*3 = 216` | Chicken 3 kg each at 4.50/5/6 gives 46.50; noodles Fresh 2 and Pantry 1 gives 20; three fees of 5. Total **S$81.50**, chicken closing 1.4 kg |

Both close noodles at zero and cover every supplied expected ingredient demand.
Tests also reverse input ordering and stop each search one combination early;
incomplete searches expose only diagnostic incumbents. These are explicit
synthetic capacities/prices, not changes to the backend seed or arbitrary pruning
of its larger domain. The earlier single-supplier S$60.50 oracle is retained.

**Three suppliers alone does not bound runtime.** Domain size is the product of
all opportunity pack counts plus one. Many offers, large capacities or multiple
arrivals can exceed the work limit, even with only three supplier identities.
These tests establish the named finite domains, not a performance guarantee for
all 24 seed offers or the full seven-day MVP. Do not remove real offer/quantity
choices without an agreed scope or sound exclusion proof to make a run pass.
The current implementation returns incomplete when its supplied domain cannot
finish within the work limit; it does not publish a heuristic incumbent.

### Update verification and remaining acceptance

Verification for the combined tree is recorded in `ML_HANDOVER.md` section 9.
Run the complete backend suite with its documented disposable PostgreSQL instance
before merging this contribution into main. In particular retain and execute
`test_snapshot_history.py`, `test_audit_guards.py`, `test_audit_upgrade.py`,
`test_sales.py`, `test_planning.py` and `test_seed_contract.py`. They test the
historical selection/audit behaviour crossed by the recipe-helper merge.
No database schema, backend publication logic, agent code or frontend behaviour
was newly implemented by this ML update.
# Pass 3E implementation note — 17 September 2026

Base: `86abb37cb12eaee8296c2418e88f2f7b9bdef0ba`; isolated branch
`feat/ml-pass3e-compatibility`. Scope: projection FEFO identity, procurement
expiry, guarded minimum-pack enumeration and semantic supplier ties, with focused
numerical/contract tests. Reuse the backend-owned 24-offer fixture and schemas;
no persistence, adapter, replay or frontend changes. Inspect independent small
exhaustive oracles, full fixture cash, expiry boundaries, cross-source ties,
applicability guards and generation/evaluation limits. The original checkout is
preserved. Backend policy tags are implemented on main; historical `sales.py`
still sorts expiry/ID and must not be described as receipt-aware parity.

# Promotion forecast application and comparison — 18 September 2026

Implementation traceability recorded before runtime changes. This focused slice
uses main `40876fc20270bc3426e15c65a36c60578c66ac80`; unfinished materiality work
is excluded. The canonical `PromotionEvent.payload.demand_multiplier` is a
dimensionless multiplier, with inclusive Singapore campaign dates and a separate
revision `effective_at`. Event `timestamp` is recording time. A promotion name
(including 1-for-1) supplies no numerical factor. Pure internal evidence types
below do not establish another Backend transport.

| Requirement | Source | Implementation | Acceptance test | Outstanding dependency |
| --- | --- | --- | --- | --- |
| Served portions; explicit assumption; normal eligibility unchanged | v2 §§5, 6.1; v3 §§3–4 | `apply_promotions`, existing baseline/allocator | `test_normal_and_explicit_multiplier_recipe_oracle`, `test_name_does_not_double_demand_without_factor`, `test_decimal_conservation_independent_of_ambient_context` | Backend freezes manager/scenario assumption source |
| Operational/knowledge time; future context; revisions/cancellation | v2 §§5.2, 6.3, 10.1; canonical PromotionEvent | `_visible_events`; revision selection per interval | `test_later_recording_cannot_change_frozen_result`, `test_known_future_effective_revision_changes_only_dinner`, `test_revisions_cancellation_and_input_order` | Complete frozen revision history, not live promotion rows |
| Preserve actual elapsed sales; no second consumption | v2 §§6.3, 7, 12.2 T02/T12 | `_actuals`; future buckets separate | `test_actual_lunch_preserved_only_future_adjusted`, `test_actual_coverage_errors_explicit` | Backend resolves active batch revisions and complete coverage |
| No compounded uplift or invented overlap/partial-bucket policy | v2 §§5.3, 6.1; v3 §7 | original unadjusted basis; explicit findings | `test_repeated_frozen_inputs_and_mutation`, `test_overlapping_promotions_explicitly_incomplete`, `test_partial_bucket_cancellation_is_not_silently_ignored` | Additional timing/stacking policies remain unsupported |
| Immutable diff and overlap evidence, no lifecycle decision | v2 §§9, 10.4, 12.2 | `compare_forecast_versions`; overlap evidence | `test_immutable_comparison_deltas_and_initial_forecast`, `test_negative_and_zero_baseline_deltas`, `test_incompatible_source_versions`, `test_changed_history_disallows_promotion_only_attribution` | Rudy maps evidence; Backend persists immutable versions |
| Existing recipes/projection/cash slice preserved | v3 §§3–8; accepted Pass 3E tags | reuse numerical functions, no policy changes | `test_downstream_projector_receives_only_adjusted_portions`; existing `test_pass3e_numerical.py` | Activity-capable frozen snapshots and publication remain separate |

Reversible implementation choices: one-day, half-hour numerical scope; exact
Decimal quantities via rational intermediates; relative deltas alone rounded to
28 significant digits, half-even. Full promotion revision history and complete
resolved elapsed half-hour batches are explicit input requirements. No threshold,
approval, procurement policy, holiday uplift or learned promotion effect is added.

## Callable promotion interface and frozen evidence

`src.promotion_forecasting` exposes:

- `apply_promotions(basis: ForecastVersion, menu_items, *, events:
  Sequence[PromotionEvent], context_evidence: SourceEvidence | None,
  context_complete: bool, as_of, known_at, result_reference, sales=(),
  actual_coverage=None) -> PromotionApplication`.
- `compare_forecast_versions(previous: ForecastVersion | None,
  current: ForecastVersion, menu_items) -> ForecastComparison`.

Construct an original `ForecastVersion` from the unchanged `seasonal_baseline`
and `allocate_service_buckets` outputs. It contains an immutable reference,
operational `as_of`, real recording cutoff `known_at`, target date, complete dated
profile, complete projected bucket vectors and source evidence. Set
`promotion_state="EXCLUDED"` and `base_reference=reference` only when the resolved
original basis excludes promotion adjustments. Insufficient baseline history
remains insufficient: do not replace `None` with zero. An already-adjusted or
unknown basis is incomplete. Amendments/cancellations must use the original
basis again, never the prior adjusted result.

`sources` is a tuple of named `SourceEvidence` values for exactly `catalogue`,
`recipe`, `history`, `model`, `profile`, `policy`, and `other_context`.
Each needs a resolvable immutable reference, availability time and captured revision.
The caller must bind catalogue/recipe versions to the actual canonical inputs;
the kernel cannot prove storage immutability or repair source selection from an
arbitrary reference string. Use an explicit empty-context artifact for
`other_context` when appropriate, not an omitted value.
`EXPLICIT_PORTION_MULTIPLIER_V1` names this numerical interpretation and
fail-closed behavior; it is not a newly approved Backend policy record.
Quantities use `PORTIONS`, canonical dish IDs and Decimal values.

`events` reuses **canonical `operations_schemas.PromotionEvent`**, not a new
API payload. `timestamp` is when a revision was recorded, `source` identifies
the explicit manager/scenario assumption, and the payload supplies identity,
revision, inclusive Singapore campaign dates, affected dishes, dimensionless
`demand_multiplier`, active state and operational revision `effective_at`.
For each promotion, the supported frozen input contains the complete visible
revision prefix starting at 1; duplicate/gapped or non-monotone revisions fail.
`context_complete=True` plus evidence is required even for an empty event list.
Events recorded after `known_at` do not enter this calculation or its output.
Visible future-effective revisions apply at the applicable future bucket, so
the adapter must not discard them merely because they follow run `as_of`.
The highest visible effective revision at the bucket start wins; inactive means
cancelled. Full-day campaign dates do not imply that a revision was effective
before its own operational clock.

The supported application period is each complete half-hour `[start, end)`.
A revision at a bucket start applies there; one at its end applies to the next
bucket. A relevant revision strictly inside a future bucket is incomplete.
The canonical campaign model has no partial-day start/end fields: an arbitrary
partial-day campaign is not supported by inventing those fields. Date windows
and explicitly timestamped revision effects are distinct. Overlapping active
promotions on the same dish/bucket are incomplete, even if their factors happen
to be one; different dishes or disjoint periods are supported. No stacking
policy or holiday effect is inferred.

The basis allocator already apportions residual millionths. Application multiplies
those **existing** bucket quantities exactly using rational intermediates and
returns finite Decimals without another rounding pass. Thus 100 portions at 1.2
sum to exactly 120; four lunch buckets are 8.0000004 and two are 7.9999992,
while each dinner bucket is 9. This preserves the original allocation and the
exact total, rather than silently rerounding each bucket to whole portions.

For intraday calls, `sales` contains caller-resolved active canonical
`SalesBatch` plus availability/revision evidence for each elapsed service
half-hour, and `actual_coverage` attests complete resolution. The canonical
complete-batch contract makes omitted dishes explicit zero. Duplicate identities,
unresolved revisions, missing intervals, partial-bucket cutoffs and late evidence
are incomplete. The kernel does not replay corrections, add daily final totals,
or infer observations in service gaps. Broader/irregular batch intervals need a
separately supported allocation contract. Actual quantities are copied unchanged
to `forecast.actuals`; **only `forecast.buckets` (future projected demand) goes to
recipe conversion / `project_inventory`**, using opening inventory at the same
operational cutoff. This avoids consuming elapsed sales twice.

`PromotionApplication.complete=False` has `forecast=None` and concrete findings;
it is not zero demand, no risk, or an approvable candidate. Complete results retain
the original basis reference, all visible revision/event references (including
cancellations), applied bucket overlaps, context evidence and actual coverage.
Repeated identical frozen inputs produce equal outputs; reference persistence
and collision prevention across runs remain Backend/adapter responsibilities.
Overlap records may support reassessment independently of a sales-deviation
threshold. They do not return KEEP/REVISE, freshness, approval or publication.

## Immutable comparison semantics

Comparison validates both artifacts and matching one-day time coverage, units,
semantic dated profile, and catalogue/recipe/model/profile/policy source versions.
Different forecast IDs are expected. Reusing one immutable reference for different
content is rejected. Different history, other context, promotion revisions,
knowledge cutoffs, actual evidence and original basis references are recorded in
`changed_context`; attribution is explicitly `NO_CAUSAL_CLAIM`.

`COMPARED` returns one `ForecastDelta` per future bucket/dish: `old`, `new`,
signed `delta=new-old`, `absolute_delta=abs(delta)` and signed fractional
`relative_delta=delta/old`. Only relative values are rounded (28 significant
digits, half-even). A zero old value gives `None` and `ZERO_BASELINE`, including
zero-to-zero. `INCOMPATIBLE` returns no deltas and findings.
`NO_PREVIOUS_VERSION` retains the valid current artifact with no deltas; it is
not a failed initial forecast. Both full immutable artifacts remain attached
to the comparison, including their evidence. No forecast is recomputed.

## Worked examples and usage

`tests/fixtures/promotion_forecast_v1.json` is explicitly synthetic. It reuses the
canonical v3 history and service-profile fixtures. At 15 February 22:00 Singapore,
the known manager/scenario assumption for 16 February chicken-rice is **1.2**.
The promotion's 1-for-1 name does not supply an additional factor.

| Dish | Original portions | Adjusted portions |
| --- | ---: | ---: |
| chicken-rice | 100 | 120 |
| fried-rice | 60 | 60 |
| chicken-noodles | 80 | 80 |
| tofu-bowl | 40 | 40 |
| vegetable-noodles | 40 | 40 |

Independent recipe totals are chicken **27.600 kg**, rice **22.000 kg**, noodles
**18.000 kg**, eggs **60 pieces**, tofu **6.000 kg**, vegetables **11.800 kg**,
oil **1.000 litres**, soy-sauce **2.000 litres**. The added 20 chicken-rice portions
consume 3 kg chicken, 2 kg rice and 0.2 litres soy-sauce. Tests pass the actual
calculated quantities through both existing recipe arithmetic and projection.
The 17:00 bucket changes from 7.5 to 9 chicken-rice portions: signed/absolute
delta 1.5; relative delta 0.2.

At an intraday 14:00 cutoff with six complete lunch batches of 7 actual
chicken-rice portions, retain **42 actual** and project **72 future** dinner
portions. Neither 42 nor an adjusted lunch forecast enters future projection.
A known revision becoming effective at 17:00 yields 40 normal lunch +72 dinner
if issued before the service day. A cancellation at 17:00 after the earlier 1.2
revision gives 48 projected lunch +60 dinner from the same original basis.

Incomplete example: two visible active promotions affecting chicken-rice in the
same bucket return `complete=False`, `forecast=None`,
`INCOMPLETE_PROMOTION_INPUT: Unsupported overlapping promotion stacking`.
An input basis already marked `APPLIED` also returns incomplete. Neither case
can be passed onward as a new purchase candidate.

From `services/api`, using the prepared environment (PowerShell shown):

```powershell
.venv/Scripts/python.exe -m pytest tests/test_promotion_forecasting.py -q
.venv/Scripts/python.exe -m pytest tests/test_promotion_forecasting.py tests/test_forecasting.py tests/test_requirements.py tests/test_service_buckets.py tests/test_inventory_projection.py tests/test_synthetic_history.py tests/test_procurement.py tests/test_pass3e_numerical.py -q
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m pyright
.venv/Scripts/python.exe -m ruff format --check src/promotion_forecasting.py tests/test_promotion_forecasting.py
```

The fixture-building example is the `case` fixture in
`tests/test_promotion_forecasting.py`; it calls the actual baseline and allocator.
Use its constructor sequence with resolved production artifacts, not its
synthetic evidence IDs. There is no database loader or new public endpoint.

## Consumer boundary and verification

**Rudy:** resolve the unchanged seasonal baseline into an original
`ForecastVersion`, call `apply_promotions`, then optionally
`compare_forecast_versions` against the prior persisted result. Preserve explicit
incomplete findings and the no-previous state. Forward only future buckets to the
existing recipe/projector/validated procurement path. Persist/read evidence via
the agreed Backend seam; do not treat a local reference string as persistence.
No full materiality engine or threshold decision is included.

**Chun Yang:** freeze complete promotion revision/event evidence and assumption
source with real recording times, catalogue/recipe/history/model/profile/policy
references, original unadjusted forecast identity, and complete resolved actual
batch coverage at the operational cutoff. Persist immutable result references.
Current `fact_history.promotions_at` returns selected promotion state and filters
revision effects at operational `as_of`; it does not by itself provide the full
recording/source-event evidence or known future-effective revision history required
here. The first-slice `forecast_input` artifact supplies baseline history only.
Activity-capable procurement snapshots, commitment-aware projection, closing-count
correction routing and sales-batch reassessment remain Backend work. No endpoint
or existing snapshot contract is silently extended by this numerical module.

Inspected current main: `40876fc20270bc3426e15c65a36c60578c66ac80` (PR #26,
intraday evidence workspace), including PR #25's versioned baseline input. The
published **unmerged** agent branch inspected is
`764a27b9f89be86a36dd3d8dcc95079f77314239`; its tool names
`forecast_demand`/`compare_forecast_versions` and `FORECAST_RESULT` evidence
category describe the consumer seam, not completed adapters. Rudy's supplied
18 September message establishes the priority, not evidence of unpublished code.
Existing #16 confirmations and Pass 3E policy tags remain unchanged.

Fresh verification: **428 numerical tests passed** (51.59 s), including 61 new
promotion/comparison cases and the synthetic service-profile correction. Ruff
passed, Pyright reported zero errors/warnings, and the two new Python files passed
format checks. Full disposable-PostgreSQL merge-gate results are recorded below.
Synthetic tests establish numerical behavior, not real uplift
accuracy, backend snapshot correctness or live Agent integration.

Full merge gate: **494 passed, 2 dependency warnings, 611.49 s** using locked
dependencies, Python 3.12.12 and PostgreSQL 18 in disposable local containers on
the same Linux clock. Command inside the Python container:
`uv run --locked pytest -q -o cache_dir=/tmp/pytest-cache`.
The source worktree was mounted read-only at `/workspace`, working directory
`/workspace/services/api`, with `UV_PROJECT_ENVIRONMENT=/tmp/promotion-venv`.
The Python image was `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`, digest
`sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58`.
PostgreSQL used a private tmpfs container; `TEST_DATABASE_URL` referenced its
disposable administrative database. The standard fixture created/dropped a unique
test database per test. No shared database, backend source, assertions or host
clock settings were changed.

The initial Windows Python + Docker PostgreSQL full command
`.venv/Scripts/python.exe -m pytest -q` produced **489 passed, 5 failed,
2 warnings, 419.88 s**. Failing tests:

- `test_audit_guards.py::test_complete_sparse_batches_and_strict_correction_identity`
- `test_sales.py::test_sales_batch_updates_an_estimate_without_mutating_physical_counts`
- `test_sales.py::test_receipt_does_not_restore_pre_receipt_consumption`
- `test_snapshot_history.py::test_commitments_receipts_cancellations_and_cycles_obey_operational_cutoff`
- `test_snapshot_history.py::test_later_sales_and_daily_corrections_do_not_change_known_snapshot`

Targeted Windows reproduction on clean unchanged main `40876fc` yielded one
coverage failure (8.28 s), then three failures/one pass for the other four cases
(27.66 s); the first sales test passed on retry and snapshot assertion locations
varied. A bracketed measurement found PostgreSQL **0.489–0.491 seconds ahead**
of Windows. Server-generated `recorded_at` versus Python `known_at` explains
the observed immediate-visibility race; no timezone-string assertion was changed.
In the Linux run, Python and PostgreSQL were within the measured request interval
(-0.000124 to +0.000791 s), and **all the same tests passed**. This supports an
environment clock problem, not a promotion regression or a waiver of failed tests.
Clock consistency remains an operational concern; these tests do not establish
correctness of every future multi-host deployment. No frontend, Bedrock or live
Agent end-to-end checks were run.
