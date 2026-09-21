# Pass 10 LOCAL Evaluation Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local, deterministic evaluation harness that compares static, rule-based, and scripted Adaptive ReStock runs on one canonical observed-input boundary while preserving evaluator truth, failures, unsupported metrics, and held-out separation.

**Architecture:** First correct historical snapshot revision reconstruction without changing live state-revision checks. Then add a small `src/evaluation` package with strict manifest/result models, a fresh seeded scenario materializer, three adapters over the existing Backend/Decision Engine/Coordinator stack, metric aggregation, and JSON output. Existing synthetic-history, promotion, backend event, and offline Agent artifacts remain the source contracts; no second simulator or live model path is added.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy/PostgreSQL, existing FastAPI services, pytest, Pyright, Ruff, Alembic.

**Spec:** Approved Pass 10 LOCAL design in the conversation; repository contracts in `docs/AGENTS_PLAN.md`, `docs/SHARED_INTEGRATION_CONTRACT.md`, `services/api/TESTING.md`, and `services/api/src/synthetic_history.py`.

## Global Constraints

- Stay on the current `agent/coordinator-control-plane` branch; do not create, push, or merge branches.
- Do not use subagents, organiser gateway, AWS/Bedrock, live LLMs, frontend, or deployment.
- Runtime adapters receive observed inputs only; evaluator-only truth remains outside runtime snapshots, tools, prompts, and Agent context.
- Static is a fair one-shot deterministic planner using the same Backend/Decision Engine boundary; it is not intentionally weakened.
- Rule-based may reuse deterministic kernels, but routing/replanning decisions are explicit and deterministic.
- Live token/model-call metrics are `null`/pending, never zero; unsupported business metrics are explicit open/unsupported values.
- Sales-driven materiality remains open until the ML-owned contract lands.
- Preserve failures, escalations, incomplete searches, and reason/detail exactly.
- Use `services/api/.pytest-tmp-base` as pytest `--basetemp`; keep temporary/cache/log artifacts uncommitted.

---

### Task 1: Correct historical replay revisions

**Files:**
- Modify: `services/api/src/planning.py:68-82,193-201`
- Test: `services/api/tests/test_snapshot_history.py`
- Test: `services/api/tests/test_planning.py` or a focused new unit test beside the replay tests

**Interfaces:**
- `current_state_revision(session)` continues returning the current authoritative revision.
- `_snapshot(session, as_of, run_id, known_at=None, captured_state_revision=None)` uses a revision reconstructed at `known_at` only when it is building a historical replay without an explicit live claim revision.

- [ ] **Step 1: Add regression assertions for replay and live claim boundaries.**

  Extend snapshot-history coverage to assert that a replay with the original `known_at` preserves both state and `procurement_contract.captured_state_revision` after later events, and that two replays at that cutoff are identical. Add a PostgreSQL-backed assertion that a claimed live run stores the current revision and is rejected after a later authoritative event changes it.

- [ ] **Step 2: Run the focused tests and verify the replay test fails only on revision drift.**

  Run from `services/api` with the documented admin URL, `TEMP`/`TMP` pointed to `.pytest-tmp-base`, `--basetemp=.pytest-tmp-base`, and cache under `.tmp/pytest-cache`:

  ```powershell
  .venv\Scripts\python.exe -m pytest -q tests/test_snapshot_history.py tests/test_planning.py --basetemp=.pytest-tmp-base -o cache_dir=.tmp\pytest-cache
  ```

- [ ] **Step 3: Implement cutoff-aware revision counting.**

  Add an optional `known_at` filter to the internal event-count query using `db.events.c.timestamp <= known_at`. Keep `current_state_revision()` calling the unfiltered form. In `_snapshot`, derive the cutoff revision only when `captured_state_revision` is absent; callers such as `claim_next_run` continue passing the live captured revision explicitly.

- [ ] **Step 4: Run the focused tests and the full baseline.**

  Confirm the replay tests, live stale-state tests, and all existing tests pass with exit code 0 and no setup errors.

- [ ] **Step 5: Commit the correctness fix separately.**

  ```powershell
  git add services/api/src/planning.py services/api/tests/test_snapshot_history.py services/api/tests/test_planning.py
  git commit -m "fix(backend): reconstruct historical snapshot revisions"
  ```

### Task 2: Define strict scenario and result contracts

**Files:**
- Create: `services/api/src/evaluation/__init__.py`
- Create: `services/api/src/evaluation/contracts.py`
- Create: `services/api/src/evaluation/manifests.py`
- Test: `services/api/tests/test_evaluation_manifests.py`

**Interfaces:**
- `ScenarioManifest.model_validate_json(...) -> ScenarioManifest`
- `ScenarioManifest.runtime_inputs() -> RuntimeScenarioInputs`
- `EvaluationRunResult`, `EvaluationAggregate`, and `MetricValue` serialize with `model_dump(mode="json")`.

