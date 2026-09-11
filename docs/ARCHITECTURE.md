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

Initial event types:

```text
SALES_UPDATED
PROMOTION_CREATED
PROMOTION_CHANGED
INVENTORY_ADJUSTED
INVENTORY_WASTED
SUPPLIER_AVAILABILITY_CHANGED
SUPPLIER_PRICE_CHANGED
DELIVERY_DELAYED
DELIVERY_SHORT
DELIVERY_CANCELLED
MANAGER_INSTRUCTION
```

## 6. Agent tools

Agent-facing capabilities should eventually expose narrow adapters such as:

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
A mismatch returns `STATE_REVISION_STALE`, performs no plan mutation, and requires
a fresh read and a new Agent run; stale output is never replayed against new state.

## 6.1 Tool implementation status

The canonical Python contract freezes the following tool names and common
request/result/error envelopes. No adapter or numerical kernel is implemented in
the current repository checkout.

| Capability | Contract | Adapter | Kernel / backend workflow |
|---|---|---|---|
| `forecast_demand`, `compare_forecast_versions` | Defined | Missing | Missing |
| ingredient requirements, estimated inventory, expiry and stockout risk | Defined | Missing | Missing |
| supplier options, feasibility, allocation enumeration | Defined | Missing | Missing |
| purchase-plan optimisation and validation | Defined | Missing | Missing |
| approval requirement and human review | Defined | Missing | Missing |
| Agent decision recording | Defined | Missing | Missing |

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
