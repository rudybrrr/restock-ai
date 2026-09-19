# ReStock AGENTS Task List

> **Purpose:** End-to-end checklist for the ReStock Agent / AI subsystem, from approved design to hackathon submission.
>
> **Primary spec:** `AGENTS_PLAN.md`
>
> **Submission deadline:** **28 September 2026, 9:00 AM SGT**
>
> Keep this file updated as work progresses. Mark completed work with `[x]`. Add short notes only where useful.

---

# 0. Preparation and Approval

- [x] Finalise Agent / AI architecture
  - [x] Target architecture: Coordinator + Demand + Inventory + Procurement & Supply specialists
  - [x] Coordinator is the only agent allowed to call another agent
  - [x] Specialists are isolated from one another
  - [x] Dynamic routing only
  - [x] Strict structured agent inputs / outputs
  - [x] Deterministic tools remain authoritative
  - [x] Backend remains the only plan-mutation authority
  - [x] Human approval remains mandatory for actionable plans
  - [x] Business-level audit trail is required
  - [x] Prompt-injection and fail-closed rules are defined
  - [x] Four-agent topology is the target, not a hard dependency

- [x] Review Agent plan with Ethan
  - [x] Apply first review
  - [x] Apply final escalation / lifecycle corrections
  - [x] Receive approval

- [x] Finalise `AGENTS_PLAN.md`
  - [x] Add `CALCULATION_INCOMPLETE`
  - [x] Add `SEARCH_LIMIT_REACHED`
  - [x] Keep incomplete calculation distinct from `TOOL_FAILURE`
  - [x] Keep incomplete calculation distinct from `NO_FEASIBLE_SUPPLIER`
  - [x] Keep only the branching lifecycle diagram

---

# 1. Set Up the Working Project

- [ ] Create the ReStock ChatGPT Project
  - [ ] Add `AGENTS_PLAN.md`
  - [ ] Add `AGENTS_TASKS.md`
  - [ ] Add the latest overall ReStock product plan
  - [ ] Add the architecture / shared-contract document
  - [ ] Add Ethan's review
  - [ ] Add hackathon briefing / rubric materials
  - [ ] Add current repository handoff / implementation notes

- [ ] Set Project instructions
  - [ ] `AGENTS_PLAN.md` is the Agent subsystem source of truth
  - [ ] Backend / shared Pydantic contracts override agent assumptions
  - [ ] Update `AGENTS_TASKS.md` after each coding pass
  - [ ] Do not mark tasks complete without tests
  - [ ] Keep changes small and reviewable
  - [ ] Do not duplicate forecasting, inventory, or optimiser logic in the Agent layer
  - [ ] Enforce business rules outside prompts

- [ ] Prepare repository workflow
  - [ ] Pull latest `main`
  - [x] Confirm repository starts cleanly
  - [x] Confirm test commands
  - [x] Create Agent implementation branch / worktree
    - Current `agent/coordinator-control-plane` branch is retained; no new branch/worktree was created in the hardening pass.
  - [x] Confirm Bedrock / runtime secrets are not committed

---

# 2. Freeze Shared Contracts with Chun Yang and Aniq

> Complete this before expanding the specialist topology.

- [x] Freeze plan lifecycle
  - [x] Decide disposition of `VALID`
  - [x] Confirm `PENDING_APPROVAL`
  - [x] Confirm `APPROVED`
  - [x] Confirm `REJECTED`
  - [x] Confirm `INVALIDATED`
  - [x] Confirm `SUPERSEDED`

- [x] Freeze Agent outcomes
  - [x] `KEEP_CURRENT_PLAN`
  - [x] `REVISE_PLAN`
  - [x] `REQUEST_HUMAN_APPROVAL`
  - [x] `ESCALATE`

- [x] Freeze escalation reasons
  - [x] `MISSING_REQUIRED_DATA`
  - [x] `NO_FEASIBLE_SUPPLIER`
  - [x] `UNRESOLVED_SHORTAGE`
  - [x] `POLICY_VIOLATION`
  - [x] `CALCULATION_INCOMPLETE`
  - [x] `TOOL_FAILURE`
  - [x] `CALL_LIMIT_REACHED`
  - [x] Detail: `SEARCH_LIMIT_REACHED`

- [x] Freeze exact Pydantic payloads
  - [x] Coordinator invocation
  - [x] Specialist delegation
  - [x] Specialist result
  - [x] Agent completion / publication
  - [x] Tool request / response
  - [x] Error payload
  - [x] Approval request
  - [x] Audit event

