# Baseline forecasting, service allocation and recipe requirements

Implemented locally on `feat/forecasting`, based on freshly fetched main
`5827515ec48183ba908151fb0016b118cd801b1c`. This is the first bounded numerical
task from v2 sections 5.2, 6, 7 and 12, with v3 sections 3-5 replacing the old
catalogue fixture. The user explicitly confirmed Ethan's v3 approval.

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

`src.inventory_projection.project_inventory` is now implemented locally. It
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
