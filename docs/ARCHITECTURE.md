# ReStock Architecture Contract

## 1. Core idea

ReStock is an adaptive restaurant inventory and procurement agent.

It should answer:

- What should we buy?
- How much?
- When?
- From which supplier?
- Is the current plan still valid if something changes?

Main rule:

> **AI decides what needs investigation and when a plan should be reconsidered. Deterministic Python systems calculate and validate the decision.**

## 2. Shared architecture

```text
Frontend (Next.js)
        ↓
FastAPI + PostgreSQL
        ↑
OpenClaw + Claude
        ↓
Forecasting / Inventory / Optimiser / Rules
```

**FastAPI/Pydantic models are the canonical shared schemas.** Backend, frontend, agent tools, and tests should follow them. Do not invent duplicate schemas independently.

## 3. Team ownership

| Person | Owns |
|---|---|
| **Chun Yang** | FastAPI, PostgreSQL, schemas, plan storage/versioning, approvals |
| **ML / Decision Engine** | Synthetic data, forecasting, recipe/BOM, inventory maths, optimiser, simulator, evaluations |
| **Rudy** | OpenClaw, Claude/Bedrock, tool calling, event reasoning, replanning, HITL, guardrails, agent tracing |
| **Ethan** | Dashboard, plan/inventory/supplier views, approval UI, timeline, API integration, demo polish |

## 4. Core shared objects

```text
MenuItem
Ingredient
RecipeItem
InventoryLot
Supplier
SupplierOffer
SalesRecord
Promotion
DemandForecast
IngredientRequirement
PurchasePlan
PurchasePlanLine
Approval
AuditEvent
```

`PurchasePlan` is the central object. Minimum fields:

```text
id
version
status
forecast_id
inventory_snapshot_id
created_at
trigger_event_id
invalidation_reason
lines[]
total_purchase_cost
expected_waste_cost
expected_stockout_cost
delivery_cost
emergency_penalty
total_expected_cost
requires_approval
approval_reason
```

Statuses:

```text
PENDING_APPROVAL
APPROVED
INVALIDATED
REJECTED
SUPERSEDED
```

Approvals must always include:

```text
plan_id
plan_version
approver
decision
timestamp
```

A stale plan version must never be approved.

## 5. Event contract

All incoming changes use:

```text
Event
- id
- type
- timestamp
- source
- payload
```

MVP event types (shared by all specialised routes and tools):

```text
SALES_UPDATED
DAILY_UPDATE_SUBMITTED
PROMOTION_CREATED
PROMOTION_CHANGED
INVENTORY_ADJUSTED
INVENTORY_WASTED
SUPPLIER_AVAILABILITY_CHANGED
SUPPLIER_PRICE_CHANGED
SUPPLIER_STATUS_CHANGED
SUPPLIER_RELIABILITY_UPDATED
EXTERNAL_ORDER_RECORDED
DELIVERY_UPDATED
DELIVERY_RECEIVED
DELIVERY_DELAYED
DELIVERY_SHORT
DELIVERY_CANCELLED
ORDER_CYCLE_UPDATED
INVENTORY_LOT_EXPIRED
MANUAL_REASSESSMENT_REQUESTED
MANAGER_INSTRUCTION
PLAN_APPROVED
PLAN_REJECTED
PLAN_SUPERSEDED
```

## 6. Agent tools

Event conventions: timestamp is real recording time; payload includes effective_at or period_start/period_end in simulation time for time-sensitive inputs. SALES_UPDATED carries a complete incremental batch with source/batch_id and dish quantities. DAILY_UPDATE_SUBMITTED carries the final submission revision and cutoff. DELIVERY_RECEIVED references the received lot and actual quantity; DELIVERY_SHORT records the outstanding or cancelled remainder without applying the receipt again.