- [x] Freeze evidence references
  - [x] Materiality evidence refs
  - [x] Forecast refs
  - [x] Inventory snapshot refs
  - [x] Supplier-state refs
  - [x] Candidate-plan refs
  - [x] Validation refs
  - [x] Policy refs

- [x] Freeze state-revision semantics
  - [x] Define `captured_state_revision`
  - [x] Define stale-publication rejection
  - [x] Define re-read / retry behaviour when state changes mid-run

- [x] Freeze tool-to-kernel adapter mapping
  - Contract names and envelopes are frozen; local adapters call the existing owning kernels/Backend ports.
  - [x] Demand tools -> Aniq forecasting kernels
  - [x] Inventory tools -> Aniq inventory / requirements kernels
  - [x] Procurement tools -> Aniq supplier / optimiser kernels
  - [x] Approval tools -> Chun Yang backend policy / workflow
  - [x] Audit tools -> Chun Yang backend persistence
  - Full local verification confirms no duplicate Agent kernels were added.

- [x] Freeze supplier reliability behaviour
  - [x] Default MVP: store / display `recent_on_time_rate`
  - [x] Do not let it affect selection unless a deterministic versioned penalty exists

---

# 3. Coding Pass 1 — Smallest Real Agent Path

> Goal: prove `OpenClaw -> Claude/Bedrock -> real FastAPI tool -> validated result -> Backend -> PLAN-v1`.

- [ ] Verify OpenClaw runtime
  - [x] Agent config loads
  - [ ] Structured output works

- [ ] Verify Claude Sonnet 4.5 / Bedrock
  - [ ] Successful model request
  - [x] Failure path tested
  - [x] Secrets stay out of prompts / logs

- [ ] Connect one real FastAPI tool
  - [ ] Canonical Pydantic request
  - [ ] Canonical Pydantic response
  - [ ] Error codes

- [ ] Build minimal Coordinator
  - [x] Receive invocation
  - [x] Read active-plan context
  - [x] Call one real tool
    - Local scripted Coordinator/specialist execution exercises injected tool ports; live OpenClaw provider execution remains pending.
  - [x] Produce typed completion payload
  - [x] Do not mutate plan state directly

- [x] Connect completion to Backend
  - [x] `run_id`
  - [x] `captured_state_revision`
  - [x] outcome
  - [x] reason codes
  - [x] evidence refs
  - [x] affected plan/version
  - [x] summary

- [x] Persist genuine `PLAN-v1`
  - [x] Backend checks state revision
  - [x] Backend validates candidate
  - [x] Backend creates immutable `PENDING_APPROVAL` version
  - [x] Audit entry written
  - PostgreSQL acceptance now proves the Backend-owned frozen forecast contract → pure numerical kernels → independently validated immutable engine artifacts → Coordinator → immutable `PENDING_APPROVAL` PLAN-v1, without `DEVELOPMENT_FIXTURE`.

- [x] Show first concise trace
  - [x] Trigger
  - [x] Agent run
  - [x] Tool call
  - [x] Validation
  - [x] Plan creation
  - PostgreSQL-backed Agent/Backend integration verifies the persisted trace locally with scripted reasoning and the test-only `DEVELOPMENT_FIXTURE` candidate.

- [x] Test Pass 1
  - [x] Happy path
  - [x] Invalid structured output
  - [x] Tool exception
  - [x] Stale state revision
  - [x] Missing required data

- [x] Review and commit Pass 1

---

# 4. Coding Pass 2 — Coordinator Control Plane

- [x] Add invocation modes
  - [x] `SCHEDULED`
  - [x] `EVENT`
  - [x] `MANUAL`

- [ ] Add Coordinator control-plane tools
  - [x] `get_active_plan`
  - [x] `get_event_context`
  - [x] `validate_final_plan`
  - [x] `record_agent_decision`
  - [ ] `request_human_review`
  - Thin adapters and a local production composition root call the authoritative Backend planning services; they do not access Backend tables directly.
  - Blocked: exact-version human-review validation is connected, but the Backend does not expose a distinct persisted review-request workflow.

- [x] Add final outcomes
  - [x] `KEEP_CURRENT_PLAN`
  - [x] `REVISE_PLAN`
  - [x] `REQUEST_HUMAN_APPROVAL`
  - [x] `ESCALATE`

- [x] Add bounded orchestration
  - [x] Max 2 specialist rounds
  - [x] Max 6 specialist calls per run
  - [x] Max 1 retry per failed tool call
  - [x] No specialist recursion
  - [x] No specialist-to-specialist calls

