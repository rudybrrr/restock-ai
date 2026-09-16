# Backend: inventory, closing counts, and deliveries

From the repository root, run `docker compose up -d postgres`. Then in `services/api`:

```sh
uv sync --locked
cp .env.example .env
# Fill MANAGER_PASSWORD and AGENT_TOKEN with distinct randomly generated values.
uv run alembic upgrade head
uv run python -m src.seed
uv run uvicorn src.main:app --host 0.0.0.0 --port 8000
```

PowerShell uses `Copy-Item .env.example .env`. Python 3.12 and uv are required.
The PostgreSQL URL must use `postgresql+psycopg://`. Docker's credentials are local development defaults only.
No credentials are seeded. Empty manager/agent credentials disable their respective access.
Migrations are explicit; starting the API does not modify the database. Seed insertion is transactional and
safe to repeat: existing IDs are preserved, never reset or overwritten. Use a new database for a clean demo.

Open [the connection check](http://localhost:8000/connect), sign in, then click **Read inventory**.
[Swagger UI](http://localhost:8000/docs) and `/openapi.json` contain the typed API contracts.
In Swagger, call login first to set the manager cookie, or use **Authorize → HTTPBearer** for the agent token.
See [TESTING.md](TESTING.md) for role-specific Swagger and HTTP scenarios.

## Teammate access

Give your teammate the host's reachable base URL, for example `http://192.168.1.20:8000`, and credentials
through a separate private channel. The teammate opens that URL plus `/connect`; `localhost` on their
machine does not reach your backend. Allow the API port through your firewall on the intended network.
Add the exact browser origin, e.g. `http://192.168.1.20:8000`, to `ALLOWED_ORIGINS` and restart the API.
If the frontend is on port 3000, add that origin too. Cross-origin browser requests must use
`credentials: 'include'`. Wildcard origins are rejected.

Use HTTPS for a hosted demo and set `COOKIE_SECURE=true`. Keep frontend and API on the same site where
possible. If using different sites, use HTTPS on both and `COOKIE_SAMESITE=none`; browser third-party-cookie
policies can still block it. `COOKIE_SECURE=false` is only for deliberate local/LAN HTTP testing.
All browser mutations, including login/logout, require an exact allowed `Origin`, even in command-line clients.

Verify health → login → inventory on the second machine, and check the browser Network panel for HTTP 200
and the seeded lots. This is a manual handover check; local tests do not prove another machine can connect.

## HTTP examples

Use your configured origin and password in the login body (never commit them):

```http
POST /api/v1/auth/login
Origin: http://localhost:8000
Content-Type: application/json

{"username":"manager","password":"<your configured password>"}
```

The response is `200 {"role":"manager","username":"manager"}` with an HttpOnly session cookie.
Retain it for subsequent requests. `GET /api/v1/inventory` returns 200 with nine dated batches;
`GET /api/v1/auth/me` reports the authenticated identity. `POST /api/v1/auth/logout` with the same cookie
and allowed Origin returns 204 and revokes that session in PostgreSQL. Sessions expire after `SESSION_HOURS`.
The agent instead sends `Authorization: Bearer <AGENT_TOKEN>`. It can read but cannot perform manager logout;
future manager mutations must use `require_manager` and `require_browser_origin`.

Protected GET routes under `/api/v1`: `/menu-items`, `/ingredients`, `/recipes`, `/suppliers`,
`/supplier-offers`, `/holidays`, `/inventory`, `/auth/me`. Missing/invalid credentials return 401;
wrong role or Origin returns 403; malformed input returns 422. Errors use
`{"success":false,"error":{"code":"UNAUTHENTICATED","message":"…","retryable":false}}`.
`GET /health` always returns `200 {"status":"ok"}` as a liveness check.

Quantities and money serialize as decimal strings. Ingredients define kg, litres, or pieces;
recipes and offers use that ingredient's unit. Money is SGD. Physical counts retain their timestamp,
including expired historical batches; they do not claim to be estimated/current usable quantities.

## Seed provenance

The synthetic fixture is dated **15 February 2026, 22:00 Asia/Singapore**: five dishes, eight ingredients,
16 recipe lines, three approved suppliers, 24 offers, and nine batches. Supplier terms are explicit demo
assumptions, not live market observations. Two chicken batches have separate expiry dates.
The two Chinese New Year holidays (17–18 February) come from the
[MOM 2026 announcement](https://www.mom.gov.sg/newsroom/press-releases/2025/0616-public-holidays-for-2026).
Holiday rows contain that source URL and imply no demand uplift or closure.

## Verification

Set `TEST_DATABASE_URL` to a PostgreSQL administrative connection whose role can create databases.
Tests create a unique `restock_test_<uuid>` database, migrate and seed it twice, verify behavior through
HTTP, and drop only that generated database in cleanup. They fail explicitly when PostgreSQL is not configured.

```sh
export TEST_DATABASE_URL=postgresql://restock:restock_dev@127.0.0.1:5432/postgres
uv run pytest
uv run pyright
uv run ruff check .
```

PowerShell: `$env:TEST_DATABASE_URL='postgresql://restock:restock_dev@127.0.0.1:5432/postgres'`.
Tests cover stored catalog reads, batch separation, manager sessions, agent permissions, invalid credentials,
logout revocation, CORS and CSRF, closing revisions, deliveries, retries, and atomic audit writes.

## Tickets 2 and 3: interactive daily and delivery flow

Apply `alembic upgrade head` before starting the updated API. In `/docs`, sign in through
`POST /api/v1/auth/login` first. Swagger supplies the browser Origin; it must be allowed.
All writes below require the manager cookie and allowed Origin. Agents can read these APIs.
The existing `/connect` inventory view shows each lot's expiry and physical observation time.

1. Execute `GET /api/v1/inventory` and `GET /api/v1/menu-items` to obtain batch and dish IDs.
2. Use `POST /api/v1/daily-updates/2026-02-16/draft` with the shape below. Add every received,
   unexpired batch and every dish. Explicit `0` is valid; missing entries prevent submission.
   Expired historical batches may optionally be counted. Quantities use each ingredient's base unit.
3. Execute `POST /api/v1/daily-updates/2026-02-16/submit` with no body. Incomplete submissions
   return 422 and preserve the draft. Read draft/history with `GET` on the day URL.
4. Correct a day by saving another complete draft and submitting again with the same cutoff.
   Previous revisions, sales, source cutoff, actor and real recording time remain in history.
   The newest revision at the latest cutoff supplies PHYSICAL inventory; dish sales are never deducted.

```json
{"cutoff":"2026-02-16T22:00:00+08:00","counts":{"chicken-01":"7.5","chicken-02":"0"},"sales":{"chicken-rice":0}}
```

This abbreviated example is a valid draft, not a complete submission. `/inventory` contains the other
batch IDs; `/menu-items` contains the other dish IDs. Source timestamps must include a timezone;
the cutoff must fall on the URL's day in Singapore. Cutoff changes on a correction return 409.

Record deliveries **before** submitting the day's closing counts:

1. Read `/supplier-offers` and copy an approved supplier/ingredient pair. POST `/api/v1/deliveries`:

   ```json
   {"supplier_id":"<supplier ID>","ingredient_id":"chicken","kind":"NORMAL","expected_quantity":"10","ordered_at":"2026-02-16T08:00:00+08:00","expected_at":"2026-02-16T10:00:00+08:00"}
   ```

   `EMERGENCY` is also supported. This records an external fact without plan approval and returns 201.
   It adds expected supply, not inventory. GET `/deliveries` or `/deliveries/{id}` to read it.
2. POST `/api/v1/deliveries/{id}/update` to record changed expectations or cancel the remainder:

   ```json
   {"expected_quantity":"10","expected_at":"2026-02-16T12:00:00+08:00","effective_at":"2026-02-16T09:00:00+08:00","cancel_remainder":false}
   ```

   Expected quantity is the total shipment quantity, including receipts. Completed/cancelled deliveries
   cannot be reopened. Updates preserve previous expectations in event snapshots.
3. POST `/api/v1/deliveries/{id}/receive`:

   ```json
   {"request_id":"supplier-slip-001","quantity":"4","received_at":"2026-02-16T12:00:00+08:00","expiry_date":"2026-02-19","remainder":"EXPECTED"}
   ```

   The result shows received `4`, outstanding `6`, cancelled `0`, and a distinct lot ID. A later receipt
   uses a new request ID and its own expiry. Set remainder to `CANCELLED` to cancel the unreceived balance.
   Identical receipt retries return current delivery state with no additional stock or events; conflicting
   reuse returns 409. Over-receipt returns 409; update the expected total first when recording extra supply.
4. Refresh `/inventory` before preparing closing counts: include the received lots. Future deliveries
   never appear as counted stock. A newly reported receipt at/before an already submitted cutoff returns
   `409 CLOSING_COUNT_CONFLICT` listing affected days. Retry with `closing_counts`, for example
   `"closing_counts":{"2026-02-16":"2"}`, supplying the new lot's physical quantity at **each** affected
   day's original cutoff. The receipt and corrected daily revisions commit atomically; prior counts and
   sales remain in history. Matching saved drafts gain the new lot while preserving other draft edits.

GET `/api/v1/events` and `/api/v1/audit` expose typed events, effective times, immutable delivery snapshots,
and recording actor/time. Each submission, purchase, update or receipt commits together with its events
and audit entries. Daily submissions now queue a durable assessment; drafts emit no assessment event.

## Tickets 7 and 8: simulated sales and first planning run

`POST /api/v1/sales-batches` accepts a complete incremental simulator interval.
Each batch has a `source`, `batch_id`, timezone-aware period bounds, and dish
quantities; omitted dishes are zero. Identical retries have no second effect,
while conflicting identities and overlapping intervals return `409`. Submit a
replacement with the **same source, batch_id and exact interval**, plus `replaces_id`,
to correct the active revision without double deduction. Empty complete reports
assert zero sales; partial reports are unsupported.

`GET /api/v1/inventory/estimated?as_of=<timestamp>` reports recipe-derived
earliest-expiry balances separately from physical observations, with coverage metadata.
Lots are excluded on the Singapore day after expiry and retained as `EXPIRED`
history.

A manager starts a durable assessment with `POST /api/v1/assessments` and an
`as_of` timestamp; it returns `202`. The agent bearer credential claims the
run at `POST /api/v1/runs/claim`, calls
`POST /api/v1/runs/{id}/tools/optimise` with forecast dish quantities, then
completes it at `POST /api/v1/runs/{id}/complete`. The tool checks frozen
inventory, recipes, complete supplier inputs, MOQ, pack size, availability,
and delivery slots before an immutable `PENDING_APPROVAL` version is stored.
Read them through `GET /runs/{id}` and `GET /plans/{version_id}`.

The described calculator is a **development fixture**, disabled by default. Set
`ENABLE_DEVELOPMENT_CALCULATOR=true` only to test backend plan/approval plumbing.
It does not implement the teammate's forecasting, materiality, dated-horizon or
contingency optimiser. Without integration or explicit fixture opt-in, its tool
returns `503 DECISION_ENGINE_NOT_CONNECTED`. Do not call tickets 5–8 fully complete
based on fixture results.

The current [backend handover](../../docs/BACKEND_HANDOVER.md) lists all new routes,
ownership boundaries, exact-version approval payloads, cycle decisions, promotion
and supplier triggers, reconciliation assumptions, and outstanding integration.

## Pass 3E Agent procurement contract

For the first connected cash slice, Backend seeds a versioned, read-only policy
and complete approved supplier domain. An Agent bearer can first verify it with:

```text
GET /api/v1/procurement-policies/CASH_SLICE_V1/versions/1
```

After claiming a run at `2026-02-15T22:00:00+08:00`, the Agent must read the
exact frozen artifact from:

```text
GET /api/v1/runs/{run_id}/procurement-contract
```

It carries `as_of`, `known_at`, `captured_state_revision`, policy version,
approved domain, all 24 frozen offer/opportunity revisions, fee grouping and the
frozen baseline state. The endpoint fails closed with `409 MISSING_REQUIRED_DATA`
when the domain is incomplete or the run cannot use the deliberately empty
first-slice baseline. The adapter must pass this artifact unchanged to the
deterministic engine; it must not fetch current supplier facts or invent defaults.

## Audit safeguards and database upgrade

Pull the current code, then run `python -m alembic upgrade head` before starting
the API. The new migrations preserve data, supersede older overlapping actionable
plans with audit records, label pre-existing plan links `LEGACY_REFERENCE`, and
add supplier-history and recording-time fields. An invalid existing ordering
interval causes upgrade to fail; correct that schedule explicitly before retrying.
Re-running seed does not replace existing offers or reconstruct overwritten history.

Each claimed snapshot records simulation `as_of`, real `known_at`, and the selected
`offer_version_ids`. Later-effective offers, promotions, cycle decisions, purchases
and receipts do not enter earlier inputs. Same-cutoff replay uses the saved
`known_at`; a fresh assessment deliberately includes newly recorded corrections.
Pre-migration overwritten offer history is unavailable and appears in
`missing_offer_history`, which blocks calculation with `MISSING_REQUIRED_DATA`.

Cycle decisions accept `effective_at`; supply the simulation clock during demos.
Omitting it uses real recording time. Promotion revisions and delivery term changes
must preserve effective-time order. Late receipts remain supported; a backdated
cancellation cannot precede already recorded delivery activity.

Only one actionable purchase-plan version may exist. A new version supersedes the
previous one and needs its own approval. New linked purchases require that current
approved version, matching supplier/ingredient, and cumulative quantity within the
line. `GET /plans/{version_id}/lines` exposes `linked_quantity` and
`uncommitted_quantity`; record actual deviations with no `source_plan_line_id`.

See the [shared contract proposal](../../docs/SHARED_INTEGRATION_CONTRACT.md) before
connecting the real engine or agent. Fee grouping, full cost validation, materiality
and contingency acceptance still need teammate integration.
