# Pass 10 LOCAL evaluation harness

The local harness compares Static, Rule, and Adaptive ReStock executions on one
strict scenario suite. The checked-in suite is
`services/api/tests/fixtures/evaluation/scenarios_v1.json` and references the
existing Backend, Decision Engine, synthetic-history, and offline-Agent
fixtures; it does not create a second simulator or truth representation.

Each `ScenarioManifest` has a runtime projection containing only the initial
authoritative state, observed events, and policy/configuration versions. The
expected outcome and `hidden_evaluator_truth` fields are evaluator-only and are
never included in snapshots, tools, prompts, or Agent context. Sales-materiality
is represented by an open scenario until the ML-owned contract is available.

`StaticBaselineAdapter` invokes its deterministic planning kernel once.
`RuleBaselineAdapter` uses the same kernel and applies only explicit
deterministic routing/replanning rules. `BackendAgentAdapter` invokes the real
Backend lifecycle, `BackendProcurementTools`, Decision Engine artifacts, and
the local scripted Coordinator/specialists. A session factory supplied to the
adapters must provide an isolated seeded Backend state for each comparison.

`EvaluationRunner.run_to_json(...)` writes a machine-readable result containing
per-scenario configuration, outcome, routing, specialist/tool/retry counts,
deterministic evidence, business-metric availability, failure/escalation
details, and local timing, followed by aggregate summaries. Local token and
live model-call metrics are explicitly `pending`; unavailable simulator
business metrics are explicitly `unsupported`, never zero-filled.

## Golden/demo preparation

The local golden pass selects five runnable scenarios from the canonical suite:

- supplier replanning (`development-supplier-availability-001`)
- promotion routing (`development-promotion-001`)
- inventory correction (`development-inventory-correction-001`)
- delivery disruption (`development-delivery-delay-001`)
- exact-version approval/stale-version handling (`development-stale-approval-001`)

Prepare a reviewable, evaluator-truth-free scenario sheet with:

```powershell
.venv\Scripts\python.exe -m src.evaluation.local_demo prepare `
  --manifest tests/fixtures/evaluation/scenarios_v1.json `
  --output .tmp/golden-demo.json
```

To execute the five scenarios through the real Backend planning kernel,
Coordinator, local specialists, and evaluation adapters, first migrate a
dedicated database whose name begins with `restock_demo_`. The runner resets and
reseeds only that explicitly dedicated database before every system/scenario
run, then writes per-system results and aggregate metrics:

```powershell
$demoDatabase = "postgresql+psycopg://.../restock_demo_local"
$env:DATABASE_URL = $demoDatabase
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m src.evaluation.local_demo run `
  --manifest tests/fixtures/evaluation/scenarios_v1.json `
  --database-url $demoDatabase `
  --output .tmp/golden-evaluation.json
```

The output contains separate `evaluation` and `approval_flow` sections. The
approval section uses the real local Agent publication path, changes an
authoritative input, attempts approval of the exact old version, and records
the resulting stale error plus the persisted audit reference. The output
preserves failures, routing, specialist/tool counts, validation and approval
outcomes, plus explicit `pending`/`unsupported` metrics. It does not include
evaluator-only expectations, private prompts, scratchpads, or raw frozen state.
The sales-materiality scenario remains open and is not selected.