- [x] Add dynamic routing
  - [x] Call only needed specialists
  - [x] Support sequential dependencies
  - [x] Do not waste calls on unrelated specialists

- [x] Test Coordinator permissions
  - [x] Cannot approve
  - [x] Cannot bypass validator
  - [x] Cannot mutate plan/database directly
  - [x] Cannot perform specialist calculations itself

- [x] Review and commit Pass 2

---

# 5. Coding Pass 3 — Procurement & Supply Specialist

> Implement first because supplier disruption is the strongest early replanning route.

- [x] Create Procurement & Supply Agent foundation
  - [x] Narrow instructions
  - [x] Strict input / output schema
  - [x] Hard tool allowlist
  - [x] No agent-spawn permission

- [x] Connect procurement tools
  - [x] Define injected canonical `ToolRequest` / `ToolResult` / backend-error port
  - [x] `get_supplier_options`
  - [x] `check_supplier_feasibility`
  - [x] `enumerate_supplier_allocations`
  - [x] `optimise_purchase_plan`
  - [x] `validate_purchase_plan`
  - [x] `get_approval_requirement`
  - Backend-owned adapters freeze and persist the authoritative contract and engine artifacts; the Procurement specialist receives only canonical references.

- [x] Support procurement constraints
  - [x] Availability
  - [x] MOQ
  - [x] Pack size
  - [x] Lead time
  - [x] Delivery cutoff / schedule
  - [x] Price
  - [x] Delivery state
  - [x] Bounded 2–3 supplier allocation

- [x] Handle typed optimiser outcomes at the injected tool boundary
  - [x] Feasible result requires trusted candidate and validation evidence
  - [x] `NO_FEASIBLE_SUPPLIER`
  - [x] `CALCULATION_INCOMPLETE / SEARCH_LIMIT_REACHED`
  - [x] `TOOL_FAILURE`
  - [x] Never treat incomplete search as proven infeasibility

- [x] Implement supplier-disruption route
  - [x] Deterministic materiality evidence exists
  - [x] Coordinator routes Procurement only initially
  - [x] Shared kernels run
  - [x] Candidate returned
  - [x] Backend validates / publishes new plan if needed
  - Local verification uses the current authoritative supplier offer revisions and
    event/materiality contracts. Expanded teammate/live supplier-domain integration
    remains outside this local submission pass.

- [x] Prove this specialist earns its existence
  - [x] Add structural scripted coverage for context-sensitive tool sequencing
  - [x] Add an offline local scenario where trusted cached context avoids unnecessary tool calls and changed context triggers bounded investigation
  - [x] Confirm the same value on the real local tool path: a current persisted
    Decision Engine feasibility ref skips optimisation, while missing/stale context
    executes supplier options, feasibility, optimisation, and validation.

- [x] Review and commit Pass 3

---

# 6. Coding Pass 4 — Demand Specialist

- [x] Confirm Demand specialist adds real reasoning value
- [x] Create Demand Agent
  - [x] Narrow instructions
  - [x] Strict input / output schema
  - [x] Hard tool allowlist
  - [x] No agent-spawn permission

- [x] Connect demand tools
  - [x] Sales context
  - [x] Promotion context
  - [x] Historical demand context
  - [x] Forecast demand
  - [x] Compare forecast versions through the Backend-owned deterministic adapter

- [x] Support demand cases
  - [x] Promotion
  - [x] Demand spike / drop
  - [x] Seasonal / weekday effects
  - [ ] Holiday context
  - [x] Forecast uncertainty
  - [x] Missing sales interval

- [x] Keep materiality authority deterministic
  - [x] Specialist interprets evidence
  - [x] Specialist never invents authoritative materiality

- [x] Prove this specialist earns its existence
  - [x] At least one scenario where contextual reasoning changes investigation / tool order

- [x] Review and commit Pass 4

---

# 7. Coding Pass 5 — Inventory Specialist

- [x] Confirm Inventory specialist adds real reasoning value
- [x] Create Inventory Agent
  - [x] Narrow instructions
  - [x] Strict input / output schema
  - [x] Hard tool allowlist
  - [x] No agent-spawn permission

- [x] Connect inventory tools
  - [x] Inventory snapshot
  - [x] Estimated inventory
  - [x] Ingredient requirements
  - [x] Expiry risk
  - [x] Stockout risk
  - [ ] Snapshot comparison

- [x] Support inventory cases
  - [x] Physical stocktake correction
  - [x] Wastage / manual adjustment
  - [x] Expiry risk
  - [ ] Safety stock
  - [x] Incoming deliveries through the frozen commitment projection
  - [x] Estimated stock between stocktakes
  - [ ] Storage constraints

