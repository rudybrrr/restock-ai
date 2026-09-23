# Backend handover

The backend owner was the first contributor. The deterministic ML modules and local Agent control plane are now merged. This document separates that working local path from the automatic worker, live provider, contingency, and deployment work that remains.

## Start here

- Behaviour and ownership: [BACKEND_SPEC.md](BACKEND_SPEC.md).
- Shared terminology and contracts: [ARCHITECTURE.md](ARCHITECTURE.md) and [../CONTEXT.md](../CONTEXT.md).
- Original ticket acceptance: [BACKEND_TICKETS.md](BACKEND_TICKETS.md).
- Setup, credentials, browser/LAN connection: [API README](../services/api/README.md).
- Use `/docs` as the simple test interface. `200` is an HTTP success status, not a 200 ms requirement. Assessments return `202`; poll their run ID.

## Current ticket position

| Ticket | Backend available | Teammate integration still required |
| --- | --- | --- |
| 1 | Auth, seeded catalog, supplier terms, expiry-dated batches, migration/setup, connection page | Verify an actual second-machine connection when a teammate is available |
| 2 | Atomic closing revisions, complete counts/sales, authoritative physical baseline, reconciliation | None for basic daily entry |
| 3 | Actual external purchases, delay/cancellation, partial receipts, retry protection and count corrections | None for basic delivery entry |
| 4 | Timestamped sales/corrections, chronological lot estimates, expiry history, missing coverage, deterministic projection/materiality, provenance, and immutable request/result evidence | Optional explicit waste-entry tooling only; discrepancies are never labelled waste |
| 5 | Durable queue, frozen inputs, real first-slice engine adapter, one-shot queued worker, Coordinator execution, candidate validation/publication, and manager evidence | Configure deployment-level worker invocation and verify the live provider |
| 6 | Exact plan/version decisions with instructions and actor/time, lifecycle transitions, ordering occasions, actual-purchase source links, and stale approval rejection | None for the supported normal-plan slice |
| 7 | Daily, promotion, supplier, delivery, sales and inventory-correction triggers; coalescing; deterministic materiality; Coordinator routing; stale-result rejection; supersession/invalidation; one-shot worker | Configure automatic worker invocation for normal event traffic |
| 8 | Immutable recommendation history and separate fixed external commitments in run inputs | Residual-horizon contingency calculation, split suppliers, emergency fees and integrated no-double-ordering acceptance |

## Backend workflow

1. Manager submits physical closing counts and final dish sales. The revision, comparison evidence, event and assessment request commit together. Drafts do not queue a run.
2. Sales batches retain timestamps and source identities. They update estimates without an LLM call. Closing counts remain unchanged. The local Demand path calls the approved deterministic materiality function through the immutable Backend request/result boundary. The merged one-shot worker can execute queued runs when invoked; automatic invocation is pending.
3. Promotion revisions and supplier facts request assessment immediately. Frozen promotions retain strict canonical event envelopes and complete known revision history. Closing-count changes emit `INVENTORY_ADJUSTED` and use an immutable deterministic assessment before a safe correction can keep the plan. Delivery delay, shortfall and cancellation events also request assessment. Ordinary receipts/orders/cycle decisions remain stored facts; their impact checks belong to the pending integration.
4. One agent attempt can run while one follow-up request waits. New triggers coalesce into the waiting run and retain event links. Claims freeze inputs effective by simulation as_of and recorded by real known_at. Supplier versions, event histories and recorded revisions prevent future facts from entering earlier snapshots. The backend rejects completion based on newer inputs and releases expired/stale attempts.
5. A new normal assessment may create a new plan identity; pass `revises_plan_id` when changing an existing horizon. Only one actionable version exists across all identities. Publication atomically supersedes the prior actionable version, preserving its status-change audit and actual commitments. Revisions do not inherit approval.
6. A manager decides the exact version. Approval never creates a delivery or marks an ingredient ordering occasion. New linked purchases match a current approved line's supplier and ingredient and stay within its cumulative allocation. Partial allocations expose an uncommitted remainder. Actual deviations use unlinked purchases; unchecked legacy links are labelled LEGACY_REFERENCE.

## API map

All operational routes below have `/api/v1` prefixes. Manager mutations require the manager session and an allowed browser Origin. Agent tools require the separate bearer credential.

