# Connected forecast and projection handback

26 September 2026 · delivery branch `feat/frontend-final-design` · main remains unchanged by this frontend handback.

CY's `backend/manager-calculation-results` was merged locally as `dafa02f`, preserving the frontend work and Aniq's main numerical merge. Backend/Agent contracts were not changed by the frontend implementation.

## Working display

Stock & sales → Forecast & projections (`/workspace/calculations`) selects an exact assessment from `/runs` and reads `/manager/runs/{run_id}/calculation-results` using the manager session. No Agent credential, fallback arithmetic or fixture response is supplied to the application.

- Daily baseline shows frozen dish names, method, eligible/matching history counts, flags and history revisions.
- Selected service buckets show the stored promotion state and fractional Decimal strings, separately from the daily baseline.
- Stock projection lets managers select an ingredient and compare existing commitments only with the exact hypothetical candidate. Opening, admitted arrivals, required usage, allocated usage, unmet, expiry and closing values are distinct.
- First shortages, lot provenance, hypothetical supply IDs, source references, clocks, policy/input versions and artifact hash remain visible.
- Historical stale results remain readable with a warning. Missing, incompatible, incomplete and `NOT_RECORDED` outputs are not treated as zero or proof of sufficient stock.

This is the successful normal first-slice artifact, including supported promotions. It is not a general 21-day result catalogue, contingency artifact, standalone sales-materiality forecast or full economic result. Approval and actual purchases remain separate existing workflows.

## Verification

The connected harness creates a disposable migrated/seeded PostgreSQL database, invokes the actual assessment worker and numerical engine using controlled specialist reasoning, starts the real HTTP API, then signs in and reads that persisted result in the production frontend. Browser requests are forwarded to the isolated API, not fulfilled with fixture JSON. The harness stops that API and disposes only its own test database. This does not claim live model/gateway or hosted deployment verification.

Reproduce from `services/api`, with the frontend production server on localhost:3025:

```powershell
$env:PYTHONPATH='.'
$env:PLAYWRIGHT_MODULE='C:/Users/rackm/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright-core'
.venv/Scripts/python.exe ../../apps/web/tests/connected-calculations.py
```

The browser checks manager login, exact run selection/read, forecast values, both projection bases, desktop/mobile overflow and console errors. Adapter tests cover wrong run/schema, malformed/missing quantities, null outputs, stale state and unrecorded results. Backend manager-result tests cover persistence parity, authorization, historical immutability and tamper rejection.

Final local gates: frontend lint and production build passed; 12 adapter/preparation tests passed; 2 PostgreSQL manager-result tests passed; the real connected browser scenario passed through normal Stock & sales navigation at 1440px and 390px with no page errors or document overflow. Screenshots were inspected. Preparation-page browser checks passed, retaining disabled waste submission and disconnected economics. Earlier initial database-unavailable and test-selector/mobile-overflow failures were repaired and rerun; a Windows console encoding failure in the harness success message was also repaired. These are local gates, not a hosted deployment or live reasoning-model acceptance.

## Remaining teammate work

- CY: broader projection/forecast paths and multi-day publication are separate work. Waste needs an approved append-only lifecycle, chronological replay, manager writes/history and validation. Full economics needs authoritative frozen inputs and persisted results.
- Rudy: consume only independently validated complete economic current candidates; diagnostics and future continuation must not become approvable plans or recorded orders.
- Aniq/team: confirm unresolved economic/terminal/continuation/waste policy choices. The older frontend handoff's optional-scope wording conflicts with Aniq's newer mandatory-scope account; do not silently settle that discrepancy through UI code.
- Frontend: waste submission and economic integration remain disabled until those agreed boundaries exist. No policy was activated here.