- [x] Keep inventory language accurate
  - [x] Physical count = physical
  - [x] Between-stocktake balance = estimated / inferred
  - [x] Unknown stays unknown

- [x] Prove this specialist earns its existence
  - [x] At least one scenario where contextual reasoning changes investigation / tool order

- [x] Review and commit Pass 5

---

# 8. Coding Pass 6 — Full Dynamic Replanning

> Local contract audit (2026-09-18, after merging `origin/main`): promotion
> application/comparison, activity-aware procurement snapshots, commitment-aware
> delivery projection, and the persisted sales-materiality contract are present.
> Inventory correction remains open because no authoritative inventory-adjustment
> event contract is present on `origin/main`.

- [x] Integrate deterministic materiality kernel for authoritative supplier availability/status changes
  - [x] Affected IDs
  - [x] Threshold / feasibility evidence
  - [x] Evidence refs
  - [x] Freshness check

- [x] Implement promotion route
  - [x] Demand uses the frozen promotion application and forecast comparison
  - [x] Inventory receives the adjusted demand only when comparison is material
  - [x] Procurement remains conditional on projected stock exposure

- [ ] Implement inventory-correction route
  - [ ] Authoritative inventory-adjustment event contract (Backend gap)
  - [ ] Safe correction routes to Inventory and proves `KEEP_CURRENT_PLAN`
  - [ ] Procurement is conditional on projected stock exposure

- [x] Implement supplier-disruption route for authoritative availability/status changes
  - [x] Procurement first
  - [x] Inventory only if exposure needs reassessment

- [x] Implement complex multi-domain route
  - [x] Demand -> Inventory -> Procurement routing is implemented
  - [x] Coordinator can perform bounded second investigation round
  - [x] PostgreSQL-backed promotion-to-publication acceptance on a dedicated local database
  - [x] Local hardening reran the supported multi-domain path and manager evidence assertions.

- [x] Implement sales-trigger materiality contract route
  - [x] Landed `SALES_MATERIALITY_V1` policy is selected and frozen by Backend
  - [x] Backend persists request/result transport with revision, `as_of`, and `known_at`
  - [x] `get_materiality()` exposes the persisted result with immutable evidence
  - [x] Missing/incomplete sales evidence fails closed
  - [x] Complete material sales with safe inventory certifies `KEEP_CURRENT_PLAN`
  - [x] Sales specialist routing is Coordinator-owned; no specialist recursion

- [x] Implement delivery-disruption route
  - [x] Inventory consumes frozen received/cancelled/outstanding commitments once
  - [x] Procurement is conditional on incremental shortage exposure

- [x] Implement `KEEP_CURRENT_PLAN` for non-material supplier events
- [x] Implement `REVISE_PLAN` for material supplier events
  - [x] Backend validates
  - [x] Backend invalidates / supersedes old version as appropriate
  - [x] Backend creates new `PENDING_APPROVAL` version
- [ ] Implement `REQUEST_HUMAN_APPROVAL`
- [x] Implement `ESCALATE` with correct reason / detail for no feasible supplier replacement

- [x] Review and commit Pass 6

---

# 9. Coding Pass 7 — Approval and Plan Safety

- [x] Implement exact-version approval
  - [x] `plan_id`
  - [x] `plan_version`
  - [x] approver
  - [x] timestamp
  - [x] decision

- [x] Implement stale-approval rejection
  - [x] Old plan reviewed
  - [x] State changes
  - [x] New plan created
  - [x] Old approval returns `PLAN_VERSION_STALE`

- [x] Implement lifecycle transitions required by supplier replanning
  - [x] `PENDING_APPROVAL -> APPROVED`
  - [x] `PENDING_APPROVAL -> REJECTED`
  - [x] `PENDING_APPROVAL -> INVALIDATED`
  - [x] `PENDING_APPROVAL -> SUPERSEDED`
  - [x] `APPROVED -> INVALIDATED`
  - [x] `APPROVED -> SUPERSEDED`

- [x] Confirm no Agent approval authority
- [x] Confirm no real order placement / payment

- [x] Review and commit Pass 7

---

# 10. Coding Pass 8 — Safety and Prompt Injection

- [x] Enforce business rules outside prompts
  - [x] Approved suppliers only
  - [x] MOQ
  - [x] Pack size
  - [x] Lead time
  - [x] Delivery cutoff
  - [x] Storage limits
  - [x] Safety-stock bounds
  - [x] Approval policy
  - [x] State freshness
  - [x] Plan-version validity
  - Deterministic procurement validation and Backend publication own these checks; local scripted reasoning receives only typed routing facts and evidence references.

