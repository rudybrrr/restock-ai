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
VALID
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
ESCALATE_INSUFFICIENT_INFORMATION
```

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
