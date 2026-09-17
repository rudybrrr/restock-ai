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
  - [ ] Confirm repository starts cleanly
  - [ ] Confirm test commands
  - [ ] Create Agent implementation branch / worktree
  - [ ] Confirm Bedrock / runtime secrets are not committed

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

- [ ] Freeze tool-to-kernel adapter mapping
  - Contract names and envelopes are frozen; adapters and owning kernels are not present in this checkout.
  - [ ] Demand tools -> Aniq forecasting kernels
  - [ ] Inventory tools -> Aniq inventory / requirements kernels
  - [ ] Procurement tools -> Aniq supplier / optimiser kernels
  - [ ] Approval tools -> Chun Yang backend policy / workflow
  - [ ] Audit tools -> Chun Yang backend persistence

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
  - [ ] Call one real tool
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

- [ ] Test Pass 1
  - [ ] Happy path
  - [x] Invalid structured output
  - [ ] Tool exception
  - [x] Stale state revision
  - [x] Missing required data

- [ ] Review and commit Pass 1

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

- [ ] Implement supplier-disruption route
  - [ ] Deterministic materiality evidence exists
  - [x] Coordinator routes Procurement only initially
  - [ ] Shared kernels run
  - [ ] Candidate returned
  - [ ] Backend validates / publishes new plan if needed
  - Deferred Backend dependency: the current one-day first-slice contract has no
    authoritative versioned supplier-change offer/opportunity domain. The Agent
    must not synthesize one.

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
  - [ ] Compare forecast versions

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
  - [ ] Incoming deliveries
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

> Local contract audit (2026-09-18): only supplier availability/status has a
> complete frozen event → materiality → Decision Engine contract in this
> checkout. Promotion revisions are persisted, but the frozen forecasting
> contract neither applies the active promotion revision nor exposes an
> immutable forecast-comparison artifact. Closing-count corrections emit
> `DAILY_UPDATE_SUBMITTED`, not `INVENTORY_ADJUSTED`, and activity-bearing runs
> intentionally lack the first-slice procurement contract. Delivery changes
> preserve event history, but the Inventory adapter rejects commitment-bearing
> snapshots until a commitment-aware projection contract exists. Sales batches
> are revisioned but are not assessment-queue triggers and do not feed the
> frozen forecast input. Do not mark the corresponding routes complete or
> synthesize local semantics around these backend-owned gaps.

- [x] Integrate deterministic materiality kernel for authoritative supplier availability/status changes
  - [x] Affected IDs
  - [x] Threshold / feasibility evidence
  - [x] Evidence refs
  - [x] Freshness check

- [ ] Implement promotion route
  - [ ] Demand
  - [ ] Inventory if needed
  - [ ] Procurement if needed

- [ ] Implement inventory-correction route
  - [ ] Inventory
  - [ ] Procurement only if sourcing changes

- [x] Implement supplier-disruption route for authoritative availability/status changes
  - [x] Procurement first
  - [ ] Inventory only if exposure needs reassessment

- [ ] Implement complex multi-domain route
  - [ ] Demand -> Inventory -> Procurement when justified
  - [ ] Coordinator can perform bounded second investigation round

- [x] Implement `KEEP_CURRENT_PLAN` for non-material supplier events
- [x] Implement `REVISE_PLAN` for material supplier events
  - [x] Backend validates
  - [x] Backend invalidates / supersedes old version as appropriate
  - [x] Backend creates new `PENDING_APPROVAL` version
- [ ] Implement `REQUEST_HUMAN_APPROVAL`
- [x] Implement `ESCALATE` with correct reason / detail for no feasible supplier replacement

- [ ] Review and commit Pass 6

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

- [ ] Review and commit Pass 7

---

# 10. Coding Pass 8 — Safety and Prompt Injection

- [ ] Enforce business rules outside prompts
  - [ ] Approved suppliers only
  - [ ] MOQ
  - [ ] Pack size
  - [ ] Lead time
  - [ ] Delivery cutoff
  - [ ] Storage limits
  - [ ] Safety-stock bounds
  - [ ] Approval policy
  - [ ] State freshness
  - [ ] Plan-version validity

- [ ] Implement fail-closed unknown-data handling
  - [x] Supplier availability at the Coordinator / Procurement orchestration boundary
  - [ ] Shelf life
  - [ ] Recipe quantity
  - [x] MOQ / pack size at the Coordinator / Procurement orchestration boundary
  - [x] Lead time at the Coordinator / Procurement orchestration boundary
  - [ ] Promotion details
  - [ ] Inventory freshness

- [ ] Test prompt injection
  - [x] Manager text tries to override policy
  - [x] Supplier text contains instructions
  - [ ] Promotion text contains instructions
  - [ ] Attempt to add unapproved supplier
  - [x] Attempt to change MOQ / budget
  - [x] Attempt to bypass approval
  - [x] Attempt to treat unknown as available

- [ ] Test tool permissions
  - [x] Procurement cannot use another domain's tools
  - [x] Procurement cannot call agents
  - [x] Procurement cannot mutate plan state

- [ ] Review and commit Pass 8

