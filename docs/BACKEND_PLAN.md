# Backend prototype plan

Status: planning consolidated into approved specification #3 and tickets #4–#12 in rudybrrr/restock-ai. See BACKEND_SPEC.md for the synthesized implementation scope and BACKEND_TICKETS.md for the dependency graph. Publication is complete; implementation has not started.

## Confirmed scope

- One restaurant, 5 dishes, 8 ingredients, and 3 approved suppliers, using seeded synthetic data.
- Demonstrate initial planning, a promotion, a supplier shortage, and a demand spike. Simple forms/buttons inject events; actual decision logic produces recommendations.
- Approval records acceptance of a recommendation only. It does not create orders, incoming deliveries, or stock receipts. Simulated inventory and supplier updates arrive separately as events.
- Every new plan version requires manager approval. Approval is bound to the exact version reviewed; outdated or invalid versions cannot be approved.
- Start with reproducible local setup, then support one shared hosted demo with a simple manager login and a separate agent credential. No registration or multiple restaurant accounts.
- Keep the backend understandable for teammate handover. A minimal test interface is sufficient; the frontend teammate owns final UI design.

## Existing foundation and responsibilities

Keep one FastAPI service and one PostgreSQL database, as specified in ARCHITECTURE.md. Pydantic models define shared API contracts. Deterministic engines run inside the Python service.

The backend owner handles persistence, schemas, APIs, plan versions, approval enforcement, and audit records. The ML teammate owns forecasting, ingredient/inventory calculations, optimisation, and evaluations. The agent teammate owns OpenClaw orchestration and reasoning. Backend work must provide clear integration points for both.

The inspected code is a scaffold: a health endpoint, PostgreSQL Docker setup, an echo agent tool, and the frontend starter page. Business tables and APIs are not implemented yet.

## Relationship to the architecture contract

This plan narrows the larger proposal for the prototype. All new versions require approval, including ordinary purchases. Approval never implies order execution. The exact status transitions and endpoint/schema changes will be reconciled with ARCHITECTURE.md once agreed.

## Confirmed plan and storage design

- A revision replaces the recommendation for its horizon, preserving earlier versions. Existing external purchases are fixed inputs; new purchase lines recommend only additional uncommitted quantities. Contingency revisions can address risks after a normal purchase was arranged.
- Plan ingredient coverage according to ordering schedules and delivery timing, with daily demand and expiry calculations. This replaces the previously agreed fixed three-day window. Daily inventory updates do not imply daily purchasing.
- Use relational tables for menu items, ingredients, recipe items, inventory lots, suppliers, supplier offers, sales records, and promotions.
- Use separate tables for plan versions, purchase lines, approvals, events, and audit entries.
- Store frozen calculation inputs and outputs as JSON snapshots attached to each plan version. These preserve the recommendation's basis without separate tables for every intermediate calculation. Exact fields and relationships remain to be specified.
- Q42 revised: accept timestamped simulated sales batches throughout the simulated day. Deterministic recipe/inventory calculations update estimated inventory for each accepted batch without calling Claude. Completed daily submission, promotions, supplier disruptions, manual requests, and material demand/stockout thresholds request assessment. No real POS integration is required; the simulator supplies the data. Q43 emergency/contingency recommendations and Q44 per-ingredient intervals remain unchanged.
- Backend HTTP tool endpoints expose the ML teammate's Python functions. The agent teammate integrates polling and tool calls with OpenClaw; that integration contract must be communicated at handover.

## Confirmed daily inputs and schedules

