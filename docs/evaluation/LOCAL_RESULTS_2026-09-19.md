# Local Evaluation Summary — 19 September 2026

This is a repository-side summary of the provider-free local harness. It reports only freshly measured local evidence from the checked-in tests and two runs of the supported golden demo. It does not report live LLM, AWS, deployment, or business-outcome metrics.

## Scope

- Canonical manifest: 19 rows.
- Runnable rows: 19; safe and material inventory-correction scenarios use the landed Backend PR #32 contract.
- Development/held-out separation: present in the manifest and enforced by tests.
- Supported golden run: 7 development scenarios × 3 local adapters = 21 executions.
- Golden scenario families: supplier replanning, promotion, delivery disruption, safe/material inventory correction, sales-materiality fail-closed routing, and stale approval.
- Golden run: against named disposable PostgreSQL database `restock_demo_20260918`.

## Golden aggregate results

| Adapter | Executions | Failed | Outcome correctness | Routing accuracy | Unnecessary specialist-call rate | Specialist calls/run | Tool calls/run |
|---|---:|---:|---:|---:|---:|---:|---:|
| Static | 7 | 0 | 0.714 | 0.143 | 0.00 | 0.0 | 0.0 |
| Rule | 7 | 0 | 0.714 | 0.714 | 0.143 | 0.0 | 0.0 |
| Adaptive ReStock (local scripted path) | 7 | 0 | 0.714 | 0.571 | 0.286 | 1.286 | 1.143 |

The local adaptive result is reported honestly, including one missed replan and one unnecessary replan in this seven-scenario selection. The inventory-correction rows produced `KEEP_CURRENT_PLAN` for the safe assessment and `REVISE_PLAN` with `INVENTORY` -> `PROCUREMENT` for the material assessment. It is not a live-model quality score.

All three adapters had zero retries per run and zero failed executions in the golden output. The stale-approval flow returned `PLAN_VERSION_STALE` and recorded an approval audit reference.

## Repeatability and reset evidence

- The run selected 7 scenarios and produced 21 scenario results.
- Runtime evidence projections—scenario ID, adapter, observed-boundary fingerprint, outcome, routing, specialist calls, tool calls, and retries—matched across runs.
- Run IDs, audit IDs, plan IDs, and local latency are intentionally run-specific and were excluded from the repeatability comparison.
- The demo reset/reseeded the dedicated database before each system/scenario run.
- Final disposable demo database counts after the second run were: `events=2`, `planning_runs=2`, `plan_versions=1`, `audit_entries=10`, `deliveries=0`. These counts are the final isolated stale-approval flow, not a claim about all intermediate resets.
- Empty migration database reached Alembic head `20260918_merge_sales_agent_audit`; seed ran twice and preserved one set of canonical rows (`ingredients=8`, `inventory_lots=9`, `supplier_offers=24`, `suppliers=3`).

## Safety and evidence

The complete PostgreSQL suite passed 782 tests after the inventory-correction integration. The database-independent synthetic-history suite passed 68 tests with its temp root outside the repository, including the output-boundary guard. The run covered Agent permissions, prompt-injection handling, lifecycle/stale approval, optimiser termination, specialist retention/routing, materiality, audit immutability, evaluation contracts, manager evidence, and local demo contracts.

The screenshot-disabled frontend evidence assertions passed for correction-aware totals, usage/overlap handling, estimates, policy/domain/history display, mobile overflow, manager run evidence, exact-version failure, absence of Agent credentials, and absence of browser-side writes outside the intended intercepted flow.

Prompt-injection resistance is covered by the backend permission and offline-agent tests. The seven-scenario golden aggregate contains no prompt-injection scenario, so no unsupported golden percentage is assigned to it.

## Pending or unsupported metrics

| Metric | Status |
|---|---|
| Live model calls | Pending live OpenClaw/Sonnet access |
| Token usage | Pending live model calls |
| Live model latency | Pending live model calls |
| Live model cost | Pending live model calls |
| Food waste, stockouts, lost sales, procurement cost, emergency-order cost, total operational cost, manual interventions | Unsupported by the current synthetic first-slice harness; never represented as zero |
| Real restaurant/SME savings | Not measured |
| Deployment reliability | Not measured |

The inventory-correction scenarios use canonical `INVENTORY_ADJUSTED` events and a persisted authoritative assessment fixture. No evaluator-only expected outcome is injected into runtime inputs, and no substitute event semantics were added.
