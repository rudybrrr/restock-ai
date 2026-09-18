# Backend and Agent integration contract

The first Pass 3E procurement input is implemented and frozen. This contract defines the Backend-owned input that the Agent adapter may send to the deterministic engine. It does not claim that the adapter, result publication, materiality checks, or contingency flow are complete.

## Ownership

- Backend persists operational facts, policy versions, approved supplier domains, frozen run snapshots, plan versions, permissions, and audit history.
- The deterministic engine owns forecasting, inventory projection, supplier feasibility, candidate search, and numerical validation.
- The Agent owns investigation and tool orchestration. It must not create policy values or replace missing evidence with defaults.

`as_of` is the operational simulation time. `known_at` is the real recording cutoff. Historical calculations use facts effective by `as_of` and recorded by `known_at`; current mutable rows cannot replace missing historical evidence. API timestamps are timezone-aware ISO 8601 instants. Clients must accept equivalent representations such as `2026-02-15T22:00:00+08:00` and `2026-02-15T14:00:00Z`; the PostgreSQL session timezone may change the serialized offset.

## Frozen first slice

| Field | Frozen value |
| --- | --- |
| Policy | `CASH_SLICE_V1`, version `1` |
| Approved domain | `CASH_SLICE_20260216_DOMAIN_V1`, version `1` |
| Forecast input | `CASH_SLICE_20260216_HISTORY_V1`, version `1` |
| Issue time | `2026-02-15T22:00:00+08:00` |
| Service date and horizon | 16 February 2026, ending `21:00 +08:00` |
| Service periods | 11:00–14:00 at 0.4; 17:00–21:00 at 0.6; 30-minute buckets |
| New-order budget | S$100 |
| Safety stock | Zero for all eight seeded ingredients |
| Reliability | `CONTEXT_ONLY` |
| Order mode | `NORMAL_ONLY` |
| Fee policy | `SUPPLIER_ARRIVAL_ONCE_V1`, grouped by `(supplier_id, arrival_at)` |
| FEFO | `FEFO_EXPIRY_RECEIVED_LOT_ID_V1` |
| New-supply expiry | `EXPIRY_ARRIVAL_PLUS_SHELF_LIFE_MINUS_ONE_V1` |
| Search and tie break | `COMPLETE_PRUNED_DOMAIN_V1`; `SUPPLIER_ID_THEN_INGREDIENT_ID_V1` |

The approved domain contains 24 frozen offer revisions and 24 dated normal-order opportunities: one for each combination of the three approved suppliers and eight seeded ingredients. Every entry carries a source revision. Missing or inconsistent entries fail with `409 MISSING_REQUIRED_DATA`.

The forecast input is a separate immutable Backend artifact. It contains the four complete Monday closing-sales observations dated 19 January, 26 January, 2 February, and 9 February 2026, plus the five-item menu manifest, target date, `SEASONAL_BASELINE_V1` method tag, recording time, and source revision. It contains inputs, not a precomputed forecast: the deterministic engine must run `seasonal_baseline` and preserve its output evidence. Missing, late-recorded, or inconsistent forecast input fails closed instead of allowing the adapter to inject fixture data.

## Agent reads

Both routes require the Agent bearer credential.

| Purpose | Route |
| --- | --- |
| Inspect the policy and complete approved domain | `GET /api/v1/procurement-policies/CASH_SLICE_V1/versions/1` |
| Read the exact input frozen for a claimed run | `GET /api/v1/runs/{run_id}/procurement-contract` |

The run contract includes `run_id`, `as_of`, `known_at`, `captured_state_revision`, the policy version, approved domain, versioned `forecast_input`, and frozen inventory, ingredients, menu, recipes, suppliers, commitments, daily history, authoritative daily sales, sales batches, promotions, holidays, order-cycle decisions, and current supplier observations. The forecast input must be effective by `as_of` and recorded by `known_at`; the complete contract is saved in the claimed run snapshot under the captured state revision.

The first-slice policy can be selected from its declared issue time through its horizon end. The policy's explicit-empty flags describe the original seeded baseline; they do not prohibit later operational activity in a run snapshot. `activity_semantics` states that the versioned forecast history remains immutable, intraday batches affect inventory and reassessment only, and the latest closing revision is authoritative for daily forecasting. Reconciliation compares the two sources and never adds them.

`commitment_projection` is selected at the same `as_of` / `known_at` / state-revision boundary. Its manifest includes every frozen external delivery. Outstanding supply carries the latest expected arrival, quantity after receipts/shortfall/cancellation, a stable projected-lot ID, and expected expiry derived from the approved offer's shelf-life revision. Closed commitments remain in the manifest with zero outstanding quantity and no projected lot. Missing expiry or approved-offer evidence marks the projection incomplete instead of inventing a value.

## Adapter rules

The Agent adapter may translate the persisted transport into the engine's typed input, but every mapped value must come from this contract or another explicitly versioned artifact. Policy identifier differences must be handled explicitly and tested; an adapter must not silently rename a policy, fetch newer supplier facts, or invent a fallback.

Only a completed search with a complete, feasible independent validation may proceed to Backend freshness and publication checks. Incomplete calculations retain their findings and null results. Existing external purchases remain fixed commitments and are never recreated as recommendation lines.

The remaining integration gate is the real adapter and result path: connect this input to the deterministic engine, persist the exact request/result evidence, map outcomes consistently, then replay the normal-plan and contingency scenarios end to end.