- Each ingredient has interval_days and starting_date. Purchasing occasions repeat at that interval without shifting dates after late entry. Mark ingredient cycles ordered or skipped; approval alone does not mark them ordered. No weekday calendars, category inheritance, or reorder-point scheduling. Rice may remain fortnightly; other seeded ingredients can have different intervals.
- Use a seeded calendar of known events and manager-entered promotions with dates and affected dishes. The forecasting teammate determines demand effects from available history or explicit demo assumptions.
- Singapore public holiday dates come from https://www.mom.gov.sg/employment-practices/public-holidays (page checked 2026-09-10). The page lists 2025, 2026, and 2027 dates and annual calendar download links. Preserve relevant source notes; holiday dates alone do not establish restaurant demand uplift, restaurant closure, or supplier closure. The local seed/import mechanism remains a proposed implementation detail.
- Add manually recorded incoming deliveries with ingredient, quantity, supplier, expected arrival, and status. These represent externally arranged purchases, independently of plan approval. Recording receipt creates the batch; the closing count includes received deliveries and sets the remaining quantity. Do not add received quantities again after that count.

## Confirmed inventory and assessment behaviour

Batch decision: each received batch is a separate inventory-lot row with its expiry date and remaining quantity. Receiving is manually entered for simulation; barcode scanning is outside scope.

Daily input decision: staff provide closing stock counts per batch and dish sales. Show each batch's expiry date beside its count. Closing counts are authoritative; sales support demand forecasting and recipe-based estimates, not an additional deduction from the submitted count. Waste entry is not required and actual waste is not measured. A difference between estimated and counted stock is an unexplained discrepancy, not proven waste.

Assessment decision: daily submission and the explicit hybrid event triggers let the agent review stock trends and revise purchase recommendations. It can produce normal, emergency, or contingency recommendations through the same deterministic tools and approved suppliers. Every actionable new version requires manager approval.

Delivery decision: one ordering session may arrange multiple deliveries on different dates. Check demand and expiry against feasible timing; report infeasibility when supplier options cannot cover the period. Purchase lines include delivery timing, with precise simulation timestamps where the intraday emergency scene requires them.

Measurement boundary: retain daily observations, sales, and recorded receipts. Any expected-waste estimate is a model output, distinct from measured waste. The broader proposal's actual-waste benchmark cannot be claimed from these inputs alone; simulator ground truth, if available from the ML teammate, must be identified separately.

Run decision: allow one agent run at a time. Administrative edits may remain blocked during a run, but the revised Q42 needs sales-batch ingestion to remain available. Proposed reconciliation: store new batches with an incremented state revision while the run uses its frozen snapshot; revalidate before publication/approval and coalesce material changes into one pending reassessment. Never hold a transaction across an LLM call. A failed run offers manual retry; rejected recommendations wait for manager instructions. Previous plans retain their actual validity status. Exact revision/coalescing implementation remains a draft detail.

## Open design branches

Contract review resolution: use KEEP_CURRENT_PLAN / REVISE_PLAN / REQUEST_HUMAN_APPROVAL / ESCALATE, with a required typed reason for escalation. Remove VALID from the MVP plan statuses and use the definitive transition table in ARCHITECTURE.md section 13. Supplier fields and their units are explicit there; the expanded event enum is in section 5. Sales reconciliation distinguishes full-day disagreement from incomplete intraday coverage. These contract details supersede older draft shorthand.

External review: see [BACKEND_REVIEW_RESPONSE.md](BACKEND_REVIEW_RESPONSE.md). Revised Q42 uses ongoing deterministic estimates from simulated sales batches and materiality-triggered agent assessment. Q43-Q44 remain accepted. The earlier single-spike update and blanket run-time edit block are superseded for sales ingestion. Canonical fields/outcomes and event/materiality clarity are included in the design draft.

1. Exact plan identity/status transitions and API payloads.
2. Minimal authentication, deployment, verification, and handover steps.

The proposed database, API, and implementation sequence are in [BACKEND_DESIGN.md](BACKEND_DESIGN.md). That document is a review draft, not an implemented API contract.

## Confirmed input and exception rules

