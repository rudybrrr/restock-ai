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
