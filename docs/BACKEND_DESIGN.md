# Backend design draft

Status: approved as the basis of specification #3 and implementation tickets #4–#12 in rudybrrr/restock-ai. The consolidated BACKEND_SPEC.md and GitHub spec capture the implementation scope; the descriptions below are not claims of existing code. The user approved API-level tests with PostgreSQL and the ticket breakdown.

## Shape and ownership

One FastAPI service, one PostgreSQL database, and one external OpenClaw agent process. Use the existing SQLAlchemy, Alembic, and Pydantic dependencies. The agent accesses data and computation through HTTP, never direct database writes. The frontend uses the same API; Pydantic/OpenAPI is the shared contract.

Keep routes thin and place transactions and rules in ordinary service functions. ML-owned Python functions receive typed input snapshots and return typed results, without owning database sessions. No additional microservices, Redis, message broker, repository abstraction framework, or separate forecast database.

## Proposed tables

| Tables | Purpose and key fields |
| --- | --- |
| menu_items, ingredients, recipe_items | Seeded dishes and recipes. Ingredient has fixed unit, interval_days, starting_date, and seeded safety-stock/storage settings; recipe links dish to ingredient with quantity per portion. |
| suppliers, supplier_offers | Approved suppliers and explicit typed fields defined in ARCHITECTURE.md section 13: price, new-order availability, MOQ, pack size, lead_time_minutes, typed order_cutoff, feasible_delivery_at timestamps, current_status, recent_on_time_rate, remaining shelf life, shipment fees, and observed_at. No unspecified feasibility JSON. |
| holidays, promotions | Source-backed holiday name/date/notes; manager-entered promotion dates and affected dishes. A holiday does not itself specify a demand multiplier. |
| inventory_lots | Ingredient, source delivery, received date, expiry date, initial quantity, latest counted quantity and count date. One row per received batch. |
| daily_updates, stock_counts, sales_records | Daily submission header with date/revision/status; batch quantities and dish sales. Preserve revisions rather than destroying earlier observations. |
| order_cycles | Ingredient, scheduled order date and OPEN/ORDERED/SKIPPED state. Unique ingredient/date; dates follow that ingredient's interval_days and starting_date. |
| purchase_plans | Stable plan_id, planning horizon and current version reference. A plan can cover several ingredients with different cycles; it is not the identity of one ingredient's order cycle. |
| incoming_deliveries | One ingredient and scheduled shipment per row: supplier, expected quantity/date, emergency flag, cycle reference if applicable, pending/cancelled/completed status. Partial receipts create lots and reduce the outstanding quantity; explicit cancellation closes the remainder. |
| planning_runs | Latest stocktake revision, trigger event, simulation as_of, target plan, input snapshot, status, outcome, error, timestamps, attempt identity and bounded deadline. |
| plan_versions, purchase_plan_lines | Plan ID, version number, run, status, frozen calculation results and costs. Lines record ingredient, supplier, quantity, unit price, cycle where applicable, emergency designation, and planned arrival. Frozen inputs distinguish existing commitments from newly recommended purchases. |
| approvals | Exact plan-version reference, decision, manager identity, time, and optional reason. |
| events, audit_entries | Input-change records and concise action/tool summaries. These are not an event-sourced database; ordinary tables hold current state. |

Use foreign keys and uniqueness constraints, including plan_id plus version and daily-update revision plus batch/dish. Quantities and money use decimal storage and typed API values. Missing operational inputs remain null/unknown, never zero. Use real UTC audit timestamps and explicit Singapore simulation timestamps for restaurant calculations.

There is intentionally no real purchase-order or payment subsystem. Incoming-delivery records capture externally arranged purchases, including emergency purchases. Multiple rows can represent a fortnightly order's staggered shipments.

## Stock consistency

Receiving records actual quantity and expiry and creates a lot. Daily closing counts set the authoritative remaining quantity for each batch, including that day's receipts. Never subtract recipe consumption again from those counts. Keep dish sales independently for forecasting and estimated usage.

