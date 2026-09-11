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
  - [ ] Agent config loads
  - [ ] Structured output works

- [ ] Verify Claude Sonnet 4.5 / Bedrock
  - [ ] Successful model request
  - [ ] Failure path tested
  - [ ] Secrets stay out of prompts / logs

- [ ] Connect one real FastAPI tool
  - [ ] Canonical Pydantic request
  - [ ] Canonical Pydantic response
  - [ ] Error codes

- [ ] Build minimal Coordinator
  - [ ] Receive invocation
  - [ ] Read active-plan context
  - [ ] Call one real tool
  - [ ] Produce typed completion payload
  - [ ] Do not mutate plan state directly

- [ ] Connect completion to Backend
  - [ ] `run_id`
  - [ ] `captured_state_revision`
  - [ ] outcome
  - [ ] reason codes
  - [ ] evidence refs
  - [ ] affected plan/version
  - [ ] summary

- [ ] Persist genuine `PLAN-v1`
  - [ ] Backend checks state revision
  - [ ] Backend validates candidate
  - [ ] Backend creates immutable `PENDING_APPROVAL` version
  - [ ] Audit entry written

- [ ] Show first concise trace
  - [ ] Trigger
  - [ ] Agent run
  - [ ] Tool call
  - [ ] Validation
  - [ ] Plan creation

- [ ] Test Pass 1
  - [ ] Happy path
  - [ ] Invalid structured output
  - [ ] Tool exception
  - [ ] Stale state revision
  - [ ] Missing required data

- [ ] Review and commit Pass 1

---

# 4. Coding Pass 2 — Coordinator Control Plane

- [ ] Add invocation modes
  - [ ] `SCHEDULED`
  - [ ] `EVENT`
  - [ ] `MANUAL`

- [ ] Add Coordinator control-plane tools
  - [ ] `get_active_plan`
  - [ ] `get_event_context`
  - [ ] `validate_final_plan`
  - [ ] `record_agent_decision`
  - [ ] `request_human_review`

- [ ] Add final outcomes
  - [ ] `KEEP_CURRENT_PLAN`
  - [ ] `REVISE_PLAN`
  - [ ] `REQUEST_HUMAN_APPROVAL`
  - [ ] `ESCALATE`

- [ ] Add bounded orchestration
  - [ ] Max 2 specialist rounds
  - [ ] Max 6 specialist calls per run
  - [ ] Max 1 retry per failed tool call
  - [ ] No specialist recursion
  - [ ] No specialist-to-specialist calls

- [ ] Add dynamic routing
  - [ ] Call only needed specialists
  - [ ] Support sequential dependencies
  - [ ] Do not waste calls on unrelated specialists

- [ ] Test Coordinator permissions
  - [ ] Cannot approve
  - [ ] Cannot bypass validator
  - [ ] Cannot mutate plan/database directly
  - [ ] Cannot perform specialist calculations itself

- [ ] Review and commit Pass 2

---

# 5. Coding Pass 3 — Procurement & Supply Specialist

> Implement first because supplier disruption is the strongest early replanning route.

- [ ] Create Procurement & Supply Agent
  - [ ] Narrow instructions
  - [ ] Strict input / output schema
  - [ ] Hard tool allowlist
  - [ ] No agent-spawn permission

- [ ] Connect procurement tools
  - [ ] `get_supplier_options`
  - [ ] `check_supplier_feasibility`
  - [ ] `enumerate_supplier_allocations`
  - [ ] `optimise_purchase_plan`
  - [ ] `validate_purchase_plan`
  - [ ] `get_approval_requirement`

- [ ] Support procurement constraints
  - [ ] Availability
  - [ ] MOQ
  - [ ] Pack size
  - [ ] Lead time
  - [ ] Delivery cutoff / schedule
  - [ ] Price
  - [ ] Delivery state
  - [ ] Bounded 2–3 supplier allocation

- [ ] Handle optimiser outcomes correctly
  - [ ] Feasible result
  - [ ] `NO_FEASIBLE_SUPPLIER`
  - [ ] `CALCULATION_INCOMPLETE / SEARCH_LIMIT_REACHED`
  - [ ] `TOOL_FAILURE`
  - [ ] Never treat incomplete search as proven infeasibility

- [ ] Implement supplier-disruption route
  - [ ] Deterministic materiality evidence exists
  - [ ] Coordinator routes Procurement only initially
  - [ ] Shared kernels run
  - [ ] Candidate returned
  - [ ] Backend validates / publishes new plan if needed

- [ ] Prove this specialist earns its existence
  - [ ] At least one scenario where contextual reasoning changes tool sequence or follow-up investigation

- [ ] Review and commit Pass 3

---

# 6. Coding Pass 4 — Demand Specialist

- [ ] Confirm Demand specialist adds real reasoning value
- [ ] Create Demand Agent
  - [ ] Narrow instructions
  - [ ] Strict input / output schema
  - [ ] Hard tool allowlist
  - [ ] No agent-spawn permission

- [ ] Connect demand tools
  - [ ] Sales context
  - [ ] Promotion context
  - [ ] Historical demand context
  - [ ] Forecast demand
  - [ ] Compare forecast versions

- [ ] Support demand cases
  - [ ] Promotion
  - [ ] Demand spike / drop
  - [ ] Seasonal / weekday effects
  - [ ] Holiday context
  - [ ] Forecast uncertainty
  - [ ] Missing sales interval

- [ ] Keep materiality authority deterministic
  - [ ] Specialist interprets evidence
  - [ ] Specialist never invents authoritative materiality