- [x] Implement fail-closed unknown-data handling
  - [x] Supplier availability at the Coordinator / Procurement orchestration boundary
  - [x] Shelf life
  - [x] Recipe quantity
  - [x] MOQ / pack size at the Coordinator / Procurement orchestration boundary
  - [x] Lead time at the Coordinator / Procurement orchestration boundary
  - [x] Promotion details
  - [x] Inventory freshness
  - [x] Forecast/history and policy/version evidence
  - Missing values remain `MISSING_REQUIRED_DATA` / incomplete; they are never defaulted into a feasible or approved plan. Sales materiality now uses the frozen Backend contract and remains fail-closed until a result is persisted.

- [x] Test prompt injection
  - [x] Manager text tries to override policy
  - [x] Supplier text contains instructions
  - [x] Promotion text contains instructions
  - [x] Attempt to add unapproved supplier
  - [x] Attempt to change MOQ / budget
  - [x] Attempt to bypass approval
  - [x] Attempt to treat unknown as available
  - [x] Attempt to force outcome, trigger a sibling, or inject fake evidence/state revision

- [x] Test tool permissions
  - [x] Coordinator alone invokes specialists
  - [x] Specialists cannot invoke agents
  - [x] Demand / Inventory / Procurement cross-domain tools fail closed
  - [x] Specialists cannot mutate plan state or approve
  - [x] No generic DB mutation tool exists; allowlists are exact and fail closed

- [x] Review and commit Pass 8

---

# 11. Coding Pass 9 — Business Audit Trail

- [x] Persist Coordinator runs
  - [x] `run_id`
  - [x] trigger
  - [x] plan/version
  - [x] captured state revision
  - [x] start/end
  - [x] outcome / reason

- [x] Persist specialist calls
  - [x] `agent_call_id`
  - [x] parent run
  - [x] objective
  - [x] context refs
  - [x] structured result evidence refs
  - [x] status / timing where canonical timestamps are supported

- [ ] Persist tool calls
  - [x] `tool_call_id`
  - [x] parent agent call
  - [x] tool name
  - [x] request schema version
  - [x] evidence / result refs
  - [x] success / failure
  - [ ] duration — no canonical duration contract; not invented locally.
  - [x] error / termination code

- [x] Persist business decision events
  - [x] Event
  - [x] Materiality evidence
  - [x] Routing
  - [x] Tool use
  - [x] Validation
  - [x] Plan transition
  - [x] Approval
  - [x] Final outcome

- [x] Keep audit history append-only
- [x] Enforce persisted audit-entry append-only history in PostgreSQL
- [x] Expose concise timeline to frontend
- [x] Do not store hidden chain-of-thought
  - PostgreSQL-backed verification covers deterministic materiality, Coordinator routing, specialist call and completion facts, tool request/result metadata, candidate validation, supersession or invalidation, exact-version approval or stale rejection, final outcome, promotion routing, delivery routing, and sales-materiality freshness/lifecycle evidence. Inventory correction remains open with the missing authoritative event contract.

- [x] Review and commit Pass 9

---

# 12. Coding Pass 10 — Evaluation Harness

> Use Aniq's shared scenario manifests, simulator truth, and business metrics.

- [x] Freeze scenario manifest format
  - [x] Inputs
  - [x] Events
  - [x] Expected deterministic truth
  - [x] Expected routing
  - [x] Expected outcome
  - [x] Expected escalation reason / detail

- [ ] Cover scenario families
  - [x] Normal planning
  - [x] Promotion
  - [x] Demand spike / drop (sales-materiality contract and fail-closed scenario)
  - [ ] Inventory correction (authoritative event contract not landed)
  - [ ] Wastage / expiry (no canonical evaluation fixture yet)
  - [x] Supplier shortage / delay / cancellation
  - [x] Price change
  - [ ] Complex combined events (no canonical combined-event fixture yet)
  - [x] Missing data
  - [x] No feasible supplier
  - [x] Optimiser search limit
  - [x] Prompt injection
  - [x] Stale approval

- [x] Build Static baseline
- [x] Build Rule-based baseline
- [x] Run adaptive ReStock with same tools / observed data