Lots created by receipts link back to the incoming delivery. A physical closing count includes that day's receipts. Between counts, only receipts after the count are added to estimated stock, and only outstanding quantities remain future supply. Received quantities must not also appear as future supply. Daily submission verifies that all batches requiring a count and all five dishes are present, with explicit zero entries allowed.

Revised Q42 input proposal: the simulator supplies sequential non-overlapping timestamped sales batches with source, batch_id/idempotency key, period_start, period_end, and per-dish quantities sold in that period. Quantities are incremental for that period, not cumulative-to-date totals. Each batch is complete for its interval; omitted dishes mean zero only under this explicit complete-batch contract. A zero-sales interval still establishes coverage. Require contiguous coverage from the latest stocktake to claim an estimate current through time T; otherwise expose the gap. Reject conflicting duplicate IDs and overlapping periods; identical retries return the original result. Corrections explicitly replace a referenced batch and recompute estimates, rather than applying a second deduction. Store batches as SALES_UPDATED events with validated payloads; no POS streaming infrastructure is needed.

Each accepted batch invokes deterministic recipe conversion and inventory estimation, not Claude. Cache estimated balances separately from immutable physical counts or derive them from the baseline and accepted events; in either case preserve an as_of and source revision. Daily final totals supersede that day's batch aggregates for historical forecasting, not add to them. A new closing stocktake is a new authoritative baseline: activity at or before its cutoff must not be deducted again. For the prototype, require a batch boundary at the stocktake cutoff; do not arbitrarily prorate a batch spanning that cutoff.

The ML teammate supplies deterministic materiality checks for forecast-versus-sales deviation and stockout/safety-stock risk. Backend invokes those checks after each batch and records their result. Only a material decision change requests agent reassessment; use a persisted outstanding-assessment marker to coalesce repeated threshold hits. Backend owns no independent competing forecast/threshold policy. Exact thresholds are seeded, documented ML inputs, not numbers invented by the agent. Daily submissions, promotions, supplier disruptions, and manual requests can independently request assessment.

Estimated inventory at time T = latest physical count + actual receipts after that count - BOM-derived sales usage after that count - explicitly recorded waste after that count +/- explicit adjustments after that count. Project usage across usable lots by earliest expiry; this is an estimate and must not overwrite physical counts. Attach coverage and as_of to every estimate. When inputs do not cover the period up to T, expose that gap and do not certify unsupported current stock. PROJECTED inventory additionally uses future demand and expected deliveries; it is not a measurement.

Historic counts remain available for trend analysis. Unexplained differences are discrepancies, not measured waste. Expiry calculations may exclude expired quantities without silently recording them as measured disposal.

Confirmed refinement: persist EXPIRED status when a lot crosses the agreed expiry boundary in simulation time; retain the lot, expiry date, and dated count history. The usable-inventory query must also check expiry dates so an unprocessed status update cannot make expired stock available. Any observed remainder can support expiry-pattern analysis, but an older count must not be labelled actual waste at expiry. How replay resets persisted statuses will be included in demo reset handling.

## Plan identity and lifecycle proposal

A purchase plan identifies a planning horizon and has immutable stored revisions numbered within its stable plan_id. It can cover ingredient-specific cycles together. A contingency is a revision for the remaining horizon of that plan; a new normal horizon gets a new plan identity. Purchase content and snapshots never change after publication; status changes and decisions are audited.

Public plan_id is the purchase_plans identity, plan_version is its increasing revision number, and version_id is the internal revision UUID. Approval payloads explicitly include plan_id and plan_version even if the route uses version_id. Ingredient-specific cycles and plan identities are separate now that a recommendation can span several schedules and post-order contingencies.