- [ ] **Step 1: Write manifest validation tests.**

  Cover required id/version/split fields, typed observed events, policy/config versions, expected routing/outcome/reason, evaluator-only truth references, extra-field rejection, invalid split, and rejection when hidden truth is embedded in runtime event payloads.

- [ ] **Step 2: Implement frozen Pydantic contracts.**

  Define strict models for scenario identity, observed event payloads, fixture references, expectations, evidence expectations, failure/escalation expectations, runtime projection, per-system outcomes, counts, timing, supported/unsupported metrics, and aggregate summaries. Runtime projection must omit evaluator truth by construction.

- [ ] **Step 3: Add manifest loading and split validation.**

  Implement `load_manifest(path)` and `load_suite(path, split=None)` with deterministic ordering, schema-version checks, held-out/development separation, and explicit `truth_ref` metadata that is never included in `runtime_inputs()`.

- [ ] **Step 4: Run manifest tests and commit the contract layer.**

  ```powershell
  .venv\Scripts\python.exe -m pytest -q tests/test_evaluation_manifests.py --basetemp=.pytest-tmp-base -o cache_dir=.tmp\pytest-cache
  git add services/api/src/evaluation services/api/tests/test_evaluation_manifests.py
  git commit -m "feat(eval): add strict scenario manifest contracts"
  ```

### Task 3: Materialize one observed state boundary

**Files:**
- Create: `services/api/src/evaluation/materializer.py`
- Modify: existing Backend seed/event helper only if a narrow reusable seam is required
- Test: `services/api/tests/test_evaluation_materializer.py`

**Interfaces:**
- `ScenarioMaterializer.materialize(manifest) -> MaterializedScenario`
- `MaterializedScenario.runtime_snapshot -> dict`
- `MaterializedScenario.apply_observed_events(...) -> None`

- [ ] **Step 1: Test truth isolation and repeatability.**

  Assert the materialized runtime snapshot contains only initial state plus observed events, never evaluator truth, and that two fresh materializations of the same manifest yield equal canonical snapshots and state revisions.

- [ ] **Step 2: Implement fresh seeded materialization.**

  Reuse the repository’s PostgreSQL fixture/seed path and existing typed event/service seams. Apply only manifest-declared observed events in manifest order. Do not copy hidden evaluator files into the database or snapshot; do not fill missing values with defaults.

- [ ] **Step 3: Add supported event-family mapping.**

  Map only existing authoritative contracts: normal planning, promotion, inventory correction, supplier availability/status/price, delivery delay/cancellation/shortfall, and typed missing-data/no-feasible/search-limit/stale/prompt-injection fixtures. Mark unsupported families open instead of synthesizing event semantics.

- [ ] **Step 4: Run materializer tests and commit.**

  ```powershell
  .venv\Scripts\python.exe -m pytest -q tests/test_evaluation_materializer.py --basetemp=.pytest-tmp-base -o cache_dir=.tmp\pytest-cache
  git add services/api/src/evaluation/materializer.py services/api/tests/test_evaluation_materializer.py
  git commit -m "feat(eval): materialize isolated observed scenarios"
  ```

### Task 4: Implement the three fair execution adapters

**Files:**
- Create: `services/api/src/evaluation/adapters.py`
- Test: `services/api/tests/test_evaluation_baselines.py`
- Test: `services/api/tests/test_evaluation_agent.py`

**Interfaces:**
- `StaticBaseline.run(materialized) -> SystemRunResult`
- `RuleBaseline.run(materialized) -> SystemRunResult`
- `AdaptiveScriptedAgent.run(materialized) -> SystemRunResult`

- [ ] **Step 1: Write adapter contract tests.**

  Assert all adapters receive the same canonical runtime boundary, static runs one deterministic plan calculation, rule routing is explicit and repeatable, adaptive uses `run_backend_coordinator` plus real Backend tools/lifecycle, and every result preserves outcome, escalation reason/detail, evidence, specialist/tool counts, retries, and failure status.

- [ ] **Step 2: Implement the static one-shot planner.**

  Claim/materialize one Backend run from the observed state, call the existing deterministic engine once, and publish/record the resulting one-shot outcome through the existing lifecycle. It must use the same policy, snapshot, kernels, and hard constraints as the other adapters and must not inspect evaluator truth or future events.

- [ ] **Step 3: Implement deterministic rule routing.**

  Use an explicit mapping from authoritative event type/materiality to the justified specialist/tool sequence. Reuse Backend tools and Decision Engine artifacts. Replan only when deterministic rules say the observed event is material; preserve escalation and incomplete-search errors.

- [ ] **Step 4: Implement the adaptive scripted-Agent path.**

  Invoke the existing Coordinator, local scripted specialist reasoning, real typed tools, and Backend publication/control-plane lifecycle. Keep model/token fields pending and record actual local timing, specialist calls, tool calls, retries, and structured-output validity.

