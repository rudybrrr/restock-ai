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
| 4 | Timestamped sales/corrections, chronological lot estimates, expiry history, missing coverage and uncovered consumption | ML-owned materiality/projections and optional explicit waste/adjustment tools |
| 5 | Durable queue, claim/status/retry, frozen inputs, trigger links, candidate persistence, outcome checks | Real forecasting, dated-horizon optimisation, supplier/cutoff/expiry feasibility, cost evaluation and agent investigation |
| 6 | Exact plan/version decisions with instructions and actor/time, ordering occasions, actual-purchase source links | Deterministic latest-state certification/invalidation for real calculated plans |
| 7 | Daily, promotion, supplier and explicit delivery-disruption triggers; coalescing; stale-result rejection | Sales/ordinary-event materiality, harmless-change certification and material invalidation |
| 8 | Immutable recommendation history and separate fixed external commitments in run inputs | Residual-horizon contingency calculation, split suppliers, emergency fees and integrated no-double-ordering acceptance |

## Backend workflow

1. Manager submits physical closing counts and final dish sales. The revision, comparison evidence, event and assessment request commit together. Drafts do not queue a run.
2. Sales batches retain timestamps and source identities. They update estimates without an LLM call. Closing counts remain unchanged. Sales-driven assessment awaits the ML-owned materiality integration.
3. Promotion revisions and supplier facts request assessment immediately. Delivery delay, shortfall and cancellation events also request assessment. Ordinary receipts/orders/cycle decisions remain stored facts; their impact checks belong to the pending integration.
4. One agent attempt can run while one follow-up request waits. New triggers coalesce into the waiting run and retain event links. Claims freeze the current inputs. The backend rejects completion based on newer inputs and releases expired/stale attempts.
5. A new normal assessment creates a new plan identity. Pass `revises_plan_id` when changing an existing horizon. Purchase content is immutable; revisions do not inherit approval.
6. A manager decides the exact version. Approval never creates a delivery or marks an ingredient ordering occasion. Actual purchases may differ and optionally reference a source line and cycle date.

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
| Agent attempt | `POST /runs/claim`, `POST /runs/{id}/tools/optimise`, `POST /runs/{id}/complete` |
| Plans and source-line IDs | `GET /plan-history`, `GET /plans/{version_id}`, `GET /plans/{version_id}/lines` |
| Exact decision | `POST /plans/{version_id}/decision` with `plan_id`, `plan_version`, `decision`, optional `instructions` |
| Audit and trigger trail | `GET /events`, `GET /audit`, `GET /runs/{id}/triggers` |

## ML and agent handoff

The OpenClaw package still contains the original echo tool. It has deliberately not been implemented on the agent owner's behalf.

`planning.py` contains a **limited development calculator**, not the final optimiser. It accepts aggregate dish quantities, converts recipes, checks basic stock/offer constraints and chooses one supplier per ingredient. It does not implement daily forecasting, lead-time stockout projections, all cutoff/shelf-life rules, supplier splitting, residual commitment subtraction or full economic costs. Do not use it to demonstrate those claims.

The calculator is disabled by default. Its tool returns `503 DECISION_ENGINE_NOT_CONNECTED` until the teammate connects the engine or a developer explicitly sets `ENABLE_DEVELOPMENT_CALCULATOR=true` for backend workflow tests. Tests opt in deliberately. Candidates and stored plans include `calculation_mode: DEVELOPMENT_FIXTURE`; the connected engine must explicitly label its own results `ENGINE`. Development results must not be presented as real first-plan or contingency acceptance.

Integration points:

- `planning._snapshot`: frozen inventory, recipes, offers, ingredient schedules, promotions, holidays, incoming commitments, cycle decisions, raw historical evidence and authoritative daily sales. Final sales appear once per day using the latest revision; never add its intraday batches again.
- `planning.optimise` / `planning_schemas.py`: replace the limited calculator behind the HTTP adapter with the teammate's deterministic engine. Preserve artifact references, cost fields and typed candidate output. Store the exact engine result before completion.
- `assessment_queue.enqueue_event`: queue a material event inside the same transaction that records it. `operations.record_event` already routes explicit triggers. Do not call the LLM from sales ingestion.
- `planning.complete_run`: publication and outcome checks; `planning.decide_plan`: manager identity/version enforcement. Add real feasibility certification and material invalidation here using engine results, preserving original snapshots and historical approval events.
- `deliveries.read_delivery`: separates received, cancelled and outstanding quantities. Pass outstanding commitments as fixed dated supply, not as new recommendation lines. Agent tools must never mutate those commitments.

Until materiality is integrated, revision checks conservatively block approval/publication after newer events. This is an explicit temporary limitation, not harmless-change certification. Full ticket closure requires the real integrated acceptance scenarios.

## Demo data and time

Seed data is synthetic, anchored at 2026-02-15 22:00 Singapore time. Suppliers differ in price, capacity, packs, lead times, reliability and fees. Delivery slots span the demo month. A repeated seed does not overwrite existing data; use a fresh disposable database to inspect revised seed values.

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

Verification on 2026-09-12: the full PostgreSQL suite passed 46 tests. After adding the explicit fixture label and a concurrency regression, all 9 planning tests passed. Ruff and Pyright also passed. Local PostgreSQL was used directly; Docker was not required for these checks.