Expose the architecture contract fields explicitly: id (public plan_id), version, status, forecast_id, inventory_snapshot_id, trigger_event_id, invalidation_reason, requires_approval, approval_reason, created_at, lines, total_purchase_cost, expected_waste_cost, expected_stockout_cost, delivery_cost, emergency_penalty, and total_expected_cost. Forecast and inventory snapshot IDs identify typed immutable artifacts in the run's stored JSON and must resolve to those exact artifacts. Do not use dummy IDs or mutable current-state references. Separate intermediate-result tables are not required just to provide IDs.

The definitive transition table is ARCHITECTURE.md section 13. New feasible actionable recommendations are PENDING_APPROVAL. From PENDING_APPROVAL allow APPROVED, REJECTED, INVALIDATED, or SUPERSEDED under the documented guards; from APPROVED allow INVALIDATED or SUPERSEDED. REJECTED, INVALIDATED, and SUPERSEDED are terminal for that version. New versions never inherit approval. Preserve invalidation rather than overwriting it with supersession. VALID is removed from the MVP enum. A no-purchase assessment is a run outcome, not an artificial approvable plan.

Input changes block approval until assessment. If the agent keeps the same recommendation, deterministic validation must certify it against the latest inputs; record that reassessment with its run snapshot, leaving the original snapshot intact. If the recommendation changes or is infeasible, the old version cannot be approved. An ordered cycle preserves the historically accepted recommendation and delivery commitments; new risk assessments do not rewrite them.

Approval and marking ingredient cycles ordered are separate manager actions. A cycle can be skipped when no purchase is needed. External order entry can differ from a recommendation and must preserve actual delivery quantities. Link actual commitments to the source version/line where available. Already committed quantities enter the optimiser as fixed supply, not new purchase lines. A contingency version replaces the remaining uncommitted recommendation, not the external purchases. Supplier disruption can INVALIDATE an ordered version for current operational use while its historical approval and commitments remain preserved. Agent tools never alter those commitments.

## Hybrid agent run

1. Accepted daily submission, promotion submission, supplier disruption (including delay/short/cancelled delivery), material threshold crossing from a sales batch, or manual reassessment requests a run. Sales batches always persist and update deterministic estimates, but do not each request Claude. State/event/revision writes and the request marker are atomic; claim freezes the inputs at a recorded state revision. Ordinary daily form drafts do not trigger calls. Event-triggered runs use the latest completed count and known subsequent activity; they do not demand a fresh stocktake. Missing required input produces an explicit escalation rather than an invented balance.
2. The single agent polls a claim endpoint. Backend atomically changes QUEUED to RUNNING and returns the snapshot/run ID. Repeated claims must not start a second run.
3. Agent selects forecast, requirements, inventory, supplier, optimisation, and validation tools. Tools use the run snapshot, not independently changing live data.
4. Agent submits exactly one outcome: KEEP_CURRENT_PLAN, REVISE_PLAN, REQUEST_HUMAN_APPROVAL, or ESCALATE. ESCALATE requires escalation_reason: MISSING_REQUIRED_DATA, NO_FEASIBLE_SUPPLIER, UNRESOLVED_SHORTAGE, POLICY_VIOLATION, or TOOL_FAILURE; other outcomes have a null escalation_reason. A revised feasible version is PENDING_APPROVAL. Requesting review of an existing pending version uses REQUEST_HUMAN_APPROVAL. A known infeasible calculation is a completed escalation, not a failed attempt. A run that crashes or times out is FAILED without a fabricated agent outcome. Backend validates outcomes and persists the result/plan atomically. Approval is always a manager action.
5. Mark the run SUCCEEDED or FAILED and release the edit restriction. Use a bounded deadline so a crashed agent cannot lock the app indefinitely. Manual retry creates a new attempt; late results from expired attempts are rejected. No long-lived database transaction spans an LLM call.

