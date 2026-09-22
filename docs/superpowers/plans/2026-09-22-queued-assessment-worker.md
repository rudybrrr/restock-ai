# Queued Assessment Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one bounded application worker that claims one queued ReStock assessment, runs the existing typed Coordinator/Backend control plane against the claimed frozen run, and publishes only through the existing Backend lifecycle.

**Architecture:** The worker is a thin composition boundary around `planning.claim_run`, `build_organiser_reasoning_models`, `BackendProcurementTools`, and `run_backend_coordinator`. It returns safe operational metadata from the typed Coordinator execution and catches only the canonical stale exception after Backend stale handling has run. A one-shot module entry point opens the configured SQLAlchemy session, invokes the worker once, and prints only the safe result.

**Tech Stack:** Python, SQLAlchemy, Pydantic, FastAPI application services, PostgreSQL integration tests, pytest, Ruff, and Pyright.

**Spec:** User request: “RUDY WORKER PASS — CLOSE #8, #10 AND AGENT PORTION OF #16”.

## Global Constraints

- Claim at most one queued run using `planning.claim_run(session)`.
- Use the exact `PlanningRun` returned by the claim, including its frozen snapshot and captured revision.
- Build typed models with `build_organiser_reasoning_models(settings)`.
- Construct `BackendProcurementTools(session)` and invoke the existing `run_backend_coordinator` seam.
- Supply only the existing narrow manual-route classifier seam when needed so the normal manager assessment trigger can enter the existing full-planning routes; event routing continues to use Coordinator defaults.
- Persist results only through Coordinator/Backend publication; the worker performs no plan or run writes.
- Do not use `planning.optimise`, OpenClaw, a second Agent framework, polling, queues, Redis, retries, invented defaults, or live organiser inference in tests.
- Preserve Coordinator failure and escalation semantics; only `NO_QUEUED_RUN` and post-publication stale completion are worker result classifications.
- Keep all evidence and publication bound to the claimed run’s captured revision.
- Do not modify Coordinator, shared projection contracts, plan lifecycle semantics, or unrelated Backend/ML/frontend code.
- Do not commit unless the required PostgreSQL tests, full PostgreSQL suite, Ruff, Pyright, and `git diff --check` pass.

### Task 1: Add the bounded worker composition module

**Files:**
- Create: `services/api/src/assessment_worker.py`

**Interfaces:**
- Consumes: `planning.claim_run(session)`, `build_organiser_reasoning_models(settings)`, `BackendProcurementTools(session)`, and `run_backend_coordinator(...)`.
- Produces: `QueuedAssessmentWorkerResult` and `run_one_queued_assessment(session, settings=None)` plus `main()` for one-shot execution.

- [ ] **Step 1: Define safe result types.**

Use an immutable Pydantic result containing only `run_id`, canonical `AgentOutcome`, publication status/reference, and a safe failure classification. Permit `NO_QUEUED_RUN` and `STATE_REVISION_STALE` as boundary classifications; use `completion.escalation_reason` for Coordinator-owned model/tool failures.

- [ ] **Step 2: Implement one claim and the exact production composition.**

Call `planning.claim_run(session)` exactly once. On `NO_QUEUED_RUN`, return a no-work result. For a claimed run, call `build_organiser_reasoning_models(settings)`, construct `BackendProcurementTools(session)`, then pass `claimed.id`, the typed procurement model, procurement tools, and the typed demand/inventory models to `run_backend_coordinator`. Use the existing `manual_classifier` injection point with a fixed `[DEMAND, INVENTORY, PROCUREMENT]` route only because `MANUAL_REASSESSMENT_REQUESTED` intentionally has no default route; event triggers retain Coordinator's existing routing. Do not read current operational tables to rebuild the run.

- [ ] **Step 3: Map only safe execution metadata.**

Use `execution.completion.outcome`, `execution.completion.escalation_reason`, and `execution.publication_result`. Report a publication reference only from the existing `created_plan_version.id`. Catch `StateRevisionStaleError` only around Coordinator execution and return a stale-rejected result after Backend stale handling has marked the run; do not mutate anything from the worker.