- [ ] Prove this specialist earns its existence
  - [ ] At least one scenario where contextual reasoning changes investigation / tool order

- [ ] Review and commit Pass 4

---

# 7. Coding Pass 5 — Inventory Specialist

- [ ] Confirm Inventory specialist adds real reasoning value
- [ ] Create Inventory Agent
  - [ ] Narrow instructions
  - [ ] Strict input / output schema
  - [ ] Hard tool allowlist
  - [ ] No agent-spawn permission

- [ ] Connect inventory tools
  - [ ] Inventory snapshot
  - [ ] Estimated inventory
  - [ ] Ingredient requirements
  - [ ] Expiry risk
  - [ ] Stockout risk
  - [ ] Snapshot comparison

- [ ] Support inventory cases
  - [ ] Physical stocktake correction
  - [ ] Wastage / manual adjustment
  - [ ] Expiry risk
  - [ ] Safety stock
  - [ ] Incoming deliveries
  - [ ] Estimated stock between stocktakes
  - [ ] Storage constraints

- [ ] Keep inventory language accurate
  - [ ] Physical count = physical
  - [ ] Between-stocktake balance = estimated / inferred
  - [ ] Unknown stays unknown

- [ ] Prove this specialist earns its existence
  - [ ] At least one scenario where contextual reasoning changes investigation / tool order

- [ ] Review and commit Pass 5

---

# 8. Coding Pass 6 — Full Dynamic Replanning

- [ ] Integrate deterministic materiality kernel
  - [ ] Affected IDs
  - [ ] Threshold / feasibility evidence
  - [ ] Evidence refs
  - [ ] Freshness check

- [ ] Implement promotion route
  - [ ] Demand
  - [ ] Inventory if needed
  - [ ] Procurement if needed

- [ ] Implement inventory-correction route
  - [ ] Inventory
  - [ ] Procurement only if sourcing changes

- [ ] Implement supplier-disruption route
  - [ ] Procurement first
  - [ ] Inventory only if exposure needs reassessment

- [ ] Implement complex multi-domain route
  - [ ] Demand -> Inventory -> Procurement when justified
  - [ ] Coordinator can perform bounded second investigation round

- [ ] Implement `KEEP_CURRENT_PLAN`
- [ ] Implement `REVISE_PLAN`
  - [ ] Backend validates
  - [ ] Backend invalidates / supersedes old version as appropriate
  - [ ] Backend creates new `PENDING_APPROVAL` version
- [ ] Implement `REQUEST_HUMAN_APPROVAL`
- [ ] Implement `ESCALATE` with correct reason / detail

- [ ] Review and commit Pass 6

---

# 9. Coding Pass 7 — Approval and Plan Safety

- [ ] Implement exact-version approval
  - [ ] `plan_id`
  - [ ] `plan_version`
  - [ ] approver
  - [ ] timestamp
  - [ ] decision

- [ ] Implement stale-approval rejection
  - [ ] Old plan reviewed
  - [ ] State changes
  - [ ] New plan created
  - [ ] Old approval returns `PLAN_VERSION_STALE`

- [ ] Implement lifecycle transitions
  - [ ] `PENDING_APPROVAL -> APPROVED`
  - [ ] `PENDING_APPROVAL -> REJECTED`
  - [ ] `PENDING_APPROVAL -> INVALIDATED`
  - [ ] `PENDING_APPROVAL -> SUPERSEDED`
  - [ ] `APPROVED -> INVALIDATED`
  - [ ] `APPROVED -> SUPERSEDED`

- [ ] Confirm no Agent approval authority
- [ ] Confirm no real order placement / payment

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
  - [ ] Supplier availability
  - [ ] Shelf life
  - [ ] Recipe quantity
  - [ ] MOQ / pack size
  - [ ] Lead time
  - [ ] Promotion details
  - [ ] Inventory freshness

- [ ] Test prompt injection
  - [ ] Manager text tries to override policy
  - [ ] Supplier text contains instructions
  - [ ] Promotion text contains instructions
  - [ ] Attempt to add unapproved supplier
  - [ ] Attempt to change MOQ / budget
  - [ ] Attempt to bypass approval
  - [ ] Attempt to treat unknown as available

- [ ] Test tool permissions
  - [ ] Specialists cannot use another domain's tools
  - [ ] Specialists cannot call agents
  - [ ] Specialists cannot mutate plan state

- [ ] Review and commit Pass 8

---

# 11. Coding Pass 9 — Business Audit Trail

- [ ] Persist Coordinator runs
  - [ ] `run_id`
  - [ ] trigger
  - [ ] plan/version
  - [ ] captured state revision
  - [ ] start/end
  - [ ] outcome / reason

- [ ] Persist specialist calls
  - [ ] `agent_call_id`
  - [ ] parent run
  - [ ] objective
  - [ ] context refs
  - [ ] structured result
  - [ ] status / timing

- [ ] Persist tool calls
  - [ ] `tool_call_id`
  - [ ] parent agent call
  - [ ] tool name
  - [ ] request schema version
  - [ ] evidence / result refs
  - [ ] success / failure
  - [ ] duration
  - [ ] error / termination code

- [ ] Persist business decision events
  - [ ] Event
  - [ ] Materiality evidence
  - [ ] Routing
  - [ ] Tool use
  - [ ] Validation
  - [ ] Plan transition
  - [ ] Approval
  - [ ] Final outcome

- [ ] Keep audit history append-only
- [ ] Expose concise timeline to frontend
- [ ] Do not store hidden chain-of-thought

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
