# ReStock numerical functions and development datasets

This revision includes baseline forecasting, recipe conversion, dated service
allocation, one-day inventory projection, reproducible development history and
one-day cash procurement with independent validation. Use [feat/forecasting](https://github.com/rudybrrr/restock-ai/tree/feat/forecasting)
and resolve its commit for a consistent source/test/documentation review. The earlier
foundation was published at e3c66b6; d298c65 was the feature branch before these
dataset/procurement additions. Neither historical commit contains these additions.
Implementation is based on approved v2 plus v3; production policies and #16 live
contracts remain unresolved. Verification records below identify their task scope.

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
integration remain outside scope. Issue #16/CY-001 remain unresolved. The smallest
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
  CY-001 corrections, database adapters, immutable evidence persistence, freshness,
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