| Action | Route |
| --- | --- |
| Daily draft/read/submit | `POST /daily-updates/{day}/draft`, `GET /daily-updates/{day}`, `POST /daily-updates/{day}/submit` |
| Timestamped sales | `POST /sales-batches` |
| Dated estimate | `GET /inventory/estimated?as_of=...` |
| Promotion revision/read | `PUT /promotions/{id}`, `GET /promotions` |
| Supplier price/availability/status/reliability | `PATCH /supplier-offers/{offer_id}` |
| Delivery create/update/receive | `POST /deliveries`, `POST /deliveries/{id}/update`, `POST /deliveries/{id}/receive` |
| Ordering occasions | `GET /order-cycles?start=...&end=...`, `POST /order-cycles/{ingredient_id}/{date}/decision` |
| Assessment | `POST /assessments`, `GET /runs`, `GET /runs/{id}`, `POST /runs/{id}/retry` |
| Agent attempt | `POST /runs/claim`, `GET /runs/{id}/procurement-contract`, `POST /runs/{id}/tools/optimise`, `POST /runs/{id}/complete` |
| Frozen Pass 3E policy/domain/forecast input | `GET /procurement-policies/CASH_SLICE_V1/versions/1` |
| Sales-materiality context | `GET /sales-threshold-policies/SALES_MATERIALITY_V1`, `GET /runs/{id}/sales-materiality-context` |
| Immutable materiality exchange | `POST /runs/{id}/sales-materiality-requests`, `GET /runs/{id}/sales-materiality-assessment`, `PUT /runs/{id}/sales-materiality-requests/{request_id}/result` |
| Inventory correction assessment | `GET /runs/{id}/inventory-adjustment-context`, `GET` or `PUT /runs/{id}/inventory-adjustment-assessment` |
| Plans and source-line IDs | `GET /plan-history`, `GET /plans/{version_id}`, `GET /plans/{version_id}/lines` |
| Exact decision | `POST /plans/{version_id}/decision` with `plan_id`, `plan_version`, `decision`, optional `instructions` |
| Audit and trigger trail | `GET /events`, `GET /audit`, `GET /runs/{id}/triggers` |

## ML and agent handoff

The OpenClaw package still contains only its smoke-test echo tool. Typed organiser reasoning adapters exist, but the OpenClaw runtime has no business tools and is not the application worker.

`planning.py` retains a **limited development calculator** for direct Backend workflow tests. It is not the real first-slice engine and must not be used to demonstrate forecasting, projection, supplier-splitting, expiry, fee, or economic-policy claims.

The real local first-slice path is connected: `decision_engine_adapter.run_first_slice_engine` consumes the frozen procurement contract, `BackendProcurementTools` exposes reference-only tools, and `backend_control_plane.run_backend_coordinator` joins the three specialists to Backend publication. `assessment_worker.run_one_queued_assessment` now claims and executes one queued application run through this path. Deployment-level invocation is still needed.

The development calculator is disabled by default and returns `503 DECISION_ENGINE_NOT_CONNECTED` unless a developer explicitly sets `ENABLE_DEVELOPMENT_CALCULATOR=true`. Tests opt in deliberately. Its candidates remain labelled `DEVELOPMENT_FIXTURE`; the merged first-slice adapter publishes `ENGINE` results. Neither path implements the contingency policy.

Integration points:

