# ReStock backend: inventory estimates, adaptive purchase plans, and version-bound approval

Published as [GitHub specification #3](https://github.com/rudybrrr/restock-ai/issues/3), labelled ready-for-agent. The implementation breakdown contains nine approved tickets with native blocking relationships. The spec and testing boundary are approved; implementation has not started.

## Problem Statement

Restaurant managers need to decide which ingredients to buy, how much, from which approved suppliers, and when. Their latest physical count can become outdated as sales occur, and a promotion, supplier shortage, or delayed delivery can make an earlier purchasing recommendation unsuitable.

The hackathon team currently has a FastAPI health endpoint, a PostgreSQL development container, an echo-only agent plugin, and a frontend starter. It needs a small, dependable backend that teammates can integrate with and take over. The backend must preserve trustworthy inputs, expose deterministic tools to the agent, maintain auditable purchase-plan versions, and prevent approval of stale or infeasible recommendations.

## Solution

Build one FastAPI service backed by one PostgreSQL database for a seeded restaurant with five dishes, eight ingredients, and three approved suppliers. Staff submit closing batch counts and dish sales daily. Timestamped simulated sales batches update estimated inventory between counts using deterministic recipe calculations, without invoking Claude for every batch.

Daily submission, promotions, supplier disruptions, material demand/stockout changes, and manual requests initiate agent assessment. The agent investigates through typed tools; the ML/decision engine forecasts and calculates feasible normal, emergency, or contingency purchase recommendations. Ingredient-specific ordering intervals and delivery timing determine coverage.

The manager reviews an immutable version and approves or rejects it. Approval never places an order. Actual external purchases and incoming deliveries are recorded separately and become fixed inputs to later calculations, preventing double-ordering. A small test interface and documented API allow teammates to verify connectivity and the complete workflow.

## User Stories

1. As a backend teammate, I want one documented service and database setup, so that I can start and understand the prototype quickly.
2. As a frontend teammate, I want canonical API models and interactive documentation, so that I do not invent incompatible request or response schemas.
3. As an agent teammate, I want authenticated HTTP tools, so that the agent can investigate without direct database access.
4. As an ML teammate, I want typed snapshots and result contracts, so that my calculations remain independent of database sessions.
5. As a manager, I want seeded dishes, recipes, ingredients, and approved suppliers, so that I can demonstrate the workflow without building a catalog.
6. As a manager, I want each received batch stored separately with quantity and expiry, so that different expiry dates are not merged.
7. As a manager, I want to submit remaining quantity per batch at closing, so that actual counts establish the next inventory baseline.
8. As a manager, I want explicit zero counts and sales distinguished from missing entries, so that the system does not guess missing information.
9. As a manager, I want daily dish sales stored independently of closing counts, so that the system learns demand without deducting the same usage twice.
10. As a simulator operator, I want timestamped sales batches, so that I can demonstrate intraday consumption without connecting a real POS system.
11. As a simulator operator, I want safe retries and explicit batch corrections, so that duplicate submissions do not consume stock twice.
12. As a manager, I want physical, estimated, and projected stock labelled with their times and coverage, so that I understand which quantities are measured.
13. As a manager, I want estimated consumption allocated to usable batches by earliest expiry, so that expiry calculations are consistent.
14. As a manager, I want expired batches excluded from usable stock but retained in history, so that their counts can inform future purchasing.
15. As a manager, I want optional known waste and unexplained discrepancies kept distinct, so that the system does not fabricate waste measurements.
16. As a manager, I want daily sales totals reconciled against intraday batches, so that disagreements and incomplete coverage remain visible.
17. As a manager, I want an interval and starting date per ingredient, so that daily, weekly, and fortnightly purchasing can coexist.
18. As a manager, I want multiple scheduled deliveries within a purchase, so that perishable ingredients need not last the entire ordering interval.
19. As a manager, I want upcoming holidays and promotions included in forecasting inputs, so that planning considers relevant future events.
20. As a manager, I want supplier prices, available quantities, and delivery constraints exposed explicitly, so that recommendations can be checked.
21. As a manager, I want promotions and supplier disruptions to request reassessment, so that changed assumptions are not ignored.
22. As a manager, I want routine sales processed without an AI call unless their impact is material, so that the prototype stays responsive and inexpensive.
23. As a manager, I want purchase quantities and costs calculated by deterministic tools, so that the agent cannot invent authoritative arithmetic.
24. As a manager, I want a concise explanation and cost breakdown for each recommendation, so that I can understand the decision.
25. As a manager, I want exact-version approval, so that an old browser tab cannot approve a changed plan.
26. As a manager, I want invalidated, superseded, and rejected versions distinguished, so that history explains what happened.
27. As a manager, I want infeasible or incomplete recommendations escalated, so that I cannot approve an unresolved shortage.
28. As a manager, I want to reject with instructions and request another attempt, so that rejection does not start an endless replanning loop.
29. As a manager, I want to record the purchases I actually arranged, so that accepted recommendations are not mistaken for orders.
30. As a manager, I want delays, cancellations, partial receipts, and remaining expected quantities recorded, so that future supply is accurate.
31. As a manager, I want the agent to recommend emergency purchases from approved suppliers, so that I can address a predicted shortage.
32. As a manager, I want contingency revisions to preserve existing commitments, so that a disruption does not cause duplicate purchases.
33. As a manager, I want an emergency delivery checked against shortage timing and quantity, so that entering an order does not falsely clear a risk.
34. As a manager, I want failed assessments to show an error and offer retry, so that an unavailable agent does not permanently lock the app.
35. As a simulator operator, I want sales accepted while the agent is running, so that inventory estimates remain current.
36. As a manager, I want stale run results revalidated before activation, so that newer operational data cannot be ignored.
37. As a manager, I want event, tool, validation, and approval history, so that I can follow the demo without exposing private reasoning.
38. As a teammate, I want a reachable base URL, credentials, and expected HTTP responses, so that I can verify integration from my own machine.
39. As a demo presenter, I want a repeatable simulation clock and seed/reset workflow, so that expiry and CNY scenarios work consistently.
40. As a backend maintainer, I want focused API-level acceptance tests, so that I can change internal code without breaking teammate workflows.

## Implementation Decisions

### Architecture and ownership

- Keep one FastAPI service, PostgreSQL, ordinary SQLAlchemy transactions, Alembic migrations, and Pydantic/OpenAPI contracts. No additional service framework or message broker.
- Backend ownership covers persistence, API schemas, event recording, run coordination, snapshots, permissions, plan lifecycle, and approval enforcement.
- The ML teammate owns forecasting, recipe/inventory mathematics, materiality rules, supplier feasibility, optimisation, simulator calculations, and evaluation. Expose these through typed Python interfaces and HTTP tool adapters; do not build a competing backend decision engine.
- The agent teammate owns OpenClaw reasoning, investigation, tool selection, and completion reporting. The frontend teammate owns final UI design.
- Keep route handlers thin, transaction/business rules in service functions, and deterministic engines independent of ORM sessions. The spec does not require a repository abstraction layer.
- Produce a minimal test interface for counts/sales, supplier/promotion changes, recommendations, incoming deliveries, and the event/run timeline.

### Persistence and identity

- Relational records cover menu items, ingredients, recipes, suppliers, offers, holidays, promotions, inventory lots, daily update revisions, batch counts, sales totals, ingredient order cycles, incoming deliveries, purchase-plan identities, immutable plan versions/lines, planning runs, approvals, events, and audit entries.
- Preserve dated physical observations and corrected submission revisions. A current balance must not replace historical counts.
- A purchase plan has a stable plan_id distinct from ingredient cycles. plan_version increases within that identity; a stored revision also has a unique internal ID. A contingency revises the remaining horizon; a new normal horizon may receive a new identity. The single-restaurant MVP permits only one actionable version (PENDING_APPROVAL or APPROVED) across all identities. Publishing a replacement atomically supersedes the previous actionable version and records its previous status and replacement ID; external commitments remain intact.
- Preserve typed immutable forecast and inventory artifacts inside stored run snapshots/results. Their IDs resolve to exact artifacts; they are not placeholders pointing at current mutable data. Separate intermediate-result tables are unnecessary.
- Use foreign keys, unique plan/version and batch/source identities, and transactional guards. Quantities and money use decimal values. Each ingredient has one base unit: kg, litres, or pieces; all recipes and offers use it. Currency is SGD.
- Real audit time is distinct from Singapore simulation time. Persist effective times, stocktake cutoffs, sales interval boundaries, and emergency arrival timestamps explicitly.

### Physical, estimated, and projected inventory

- Each actual receipt creates a separate lot with actual quantity and expiry, linked to its incoming delivery. A closing count includes receipts already received that day and becomes authoritative.
- Estimate stock from the latest physical count plus subsequent actual receipts, minus subsequent recipe-derived sales usage and optional recorded waste, plus or minus explicit adjustments. Apply only activity after the baseline cutoff. Never deduct sales again from a submitted closing count.
- Attribute estimated usage to usable lots by earliest expiry. Estimates remain separate from physical observations. Preserve missing coverage and any calculated shortage; do not invent stock.
- Simulated sales batches are complete incremental reports for sequential, non-overlapping intervals, carrying source, batch identity, start/end times, and dish quantities. Omitted dishes mean zero only under that explicit complete-batch contract. Zero-sales intervals can establish coverage.
- Corrections retain source, batch_id and exact interval bounds, name the active replaces_id and increment revision. Partial reports and unrelated-interval replacements are unsupported.
- Identical retries have no additional effect; conflicting duplicate identities and overlapping additive periods are rejected. Corrections replace a referenced batch revision and recompute the estimate. Require a batch boundary at a stocktake cutoff rather than guessing how to split aggregate sales.
- Final daily sales replace that day's batch aggregation for historical forecasting; they are not added to it. Reconcile per dish and equal interval: complete coverage gives MATCHED or RECONCILIATION_DISCREPANCY with both totals and a signed difference; incomplete coverage gives INCOMPLETE_COVERAGE.
- Preserve PHYSICAL, ESTIMATED, and PROJECTED provenance with time/coverage metadata. Forecast consumption and expected deliveries produce projections, not measured stock.
- Mark lots EXPIRED from the start of the day after their expiry date in Singapore simulation time. Retain lot/count history and exclude expired stock even if a cached status has not yet been refreshed. A historical remainder is not proof of actual waste at expiry.
- Recorded waste is optional. Distinguish it from unexplained stock discrepancy, expected future waste, and labelled simulator ground truth.

### Scheduling, holidays, and suppliers

- Each ingredient has positive interval_days (schema and database enforced) and starting_date. Cycles recur from that anchor and can be OPEN, ORDERED, or SKIPPED; late entry does not shift future dates. Cycle decisions carry operational effective_at separately from real decided_at; omitted effective_at means real recording time, so the simulator must supply its clock explicitly. No weekday calendars, category inheritance, or reorder-point rules.
- Plan until the ingredient's next feasible replenishment opportunity, accounting for lead time, stock consumption, expiry, and already committed deliveries. Permit staggered arrivals.
- Seed relevant Singapore holiday dates with provenance from the [MOM public-holidays page](https://www.mom.gov.sg/employment-practices/public-holidays). Do not fetch the website during each run or infer demand uplift, restaurant closure, or supplier closure solely from a holiday.
- Promotions carry dates and affected dishes. Forecast effects come from ML-owned history or explicitly labelled simulation assumptions.
- Supplier offers expose: identities; unit_price; available_quantity; moq; pack_size; lead_time_minutes; order_cutoff; feasible_delivery_at; current_status; recent_on_time_rate; shelf_life_days_on_arrival; delivery_fee_sgd; emergency_fee_sgd; and observed_at.
- Availability means quantity available for new commitments at observed_at; existing commitments are not deducted twice. Allocations across lines respect this total unless explicit replenishment data exists.
- Cutoff is explicitly NONE, LOCAL_TIME in Singapore time, or UNKNOWN. Delivery timestamps are timezone-aware; an empty feasible list means none and null means unknown. Arrival must satisfy lead time and cutoff.
- Offer status is AVAILABLE, UNAVAILABLE, or UNKNOWN. Shipment delay/short/cancellation belongs to incoming deliveries. On-time rate is a fraction from zero to one. MOQ and pack size use ingredient units; fees are explicit per-line/shipment values for the prototype.
- Required unknown inputs prevent unsupported feasibility claims. Do not substitute zero or assume unlimited supply.

### Events and assessment

- Persist each accepted mutation and its event atomically. The envelope contains id, type, timestamp, source, and typed payload. Real recording time is separate from effective simulation time.
- Canonical event names are SALES_UPDATED, DAILY_UPDATE_SUBMITTED, PROMOTION_CREATED, PROMOTION_CHANGED, INVENTORY_ADJUSTED, INVENTORY_WASTED, SUPPLIER_AVAILABILITY_CHANGED, SUPPLIER_PRICE_CHANGED, SUPPLIER_STATUS_CHANGED, SUPPLIER_RELIABILITY_UPDATED, EXTERNAL_ORDER_RECORDED, DELIVERY_UPDATED, DELIVERY_RECEIVED, DELIVERY_DELAYED, DELIVERY_SHORT, DELIVERY_CANCELLED, ORDER_CYCLE_UPDATED, INVENTORY_LOT_EXPIRED, MANUAL_REASSESSMENT_REQUESTED, and MANAGER_INSTRUCTION.
- Daily submission, promotions, supplier disruptions, and manual instructions request assessment. Every sales batch updates deterministic estimates, but requests the agent only when ML-owned materiality checks detect a meaningful demand or stockout-risk change. Ordinary receipt/order/cycle/expiry changes use deterministic impact checks.
- Draft daily edits do not trigger assessments. Specialised routes and generic event ingestion must not apply the same mutation twice.
- Deterministic materiality considers changed feasibility, forecast demand, safety stock, arrival timing, costs/allocation, or required unknown inputs. A temporary approval block pending assessment is not automatically INVALIDATED.
- Keep one running agent attempt and one coalesced pending reassessment in PostgreSQL. Sales remain ingestible during runs and increment state revision; administrative edits may return RUN_IN_PROGRESS.
- Claim freezes the run snapshot and records its revision. All tools for the attempt use it. Before activation or approval, revalidate relevant current state and atomically verify its revision. A stale candidate that cannot be certified stays historical and causes reassessment.
- Snapshots select facts effective by as_of and recorded by the frozen real-time known_at. Supplier observations are immutable full versions; promotion and delivery terms retain event history. Receipts, stock counts, final daily revisions and corrected sales are filtered by recording time as well as their operational bounds. A late receipt does not import later delivery terms or future closing-count corrections. Future effective facts are excluded. Replaying the same run ID, as_of and known_at against preserved history reproduces its base inputs; saved snapshots remain authoritative artifacts.
- Pre-upgrade supplier values that were already overwritten cannot be recovered. The upgrade preserves the existing offer as a baseline and recording-time history begins at migration for previously untimestamped rows. Missing eligible offer history is explicit missing data, never replaced with today's values. Recipe/catalog changes remain outside the MVP write API.
- Never hold a database transaction during the LLM call. Bounded deadlines, manual retry, and late-attempt rejection prevent permanent locks. A retry is a new attempt; repeated completion is idempotent.
- Run states are QUEUED, RUNNING, SUCCEEDED, and FAILED. Business escalation can be a successful completed assessment. A crash or timeout has failure metadata without fabricating an agent outcome.

### Plan outcomes, statuses, and purchases

- AgentOutcome is KEEP_CURRENT_PLAN, REVISE_PLAN, REQUEST_HUMAN_APPROVAL, or ESCALATE.
- ESCALATE requires one reason: MISSING_REQUIRED_DATA, NO_FEASIBLE_SUPPLIER, UNRESOLVED_SHORTAGE, POLICY_VIOLATION, or TOOL_FAILURE. Other outcomes have no escalation reason.
- REVISE_PLAN publishes a new feasible pending version. REQUEST_HUMAN_APPROVAL refers to an existing valid pending version. KEEP_CURRENT_PLAN retains a certified recommendation or records NO_PURCHASE_REQUIRED with no plan identity when no plan exists and nothing needs buying.
- Each version exposes id/plan_id, version, status, forecast_id, inventory_snapshot_id, trigger_event_id, invalidation_reason, requires_approval, approval_reason, created_at, lines, total_purchase_cost, expected_waste_cost, expected_stockout_cost, delivery_cost, emergency_penalty, and total_expected_cost.
- New actionable versions enter PENDING_APPROVAL. From there allow APPROVED, REJECTED, INVALIDATED, or SUPERSEDED under their guards. APPROVED may become INVALIDATED or SUPERSEDED. The other three states are terminal for that version. VALID is not an MVP status.
- INVALIDATED records a material validity failure or an assumption that cannot be certified. SUPERSEDED records replacement without such failure. REJECTED is a manager decision. Preserve invalidation reasons and historical approvals; never transfer approval to a newer version or revive terminal versions.
- Every new actionable version requires approval of exact plan_id and plan_version by an authenticated manager, with decision and timestamp. Reject stale versions and infeasible candidates. Rejection may include instructions but does not automatically loop into another plan.
- Approval never creates a purchase or delivery. The owner records actual external purchases, which may differ from the recommendation, and marks affected ingredient cycles ordered or skipped.
- Existing external commitments are fixed inputs to later optimisation. Additional contingency lines cover only uncommitted purchases; they do not re-order quantities already arranged.
- Emergency recommendations use the same approved suppliers and deterministic tools. Include arrival timing and costs; if no candidate covers the shortage, escalate. A planned afternoon purchase cannot be assumed to arrive that morning.
- Owners can update delivery expectations, record cancellation, and receive actual quantities with expiry. Partial receipts create lots and explicitly leave the remainder expected or cancelled. Expected supply is not stock on hand.
- Audit records preserve event, plan/version, actor, action, concise reason, tools called, result, and timestamps. Expose summaries, not hidden chain-of-thought.

### API integration and access

- Preserve GET /health returning HTTP 200 and status ok. It is a liveness check, not evidence that the database or agent works.
- Publish interactive documentation at /docs and canonical OpenAPI models. Business routes use /api/v1.
- Provide manager login/logout, catalog/inventory/offer/holiday reads, daily draft/read/submit operations, promotion and supplier updates, validated event ingestion, delivery creation/update/receipt, order-cycle actions, plan/history reads and approve/reject, manual run requests, run status/retry, and audit/event reads.
- Agent-only operations claim runs, invoke forecasting/requirements/inventory/supplier/optimisation/validation tools, and report completion. Validate candidate creation through the same publication service whether reached by a tool or completion; never allow raw unvalidated plan insertion.
- Run requests return HTTP 202 with a stable run reference after durable acceptance; clients poll for completion. They do not hold an HTTP request until Claude finishes. Expose whether a request started or joined a pending assessment.
- Successful reads use HTTP 200; creations use documented success responses; stale plan, conflicting idempotency, or run-state conflicts use HTTP 409. Invalid payloads and permission failures have documented HTTP statuses and the shared error envelope with code, message, retryable, and optional details.
- Use a simple configured manager account and secure session cookie for the hosted demo, separate from the agent credential. Agent permissions cannot approve, mutate supplier/recipe policy, or record purchases/receipts. Protect browser mutations and configure explicit allowed frontend origins.
- Handover includes a reachable base URL, test credentials delivered separately, seed instructions, request/response examples, and a connection check from another machine. localhost on a teammate's laptop is not the host backend.
- HTTP 200 is a success status; 200 ms is latency. No arbitrary 200 ms service-level requirement is introduced.

## Testing Decisions

The approved primary testing boundary is the public FastAPI HTTP API with a real isolated PostgreSQL test database. Extend the existing FastAPI TestClient health-test pattern rather than testing route/service/ORM internals separately. Exercise agent claim, tool, and completion contracts through HTTP too.

Use controlled agent/tool responses only where needed to reproduce failures, stale completion, and exact boundary conditions. Do not mock PostgreSQL when testing atomicity, constraints, idempotency, or concurrency. A separate integrated demo must use the actual ML calculations and OpenClaw tool orchestration; canned purchase recommendations do not satisfy acceptance.

Tests assert externally visible responses, persisted history exposed through APIs, permission outcomes, and final inventory/plan behaviour. Do not assert private function calls, SQL text, internal class structure, or fragile LLM wording.

Cover these behaviours:

1. Health is reachable; authenticated inventory reads return seeded batches; missing or wrong credentials cannot access protected actions.
2. A valid daily submission stores all batch/dish entries; missing differs from explicit zero; final physical counts are not reduced again by the same day's sales.
3. Timestamped sales update estimates by recipe usage while leaving physical observations unchanged. Non-material batches do not create an agent assessment; material input does.
4. Duplicate batches/receipts/completions have one effect; conflicting duplicates and overlapping additive periods are rejected; correction recomputes without double subtraction.
5. Complete matching sales coverage yields MATCHED, complete differing totals yield a discrepancy, and partial coverage yields INCOMPLETE_COVERAGE. Final totals appear once in forecast history.
6. Expiry excludes a lot on the day after expiry, retains dated history, and never declares unobserved waste.
7. Receipts appear either as received stock or outstanding expected supply, never both. Short receipts and cancellation preserve correct remaining quantities.
8. Per-ingredient schedule anchors remain stable after ordered/skipped/late recording; arrival feasibility respects lead time, cutoff, slots, expiry, MOQ, pack sizes, and new-order availability.
9. Outcome/reason combinations validate; known infeasibility escalates without an approvable plan; a failed attempt remains distinct.
10. Test all allowed plan transitions and rejection of terminal-state revival, stale approvals, and approval inheritance. An agent credential cannot approve.
11. Sales continue during an agent attempt. Newer material data prevents unsafe activation; repeated triggers coalesce. Expired attempts cannot publish late results, and manual retry is possible.
12. Emergency deliveries clear projected shortages only if timing and quantities suffice. Contingency plans preserve external commitments and do not recommend them again.
13. Audit history exposes the triggering inputs, tools, validation result, plan versions, and manager decisions.
14. A teammate can reach health, log in, read seeded inventory, submit input, receive a run reference, poll its result, and observe a deliberate stale-approval conflict. A browser smoke check verifies allowed-origin integration separately from HTTP client tests.

Integrated acceptance story: create and approve a normal plan; submit a promotion causing material invalidation and a new pending version; reduce supplier availability to produce a real feasible split; reject approval of the older version; approve and record actual purchases; submit timestamped sales causing projected stockout; calculate a feasible emergency/contingency version against those commitments; approve and record its delivery; reassess and show whether the shortage is covered. Retain the complete event/plan/approval trail.

## Out of Scope

- Multiple restaurants, registration, supplier onboarding, enterprise roles, or a general procurement platform.
- Real POS/barcode integrations, unrestricted continuous streams, or autonomous observation of information not supplied to the backend.
- Autonomous order placement, payments, supplier negotiation, or modification of existing commitments by the agent.
- Mandatory waste measurement, invented waste labels, deep supplier analytics, and LLM self-retraining claims.
- Weekday calendars, category inheritance, reorder-point scheduling, automatic unit conversion, or a general scheduling engine.
- Additional microservices, Redis/message brokers, event-sourced reconstruction of the entire database, and a general workflow engine.
- Production UI design, a full dashboard suite, or implementing teammates' ML/agent ownership independently.
- Selecting a hosting vendor or promising benchmark improvements before they are measured.

## Further Notes

The repository currently implements only health checking on the backend. This specification describes work to build, not verified existing behaviour. Database migrations, seeds, HTTP examples, focused tests, and teammate handover are deliverables.

Build in vertical slices: canonical contracts and seedable persistence; counts/sales/receipts; snapshots, agent runs and plan approval; ML/agent integration; then minimal test UI and a shared hosted smoke test. Real calculations must replace clearly labelled integration fixtures before the final demo.

Keep existing catalog and policy configuration seeded and readable. The backend owns consistency and permissions; the ML engine owns numerical decisions; the agent owns investigation. Preserve this separation so the team can change one area without rewriting the others.

The user approved the testing boundary, GitHub tracker, and nine-ticket breakdown. Publish the spec and implementation tickets with the ready-for-agent label; blocked tickets become actionable only when their declared dependencies are complete. Publication does not start implementation or assign teammates.
