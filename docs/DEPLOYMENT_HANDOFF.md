# Deployment handoff

No hosted target, URL, or teammate-controlled deployment credential was available in the final local validation environment. This is a mechanical handoff for the owner of the selected host, not a claim that the app is deployed. The intended host provider is not fixed in the repository; earlier planning mentioned AWS Lightsail only conditionally.

## Required runtime shape

- One PostgreSQL database reachable by both FastAPI and the assessment worker. Use the same `DATABASE_URL` for both. Apply migrations explicitly before either process starts; the API does not migrate or seed on startup.
- One FastAPI process and one separately supervised `python -m src.assessment_worker --loop` process. The worker polls about every two seconds while idle; it must remain running for queued assessments to progress. Restart both under the host's normal process supervisor. A previous failed run is terminal; submit a fresh assessment after correcting a failure.
- One Next.js frontend built with the intended public API origin. Static `NEXT_PUBLIC_API_BASE_URL` is bundled at build time, so rebuild if that origin changes.
- An HTTPS frontend and HTTPS API on the same site where possible. Set exact frontend and API browser origins in `ALLOWED_ORIGINS`; wildcard is rejected. Use `COOKIE_SECURE=true` and `COOKIE_SAMESITE=lax` for a same-site deployment. If separate sites are unavoidable, use `COOKIE_SAMESITE=none` with secure cookies and verify the browser's third-party-cookie behavior.

## Backend and worker configuration

Populate Backend/worker secrets through the host's secret store or an untracked `.env`. Never put them in `NEXT_PUBLIC_*` values or a committed file.

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | Shared PostgreSQL `postgresql+psycopg://` connection |
| `MANAGER_USERNAME`, `MANAGER_PASSWORD` | Manager login; password must differ from Agent token |
| `AGENT_TOKEN` | Backend/worker Agent boundary; never frontend |
| `ALLOWED_ORIGINS` | JSON list of exact browser origins |
| `COOKIE_SECURE`, `COOKIE_SAMESITE`, `SESSION_HOURS` | Session cookie settings |
| `LLM_GATEWAY_URL`, `LLM_GATEWAY_API_KEY`, `LLM_MODEL` | Organiser's Ollama-compatible gateway route and model |
| `LLM_GATEWAY_TIMEOUT_SECONDS`, `LLM_NUM_PREDICT` | Optional gateway limits; typed decisions cap their budget at 1024 and allow one malformed/schema repair |
| `ENABLE_DEVELOPMENT_CALCULATOR` | Keep `false`; the development calculator is not the production procurement engine |

If this machine's configured HTTP proxy is inherited by the worker, add the gateway **hostname only** to the process's `NO_PROXY` and `no_proxy` before launch. This bypass was needed for live validation on this machine. It is an environment procedure, not a source-code default; verify the hosted network independently.

## Install and start

From `services/api` after setting configuration:

```powershell
uv sync --locked
uv run alembic upgrade head
# Use the synthetic seed only for a deliberately isolated demo database.
uv run python -m src.seed
uv run uvicorn src.main:app --host 0.0.0.0 --port 8000
```

Start the worker as a second supervised process in the same directory and environment:

```powershell
uv run python -m src.assessment_worker --loop
```

From the repository root, build the frontend for the chosen public API origin:

```powershell
$env:NEXT_PUBLIC_API_BASE_URL='https://<api-host>'
pnpm install --frozen-lockfile
cd apps/web
pnpm lint
pnpm build
pnpm start
```

The seed is insert-only, but it introduces synthetic menu, inventory, suppliers, offers, and policy. Do not seed a real operational database unless those demo facts are intentionally desired. The demo date is 16 February 2026 Singapore time.

## Acceptance and restart check

1. Verify `GET /health` → 200 and frontend `/login` loads over HTTPS.
2. Log in using the manager account; verify `/api/v1/auth/me` → 200 and Inventory loads. Inspect `Secure`, `HttpOnly`, SameSite, and allowed-origin behavior in the browser.
3. Verify gateway DNS/TCP/TLS/auth from the worker host without printing credentials or provider content. Start the worker; queue one **new** assessment and confirm it transitions `QUEUED → RUNNING → SUCCEEDED` on the shared database. A successful run may still safely escalate for unsupported domain facts, so inspect outcome separately.
4. Open Activity evidence, Recommendations, and exact-version approval. Confirm that a stale plan returns `PLAN_VERSION_STALE` and that approval never records a Delivery.
5. Restart API and worker with the same environment. Recheck health and queue polling. The API uses `pool_pre_ping=True`; monitor process logs for sanitized errors, and do not log raw model messages, prompts, or secrets.

The remaining external action is to choose/provision the actual HTTPS host and database, provide the organiser gateway access and host secrets, run these commands, and perform the hosted browser/worker smoke test. Do not label the deployment complete before that test.