- `planning._snapshot`: frozen inventory, recipes, offers, ingredient schedules, promotions, holidays, incoming commitments, cycle decisions, raw historical evidence and authoritative daily sales. Final sales appear once per day using the latest revision; never add its intraday batches again.
- `GET /runs/{id}/procurement-contract`: Agent-only exact first-slice input after claim. It contains `CASH_SLICE_V1` policy version 1, all 24 frozen offer/opportunity revisions, the versioned four-Monday `forecast_input`, fee grouping, state revision, `as_of`, `known_at`, frozen operational activity, explicit forecast-activity semantics, and an adapter-ready fixed-commitment projection. Feed `forecast_input.payload.history` to the deterministic forecaster; do not inject test history or replace any contract value with current facts or adapter defaults. Intraday batches update estimated stock and request reassessment but never alter or get added to the versioned baseline history. The companion policy route is useful for validating the policy, domain, and forecast input before a run exists.
- `fact_history.py`: select supplier versions and promotion/delivery histories at operational and recording cutoffs. Snapshot `known_at` and version IDs support deterministic replay. Delivery receipts include only effective/recorded receipts; future closing-count corrections are excluded. Historical views must not call the current-state `read_delivery` helper.
- `decision_engine_adapter.py`: authoritative normal-plan adapter over the frozen contract and pure engine. `planning.optimise` remains only the opt-in development HTTP tool; do not route the worker through it.
- `assessment_queue.enqueue_event`: queue a material event inside the same transaction that records it. `operations.record_event` already routes explicit triggers. Do not call the LLM from sales ingestion.
- `planning.complete_run`: publication and outcome checks; `planning.decide_plan`: manager identity/version enforcement. Sales-triggered runs now require the immutable materiality result. Incomplete results must escalate, material results cannot keep the plan, and complete non-material results may keep it without procurement optimisation. The broader real-plan feasibility and invalidation integration remains.
- `sales_materiality_contracts.py` and `demand_tools.py`: Backend-owned selection, persistence, hashing, idempotency, freshness, completion gate, and merged Agent adapter. The worker must preserve this path and must not use the old fixture threshold or a fallback.
- `deliveries.read_delivery`: separates received, cancelled and outstanding quantities. The run contract's `commitment_projection` freezes those quantities after delay, shortfall, receipt, and cancellation history, derives expected expiry from the captured approved offer revision, and assigns stable projected-lot identities. Pass outstanding commitments as fixed dated supply, not as new recommendation lines. Agent tools must never mutate those commitments.
- `sales.estimated_inventory`: historical replay now follows `FEFO_EXPIRY_RECEIVED_LOT_ID_V1`, ordering usable lots by expiry, receipt time, then lot ID. This matches the merged numerical projector for equal-expiry lots.

Revision checks continue to block approval/publication after newer events. The one-shot worker is merged, but automatic application execution still needs a deployment trigger.

## Demo data and time

Seed data is synthetic, anchored at 2026-02-15 22:00 Singapore time. Suppliers differ in price, capacity, packs, lead times, reliability and fees. Delivery slots span the demo month. The Pass 3E policy domain is a separate immutable 24-offer fixture so it does not silently reinterpret those mutable live supplier terms. A repeated seed does not overwrite existing data; use a fresh disposable database to inspect revised seed values.

Apply `alembic upgrade head` before starting the updated API. Existing overlapping actionable versions are superseded with audit records; legacy purchase links retain reference-only provenance. Supplier values overwritten before this upgrade cannot be reconstructed: migration captures the existing offer as its baseline. Missing eligible history is explicit, not today's data substituted into a past assessment. Recording-time replay for previously untimestamped rows begins at migration. Old saved run artifacts remain preserved.

Sales corrections retain source, batch ID and exact period. Cycle decisions should supply effective_at in simulation time; omission means real time. Promotion and delivery-term revisions cannot precede already recorded relevant activity. Late receipt reconciliation remains supported.

The [shared integration contract](SHARED_INTEGRATION_CONTRACT.md) freezes the first-slice policy, approved supplier domain, forecast input, fee grouping, Agent read boundary, and Backend materiality exchange. The normal engine adapter, plan publication, and one-shot worker are merged. Automatic worker invocation, live-provider proof, and contingency acceptance remain integration work.

One review recommendation is deliberately not adopted: reported `AVAILABLE` status does not prove an offer is calculable. Partial supplier facts may retain unknown fields; the calculator rejects missing required inputs before using them. This follows the approved architecture's distinction between reported status and certified feasibility, rather than replacing unknown values with zero or discarding partial facts.

Business-day reconciliation uses Singapore midnight through the submitted closing cutoff. Submit zero-sale intervals to establish coverage before opening. Overnight business-day configuration is outside this daytime prototype. Each revision retains comparison evidence. Incomplete coverage is not a sales discrepancy, and discrepancies/uncovered recipe consumption are not measured waste.

The database retains expired lots; chronological estimates exclude them after their expiry date. Separate received batches keep separate expiry dates. Forecasts and expected deliveries must be labelled projected rather than physical.

## Checks

Run from `services/api`, using its environment and the test PostgreSQL URL described in the API README:

```text
python -m ruff check .
python -m pyright
python -m pytest -q
```

Tests create isolated databases, apply all migrations, seed twice and drop those test databases afterward. They prove the local deterministic ML/Agent/Backend integration, but not live OpenClaw/Bedrock behavior, a hosted deployment, or a second-machine connection.

Verification on 2026-09-22: the complete PostgreSQL suite passed all 1,018 tests on merged PR #37 commit `fe81a29`; Ruff, Pyright, frontend lint, and the production frontend build also passed. PR #38 added and passed the exact-version rejection/retry acceptance test. These results do not prove the pending application worker, live model/provider, contingency flow, hosted deployment, or second-machine demo.