---

# 11. Coding Pass 9 — Business Audit Trail

- [x] Persist Coordinator runs
  - [x] `run_id`
  - [x] trigger
  - [x] plan/version
  - [x] captured state revision
  - [x] start/end
  - [x] outcome / reason

- [ ] Persist specialist calls
  - [x] `agent_call_id`
  - [x] parent run
  - [ ] objective
  - [x] context refs
  - [ ] structured result
  - [ ] status / timing

- [ ] Persist tool calls
  - [x] `tool_call_id`
  - [x] parent agent call
  - [x] tool name
  - [ ] request schema version
  - [x] evidence / result refs
  - [x] success / failure
  - [ ] duration
  - [ ] error / termination code

- [ ] Persist business decision events
  - [x] Event
  - [x] Materiality evidence
  - [x] Routing
  - [x] Tool use
  - [x] Validation
  - [x] Plan transition
  - [x] Approval
  - [x] Final outcome

- [x] Keep audit history append-only
- [ ] Expose concise timeline to frontend
- [x] Do not store hidden chain-of-thought
  - PostgreSQL-backed supplier-replanning verification now covers deterministic materiality, Coordinator routing, Procurement tool calls, candidate validation, supersession or invalidation, exact-version approval or stale rejection, and final outcome. Promotion, inventory, delivery, and Demand audit paths remain open.

- [ ] Review and commit Pass 9

---

# 12. Coding Pass 10 — Evaluation Harness

> Use Aniq's shared scenario manifests, simulator truth, and business metrics.

- [ ] Freeze scenario manifest format
  - [ ] Inputs
  - [ ] Events
  - [ ] Expected deterministic truth
  - [ ] Expected routing
  - [ ] Expected outcome
  - [ ] Expected escalation reason / detail

- [ ] Cover scenario families
  - [ ] Normal planning
  - [ ] Promotion
  - [ ] Demand spike / drop
  - [ ] Inventory correction
  - [ ] Wastage / expiry
  - [ ] Supplier shortage / delay / cancellation
  - [ ] Price change
  - [ ] Complex combined events
  - [ ] Missing data
  - [ ] No feasible supplier
  - [ ] Optimiser search limit
  - [ ] Prompt injection
  - [ ] Stale approval

- [ ] Build Static baseline
- [ ] Build Rule-based baseline
- [ ] Run adaptive ReStock with same tools / observed data

- [ ] Measure Agent metrics
  - [ ] Routing accuracy
  - [ ] Unnecessary specialist-call rate
  - [ ] Structured-output validity
  - [ ] Keep / revise / approval / escalation accuracy
  - [ ] Missed replans
  - [ ] Unnecessary replans
  - [ ] Prompt-injection resistance
  - [ ] Policy-violation rate
  - [ ] Calls / latency / token usage

- [ ] Measure business metrics
  - [ ] Food waste
  - [ ] Stockouts
  - [ ] Lost sales
  - [ ] Procurement cost
  - [ ] Emergency-order cost
  - [ ] Total operational cost
  - [ ] Manual interventions

- [ ] Separate development and held-out cases
- [ ] Freeze evaluated config before held-out run
- [ ] Preserve failures honestly
- [ ] Reach 30–50 benchmark scenarios

- [ ] Review and commit Pass 10

---

# 13. Frontend Agent Evidence

- [ ] Show active plan / status / version
- [ ] Show plan history
- [ ] Show exact pending approval version
- [ ] Show stale approval errors
- [ ] Show event timeline
- [ ] Show Coordinator routing
- [ ] Show specialist calls
- [ ] Show tool-call summaries
- [ ] Show validation result
- [ ] Show concise decision explanation
- [ ] Show benchmark results
- [ ] Review end-to-end UI with Ethan

---

# 14. Golden Acceptance Scenario

- [ ] Start with `PLAN-v2` pending or approved
- [ ] Supplier availability falls
- [ ] Deterministic materiality evidence records affected allocation
- [ ] Coordinator routes only necessary specialist(s)
- [ ] Procurement specialist uses shared supplier / optimiser kernels
- [ ] Candidate passes deterministic validation
- [ ] Coordinator returns `REVISE_PLAN`
- [ ] Backend checks current state revision
- [ ] Backend invalidates / supersedes `PLAN-v2`
- [ ] Backend creates `PLAN-v3 PENDING_APPROVAL`
- [ ] Attempt approval of `PLAN-v2`
  - [ ] Receive `PLAN_VERSION_STALE`
- [ ] Manager approves exact `PLAN-v3`
- [ ] Full event / routing / tool / validation / approval trace is visible
- [ ] Repeat from clean seed successfully

---

# 15. Hero Demo

- [ ] Monday: normal scheduled planning
  - [ ] Demand -> Inventory -> Procurement
  - [ ] `PLAN-v1 PENDING_APPROVAL`
  - [ ] Manager approval

- [ ] Thursday morning: promotion
  - [ ] Demand reassessment
  - [ ] Inventory impact
  - [ ] Procurement revision if needed
  - [ ] New plan

