# Pending feature integration — frontend handoff

26 September 2026 · local `feat/frontend-final-design` · for CY, Aniq and Rudy.

Update: bounded first-slice forecast/projection results are now connected. See [the current calculation-results handback](FRONTEND_CALCULATION_RESULTS_HANDOFF.md). The disconnected forecast/projection descriptions below are the historical preparation request, not current availability. Waste and full-economic integration remain pending; optional-scope wording below requires reconciliation with Aniq's later handoff.

## What has been prepared

Frontend preparation is now available for forecast results, general stock projections, waste entry and economic results. **These are not newly completed integrations or working demo features.** No backend/Agent/ML contracts were changed and no new endpoint was invented. Delivery branch: `feat/frontend-final-design`; do not merge to main before team review.

Review page: `http://localhost:3025/workspace/preparation` (requires manager login). It is deliberately absent from the five-area demo navigation, and clearly labelled integration preparation. Normal demo workflows remain unchanged. No sample forecasts, stock projections or cost results are supplied to this page.

| Area | Frontend work prepared | Still blocked on |
| --- | --- | --- |
| Forecast results | Bucket/dish result table, method, horizon, censored-history indicator, completeness/warnings, provenance, disconnected/loading/empty/error states | Authoritative stored output plus an agreed manager read boundary |
| Stock projections | Per-cutoff ingredient balances, expected arrivals, use, expiry loss, shortfall, coverage; existing-only versus with-recommendation distinction | Engine-owned projection semantics and version-bound manager output |
| Waste entry | Batch/quantity/unit/time/note form layout; temporary fields and reset; submission explicitly disabled | Agreed waste persistence, inventory effect, eligibility and correction contract |
| Economic results | Stored component/total display, explicit scope, exact decimal strings, completeness/optimality distinctions | Agreed economic objective/horizon and stored certified outputs; the full scorer is not frontend work |

Tables are the first display slice. Forecast/projection charts and drill-down filters are not finished; those should follow agreement on buckets, units and completeness semantics. No inference, FEFO simulation, forecast, optimisation or economic total is computed in the browser.

## Files and intended integration

- `apps/web/lib/prepared-results.ts`: proposed **frontend display models**, not an approved Backend schema.
- `apps/web/components/prepared-feature-views.tsx`: reusable forecast/projection/economics result components, provenance and unavailable states, disabled waste scaffold.
- `apps/web/app/workspace/preparation/page.tsx`: disconnected review page.
- `apps/web/tests/prepared-features.test.cjs`: isolated rendering tests; artificial inputs exist only in tests.
- `apps/web/tests/preparation-browser.cjs`: preparation-page checks, no operational writes or speculative feature endpoints.

CY does not need to implement these camelCase models verbatim. Agree the canonical persisted wire schema first; ET will map it into display models via a typed manager-session adapter. On connection, runtime validation must reject incompatible/ambiguous payloads rather than defaulting missing values. Existing `api()` supplies manager cookie authentication and session-expiry handling; no Agent token belongs in the frontend.

## Existing evidence to reuse, not duplicate

Current manager routes already expose procurement policy/domain and captured commitment evidence, plus sales-materiality and inventory-adjustment records:

- `/api/v1/manager/procurement-policies`
- `/api/v1/manager/procurement-policies/{policy_id}/versions/{version}`
- `/api/v1/manager/runs/{run_id}/procurement-evidence`
- `/api/v1/manager/runs/{run_id}/sales-materiality`
- `/api/v1/manager/runs/{run_id}/inventory-adjustment`

These are useful existing evidence sources, **not proof of a general forecast/projection result feed**. Sales materiality contains forecast-related evidence and may be reusable after agreeing scope. Agent-only staged contingency artifacts must not be called with manager credentials. Agree whether to extend an existing safe read artifact or provide a separate persisted manager read; this handoff does not prescribe new URL names.

## Decisions / outputs needed from teammates

### 1. Forecast — Aniq + CY

Aniq: identify the canonical forecast output and method/version tags. CY: identify persistence, discovery/selection and the manager read boundary.

The display needs:

- Artifact identity, version, associated assessment/run, operational cutoff, knowledge cutoff and captured state revision.
- Explicit horizon, Singapore timezone, service buckets (start/end, boundary convention), dish IDs/names and predicted portion values.
- Coverage/completeness, missing versus zero values, censored-history flags and warnings. Confirm whether portions are fractional expectations or rounded values.
- How to select the result for a run/plan/service date without silently replacing historical output with a newer artifact.

