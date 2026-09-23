# Backend and Agent integration contract

The first Pass 3E procurement input and the Backend-owned sales-materiality boundary are implemented and frozen. This contract defines the authoritative input that the Agent adapter may send to the deterministic engine. It does not claim that the Agent adapter or contingency flow is complete.

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

An approved opportunity can also carry `shipment_group_id`. Backend stores and freezes that explicit identity; the contingency adapter may use it to group *new* purchase lines for one shipment charge. `null` means no grouping was approved and must not be replaced with an inferred supplier/arrival group. The seeded normal-only domain has `null` for this field. This additive transport field does not activate contingency search or change the normal fee policy.

The forecast input is a separate immutable Backend artifact. It contains the four complete Monday closing-sales observations dated 19 January, 26 January, 2 February, and 9 February 2026, plus the five-item menu manifest, target date, `SEASONAL_BASELINE_V1` method tag, recording time, and source revision. It contains inputs, not a precomputed forecast: the deterministic engine must run `seasonal_baseline` and preserve its output evidence. Missing, late-recorded, or inconsistent forecast input fails closed instead of allowing the adapter to inject fixture data.

## Agent reads

Both routes require the Agent bearer credential.

| Purpose | Route |
| --- | --- |
| Inspect the policy and complete approved domain | `GET /api/v1/procurement-policies/CASH_SLICE_V1/versions/1` |
| Read the exact input frozen for a claimed run | `GET /api/v1/runs/{run_id}/procurement-contract` |
| Inspect the approved sales threshold policy | `GET /api/v1/sales-threshold-policies/SALES_MATERIALITY_V1` |
| Read the policy and references frozen for a claimed run | `GET /api/v1/runs/{run_id}/sales-materiality-context` |

The run contract includes `run_id`, `as_of`, `known_at`, `captured_state_revision`, the policy version, approved domain, versioned `forecast_input`, and frozen inventory, ingredients, menu, recipes, suppliers, commitments, daily history, authoritative daily sales, sales batches, promotions, holidays, order-cycle decisions, and current supplier observations. The forecast input must be effective by `as_of` and recorded by `known_at`; the complete contract is saved in the claimed run snapshot under the captured state revision.

A PostgreSQL/API acceptance test now records a 10 kg vegetables delivery, receives 6 kg, delays the outstanding 4 kg, and claims a later assessment. The frozen contract contains the received lot in opening inventory and only the 4 kg remainder in `commitment_projection`, with the updated arrival and expected expiry. This proves the fixed-commitment input boundary for the supplier-delay demo. It does not supply the residual post-assessment forecast, coverage windows, activated contingency policy, or Agent route needed to recommend additional stock.

The first-slice policy can be selected from its declared issue time through its horizon end. The policy's explicit-empty flags describe the original seeded baseline; they do not prohibit later operational activity in a run snapshot. `activity_semantics` states that the versioned forecast history remains immutable, intraday batches affect inventory and reassessment only, and the latest closing revision is authoritative for daily forecasting. Reconciliation compares the two sources and never adds them.

`commitment_projection` is selected at the same `as_of` / `known_at` / state-revision boundary. Its manifest includes every frozen external delivery. Outstanding supply carries the latest expected arrival, quantity after receipts/shortfall/cancellation, a stable projected-lot ID, and expected expiry derived from the approved offer's shelf-life revision. Closed commitments remain in the manifest with zero outstanding quantity and no projected lot. Missing expiry or approved-offer evidence marks the projection incomplete instead of inventing a value.

## Sales-materiality request and result

`SALES_MATERIALITY_V1` is stored as a versioned Backend policy and selected by `as_of`, `known_at`, and captured state revision. It freezes Aniq's approved rule: cumulative per-dish deviation is material when it is at least `max(5, 0.2 × expected)`, after at least 20 expected portions and two complete half-hour buckets in the one-day Singapore demo scope. The policy endpoint contains the persisted definition; the run context adds the selected-policy and snapshot evidence references.

The Agent owns the numerical call but uses Backend as the immutable record boundary:

| Step | Route |
| --- | --- |
| Persist the exact engine request | `POST /api/v1/runs/{run_id}/sales-materiality-requests` |
| Read the persisted exchange | `GET /api/v1/runs/{run_id}/sales-materiality-assessment` |
| Persist the exact engine result | `PUT /api/v1/runs/{run_id}/sales-materiality-requests/{request_id}/result` |

The request combines the issued forecast, versioned forecast input, catalogue, plan/safety references, risk input, snapshot evidence, and selected threshold policy with its evidence. Backend hashes and stores the canonical request. One request is allowed per run; an identical retry is idempotent and a different retry returns `409 MATERIALITY_REQUEST_CONFLICT`.

The result must identify the same run, clocks, state revision, snapshot, forecast input, policy version, coverage horizon, and required evidence references. Backend hashes and stores it once. An identical retry is idempotent and a changed result returns `409 MATERIALITY_RESULT_CONFLICT`. A new operational event makes the running contract stale and prevents request/result persistence or publication.

Sales-triggered runs require this persisted result before completion. An incomplete result can only lead to escalation; a material result cannot keep the plan unchanged; a complete non-material result may certify `KEEP_CURRENT_PLAN` without running the procurement optimiser. Manager approval and external order recording remain separate.

## Promotion and inventory-correction events

The frozen `promotions` collection contains complete canonical `PromotionEvent` records rather than flattened current state. Every entry has the event ID, type, recording timestamp, source, and strict `PromotionEventPayload`. The full known revision history is retained, including a known future-effective revision, because the numerical promotion function selects the effective revision for each service bucket. Assumption provenance belongs in the event `source`; it is not an extra payload field.

A closing correction that changes at least one physical lot count emits a canonical `INVENTORY_ADJUSTED` event in addition to `DAILY_UPDATE_CORRECTED`. Its payload identifies both daily revisions and each changed lot's ingredient, unit, previous quantity, corrected quantity, and delta. The exact events that requested a run are frozen through `trigger_event_ids`.

Agent-only inventory-correction routes are:

| Step | Route |
| --- | --- |
| Read the frozen correction events and corrected inventory | `GET /api/v1/runs/{run_id}/inventory-adjustment-context` |
| Persist or read the deterministic result | `PUT` or `GET /api/v1/runs/{run_id}/inventory-adjustment-assessment` |

The result is bound to the run clocks, state revision, snapshot, corrected inventory snapshot, trigger event IDs, plan reference, and evidence references. It is hash-bound and immutable with exact idempotent retries. A stale run cannot accept a first result. An incomplete result must escalate, a material result cannot keep the plan, and a complete non-material result may certify `KEEP_CURRENT_PLAN` without procurement optimisation. Backend persists and validates this boundary; the Agent or numerical tool determines materiality.

## Adapter rules

The Agent adapter may translate the persisted transport into the engine's typed input, but every mapped value must come from this contract or another explicitly versioned artifact. Policy identifier differences must be handled explicitly and tested; an adapter must not silently rename a policy, fetch newer supplier facts, or invent a fallback.

Only a completed search with a complete, feasible independent validation may proceed to Backend freshness and publication checks. Incomplete calculations retain their findings and null results. Existing external purchases remain fixed commitments and are never recreated as recommendation lines.

The remaining sales-materiality integration gate is Rudy's adapter: fetch the context, persist the exact request, call Aniq's pure function, map its result without collapsing `None`/`False`/`True`, and persist that result. The wider project still needs the normal-plan and contingency scenarios replayed end to end.