Proposed concurrency refinement for revised Q42: the database enforces one RUNNING agent attempt. Sales batches remain accepted during it and increment the operational state revision. Administrative mutations may still return RUN_IN_PROGRESS. Use a single pending-assessment marker with covered event IDs/revision to coalesce material follow-ups. Frozen tool inputs stay unchanged. Before publishing or approving, deterministic checks must validate against current inputs and an atomic revision check must confirm those inputs remain current. If relevant newer data cannot be certified, reject candidate activation and request reassessment; preserve the old run as historical evidence. Do not blindly approve an old candidate because its run finished successfully. No long transaction spans the LLM call. Timeouts and late-attempt rejection remain required. A separate broker or unrestricted concurrent agent execution is unnecessary.

## Proposed API surface

All business routes use /api/v1. Exact request/response models will be defined in Pydantic before teammates integrate.

| Area | Proposed routes |
| --- | --- |
| Access | POST /auth/login, POST /auth/logout; GET /health |
| Daily input | GET /daily-updates/{date}, PUT /daily-updates/{date}, POST /daily-updates/{date}/submit |
| Reference/state | GET /menu-items, /ingredients, /inventory, /suppliers, /holidays, /promotions |
| Changes | POST/PATCH /promotions; PATCH /supplier-offers/{id}; POST /events for a validated, manager-authorised simulated sales update or explicit operational event |
| External purchases | POST /incoming-deliveries; PATCH /incoming-deliveries/{id}; POST /incoming-deliveries/{id}/receive |
| Cycles | GET /order-cycles; POST /order-cycles/{id}/mark-ordered; POST /order-cycles/{id}/skip |
| Plans | GET /plans/active, /plans/{version_id}; POST /plans/{version_id}/approve or /reject |
| Runs | POST /runs for manual assessment; GET /runs/{id}; POST /runs/{id}/retry; agent-only POST /runs/claim and /runs/{id}/complete |
| Computation | Agent-only POST /tools/forecast, /requirements, /inventory, /supplier-options, /optimise, /validate |
| Timeline | GET /events, /audit |

Use the existing architecture error envelope. Add explicit conflict codes for incomplete daily input, a run in progress, and expired attempts. Stale approval returns a conflict and the current version reference. Agent credentials cannot call manager approval, supplier mutation, receipt, or cycle-ordering endpoints.

Every operational mutation stores Event {id, type, timestamp, source, payload} atomically with its relational state change, including mutations through specialised endpoints. ARCHITECTURE.md section 5 is the canonical expanded enum, including DAILY_UPDATE_SUBMITTED, DELIVERY_RECEIVED, and MANUAL_REASSESSMENT_REQUESTED. Audit entries explicitly preserve timestamp, event_id, plan_id, plan_version, actor, action, reason_summary, tools_called, and result. This does not imply event sourcing or automatic agent invocation for every event.

Approval blocking pending assessment is distinct from invalidation. Deterministic validation/impact checks record affected assumptions, validation result, materiality, and invalidation reason. A harmless relevant change can certify KEEP_CURRENT_PLAN against a new run snapshot without mutating the original recommendation. A material change invalidates it. ML owns calculations, the agent selects investigations, and the backend persists and enforces the result; no separate materiality microservice is needed.

Inventory responses label PHYSICAL, ESTIMATED, and PROJECTED balances with timestamps, input coverage and provenance. Simulated timestamped batches support ongoing intraday estimates; ordinary daily totals alone do not. Optional known waste from staff or simulator is an explicit event with quantity, effective time, and source. Deductions apply only after the stocktake boundary and only once. Staff waste entry is never required; unknown discrepancies are not waste. This is a simulated POS input contract with deterministic monitoring, not a production POS integration.

## Minimal test interface

Daily-entry form, current recommendation with approve/reject, incoming-delivery form/list, and a concise run/timeline view. Show simulated date, last counted date, and expected delivery separately. Frontend teammate owns the final layout. Keep credentials out of client-delivered agent configuration.

## Implementation order and handover

