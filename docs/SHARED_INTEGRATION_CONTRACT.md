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

## Agent reads

Both routes require the Agent bearer credential.

| Purpose | Route |
| --- | --- |
| Inspect the policy and complete approved domain | `GET /api/v1/procurement-policies/CASH_SLICE_V1/versions/1` |
| Read the exact input frozen for a claimed run | `GET /api/v1/runs/{run_id}/procurement-contract` |

The run contract includes `run_id`, `as_of`, `known_at`, `captured_state_revision`, the policy version, approved domain, and frozen inventory, ingredients, menu, recipes, suppliers, commitments, daily history, and sales batches.

This first fixture is available only at its declared issue time and with its explicit empty commitments and post-count activity. Other activity returns `409 MISSING_REQUIRED_DATA` instead of producing a partially inferred contract.

## Adapter rules

The Agent adapter may translate the persisted transport into the engine's typed input, but every mapped value must come from this contract or another explicitly versioned artifact. Policy identifier differences must be handled explicitly and tested; an adapter must not silently rename a policy, fetch newer supplier facts, or invent a fallback.

Only a completed search with a complete, feasible independent validation may proceed to Backend freshness and publication checks. Incomplete calculations retain their findings and null results. Existing external purchases remain fixed commitments and are never recreated as recommendation lines.

The remaining integration gate is the real adapter and result path: connect this input to the deterministic engine, persist the exact request/result evidence, map outcomes consistently, then replay the normal-plan and contingency scenarios end to end.
