# ReStock Architecture Contract

The detailed Agent authority, orchestration, failure, and evaluation design is
maintained in [AGENTS_PLAN.md](AGENTS_PLAN.md). This document defines the shared
system boundary and must use the same canonical backend contracts.

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

The MVP uses a branching, version-bound lifecycle:

```text
PENDING_APPROVAL
-> APPROVED | REJECTED | INVALIDATED | SUPERSEDED

APPROVED
-> INVALIDATED | SUPERSEDED
```

Every new actionable recommendation is created as `PENDING_APPROVAL`. `REJECTED`
records an explicit manager decision, `INVALIDATED` records a material assumption
failure, and `SUPERSEDED` records replacement by a newer version without asserting
that the older version became unsafe. `VALID` has no distinct MVP meaning and is
not a canonical status.

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
```

## 6. Agent tools

Event conventions: timestamp is real recording time; payload includes effective_at or period_start/period_end in simulation time for time-sensitive inputs. SALES_UPDATED carries a complete incremental batch with source/batch_id and dish quantities. DAILY_UPDATE_SUBMITTED carries the final submission revision and cutoff. DELIVERY_RECEIVED references the received lot and actual quantity; DELIVERY_SHORT records the outstanding or cancelled remainder without applying the receipt again.

Trigger mapping: DAILY_UPDATE_SUBMITTED, PROMOTION_CREATED, PROMOTION_CHANGED, MANUAL_REASSESSMENT_REQUESTED, MANAGER_INSTRUCTION, and explicit supplier/disruption events request assessment. SALES_UPDATED always updates estimates, but requests the agent only on deterministic materiality. Ordinary receipt/order/cycle/expiry events persist state and use deterministic impact checks before requesting reassessment. Draft form edits emit no completed submission event. All event-driven mutations are applied once; special routes and event ingestion cannot both apply the same change.

Agent-facing capabilities should expose narrow adapters such as:

```text
get_active_plan()
get_event_context()
forecast_demand()
compare_forecast_versions()
calculate_ingredient_requirements()
calculate_estimated_inventory()
calculate_expiry_risk()
calculate_stockout_risk()
get_supplier_options()
check_supplier_feasibility()
enumerate_supplier_allocations()
optimise_purchase_plan()
validate_purchase_plan()
get_approval_requirement()
request_human_review()
record_agent_decision()
```

These are typed adapters over backend or Decision Engine implementations, not
independent calculations. A listed contract does not imply that its adapter or
kernel has been implemented. The agent must **not** directly create or mutate plan
rows, change budgets, recipes, MOQ, supplier contracts or approval thresholds,
invent stock, add unapproved suppliers, approve purchases, or bypass policy.

Every agent cycle ends with one outcome:

```text
KEEP_CURRENT_PLAN
REVISE_PLAN
REQUEST_HUMAN_APPROVAL
ESCALATE
```

`ESCALATE` carries one canonical reason:

```text
MISSING_REQUIRED_DATA
NO_FEASIBLE_SUPPLIER
UNRESOLVED_SHORTAGE
POLICY_VIOLATION
CALCULATION_INCOMPLETE
TOOL_FAILURE
CALL_LIMIT_REACHED
```

The optional detail `SEARCH_LIMIT_REACHED` applies to
`CALCULATION_INCOMPLETE`. It means bounded search ended inconclusively;
`NO_FEASIBLE_SUPPLIER` means deterministic search established infeasibility, and
`TOOL_FAILURE` means execution itself failed.

Agents submit a typed completion with a captured state revision and evidence
references. Backend alone compares the revision, validates the candidate, applies
the plan transition, persists the immutable version, and records audit history.
`captured_state_revision` is the opaque revision read before Agent reasoning.
Publication compares it with the current authoritative revision before any write.
A mismatch returns a canonical stale-state error, performs no plan mutation, and requires
a fresh read and a new Agent run; stale output is never replayed against new state.

At the Agent boundary, `REVISE_PLAN` requests publication of a referenced candidate.
Backend accepts that outcome only after the candidate passes persisted-state validation
and a new immutable version is published as `PENDING_APPROVAL`.
`REQUEST_HUMAN_APPROVAL` requests review of an existing valid pending version.
`KEEP_CURRENT_PLAN` means no new recommendation is needed; see the no-purchase case
in section 13. Known infeasibility is a completed assessment with escalation, not a
technical run failure. An uncompleted attempt or timeout is `FAILED` with error
metadata and does not fabricate an Agent response.

## 6.1 Tool implementation status

The canonical Python contract freezes the following tool names and common
request/result/error envelopes. Backend and Decision Engine implementation status
must be verified from the concrete service code and tests; a listed contract alone
does not prove that an adapter or kernel exists.

Future adapters must replace their generic `parameters` payload with the owning
kernel's canonical typed inputs when those interfaces land. They must not add a
second implementation of forecasting, inventory, supplier, optimisation,
validation, or policy logic.

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
STATE_REVISION_STALE
PLAN_INVALID
MISSING_REQUIRED_DATA
NO_FEASIBLE_SUPPLIER
UNRESOLVED_SHORTAGE
CALCULATION_INCOMPLETE
SEARCH_LIMIT_REACHED
POLICY_VIOLATION
OPTIMISATION_FAILED
FORECAST_FAILED
AGENT_OUTPUT_INVALID
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
state_revision
actor
action
agent_run_id
specialist_call_id
tool_call_id
evidence_refs[]
requested_outcome
plan_transition
approval_action
final_outcome
reason_codes[]
summary
```

Audit history is append-only and business-level. Frontend should show concise
trigger, tool, validation, transition, approval, and outcome summaries. Do not
persist or expose hidden chain-of-thought.

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
- Ingredients use interval_days and starting_date only. No weekday calendars, category inheritance, or reorder-point scheduling.
- One bounded agent run executes at a time. Administrative edits may be blocked, but sales batches must remain ingestible. Proposed backend coordination uses state revisions and one coalesced pending assessment; publication/approval must revalidate against newer relevant state. Snapshots remain frozen; timeouts release restrictions and late results are rejected.
- Closing batch counts are authoritative. Timestamped post-count activity supports ESTIMATED inventory; forecast balances are PROJECTED. Partial sales and final daily totals must not be summed twice. Optional recorded waste is distinct from discrepancies and forecast waste.
- Agent-selected deterministic tools may produce emergency/contingency recommendations using approved suppliers. Existing external commitments are fixed inputs, not new purchase lines. A disruption can invalidate current operational reliance on an ordered version without deleting its approval or changing its purchase history.
- Every new recommendation requires manager approval and must be feasible. Approval does not execute purchases. The owner records actual external orders and receipts separately.
- Batches remain stored as EXPIRED starting the day after expiry in Singapore simulation time. The intraday scenario requires explicit event/arrival times; daily delivery defaults must not backdate emergency arrivals.
- PurchasePlan.id is stable across revisions and distinct from ingredient order cycles. Approvals carry plan_id and plan_version. Snapshot IDs resolve to preserved artifacts even if stored as typed JSON.

The approved scope is in BACKEND_SPEC.md. Current implementation and teammate integration gaps are recorded in BACKEND_HANDOVER.md. These contracts describe the target behaviour; consult the handover before assuming every integration is implemented. The outcome/reason split and lifecycle table below supersede the older ESCALATE_INSUFFICIENT_INFORMATION and VALID names.


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