Trigger mapping: DAILY_UPDATE_SUBMITTED, PROMOTION_CREATED, PROMOTION_CHANGED, MANUAL_REASSESSMENT_REQUESTED, MANAGER_INSTRUCTION, and explicit supplier/disruption events request assessment. SALES_UPDATED always updates estimates, but requests the agent only on deterministic materiality. Ordinary receipt/order/cycle/expiry events persist state and use deterministic impact checks before requesting reassessment. Draft form edits emit no completed submission event. All event-driven mutations are applied once; special routes and event ingestion cannot both apply the same change.

The OpenClaw agent should eventually call:

```text
get_active_plan()
get_event_context()
forecast_demand()
calculate_requirements()
get_inventory_state()
get_supplier_options()
optimise_purchase_plan()
validate_plan()
create_plan()
request_approval()
record_agent_decision()
```

The agent must **not** directly change budgets, recipes, MOQ, supplier contracts, approval thresholds, invent stock, add unapproved suppliers, approve purchases, or bypass policy.

Every agent cycle ends with one outcome:

```text
KEEP_CURRENT_PLAN
REVISE_PLAN
REQUEST_HUMAN_APPROVAL
ESCALATE
```

For ESCALATE, escalation_reason is required and must be one of MISSING_REQUIRED_DATA, NO_FEASIBLE_SUPPLIER, UNRESOLVED_SHORTAGE, POLICY_VIOLATION, or TOOL_FAILURE. For other outcomes it is null. Known infeasibility is a completed assessment with escalation, not a technical run failure. A tool failure can be reported as ESCALATE/TOOL_FAILURE if the agent finishes with that outcome; an uncompleted attempt or timeout is FAILED with error metadata and does not fabricate an agent response.

REVISE_PLAN means a new feasible version was published and is pending approval. REQUEST_HUMAN_APPROVAL means an existing valid pending version needs review. KEEP_CURRENT_PLAN means no new recommendation is needed; see the no-purchase case in section 13. Backend validation checks the outcome against persisted state.

## 7. Backend API

Initial API surface:

```text
GET  /health

GET  /api/v1/plans/active
GET  /api/v1/plans/{id}
POST /api/v1/plans
POST /api/v1/plans/{id}/approve
POST /api/v1/plans/{id}/reject

GET  /api/v1/inventory
GET  /api/v1/suppliers
GET  /api/v1/promotions

POST /api/v1/events
GET  /api/v1/events
GET  /api/v1/audit
```

Keep deterministic engines inside the Python service for the MVP. No unnecessary microservices.

## 8. Shared error contract

```text
success: false

error:
  code
  message
  retryable
  details?
```

Important error codes:

```text
PLAN_VERSION_STALE
PLAN_INVALID
MISSING_REQUIRED_DATA
NO_FEASIBLE_SUPPLIER
POLICY_VIOLATION
OPTIMISATION_FAILED
FORECAST_FAILED
RESOURCE_NOT_FOUND
```

Unknown data stays **UNKNOWN**. Never invent missing operational values.

## 9. Audit / observability

Record:

```text
timestamp
event_id
plan_id
plan_version
actor
action
reason_summary
tools_called[]
result
```

Frontend should show concise event, tool, and decision summaries. Do not expose hidden chain-of-thought.

## 10. Week 1 integration target

Everyone builds toward one vertical slice:

```text
Synthetic POS
    ↓
Demand forecast
    ↓
Recipe/BOM conversion
    ↓
Inventory check
    ↓
Supplier options
    ↓
Purchase recommendation
    ↓
PLAN-v1 stored
    ↓
Displayed on frontend
```

Do not build extra features before this works end-to-end.

## 11. Golden rules

1. **Pydantic models are canonical.**
2. **Claude reasons; Python calculates.**
3. **Plans are versioned.**
4. **Material changes can invalidate plans.**
5. **Approvals belong to exact plan versions.**
6. **Unknown values are never guessed.**
7. **Simulate the restaurant world, not the decision logic.**
8. **Keep the MVP small and integrated.**


## 12. Agreed prototype operating scope

The backend-owner planning session refined the larger proposal as follows:

