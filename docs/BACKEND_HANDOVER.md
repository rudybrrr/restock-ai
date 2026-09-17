# Backend handover

The backend owner is the first contributor. On 2026-09-12 the owner explicitly deferred ML and OpenClaw implementation to teammates. This document separates the working backend from that integration work; it does not declare tickets 1–8 fully complete.

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
| 4 | Timestamped sales/corrections, chronological lot estimates, expiry history, missing coverage and uncovered consumption | Connect the merged projection functions to materiality decisions; optional explicit waste/adjustment tools |
| 5 | Durable queue, claim/status/retry, frozen inputs, Pass 3E policy/domain, trigger links, candidate persistence, outcome checks | Connect the merged forecasting/procurement functions through the Agent adapter and real publication path |
| 6 | Exact plan/version decisions with instructions and actor/time, ordering occasions, actual-purchase source links | Deterministic latest-state certification/invalidation for real calculated plans |
| 7 | Daily, promotion, supplier and explicit delivery-disruption triggers; coalescing; stale-result rejection | Sales/ordinary-event materiality, harmless-change certification and material invalidation |
| 8 | Immutable recommendation history and separate fixed external commitments in run inputs | Residual-horizon contingency calculation, split suppliers, emergency fees and integrated no-double-ordering acceptance |

## Backend workflow

1. Manager submits physical closing counts and final dish sales. The revision, comparison evidence, event and assessment request commit together. Drafts do not queue a run.
2. Sales batches retain timestamps and source identities. They update estimates without an LLM call. Closing counts remain unchanged. Sales-driven assessment awaits the ML-owned materiality integration.
3. Promotion revisions and supplier facts request assessment immediately. Delivery delay, shortfall and cancellation events also request assessment. Ordinary receipts/orders/cycle decisions remain stored facts; their impact checks belong to the pending integration.
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
| Frozen Pass 3E policy/domain | `GET /procurement-policies/CASH_SLICE_V1/versions/1` |
| Plans and source-line IDs | `GET /plan-history`, `GET /plans/{version_id}`, `GET /plans/{version_id}/lines` |
| Exact decision | `POST /plans/{version_id}/decision` with `plan_id`, `plan_version`, `decision`, optional `instructions` |
| Audit and trigger trail | `GET /events`, `GET /audit`, `GET /runs/{id}/triggers` |

## ML and agent handoff

The OpenClaw package still contains the original echo tool. It has deliberately not been implemented on the agent owner's behalf.

`planning.py` contains a **limited development calculator**, not the final optimiser. It accepts aggregate dish quantities, converts recipes, checks basic stock/offer constraints and chooses one supplier per ingredient. It does not implement daily forecasting, lead-time stockout projections, all cutoff/shelf-life rules, supplier splitting, residual commitment subtraction or full economic costs. Do not use it to demonstrate those claims.

The pure numerical modules in `forecasting.py`, `inventory_projection.py`, and `procurement.py` are present on `main`, but they are not connected to the run/tool/publication path. The Agent adapter owns that connection and must consume the frozen procurement contract rather than rebuilding Backend inputs.

The calculator is disabled by default. Its tool returns `503 DECISION_ENGINE_NOT_CONNECTED` until the teammate connects the engine or a developer explicitly sets `ENABLE_DEVELOPMENT_CALCULATOR=true` for backend workflow tests. Tests opt in deliberately. Candidates and stored plans include `calculation_mode: DEVELOPMENT_FIXTURE`; the connected engine must explicitly label its own results `ENGINE`. Development results must not be presented as real first-plan or contingency acceptance.

Integration points:

- `planning._snapshot`: frozen inventory, recipes, offers, ingredient schedules, promotions, holidays, incoming commitments, cycle decisions, raw historical evidence and authoritative daily sales. Final sales appear once per day using the latest revision; never add its intraday batches again.
- `GET /runs/{id}/procurement-contract`: Agent-only exact first-slice input after claim. It contains `CASH_SLICE_V1` policy version 1, all 24 frozen offer/opportunity revisions, fee grouping, state revision, `as_of`, `known_at`, and the frozen operational baseline. Do not replace any of it with current facts or adapter defaults. The companion policy route is useful for validating a policy/domain before a run exists.
- `fact_history.py`: select supplier versions and promotion/delivery histories at operational and recording cutoffs. Snapshot `known_at` and version IDs support deterministic replay. Delivery receipts include only effective/recorded receipts; future closing-count corrections are excluded. Historical views must not call the current-state `read_delivery` helper.
- `planning.optimise` / `planning_schemas.py`: replace the limited calculator behind the HTTP adapter with the teammate's deterministic engine. Preserve artifact references, cost fields and typed candidate output. Store the exact engine result before completion.
- `assessment_queue.enqueue_event`: queue a material event inside the same transaction that records it. `operations.record_event` already routes explicit triggers. Do not call the LLM from sales ingestion.
- `planning.complete_run`: publication and outcome checks; `planning.decide_plan`: manager identity/version enforcement. Add real feasibility certification and material invalidation here using engine results, preserving original snapshots and historical approval events.
- `deliveries.read_delivery`: separates received, cancelled and outstanding quantities. Pass outstanding commitments as fixed dated supply, not as new recommendation lines. Agent tools must never mutate those commitments.
- `sales.estimated_inventory`: historical replay now follows `FEFO_EXPIRY_RECEIVED_LOT_ID_V1`, ordering usable lots by expiry, receipt time, then lot ID. This matches the merged numerical projector for equal-expiry lots.

Until materiality is integrated, revision checks conservatively block approval/publication after newer events. This is an explicit temporary limitation, not harmless-change certification. Full ticket closure requires the real integrated acceptance scenarios.

## Demo data and time

Seed data is synthetic, anchored at 2026-02-15 22:00 Singapore time. Suppliers differ in price, capacity, packs, lead times, reliability and fees. Delivery slots span the demo month. The Pass 3E policy domain is a separate immutable 24-offer fixture so it does not silently reinterpret those mutable live supplier terms. A repeated seed does not overwrite existing data; use a fresh disposable database to inspect revised seed values.

Apply `alembic upgrade head` before starting the updated API. Existing overlapping actionable versions are superseded with audit records; legacy purchase links retain reference-only provenance. Supplier values overwritten before this upgrade cannot be reconstructed: migration captures the existing offer as its baseline. Missing eligible history is explicit, not today's data substituted into a past assessment. Recording-time replay for previously untimestamped rows begins at migration. Old saved run artifacts remain preserved.

Sales corrections retain source, batch ID and exact period. Cycle decisions should supply effective_at in simulation time; omission means real time. Promotion and delivery-term revisions cannot precede already recorded relevant activity. Late receipt reconciliation remains supported.

The [shared integration contract](SHARED_INTEGRATION_CONTRACT.md) freezes the first-slice policy, approved supplier domain, fee grouping, and Agent read boundary. The real engine adapter, result persistence/publication, materiality certification, and contingency acceptance remain integration work. This backend is not yet the complete integrated demo.

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

Tests create isolated databases, apply all migrations, seed twice and drop those test databases afterward. Backend tests do not prove real ML/OpenClaw integration, a hosted deployment, or a second-machine connection.

Verification on 2026-09-17: Ruff and Pyright passed, and the full PostgreSQL suite passed all 429 tests after the Pass 3E numerical merge, timezone-agnostic contract-test correction, and FEFO replay alignment. These results verify the repository's backend and numerical behavior, but do not prove the unimplemented Agent adapter or end-to-end demo.
