# Manager calculation results

Implementation branch: `backend/manager-calculation-results`. This is the Backend
handback for the forecast/projection portion of `FRONTEND_PENDING_FEATURES_HANDOFF.md`.
It is not yet a connected frontend feature or a hosted-deployment claim.

The [response example](examples/manager-calculation-results.json) is an actual
HTTP 200 manager response from a fresh, migrated, seeded PostgreSQL instance.
Its plan used the real numerical engine with controlled specialist reasoning.
The database was disposed after capture; its IDs are illustrative immutable
identities, not references to records in the team's current demo database.

## Read contract

`GET /api/v1/manager/runs/{run_id}/calculation-results` uses the existing manager
session cookie. No Agent token is needed or accepted as manager authorization.
The response model is `ManagerCalculationDisplay` in OpenAPI `/docs`.

- `AVAILABLE` returns an immutable, content-addressed `artifact` with schema
  `MANAGER_CALCULATION_OUTPUTS_V1` and a SHA-256 over its canonical JSON content.
- `NOT_RECORDED` returns `artifact: null`, not empty buckets or zero forecasts.
  This includes queued runs, historical runs produced before this implementation,
  and calculation paths that have not persisted this artifact.
- Unknown run: 404. Missing login: 401. Agent-only caller: 403.
- An inconsistent stored artifact returns 409 `CALCULATION_ARTIFACT_MISMATCH`.
- `stale` compares the artifact's captured revision with current Backend revision.
  Stale output remains readable as history. The artifact is never replaced on GET.
- `plan_version_id` links the run's published version when present. Proposed
  supplies bind to `artifact.outputs.candidate_id`; neither presence nor a
  projection establishes manager approval.

Select an existing run through the existing run list, then fetch that exact ID.
There is no implicit latest-result substitution and no recalculation on read.

## Forecast

Outputs include run ID, operational/knowledge cutoffs, state revision, policy and
forecast-input identities/versions, `ForecastVersion`, frozen dish names, and the
per-dish `DishForecast` baseline metadata. Baseline metadata retains method,
eligible-day counts, matching-weekday counts, used-history references and coverage
flags. `censored_history_present` records whether the frozen input contained
censored observations; it does not claim those observations were used.

The method tag is `SEASONAL_BASELINE_V1`; the selected forecast's promotion state
and source references remain explicit. Baseline daily expectations and selected
promotion-aware bucket expectations are different fields, not interchangeable.
Portions are fractional Decimal expectations serialized as strings. Null is not
zero. Buckets are `[start, end)` in the declared `Asia/Singapore` timezone. This
first-slice output does not imply a general 21-day forecast.

## Projection

`existing_commitments_projection` runs the canonical `project_inventory` kernel
on the same frozen inputs used by procurement. `with_recommendation_projection`
is the independent candidate validator's actual projection, not a browser or read
endpoint reconstruction. `proposed_supply_ids` identifies hypothetical additions.
Both use the canonical `InventoryProjection` schema exposed in OpenAPI.

For each bucket, ingredient balances contain canonical units and opening,
admitted arrivals, required usage, allocated usage, unmet demand, expired and
closing quantities. Required usage differs from allocated usage if a shortage
occurs. Lot balances preserve upstream lot keys and origin classifications.
Existing expected supplies and proposed purchases remain distinct through their
identifiers. Received stock is already in opening inventory. Do not add it again.
Expiry is the existing FEFO boundary: usable through expiry date, excluded from
the next day. Projected expiry is not observed waste.

Inspect each projection's `complete`, `findings`, horizon and nullable output
collections. A known shortage is not the same as incomplete evidence. These
projections do not certify full economics, optimality or a future ordering cycle.
Budget/storage certification remains with the existing candidate validation.

## Persistence and scope

The normal first-slice engine persists these outputs in the existing run snapshot
alongside its candidate and validation, so no extra database table or migration is
needed. Repeated calculation must produce the same stored output; conflicting
content fails with 409 `CALCULATION_ARTIFACT_CONFLICT`. Read-side validation checks
the hash and the run/revision binding. Existing run-snapshot lifecycle protections
continue to apply.

Current availability of `calculation-results` is successful normal first-slice
calculations (including supported promotion calculations). Contingency and
incomplete/no-candidate normal results need additional explicit mapping; do not
display this as an all-scenario result catalogue yet.

## Sales assessment forecast

The existing `GET /api/v1/manager/runs/{run_id}/sales-materiality` additionally
returns `issued_forecast` (`IssuedForecastDisplay`, version
`ISSUED_FORECAST_DISPLAY_V1`). This allowlists the exact persisted forecast,
frozen dish names, input identity/version, plan reference, assessment clocks,
revision and canonical request SHA-256. It does not expose the engine request.
The route still returns null when no sales assessment exists.

This forecast is the issued comparison basis, not a new demand adjustment. Its
own clocks can precede the assessment clocks. Per-dish method/eligible-history
metadata is unavailable in this exchange and is explicitly identified as such;
it is not reconstructed on read. The existing `result.projection`, findings,
limitations and completeness retain the canonical calculated stock-risk output.
An incomplete materiality result does not imply its comparison forecast is zero
or that no stock risk exists. Select this response by the exact sales run ID.

Waste entry remains disabled pending its approved persistence, inventory-effect,
correction and eligibility contract. Full-economic policy activation and result
publication remain separate from `CASH_SLICE_V1`/`NEW_PURCHASE_CASH_ONLY`.

ET should map the canonical response into frontend display models, preserve all
unknown/stale states, and connect a real scenario before enabling normal-navigation
tabs. This handback does not authorize frontend fallback calculations.

## Verification

Integration baseline `5b0dbc7` combines Rudy's `50a78e0` with main `30f50a9`.
Its worker acceptance passed 17 tests; the remaining suite, excluding that
already-passed file, passed 1,314 tests (1,331 total). Ruff and Pyright passed.
This baseline result is separate from the subsequent manager-output feature.

Two PostgreSQL manager-result tests passed (storage/read parity, Decimal strings,
unavailable output, retained history, stale marking, tamper rejection and manager
authorization). Twenty worker/engine regressions passed. Ruff passed and Pyright
reported zero errors/warnings. These results cover this Backend slice; frontend
rendering and hosted end-to-end acceptance remain pending.