- One restaurant, 5 dishes, 8 ingredients, and 3 approved suppliers. One FastAPI service, PostgreSQL database, and agent process.
- Revised Q42: timestamped simulated sales batches deterministically update estimated inventory after the latest physical count without invoking Claude for every batch. Daily submission, promotions, supplier disruptions, material demand/stockout thresholds, and manual requests trigger agent assessment. No real POS integration is required; estimates describe only supplied activity with explicit coverage.
- Ingredients use positive interval_days and starting_date only. No weekday calendars, category inheritance, or reorder-point scheduling. Cycle decisions accept effective_at in simulation time, separate from real decided_at; omitted effective_at means real time.
- One bounded agent run executes at a time. Administrative edits may be blocked, but sales batches must remain ingestible. Proposed backend coordination uses state revisions and one coalesced pending assessment; publication/approval must revalidate against newer relevant state. Snapshots remain frozen; timeouts release restrictions and late results are rejected.
- Closing batch counts are authoritative. Timestamped post-count activity supports ESTIMATED inventory; forecast balances are PROJECTED. Partial sales and final daily totals must not be summed twice. Optional recorded waste is distinct from discrepancies and forecast waste.
- Agent-selected deterministic tools may produce emergency/contingency recommendations using approved suppliers. Existing external commitments are fixed inputs, not new purchase lines. A disruption can invalidate current operational reliance on an ordered version without deleting its approval or changing its purchase history.
- Every new recommendation requires manager approval and must be feasible. Approval does not execute purchases. The owner records actual external orders and receipts separately.
- Batches remain stored as EXPIRED starting the day after expiry in Singapore simulation time. The intraday scenario requires explicit event/arrival times; daily delivery defaults must not backdate emergency arrivals.
- PurchasePlan.id is stable across revisions and distinct from ingredient order cycles. Approvals carry plan_id and plan_version. Snapshot IDs resolve to preserved artifacts even if stored as typed JSON.
- One actionable version (PENDING_APPROVAL or APPROVED) is allowed across all plan identities. Publishing a replacement atomically supersedes the prior actionable version and emits PLAN_SUPERSEDED with previous status and replacement version ID. Existing external commitments survive.
- Frozen inputs use operational as_of and real known_at cutoffs. Immutable supplier observations and promotion/delivery event history preserve earlier facts; counts, receipts and sales corrections have recording timestamps. Do not read today's mutable rows when rebuilding a historical assessment. Legacy missing history is explicit missing data, not inferred historical values.
- Complete simulator sales batches may omit zero dishes. Corrections preserve source, batch_id and exact bounds. New source_plan_line_id purchase links require the current approved version, matching supplier/ingredient and a cumulative allocation within its quantity; deviations are unlinked actual purchases. Existing unchecked links remain labelled LEGACY_REFERENCE.

The approved scope is in BACKEND_SPEC.md. Current implementation and teammate integration gaps are recorded in BACKEND_HANDOVER.md. These contracts describe the target behaviour; consult the handover before assuming every integration is implemented. The outcome/reason split and lifecycle table below supersede the older ESCALATE_INSUFFICIENT_INFORMATION and VALID names.

Shared fee grouping, full cost/policy inputs, reliability and additional escalation reasons are proposed in SHARED_INTEGRATION_CONTRACT.md. Those proposals are not frozen until Aniq and Rudy agree; current development fixtures do not establish the real-engine acceptance results.


## 13. MVP lifecycle and supplier schema

### Plan status transitions

| From | To | Guard |
| --- | --- | --- |
| New feasible actionable recommendation | PENDING_APPROVAL | Deterministic validation passed; exact snapshot and version persisted. |
| PENDING_APPROVAL | APPROVED | Manager approves the exact current version; latest-state validation passes. |
| PENDING_APPROVAL | REJECTED | Manager rejects that version. |
| PENDING_APPROVAL or APPROVED | INVALIDATED | Deterministic materiality check finds a changed assumption requiring replanning, an unsafe/infeasible allocation, or a required input that can no longer be certified. |
| PENDING_APPROVAL or APPROVED | SUPERSEDED | A newer version replaces it without a material-validity failure being recorded. |