**Forecast inputs are not forecast outputs.** Do not extrapolate a bounded first-slice result into a general 21-day forecast. Frontend will not generate a fallback forecast.

### 2. Projection — Aniq + CY

Confirm the source calculation and horizon/bucket semantics. Return version-bound ingredient/time outputs with units, usable balance, expected arrivals, projected use, projected expiry loss, shortfall and coverage status.

- Explicitly distinguish existing commitments only from a projection including a particular recommendation version.
- Clarify whether arrivals are received facts, outstanding fixed commitments or proposed purchases; prevent double counting. Define aggregation and start/end-of-bucket balance semantics.
- Preserve lot provenance/expiry evidence where supported. Apply the agreed expiry/FEFO rules upstream, not in browser code.
- Identify storage/budget/stockout warnings and whether unknown/incomplete balances can be displayed, with limitations.

A projected expiry loss is **not staff-measured waste**. The existing counted/estimated inventory views continue to work separately.

### 3. Waste — CY, with Aniq/Rudy semantics review

This is an optional scope decision, not a mandatory expansion of the MVP. If the team keeps waste out of scope, retain the scaffold outside demo navigation and do not enable submission.

Before connecting it, agree:

- Append-only observation identity, received lot reference, canonical ingredient unit, exact positive quantity, observed time, recorded time, actor and optional note/reason.
- Eligibility (including expired lots), quantity limits, concurrency/stale handling, idempotent retries, correction/reversal rules and manager authorization.
- Whether a waste entry changes an inventory ledger, affects estimates, or is evidence-only; how it relates to a later physical closing count without deducting twice.
- List/history/read contract and validated write response/errors. Any resulting assessment trigger belongs to Backend/Agent contracts.

No waste history/persistence, final write validation or error/retry wiring has been built yet. The current form cannot submit and does not store a draft in browser storage. Changing tabs clears its temporary inputs. Do not infer waste from unexplained discrepancies.

### 4. Full economic scoring — Aniq, CY, Rudy

Agree whether this is still intended scope and identify the actual approved objective and coverage horizon. Aniq owns scoring; CY owns versioned output persistence and manager-safe reads; Rudy consumes/publishes the validated result through the established assessment flow.

Frontend needs the exact plan/result/policy versions, covered horizon, SGD decimal components, shipment-fee grouping semantics, completeness, feasibility and search/optimality certification. Expected purchase, shipment, emergency, waste, stockout and total values must distinguish zero from unavailable.

`CASH_SLICE_V1` / `NEW_PURCHASE_CASH_ONLY` stays cash-only: it must never be labelled full-horizon economics. Candidate feasibility does not establish search completeness or optimality. The prepared economics view never sums costs, changes policy or fills missing costs with zero.

## Suggested ownership / handback

| Owner | Hand back |
| --- | --- |
| Aniq | Canonical result schemas/semantics, examples from real persisted scenarios, method/objective/version tags and completeness rules |
| CY | Canonical persistence/read or approved write boundaries, manager permissions, migrations if needed, error semantics and stable artifact IDs |
| Rudy | Where those artifacts are attached to runs/plans and which demo scenarios genuinely exercise them; no competing policy schema |
| ET/frontend | Map approved responses, add selectors/charts as justified, wire real waste flow only if approved, place connected tabs in existing areas, test integration |

Please return the canonical schema/endpoint names, real response examples, references and implementation status. **This handoff is a proposal for integration discussion, not approval to replace shared contracts or expand scope.**

## Acceptance before exposing these as working features

1. An authenticated manager can read the exact persisted artifact without Agent credentials.
2. Missing, empty, incomplete, stale and unsupported results remain distinguishable from zero/safe/optimal results.
3. A real Backend/ML result is rendered at its declared horizon; no synthetic data is silently substituted.
4. Existing commitments and proposed purchases remain distinct; existing approval/allocation behaviour is unchanged.
5. If approved, waste write/retry/correction tests prove its inventory effect and avoid double deduction.
6. Frontend lint/build, responsive/error states and a live end-to-end scenario pass. Only then add working tabs to normal navigation.

## Verification scope

Lint/build and six rendering tests pass. Preparation browser tests exercise all four tabs at desktop/mobile sizes, disabled waste submission and reset, and reject operational writes or speculative API requests. These verify frontend preparation, not a completed live integration. Existing mock-data browser checks remain separate from real Backend/Agent/ML acceptance.