- [ ] Thursday afternoon: supplier shortage
  - [ ] Procurement routed first
  - [ ] Supplier allocation changes
  - [ ] New plan + approval

- [ ] Friday: demand exceeds forecast
  - [ ] Demand reassessment
  - [ ] Inventory exposure
  - [ ] Procurement re-evaluation
  - [ ] Emergency / shortage outcome

- [ ] Show one safety case
- [ ] Show one escalation / failure case
- [ ] Finish with audit trail + benchmark results
- [ ] Rehearse within demo time limit
- [ ] Prepare seeded fallback demo state

---

# 16. Rubric Audit

- [ ] Goal & Scope Definition
  - [ ] Clear user, objective, boundaries, metrics

- [ ] Architecture & Reasoning Loop
  - [ ] Dynamic routing visible
  - [ ] Bounded re-reasoning visible
  - [ ] Explicit state visible
  - [ ] Each retained specialist is justified

- [ ] Tool Use & Integration
  - [ ] Real typed tools
  - [ ] Deterministic calculations
  - [ ] Failure behaviour demonstrated

- [ ] Autonomy & Human-in-the-Loop
  - [ ] Autonomous investigation
  - [ ] Human approval
  - [ ] Stale approval rejection

- [ ] Safety, Security & Guardrails
  - [ ] Prompt injection tested
  - [ ] Permissions tested
  - [ ] Hard rules outside LLM
  - [ ] Unknowns fail safely

- [ ] Observability & Evaluation
  - [ ] Full audit history
  - [ ] Agent / tool traces
  - [ ] Baseline comparison
  - [ ] Held-out evaluation

- [ ] Platform & Tooling Usage
  - [ ] OpenClaw
  - [ ] Claude Sonnet 4.5 / Bedrock
  - [ ] FastAPI / Pydantic
  - [ ] PostgreSQL
  - [ ] End-to-end deployed system

- [ ] Every rubric claim has visible evidence

---

# 17. Deployment and Reliability

- [ ] Coordinate deployment choice with Chun Yang
- [ ] Deploy backend
- [ ] Deploy frontend
- [ ] Deploy / configure Agent runtime
- [ ] Configure Bedrock credentials securely
- [ ] Run database migrations
- [ ] Seed demo data
- [ ] Verify production-like end-to-end flow

- [ ] Test degraded conditions
  - [ ] Bedrock unavailable
  - [ ] Tool unavailable
  - [ ] Stale state
  - [ ] Invalid agent output
  - [ ] Optimiser incomplete search
  - [ ] Duplicate event
  - [ ] Retry path

- [ ] Add infrastructure telemetry only if time remains
  - [ ] OpenTelemetry
  - [ ] CloudWatch
  - [ ] Additional CI observability

---

# 18. Final Hardening

- [ ] Run full test suite
- [ ] Run Agent permission suite
- [ ] Run prompt-injection suite
- [ ] Run approval / stale-version suite
- [ ] Run optimiser termination suite
- [ ] Run full benchmark
- [ ] Run golden acceptance scenario
- [ ] Run hero demo from clean seed

- [ ] Review audit records
  - [ ] No chain-of-thought
  - [ ] No secrets
  - [ ] No missing evidence refs
  - [ ] Historical records remain immutable

- [ ] Review code quality
  - [ ] No duplicated ML / optimiser kernels
  - [ ] No general DB mutation tool exposed to agents
  - [ ] No unnecessary permissions
  - [ ] No decorative specialists
  - [ ] No stale enums / statuses
  - [ ] No target metrics presented as achieved results

- [ ] Freeze submission build
- [ ] Record final commit SHA

---

# 19. Submission Materials

- [ ] Finalise README
  - [ ] Problem
  - [ ] Solution
  - [ ] Agent architecture
  - [ ] Setup
  - [ ] Demo flow
  - [ ] Safety
  - [ ] Evaluation
  - [ ] Limitations

- [ ] Finalise architecture diagram
- [ ] Finalise Agent routing / permission diagram
- [ ] Finalise measured results
  - [ ] Replace target placeholders
  - [ ] Label synthetic data clearly
  - [ ] Report failed cases honestly

- [ ] Finalise submission description
  - [ ] One-line pitch
  - [ ] Business value
  - [ ] Why agents are necessary
  - [ ] Why retained specialists are justified
  - [ ] Platform usage
  - [ ] Guardrails
  - [ ] Evaluation evidence

- [ ] Prepare required video / screenshots
- [ ] Verify repository link
- [ ] Verify deployed app link
- [ ] Verify demo links / permissions

---

# 20. Final Submission Check — 27 September

- [ ] Stop adding non-essential features
- [ ] Merge final approved changes
- [ ] Run clean deployment
- [ ] Run full tests
- [ ] Run golden scenario
- [ ] Run hero demo
- [ ] Verify benchmark numbers
- [ ] Verify README / diagrams
- [ ] Verify submission form answers
- [ ] Verify all URLs
- [ ] Verify no secrets in repository
- [ ] Verify migrations
- [ ] Verify demo reset / seed process
- [ ] Prepare local fallback demo
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
