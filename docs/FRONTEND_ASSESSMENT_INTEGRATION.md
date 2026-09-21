# Assessment evidence integration — 21 September 2026

Status: implemented and verified locally. No commit or push performed for this slice.

## Scope and implementation

| Requirement | User-facing location | Evidence source |
| --- | --- | --- |
| Structured stock correction history | Daily update closing tab and Activity timeline | INVENTORY_ADJUSTED events: before/after quantities, signed difference, actor, effective time and revision references |
| Incomplete-calculation explanation | Assessment evidence and exact-run page | Recorded CALCULATION_INCOMPLETE outcome/reason; never presented as no purchase needed |
| Forecast activity semantics | Procurement policy/input evidence | Canonical activity_semantics; historical runs missing the field remain explicitly unavailable |
| Fixed existing-purchase evidence | Frozen run policy panel | Captured commitment_projection, received/cancelled/outstanding quantities and expiry provenance |
| Sales and stock correction results | Expandable assessment panels | Manager-only read endpoints wrapping Backend-owned persisted result contracts |
| Disruption-to-assessment links | Delivery disruption history and Activity | Persisted event/run association, not inferred from the latest run |

Exact run pages use `/workspace/activity/{runId}`. Recommendation detail links to its recorded run, and run-to-plan links retain the exact plan version.

## Read boundaries

- `GET /api/v1/manager/runs/{run_id}/sales-materiality`
- `GET /api/v1/manager/runs/{run_id}/inventory-adjustment`
- `GET /api/v1/manager/events/{event_id}/assessments`
- Existing manager procurement display includes activity semantics and frozen commitments.

No engine request, arbitrary frozen_state, or agent credentials are exposed by the new sales display. Existing agent-only routes remain unchanged. Missing assessments return null for an existing run; unrelated errors and unknown runs remain errors. The UI distinguishes absent, requested, incomplete, unknown, material and complete/non-material results.

## Verification performed

- Production Next.js build and TypeScript: passed.
- ESLint for the four new components: passed.
- Ruff for changed API modules and manager unit test: passed.
- Seven database-independent manager/materiality/inventory-adjustment tests: passed.
- Expanded evidence browser suite: passed using intercepted API fixtures. Covers correction history, exact assessment navigation, distinct delivery-event links, frozen purchase quantities/provenance, recorded activity rules, missing/requested results, incomplete/null semantics, completed non-material result, and viewport overflow at 390/768/1440 pixels. Browser requests are GET-only and contain no Authorization token.
- Assessment screenshots reviewed. These browser results prove rendering against fixtures, not live agent integration.

## Database and live verification

PostgreSQL subsequently became available on 127.0.0.1:5432. The procurement and sales-materiality contract tests passed (nine tests); the inventory-adjustment contract test passed after correcting an existing string-format assertion to compare exact Decimal values (`0.500` equals `0.5`). No runtime quantity calculation was changed. These tests exercise persisted manager results, agent-role rejection, event/run association and frozen contract display using disposable databases.

Reproduce from services/api with TEST_DATABASE_URL set securely:

`pytest tests/test_procurement_contract.py tests/test_sales_materiality_contract.py tests/test_inventory_adjustment_contract.py`

The existing live browser check passed on localhost:3002: real manager login, canonical policy, 24 offers/opportunities, persisted historical input and inventory reads. The isolated port 3012 was correctly rejected by the API origin allowlist; using the already-approved port resolved login without changing CORS settings. Populated new panels were tested with intercepted browser fixtures, while persisted result responses were verified through the database-backed HTTP tests; no claim is made of live agent-generated results. No operational records were written by the live browser check. No migrations or policy activation are added by this frontend slice.

## Deliberately outside this slice

Agent execution, forecast publication, multi-day projection APIs and physical simulator APIs are not implemented here. The frontend displays persisted evidence only and does not calculate or certify materiality itself.