- [ ] Measure Agent metrics
  - [x] Routing accuracy
  - [x] Unnecessary specialist-call rate
  - [x] Structured-output validity
  - [x] Keep / revise / approval / escalation accuracy
  - [x] Missed replans
  - [x] Unnecessary replans
  - [x] Prompt-injection resistance
  - [x] Policy-violation rate
  - [x] Calls / latency / retries
  - [ ] Token usage / live model-call metrics (pending live model)

- [ ] Measure business metrics
  - [ ] Food waste
  - [ ] Stockouts
  - [ ] Lost sales
  - [ ] Procurement cost
  - [ ] Emergency-order cost
  - [ ] Total operational cost
  - [ ] Manual interventions

- [x] Separate development and held-out cases
- [x] Freeze evaluated config before held-out run
- [x] Preserve failures honestly
- [ ] Reach 30–50 benchmark scenarios

- [ ] Review and commit Pass 10

Closure verification (2026-09-18): the real local demo was prepared and run
twice against dedicated PostgreSQL database `restock_demo_20260918`. Five
supported scenarios produced stable boundary fingerprints, outcomes, routing,
specialist/tool counts, and stale-approval evidence; per-run identifiers and
latency remain intentionally run-specific. Promotion completed through the
real local path, sales missing-result routing escalated with
`MISSING_REQUIRED_DATA`, live model metrics remained `pending`, business
metrics remained `unsupported`, and evaluator truth stayed separate from
runtime evidence. Inventory correction remains open because the authoritative
inventory-adjustment event contract is not landed.

---

# 13. Frontend Agent Evidence

- [x] Show active plan / status / version
- [x] Show plan history
- [x] Show exact pending approval version
- [x] Show stale approval errors
- [x] Show event timeline
- [x] Show Coordinator routing
- [x] Show specialist calls
- [x] Show tool-call summaries
- [x] Show validation result
- [x] Show concise decision explanation
- [ ] Show benchmark results
  - Not persisted into manager runs; local results are documented in `docs/evaluation/LOCAL_RESULTS_2026-09-19.md`.
- [ ] Review end-to-end UI with Ethan

Closure verification (2026-09-18): manager-safe evidence API and browser
assertions passed with screenshots disabled. The projection exposed plan,
approval, routing, specialist/tool, validation, decision, and evaluation
summary fields without raw frozen state, prompts, scratchpads, or secrets.

---

# 14. Golden Acceptance Scenario

Closure status (2026-09-18): supplier, promotion, delivery-disruption, sales
fail-closed, and stale-approval paths exercised on the real local runner.
Inventory correction remains the only contract-gated Golden Acceptance gap:
Backend has not landed an authoritative inventory-adjustment event contract.
No substitute semantics were added.

- [x] Start with an isolated pending or approved plan version
- [x] Supplier availability falls
- [x] Deterministic materiality evidence records affected allocation
- [x] Coordinator routes only necessary specialist(s)
- [x] Procurement specialist uses shared supplier / optimiser kernels
- [x] Candidate passes deterministic validation
- [x] Coordinator returns `REVISE_PLAN` where a material replacement is proven
- [x] Backend checks current state revision
- [x] Backend invalidates / supersedes the prior actionable version as appropriate
- [x] Backend creates a new `PENDING_APPROVAL` version
- [x] Attempt approval of the prior exact version
  - [x] Receive `PLAN_VERSION_STALE`
- [x] Manager exact-version approval is exercised on the current version
- [x] Full event / routing / tool / validation / approval trace is visible
- [x] Repeat from clean seed successfully

---

# 15. Hero Demo

Closure status (2026-09-18): the supported local reset/prepare/run mechanism
was verified twice from the same dedicated demo database without carry-over
plans, events, commitments, or revision drift. Promotion, delivery, supplier,
sales fail-closed, and stale-approval paths are supported; inventory correction
remains open pending the authoritative Backend event contract.

- [ ] Monday: normal scheduled planning
  - [ ] Demand -> Inventory -> Procurement
  - [ ] `PLAN-v1 PENDING_APPROVAL`
  - [ ] Manager approval
  - Not part of the five-scenario golden selection; retain as a future rehearsal extension.

- [x] Promotion reassessment
  - [x] Demand reassessment
  - [x] Inventory impact
  - [x] Procurement revision if needed
  - [x] New plan where material

- [x] Supplier shortage/disruption
  - [x] Procurement routed first
  - [x] Supplier allocation changes
  - [x] New plan + approval boundary

- [ ] Friday: demand exceeds forecast
  - [ ] Demand reassessment
  - [ ] Inventory exposure
  - [ ] Procurement re-evaluation
  - [ ] Emergency / shortage outcome
  - Not selected for the supported golden demo; the current sales-materiality scenario is fail-closed when its authoritative result is absent.