REJECTED, INVALIDATED, and SUPERSEDED are terminal for that version. Replanning creates a new version; it does not revive a terminal one. Do not overwrite INVALIDATED with SUPERSEDED and lose the causal state. Historical approvals and external commitments survive status changes. Idempotent repeat requests return the existing result, not a new transition. Superseding an approved version never transfers approval to its replacement.

VALID is removed from the MVP enum. A no-action assessment is a run result, not a no-approval plan status: KEEP_CURRENT_PLAN retains an existing certified version; when there is no plan and nothing to buy, record KEEP_CURRENT_PLAN with plan_id=null and reason NO_PURCHASE_REQUIRED. No artificial empty plan is needed. Known infeasibility uses ESCALATE and publishes no approvable candidate.

### SupplierOffer fields

All decision-relevant fields are explicit typed fields, never an unspecified feasibility object:

| Field | Meaning |
| --- | --- |
| id, supplier_id, ingredient_id | Stable identities; only approved seeded suppliers are eligible. |
| unit_price | Decimal SGD per ingredient base unit. |
| available_quantity | Decimal quantity available for NEW commitments as of observed_at; do not subtract existing orders from this value again. Planned allocations across delivery lines must respect this total unless explicit replenishment data exists. |
| moq, pack_size | Decimal quantities in the same base unit; minimum per purchase line and positive pack multiple for the prototype. |
| lead_time_minutes | Explicit nonnegative order-to-arrival duration, supporting intraday emergency supply. |
| order_cutoff | Explicit tagged value: NONE, LOCAL_TIME with an Asia/Singapore time, or UNKNOWN. NONE is not the same as unknown. |
| feasible_delivery_at | Explicit timezone-aware arrival timestamps for the demo horizon. Empty means no feasible slots; null means unknown. Arrival must also satisfy lead time and cutoff. |
| current_status | AVAILABLE, UNAVAILABLE, or UNKNOWN for new supply; shipment delay/short/cancel status belongs to incoming_deliveries. |
| recent_on_time_rate | Decimal fraction from 0 to 1, or null when unknown. |
| shelf_life_days_on_arrival | Guaranteed remaining usable days for planning, positive integer or null when unknown; actual received lots retain their actual expiry dates. |
| delivery_fee_sgd, emergency_fee_sgd | Explicit decimal per-line/shipment fees for the bounded prototype; zero is explicit. No hidden cross-line fee consolidation. |
| observed_at | Simulation timestamp of the reported offer data; audit creation time is separate. |

lead_time_minutes and feasible_delivery_at make the review's generic lead_time and delivery dates precise. A structured cutoff is a narrow typed union, not arbitrary feasibility JSON. Unknown inputs remain unknown; if a decision depends on them, escalate. The agent cannot assume supplier holiday closure or demand uplift from calendar dates alone.

### Sales reconciliation acceptance checks

Compare final daily dish totals with the latest non-duplicated batch revisions for the SAME dish and SAME business-day interval. With complete interval coverage, record MATCHED or a per-dish RECONCILIATION_DISCREPANCY with both totals and signed difference. With incomplete coverage, record INCOMPLETE_COVERAGE; do not label an expected partial-day difference a sales error. Explicit daily final totals are authoritative for historical forecasting, without adding intraday totals. Preserve batches and comparison evidence.

For the daytime MVP, the business-day sales interval runs from Singapore midnight through that day's submitted closing cutoff. Zero-sales batches may establish coverage before opening. Overnight business-day configuration is not implemented. Each closing revision preserves its comparison evidence; corrected final totals supersede earlier revisions in authoritative forecasting history.

Tests must cover a matching full day, a mismatching full day, incomplete coverage, duplicate batch retry, corrected batch, and a new physical count resetting the inventory baseline without a second deduction. A sales discrepancy is not inventory waste and does not prevent an independently valid physical count becoming the new stock baseline.