1. Agree typed models and example payloads; reconcile ARCHITECTURE.md with the final scope.
2. Add database configuration, Alembic migrations, and reproducible seed/reset commands for the demo database.
3. Implement counts, sales, receipts, cycles, and read endpoints. Verify receipt/count consistency before agent integration.
4. Implement snapshots, run status, plan persistence, approval enforcement, and audit entries.
5. Connect ML functions through typed tool endpoints; integrate the agent's claim/tool/complete loop. Temporary integration fixtures must be clearly labelled and replaced by real calculations for the demo.
6. Add the small test interface and verify local startup, then deploy the shared demo using the agreed credentials.

Handover files: environment-variable example, startup/migration/seed instructions, API examples, sample agent run, owner map, and one reproducible CNY scenario including an emergency delivery.

Focused checks: counts do not double-deduct sales; receipt retries do not duplicate stock; partial receipts do not double-count expected supply; incomplete input blocks submission; stale versions cannot be approved; agent cannot approve; failed/expired runs release restrictions and reject late writes; emergency arrival timing determines whether the projected shortage is covered; ordered-cycle history stays intact. Add lifecycle/permission tests for every allowed transition and rejection of terminal-state revival. Test outcome/reason combinations and unknown supplier inputs.

Sales reconciliation tests compare batch sums and daily totals per dish over the same day with complete coverage. Record MATCHED or RECONCILIATION_DISCREPANCY with both totals and signed delta. Partial coverage instead records INCOMPLETE_COVERAGE. Include duplicate retries and corrected batches; only the latest accepted batch revision contributes. Final daily totals are used once for historical forecasting, and the new physical count becomes the inventory baseline even if sales totals differ. Do not convert sales discrepancy into waste or another stock deduction.

## Remaining product decisions

Q42 uses deterministic intraday estimates from successive simulated sales batches, with materiality-triggered assessment. Q43-Q44 remain accepted. The four review contract gaps are resolved in ARCHITECTURE.md: outcome/reason separation, definitive statuses, explicit supplier fields, and expanded events. Batch boundaries and concurrency conventions remain documented implementation proposals for final review. Hosting provider selection can remain deferred until the local vertical slice works. No application code has been implemented by this planning work.

Expiry convention: a batch is usable through its expiry date, then EXPIRED at the start of the next Singapore simulation day. Retain batches and counts. Routine demand calculations can use daily steps; the demand-spike scene uses explicit simulation times and emergency arrival timestamps. An afternoon emergency purchase cannot be assumed to have arrived that morning. ML's stockout estimate needs remaining-service demand/time information from the seeded scenario, not just a daily total.

Feasibility rule: unresolved shortages and failed validation block approval. Display the issue as an escalation; the owner may enter an external emergency delivery and reassess. Recording a delivery does not itself prove feasibility.

## Proposed implementation conventions for final review

- Keep seeded catalog data and holiday dates in version-controlled seed files. Load holiday dates into the database with source metadata. Do not fetch the MOM website during a planning run.
- One manager account configured through environment settings, with password verification and a secure HTTP-only session cookie for the hosted demo. Use a separate environment-configured bearer credential for the agent. No user-management tables or registration UI. Enforce permissions in the backend.
- Use ordinary synchronous SQLAlchemy sessions with short transactions. Backend constraints enforce one running agent attempt plus a coalesced pending request; a configured deadline releases an abandoned attempt on the next status/claim/write request. Use a ten-minute initial deadline, adjustable after integration; late completions are rejected.
- Expose generated API documentation for teammate testing. Use JSON seed files and a single documented seed command; reset only the designated demo database. No tests call external AI services by default.
- Keep Python code in db.py, models.py, schemas/, routers/, services/, and engines/. Put ML-owned calculations in engines/ and keep business persistence in services/. Add folders only as the implementation needs them.
- Test the local workflow first. Hosting and provider-specific setup are a later deployment step, not a dependency for starting the backend implementation.