- [x] Show one safety case
- [x] Show one escalation / failure case
- [x] Finish with audit trail + local evaluation summary
- [x] Rehearse within demo time limit
- [x] Prepare seeded fallback demo state

---

# 16. Rubric Audit

- [x] Goal & Scope Definition
  - [x] Clear user, objective, boundaries, metrics

- [x] Architecture & Reasoning Loop
  - [x] Dynamic routing visible
  - [x] Bounded re-reasoning visible
  - [x] Explicit state visible
  - [x] Each retained specialist is justified

- [x] Tool Use & Integration
  - [x] Real typed tools
  - [x] Deterministic calculations
  - [x] Failure behaviour demonstrated

- [x] Autonomy & Human-in-the-Loop
  - [x] Autonomous investigation
  - [x] Human approval
  - [x] Stale approval rejection

- [x] Safety, Security & Guardrails
  - [x] Prompt injection tested
  - [x] Permissions tested
  - [x] Hard rules outside LLM
  - [x] Unknowns fail safely

- [x] Observability & Evaluation
  - [x] Full audit history
  - [x] Agent / tool traces
  - [x] Baseline comparison
  - [x] Held-out evaluation separation

- [ ] Platform & Tooling Usage
  - [ ] OpenClaw — live runtime verification pending.
  - [ ] Claude Sonnet 4.5 / Bedrock — live model verification pending.
  - [x] FastAPI / Pydantic
  - [x] PostgreSQL
  - [ ] End-to-end deployed system — deployment is out of scope for this pass.

- [x] Every local rubric claim has visible repository/test/demo evidence

---

# 17. Deployment and Reliability

- [ ] Coordinate deployment choice with Chun Yang
- [ ] Deploy backend
- [ ] Deploy frontend
- [ ] Deploy / configure Agent runtime
- [ ] Configure Bedrock credentials securely
- [x] Run database migrations locally
- [x] Seed demo data locally
- [ ] Verify production-like end-to-end flow — deployment pending.

- [ ] Test degraded conditions
  - [ ] Bedrock unavailable
  - [x] Tool unavailable
  - [x] Stale state
  - [x] Invalid agent output
  - [x] Optimiser incomplete search
  - [x] Duplicate event
  - [x] Retry path

- [ ] Add infrastructure telemetry only if time remains
  - [ ] OpenTelemetry
  - [ ] CloudWatch
  - [ ] Additional CI observability

---

# 18. Final Hardening

- [x] Run full test suite
- [x] Run Agent permission suite
- [x] Run prompt-injection suite
- [x] Run approval / stale-version suite
- [x] Run optimiser termination suite
- [x] Run supported local benchmark
- [x] Run supported golden acceptance scenarios
- [x] Run supported hero-demo preparation/execution from clean seed

- [x] Review audit records
  - [x] No chain-of-thought
  - [x] No secrets
  - [x] No missing evidence refs in supported local flows
  - [x] Historical records remain immutable

- [x] Review code quality
  - [x] No duplicated ML / optimiser kernels
  - [x] No general DB mutation tool exposed to agents
  - [x] No unnecessary permissions
  - [x] No decorative specialists
  - [x] No stale enums / statuses
  - [x] No target metrics presented as achieved results

Closure verification (2026-09-19): full PostgreSQL suite passed (773 tests),
including the landed sales-materiality route and dedicated migration-head
merge. The supported golden/demo path passed twice; inventory correction,
live LLM, AWS, deployment, and undefined persisted human-review workflow
remain explicitly incomplete.

- [x] Freeze local submission build
- [x] Record final commit SHA after focused commits

---

# 19. Submission Materials

- [x] Finalise README
  - [x] Problem
  - [x] Solution
  - [x] Agent architecture
  - [x] Setup
  - [x] Demo flow
  - [x] Safety
  - [x] Evaluation
  - [x] Limitations

- [x] Finalise architecture diagram
- [x] Finalise Agent routing / permission diagram
- [x] Finalise measured results
  - [x] Replace target placeholders
  - [x] Label synthetic data clearly
  - [x] Report failed cases honestly

- [x] Finalise local submission description
  - [x] One-line pitch
  - [x] Business value
  - [x] Why agents are necessary
  - [x] Why retained specialists are justified
  - [x] Platform usage, with live providers marked pending
  - [x] Guardrails
  - [x] Evaluation evidence

- [x] Prepare required video / screenshots capture plan
- [x] Verify repository link locally
- [ ] Verify deployed app link
- [ ] Verify demo links / permissions