- [ ] **Step 5: Run adapter regression tests and commit.**

  ```powershell
  .venv\Scripts\python.exe -m pytest -q tests/test_evaluation_baselines.py tests/test_evaluation_agent.py --basetemp=.pytest-tmp-base -o cache_dir=.tmp\pytest-cache
  git add services/api/src/evaluation/adapters.py services/api/tests/test_evaluation_baselines.py services/api/tests/test_evaluation_agent.py
  git commit -m "feat(eval): add fair local baseline and agent adapters"
  ```

### Task 5: Add scenario suite and deterministic metrics

**Files:**
- Create: `services/api/tests/fixtures/evaluation/scenarios_v1.json`
- Create: `services/api/src/evaluation/metrics.py`
- Create: `services/api/src/evaluation/runner.py`
- Test: `services/api/tests/test_evaluation_metrics.py`
- Test: `services/api/tests/test_evaluation_runner.py`

**Interfaces:**
- `run_suite(manifest_path, split, output_dir) -> EvaluationAggregate`
- `compute_agent_metrics(results) -> dict[str, MetricValue]`
- `compute_business_metrics(results) -> dict[str, MetricValue]`

- [ ] **Step 1: Define meaningful development and held-out cases.**

  Encode only supported authoritative scenarios, with expected evidence and outcomes defined before execution. Keep sales-driven materiality out of both splits and include explicit open records for unsupported business metrics instead of fake cases.

- [ ] **Step 2: Write metric tests before implementation.**

  Cover routing accuracy, unnecessary specialist-call rate, structured-output validity, KEEP/REVISE/approval/escalation correctness, missed/unnecessary replans, prompt-injection resistance, policy violations, calls/tools/retries, null pending live metrics, failure-preserving aggregates, and canonical evaluator metric passthrough when available.

- [ ] **Step 3: Implement metrics and runner.**

  Run each scenario through a fresh materialization and all three adapters from the identical runtime boundary. Compare to manifest expectations without mutating results. Record per-system timing and counts, exact failure/escalation details, deterministic evidence, config/version ids, and explicit unsupported/open metrics.

- [ ] **Step 4: Implement deterministic JSON output.**

  Write one per-run result file and aggregate summary with stable ordering, schema version, split, scenario/config ids, and no evaluator-only truth. Never discard failed or incomplete runs.

- [ ] **Step 5: Run runner/metric tests and commit.**

  ```powershell
  .venv\Scripts\python.exe -m pytest -q tests/test_evaluation_metrics.py tests/test_evaluation_runner.py --basetemp=.pytest-tmp-base -o cache_dir=.tmp\pytest-cache
  git add services/api/src/evaluation services/api/tests/fixtures/evaluation services/api/tests/test_evaluation_metrics.py services/api/tests/test_evaluation_runner.py
  git commit -m "feat(eval): run shared scenarios and aggregate metrics"
  ```

### Task 6: Update ledger and complete verification

**Files:**
- Modify: `docs/AGENTS_TASKS.md:551-610`
- Modify: `docs/superpowers/plans/2026-09-18-pass-10-local-evaluation-harness.md` if task checkboxes are tracked
- Test/command outputs: repository-local `.pytest-tmp-base` and `.tmp` only; do not commit

- [ ] **Step 1: Mark only proven Pass 10 LOCAL items.**

  Mark manifest freeze, supported scenario families, baselines, local adaptive run, measured supported Agent metrics, development/held-out separation, failure preservation, and supported scenario count only after tests and suite execution prove them. Leave sales materiality, live token/model metrics, live LLM evaluation, and unsupported business metrics open.

- [ ] **Step 2: Run the complete required verification matrix.**

  ```powershell
  .venv\Scripts\python.exe -m pytest -q --basetemp=.pytest-tmp-base -o cache_dir=.tmp\pytest-cache
  .venv\Scripts\python.exe -m pytest -q -m "not postgres" --basetemp=.pytest-tmp-base -o cache_dir=.tmp\pytest-cache
  .venv\Scripts\python.exe -m pyright
  .venv\Scripts\python.exe -m ruff check src tests
  .venv\Scripts\python.exe -m alembic check
  git diff --check
  rg -n -i "(password|secret|token|api[_-]?key|private[_-]?key)\s*[:=]\s*['\"]" services/api/src services/api/tests docs --glob '!*.lock'
  ```

  The PostgreSQL suite must exit 0 with no setup errors. Treat any secret-scan match as a blocker to resolve before commit; documented variable names and test placeholders are acceptable only when no credential value is present.

- [ ] **Step 3: Inspect status and commit documentation separately.**

  ```powershell
  git diff --check
  git status --short
  git add docs/AGENTS_TASKS.md docs/superpowers/plans/2026-09-18-pass-10-local-evaluation-harness.md
  git commit -m "docs(agents): record Pass 10 local evaluation harness"
  ```

- [ ] **Step 4: Confirm only focused commits and no temporary artifacts.**

  Verify `.pytest-tmp-base`, `.tmp` logs/cache, prior untracked artifacts, credentials, and generated results are not staged. Report the exact test/quality exit statuses and any explicitly open semantics.