- Preserve expired batches and dated counts, marking them EXPIRED rather than deleting them. A batch is usable through its expiry date and expires the following day. Routine forecasts use daily steps and before-service delivery assumptions; the hybrid intraday scene requires explicit event/arrival times, not assumed morning arrival for an afternoon purchase. Historical counts support expiry-pattern analysis but are not automatically measured waste.
- Block approval when a recommendation has an unresolved shortage or fails deterministic validation. Show the issue and available options as an escalation. The owner can record an emergency delivery or correct inputs and request reassessment; approval is available only after validation passes.
- Require counts for all remaining batches and sales totals for all five dishes to complete a daily submission. Other hybrid assessments use the latest complete stocktake and explicitly timestamped subsequent activity; they do not require inventing a fresh physical count. Missing required data is not zero and blocks unsupported calculations.
- Each ingredient has a fixed unit: kg, litres, or pieces. Recipes, inventory, and supplier quantities use that unit. Costs use SGD. Automatic unit conversion is outside scope.
- Use a selectable simulation date, initially seeded before CNY, and a fixed starting order date. Forecasting and expiry calculations use the simulation date; audit timestamps record real time.
- When stock cannot cover demand until delivery, the agent invokes existing deterministic tools to evaluate feasible emergency purchases from approved suppliers. Publish a versioned, approvable recommendation only if the candidate covers the shortage and passes rules. Otherwise escalate. The owner places any actual order externally and records it through the existing incoming-delivery form, including quantity, supplier, expected arrival, and emergency designation. Subsequent assessments include it as committed expected supply.
- An emergency order is expected supply, not stock on hand. On the next assessment, check its quantity and arrival timing against the shortage. An entry alone does not establish that the shortage is resolved; late, insufficient, or cancelled deliveries must not falsely clear it. Actual receipt follows the existing batch and closing-count flow.
- After external ordering, preserve historical approval and purchase commitments. A disruption may invalidate that plan for current operational use and produce a contingency revision for its residual horizon. Existing commitments are fixed calculation inputs; additional recommendation lines must not re-order them. Owner-entered delay/cancellation/receipt updates remain audited facts; the agent cannot silently rewrite commitments.
- Emergency orders use the same three approved suppliers. Supplier onboarding is outside the prototype.
- The owner may update delivery arrival dates, cancel a delivery, or record actual received quantity and expiry date. For a short delivery, explicitly record whether the remainder is still expected or cancelled.
- Generated recommendations are read-only. The manager can reject with instructions and rerun. Actual external purchases are entered separately and may differ from the recommendation.
- Seed dishes, recipes, ingredients, suppliers, and holiday dates. Provide simple input forms for daily counts/sales, promotions, supplier prices/availability, and external orders/deliveries. Setup changes can be made in seed files.

## Workflow explanation

Staff supply dated per-batch closing stock counts, dish sales, and known changes such as promotions or supplier availability, then select "Complete daily update & run planning". Stock counting is outside ReStock's automation scope.

For a planning run, the backend supplies a consistent snapshot of operational inputs. The agent investigates upcoming demand and supply changes and selects the relevant deterministic tools. Forecasting estimates daily dish sales using history and explicitly supplied future-event information; recipes convert these to ingredient demand.

For each ingredient, ordering opportunities and feasible delivery dates determine the coverage period. Inventory calculations project stock consumption and expiry over time, including any explicitly recorded incoming deliveries. They must distinguish counted stock from projected stock and identify shortages before a new delivery can arrive.

The optimiser calculates feasible purchase quantities and supplier choices, respecting availability, pack sizes, minimum quantities, timing, and applicable policies. The backend validates and stores the complete recommendation with its inputs, calculation outputs, and concise explanation. The manager approves or rejects that exact version; approval does not place an order.

For example, a fortnightly rice order whose coverage overlaps CNY may need a larger quantity if the forecast supports increased demand. The system must not automatically assume every restaurant experiences a holiday surge or present a forecast as a measured stock quantity.

The backend owns persistence, access checks, tool endpoints, versioning, and approval enforcement. Forecasting and optimisation remain the ML teammate's implementation; investigation and tool selection remain the agent teammate's implementation.

Resolve the prerequisites before specifying dependent details. Record decisions here as they are agreed; create an ADR only for a consequential trade-off that needs a separate explanation.
