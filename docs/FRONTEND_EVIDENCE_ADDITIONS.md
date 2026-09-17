# Intraday monitoring and procurement evidence

Local implementation, 17 September 2026. Not pushed.

## User-facing additions

- **Intraday sales** navigation: selected service-day reporting window, ten-second polling with pause/manual refresh, correction-aware report totals, explicit gaps and boundary-crossing exclusions, and overlap suppression. No live POS connection is implied.
- Recipe-implied ingredient usage uses exact decimal multiplication and current catalogue recipes. It is not measured depletion or waste.
- Backend estimated-stock snapshots at the window start, latest included report end, and window end show usable stock, coverage and uncovered consumption. They are not forecast projections.
- **Activity → Assessments** exposes operational/knowledge cutoffs, input revision, contract capture status, missing offer history, completion time and plain-language recorded outcomes.
- Run-to-recommendation links request the exact version through `/plans/{version_id}`. Missing versions display an error instead of selecting another recommendation.
- **Recommendations → Policy** browses persisted immutable versions, service coverage, constraints, deterministic tags, all frozen offers/opportunities and opening-lot provenance.
- **Recommendations → Forecast** displays versioned historical inputs separately from the still-unavailable forecast output.
- Runs with frozen contracts display their exact policy/domain/input evidence, not the latest catalogue terms.
- Inventory explains the shared FEFO order: expiry, receipt time, lot ID.

## Manager API boundary

Three new read-only manager-session routes reuse canonical Backend schemas and validation:

- `GET /api/v1/manager/procurement-policies`
- `GET /api/v1/manager/procurement-policies/{policy_id}/versions/{version}`
- `GET /api/v1/manager/runs/{run_id}/procurement-evidence`

The display response whitelists policy, approved domain and forecast input. Arbitrary `frozen_state` is excluded. Agent-only routes keep their existing role requirements. No agent token is sent by the browser; no policy-editing or purchasing workflow was added.

The development database was upgraded using the two existing additive migrations to `20260917_forecast_input`, then the existing insert-only seed was run. No migration or seed code was changed. Existing records are preserved by `ON CONFLICT DO NOTHING`. A canonical read verified CASH_SLICE_V1 v1, 24 offers, 24 opportunities and four historical observations.

## Verification

- TypeScript, ESLint and production build passed during implementation.
- `node --test tests/intraday.test.cjs`: five arithmetic/correction/coverage tests passed.
- Existing `tests/browser-smoke.cjs`: passed against an isolated production preview with intercepted API responses.
- `tests/evidence-browser.cjs`: passed for correction totals, overlap suppression, estimates, policy/domain/history, mobile overflow, run evidence, exact-version errors and absence of agent credentials/writes.
- `tests/test_manager_evidence_unit.py`: passed using canonical seed artifacts and an isolated FastAPI app with mocked database access. Tests manager role enforcement and response exclusion, not database persistence.
- PostgreSQL-backed `tests/test_procurement_contract.py`: seven tests passed, including manager/agent boundaries, missing versions, missing run contracts and exact frozen-run responses.
- `tests/test_access.py`, `tests/test_sales.py`, and the isolated manager-evidence test: 17 tests passed together. Database tests used disposable, uniquely named test databases.
- `tests/live-evidence-browser.cjs`: real manager login, policy/24-offer/24-opportunity read, historical inputs and estimated inventory passed against the local application. No operational records were created; only the test's login/logout session changed.
- Ruff and Pyright passed for the changed backend modules/tests; browser screenshots were inspected. Mobile overflow checks cover sales, policy and forecast-history panels.

An initial Windows listener check did not detect PostgreSQL, but a subsequent direct TCP/database check succeeded. This is no longer a verification blocker.

## Still deliberately unavailable

Real forecast outputs, shortage projections, integrated engine-generated plans/search certificates, automatic materiality, emergency/contingency calculations, measured waste and full agent tool narratives remain clearly separated from the new evidence displays.

## Local checks

From `apps/web`, run TypeScript, ESLint, `next build`, and the two browser test scripts against a local production preview. Set `UI_TEST_URL` and `PLAYWRIGHT_MODULE` when using an external Playwright installation.

From `services/api`, run `pytest tests/test_manager_evidence_unit.py`. With PostgreSQL available and `TEST_DATABASE_URL` pointing to a role allowed to create disposable test databases, run `pytest tests/test_procurement_contract.py`. The existing fixture creates uniquely named test databases and removes only those databases afterward.

The optional live browser check requires `RESTOCK_TEST_PASSWORD` supplied securely, plus `PLAYWRIGHT_MODULE` and optionally `UI_TEST_URL`. It must never be replaced by hardcoded credentials. The application is available locally at port 3002 with the API at port 8000.
