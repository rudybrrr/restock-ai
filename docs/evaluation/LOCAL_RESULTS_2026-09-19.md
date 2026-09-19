# Local Evaluation Summary — 19 September 2026

This is a repository-side summary of the provider-free local harness. It reports only freshly measured local evidence from the checked-in tests and two runs of the supported golden demo. It does not report live LLM, AWS, deployment, or business-outcome metrics.

## Scope

- Canonical manifest: 18 rows.
- Runnable rows: 17; one row remains open for inventory correction because the authoritative Backend inventory-adjustment event contract is absent.
- Development/held-out separation: present in the manifest and enforced by tests.
- Supported golden run: 5 development scenarios × 3 local adapters = 15 executions per run.
- Golden scenario families: supplier replanning, promotion, delivery disruption, sales-materiality fail-closed routing, and stale approval.
- Repeated golden runs: 2, against named disposable PostgreSQL database `restock_demo_hardening_20260919`.

## Golden aggregate results

| Adapter | Executions | Failed | Outcome correctness | Routing accuracy | Unnecessary specialist-call rate | Specialist calls/run | Tool calls/run |
|---|---:|---:|---:|---:|---:|---:|---:|
| Static | 5 | 0 | 0.80 | 0.20 | 0.00 | 0.0 | 0.0 |
| Rule | 5 | 0 | 0.80 | 0.80 | 0.20 | 0.0 | 0.0 |
| Adaptive ReStock (local scripted path) | 5 | 0 | 0.60 | 0.40 | 0.40 | 1.2 | 1.2 |

The local adaptive result is reported honestly, including one missed replan and one unnecessary replan in this five-scenario selection. It is not a live-model quality score.

All three adapters had zero retries per run and zero failed executions in the golden output. The stale-approval flow returned `PLAN_VERSION_STALE` and recorded an approval audit reference.

## Repeatability and reset evidence

- Both runs selected 5 scenarios and produced 15 scenario results.
- Runtime evidence projections—scenario ID, adapter, observed-boundary fingerprint, outcome, routing, specialist calls, tool calls, and retries—matched across runs.
- Run IDs, audit IDs, plan IDs, and local latency are intentionally run-specific and were excluded from the repeatability comparison.
- The demo reset/reseeded the dedicated database before each system/scenario run.
- Final disposable demo database counts after the second run were: `events=2`, `planning_runs=2`, `plan_versions=1`, `audit_entries=10`, `deliveries=0`. These counts are the final isolated stale-approval flow, not a claim about all intermediate resets.
- Empty migration database reached Alembic head `20260918_merge_sales_agent_audit`; seed ran twice and preserved one set of canonical rows (`ingredients=8`, `inventory_lots=9`, `supplier_offers=24`, `suppliers=3`).

## Safety and evidence

The full PostgreSQL suite passed 773 tests, including Agent permissions, prompt-injection handling, lifecycle/stale approval, optimiser termination, specialist retention/routing, materiality, audit immutability, evaluation contracts, manager evidence, and local demo contracts. The explicit database-independent selection passed 681 tests after including the health endpoint.

The screenshot-disabled frontend evidence assertions passed for correction-aware totals, usage/overlap handling, estimates, policy/domain/history display, mobile overflow, manager run evidence, exact-version failure, absence of Agent credentials, and absence of browser-side writes outside the intended intercepted flow.

Prompt-injection resistance is covered by the backend permission and offline-agent tests. The five-scenario golden aggregate contains no prompt-injection scenario, so no unsupported golden percentage is assigned to it.

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

The inventory-correction scenario remains explicitly blocked by the missing authoritative event contract. No substitute event semantics or fake evaluation fixture were added.