- [ ] **Step 4: Add the one-shot module entry point.**

`main()` should load `Settings`, create an engine with `pool_pre_ping=True`, open one `Session`, call `run_one_queued_assessment`, print its JSON-safe operational result, and dispose the engine. It must execute one assessment and exit.

- [ ] **Step 5: Run focused static checks.**

Run `python -m compileall src/assessment_worker.py`, Ruff on the module, and Pyright on the API package before adding integration tests.

### Task 2: Add PostgreSQL worker integration coverage

**Files:**
- Create: `services/api/tests/test_assessment_worker.py`

**Interfaces:**
- Consumes: the normal `client` assessment/event APIs, the new worker entry point, and existing typed specialist decision models.
- Produces: acceptance evidence for real engine publication, event routing/materiality, stale completion, and fail-closed reasoning/tool failure.

- [ ] **Step 1: Build deterministic typed reasoning stubs.**

Implement test-local typed procurement, demand, and inventory models that return only validated `CALL_TOOL`/`COMPLETE` decisions and never calculate quantities. Patch the worker module’s model-builder symbol so the worker still follows the production model injection path without live gateway calls.

- [ ] **Step 2: Add manager assessment to real engine plan coverage.**

POST `/api/v1/assessments`, invoke `run_one_queued_assessment`, and assert the run succeeds with a `REVISE_PLAN` completion, a persisted `PENDING_APPROVAL` plan, and `calculation_mode == ENGINE`. Assert the result was produced through the existing publication result and no `DEVELOPMENT_FIXTURE` candidate was accepted.

- [ ] **Step 3: Add harmless and material event family coverage.**

Use the existing event/API helpers to queue harmless, promotion, supplier, sales, and inventory events. Run one worker invocation per queued run. Assert harmless events keep the current plan without a replacement and each material family either publishes a valid engine revision or returns the canonical typed escalation dictated by the Backend materiality result.

- [ ] **Step 4: Add stale completion coverage.**

POST an assessment, claim it directly, mutate operational state through the normal API, then invoke the Coordinator path for that claimed run. Assert `StateRevisionStaleError` is surfaced only after the Backend marks the run failed with `STATE_REVISION_STALE`, no new active plan is published, and no fixture candidate appears.

- [ ] **Step 5: Add model/tool failure coverage.**

Inject one controlled typed reasoning or tool failure through the existing Coordinator ports. Assert the canonical Coordinator outcome/reason is preserved, no fake plan is created, no fixture fallback is reachable, and no pending plan is published when authoritative calculation did not succeed.

- [ ] **Step 6: Add exact frozen-run contract assertions.**

Capture the claimed run ID and input revision in the test stubs/tools; assert all invocation/delegation/evidence references use that run and revision, and that the worker never supplies a reconstructed current-state snapshot.

### Task 3: Execute required validation and review the diff

**Files:**
- Modify only the worker/test files above unless a narrowly necessary test-harness import adjustment is required.

- [ ] **Step 1: Run the new worker tests.**

Run `python -m pytest tests/test_assessment_worker.py -q` with PostgreSQL configured.

- [ ] **Step 2: Run the required focused regression tests.**

Run the named integration, control-plane, decision-engine, supplier, inventory-correction, sales/materiality, and promotion test modules.

- [ ] **Step 3: Run the full PostgreSQL suite.**

Run the repository’s normal API test command with PostgreSQL and record the complete pass/fail count.

- [ ] **Step 4: Run Ruff, Pyright, and diff checks.**

Run Ruff, Pyright, and `git diff --check`; inspect the diff for unrelated Backend/ML/frontend changes and confirm no live organiser inference or deployment occurred.

- [ ] **Step 5: Decide commit eligibility.**

If and only if every requested check passes, report that the branch is ready without committing unless separately requested. If any required check fails, do not commit and report the exact blocker.
