# Local Hardening and Submission Preparation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exhaust locally-completable hardening and submission-preparation work without changing the inventory-adjustment contract, human-review semantics, live integrations, or deployment.

**Architecture:** Preserve the current Backend-authoritative Coordinator/specialist topology and deterministic decision engines. This pass verifies existing behavior, tightens reproducibility and claims, and documents the real local evidence rather than adding new domain behavior.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy/PostgreSQL, Alembic, pytest, Ruff, Pyright, Next.js, TypeScript, ESLint, existing local demo/evaluation harness.

**Spec:** User-approved local hardening and submission-preparation request in the active task.

## Global Constraints

- Stay on the current `agent/coordinator-control-plane` branch; do not create, switch, push, or merge branches.
- Do not implement or infer the authoritative inventory-adjustment event contract.
- Do not implement persisted human-review workflow semantics that are not defined by the Backend.
- Do not use live LLM/OpenClaw/Sonnet, AWS/Bedrock, deployment, screenshots, or external submission actions.
- Preserve pre-existing untracked artifacts and never stage them.
- Limit destructive database operations to explicitly named disposable local databases.
- Prefer documentation and verification; change code only for a concrete failing test, reproducibility issue, or quality defect.

### Task 1: Audit and classify the task ledger

**Files:**
- Modify: `docs/AGENTS_TASKS.md`

- [x] Classify unchecked work quickly into local A, inventory-contract B, live-LLM C, deployment D, or optional/post-submission E.
- [x] Mark only items directly proven by current tests, code, or local demo as complete.
- [x] Add concise dated closure notes for remaining blockers and pending external work.

### Task 2: Run and harden the local verification matrix

**Files:**
- Modify: only concrete test/code files exposed by a failing check.

- [x] Run PostgreSQL and database-independent backend suites and focused Agent, safety, lifecycle, optimiser, materiality, audit, evaluation, golden/demo, and evidence tests.
- [x] Run frontend lint, TypeScript, production build, and permitted browser assertions without screenshots.
- [x] Verify migrations base-to-head, Alembic check, Pyright, Ruff, git diff check, and secret scan.
- [x] Fix only concrete failures, then rerun the affected and full checks.

### Task 3: Prove disposable reset and demo repeatability

**Files:**
- Modify: existing demo/reset documentation or scripts only if a reproducibility issue is proven.

- [x] Use explicitly named disposable PostgreSQL databases for migration, seed, reset, and repeat-run checks.
- [x] Record seed idempotency, clean reset, stable fingerprints, no duplicate commitments/plans/events, and evaluator/runtime separation.
- [x] Do not touch shared or production databases.

### Task 4: Finalize repository documentation and submission material

**Files:**
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: existing evaluation/demo documentation as appropriate
- Create or modify: local submission/evaluation/demo checklist documentation if a suitable existing file is absent

- [x] Document problem, solution, architecture, routing permissions, deterministic/LLM boundary, setup, demo, safety, evaluation, limitations, and current measured evidence.
- [x] Include Mermaid/text diagrams grounded in the current implementation.
- [x] State live model, AWS, deployment, live token/cost, real-world savings, and missing inventory-adjustment/human-review items as pending where applicable.
- [x] Prepare the exact screen/state capture checklist without taking screenshots or running screenshot automation.

### Task 5: Final verification and focused commits

**Files:**
- Modify: `docs/AGENTS_TASKS.md` with final exact counts and open-item status.

- [x] Re-run the strongest available matrix after edits.
- [x] Verify only intended files are staged; exclude all pre-existing untracked artifacts.
- [x] Create focused commits for local hardening/tests and documentation/ledger updates; do not push or merge.
- [x] Record final commit SHAs and exact command exit statuses.

## Final local verification record

- Focused documentation and ledger commits were created; final SHAs are reported in the completion handoff.
- Backend PostgreSQL suite: exit 0, `773 passed, 2 warnings`.
- Database-independent suite: exit 0, `681 passed, 2 warnings`.
- Ruff, Pyright, ESLint, TypeScript, production build, Alembic upgrade/check, sequential seed, local demo repeat, screenshot-disabled browser assertions, `git diff --check`, and secret scan: exit 0.