---

# 20. Final Submission Check — 27 September

- [x] Stop adding non-essential features
- [ ] Merge final approved changes
- [ ] Run clean deployment
- [x] Run full local tests
- [x] Run supported golden scenario
- [x] Run supported local hero demo
- [x] Verify local benchmark numbers
- [x] Verify README / diagrams
- [ ] Verify submission form answers
- [ ] Verify all URLs
- [x] Verify no secrets in repository
- [x] Verify migrations
- [x] Verify demo reset / seed process
- [x] Prepare local fallback demo
- [ ] Get final team approval

---

# 21. Submission Day — 28 September 2026

> **Deadline: 9:00 AM SGT. Submit with buffer.**

- [ ] Open final submission form early
- [ ] Re-check required fields
- [ ] Re-check repository link
- [ ] Re-check deployed application link
- [ ] Re-check video / demo link
- [ ] Re-check team information
- [ ] Re-check project description
- [ ] Re-check measured claims
- [ ] Submit before deadline with buffer
- [ ] Capture submission confirmation
- [ ] Save confirmation reference / screenshot
- [ ] Tag final submitted commit
- [ ] Mark hackathon submission complete

---

# 22. Optional Post-Submission / Finale Preparation

> Only after the submission is safely complete.

- [ ] Review feedback
- [ ] Fix critical demo reliability issues only
- [ ] Improve presentation clarity
- [ ] Rehearse judge Q&A
  - [ ] Why multi-agent?
  - [ ] Why not one agent?
  - [ ] Why does each specialist exist?
  - [ ] What is deterministic vs LLM?
  - [ ] How is prompt injection handled?
  - [ ] How are stale approvals prevented?
  - [ ] How is everything audited?
  - [ ] What did evaluation prove?
- [ ] Prepare finale demo backup

---

# Local hardening classification and closure — 2026-09-19

Classification was performed against the current checkout and then limited to locally completable work:

- **A — completed locally:** repository/test-command verification; local tool-to-kernel mapping; Coordinator and specialist permission coverage; supplier/promotion/delivery/sales-materiality/stale-approval local paths; supported golden/demo preparation and repeat execution; audit/evidence/frontend surfaces; rubric-local evidence; local degraded-condition tests; migration/seed/reset checks; README, architecture, routing, evaluation, demo, submission, and capture-plan documentation; quality/claims/secret scans.
- **B — blocked by the missing inventory-adjustment contract:** inventory-correction route, its safe `KEEP_CURRENT_PLAN`/conditional Procurement behavior, the inventory-correction evaluation fixture, and the inventory-correction Golden Acceptance step. No substitute semantics were added.
- **C — requires live LLM/gateway:** OpenClaw structured-output runtime verification, successful Sonnet/Bedrock request, live model calls, live token usage, live model latency/cost, live-model evaluation, and Bedrock-unavailable runtime verification.
- **D — requires deployment:** deployed backend/frontend/Agent runtime, production-like end-to-end flow, deployed URL verification, and hosted reliability/telemetry.
- **E — optional, external, or undefined:** ChatGPT Project setup/instructions, external team review/submission actions, 30–50 scenario expansion, unsupported business metrics, holiday/snapshot-comparison/safety-stock/storage extensions without a current acceptance contract, persisted human-review workflow semantics, canonical tool-call duration, and final video/screenshots/URLs.

Fresh verification record:

- Full PostgreSQL suite: **773 passed, 2 warnings, exit 0**.
- Database-independent selection including health: **681 passed, 2 warnings, exit 0**.
- Ruff: **exit 0**; Pyright: **0 errors, 0 warnings, 0 informations**; ESLint: **exit 0**; TypeScript: **exit 0**; production build: **exit 0**.
- Alembic empty-database upgrade: **exit 0**, head `20260918_merge_sales_agent_audit`; Alembic check: **exit 0**, no new operations.
- Seed twice on the named disposable migration DB: **both exit 0**.
- Golden demo prepare: **exit 0**; two golden demo runs: **both exit 0**; 5 scenarios × 3 adapters, 0 failed executions each run, stable runtime evidence fingerprints.
- Screenshot-disabled frontend evidence assertions: **exit 0**.
- `git diff --check`: **exit 0**. Secret-value scan: **no matches**. Pre-existing untracked artifacts were preserved and not staged.

Open items intentionally retained: inventory-adjustment contract, undefined persisted human-review workflow, live LLM/OpenClaw/AWS, deployment, live-model metrics, real business outcomes, and external submission URLs/video/actions.
