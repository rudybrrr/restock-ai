# ReStock API teammate testing guide

This guide uses the seeded local demo. It explains both credentials and provides scenarios for the currently
available daily-update and delivery APIs. Start PostgreSQL, apply migrations, seed the database, and run the API
as described in [README.md](README.md), then open [Swagger UI](http://localhost:8000/docs).

## Configure test credentials

Set distinct values in your local `.env` and restart the API:

```dotenv
MANAGER_USERNAME=manager
MANAGER_PASSWORD=<private manager password>
AGENT_TOKEN=<different private token>
COOKIE_SECURE=false
```

Use `COOKIE_SECURE=false` only for HTTP localhost testing. Use `true` when the API runs over HTTPS. Do not commit
`.env` or share either credential in tickets, chat, or screenshots.

| Scenario | Credential and Swagger setup | Expected result |
| --- | --- | --- |
| Manager read and write | Execute `POST /api/v1/auth/login` with manager credentials | Browser holds a manager session cookie |
| Agent read | **Authorize** → `HTTPBearer` → paste `AGENT_TOKEN` only | `/auth/me` identifies the agent and reads return 200 |
| Agent write denial | Keep HTTPBearer authorized, call a manager write | `403 MANAGER_REQUIRED` |
| Anonymous denial | Log out or use a private browser window | Protected route returns `401 UNAUTHENTICATED` |

Deliveries, receipts, daily drafts, and daily submissions are manager-owned facts. Use the manager login to create
a delivery. The agent token must receive 403 on that route; this verifies permissions. To switch back to manager,
clear the HTTPBearer token under **Authorize**, then log in again.

## Scenario 1: verify both credentials

### Manager

1. Expand `POST /api/v1/auth/login`, choose **Try it out**, enter the manager username and password, then execute.
2. Expect `200 {"role":"manager","username":"manager"}`.
3. Execute `GET /api/v1/auth/me`, then `GET /api/v1/inventory`; both return `200`.

Swagger sends the localhost Origin and retains the session cookie automatically. The cURL preview does not retain
that cookie, so use it only as a request-shape reference.

### Agent

1. Click **Authorize** at the top of Swagger.
2. Under `HTTPBearer`, paste the `AGENT_TOKEN` value without the word `Bearer`.
3. Execute `GET /api/v1/auth/me` and `GET /api/v1/inventory`. Expect `200`; `/auth/me` returns role `agent`.
4. Try `POST /api/v1/deliveries` with the body in Scenario 2. Expect `403 MANAGER_REQUIRED`.

## Scenario 2: create a normal delivery as manager

Clear the agent token and sign in as manager. The seeded approved supplier IDs are `fresh`, `pantry`, and `market`.
Call `GET /api/v1/supplier-offers` to confirm a supplier/ingredient pair. Create a delivery through
`POST /api/v1/deliveries`:

```json
{
  "supplier_id": "fresh",
  "ingredient_id": "chicken",
  "kind": "NORMAL",
  "expected_quantity": "10.000",
  "ordered_at": "2026-02-16T08:00:00+08:00",
  "expected_at": "2026-02-16T10:00:00+08:00"
}
```

Expect `201`. Copy the returned `id`. The result has `received_quantity: "0.000"` and
`outstanding_quantity: "10.000"`: it is expected supply, so `/inventory` has no new lot yet. Repeat with
`"kind":"EMERGENCY"` to record an emergency delivery; this does not require a purchase-plan approval.

## Scenario 3: receive a delivery in two lots

Use the ID from Scenario 2 with `POST /api/v1/deliveries/{delivery_id}/receive`:

```json
{
  "request_id": "team-demo-receipt-1",
  "quantity": "4.000",
  "received_at": "2026-02-16T10:00:00+08:00",
  "expiry_date": "2026-02-19",
  "remainder": "EXPECTED"
}
```

Expect `200`: received `4.000`, outstanding `6.000`, and a new lot ID. Execute the identical request again to
test retry safety; it returns `200` with no duplicate lot. Change the quantity while retaining the request ID to
test a conflicting retry; expect `409 IDEMPOTENCY_CONFLICT`.

Receive the remainder with a new request ID and expiry:

```json
{
  "request_id": "team-demo-receipt-2",
  "quantity": "6.000",
  "received_at": "2026-02-16T11:00:00+08:00",
  "expiry_date": "2026-02-21",
  "remainder": "CANCELLED"
}
```

`GET /inventory` now includes two new physical lots. `GET /deliveries/{delivery_id}` reports the received,
cancelled, and outstanding quantities.

## Scenario 4: delay, short, or cancel future supply

Create another delivery, then call `POST /api/v1/deliveries/{delivery_id}/update` before receiving it:

```json
{
  "expected_quantity": "8.000",
  "expected_at": "2026-02-16T12:00:00+08:00",
  "effective_at": "2026-02-16T09:00:00+08:00",
  "cancel_remainder": false
}
```

Expect outstanding `8.000`. This writes update, delay, and short-supply events where applicable. Repeat with
`"cancel_remainder":true` to cancel unreceived stock. Outstanding becomes `0.000`; later updates return
`409 DELIVERY_CLOSED`.

## Scenario 5: closing counts and sales

Choose a day after every receipt you intend to count. First call `GET /inventory` and `GET /menu-items` to get the
current lot and dish IDs. A submitted daily draft needs every received, unexpired lot and every dish; explicit zero
is valid and different from missing input.

```json
{
  "cutoff": "2026-02-16T22:00:00+08:00",
  "counts": {
    "chicken-01": "7.500",
    "chicken-02": "0.000",
    "<every other current lot ID>": "0.000"
  },
  "sales": {
    "chicken-rice": 10,
    "fried-rice": 0,
    "chicken-noodles": 0,
    "tofu-bowl": 0,
    "vegetable-noodles": 0
  }
}
```

Save it with `POST /api/v1/daily-updates/{day}/draft`, then submit with
`POST /api/v1/daily-updates/{day}/submit` and no body. An incomplete draft returns
`422 INCOMPLETE_DAILY_UPDATE` but remains saved. A corrected complete draft with the same cutoff creates the next
revision. The closing counts remain physical observations; sales are recorded separately and are never deducted
from those counts.

## Scenario 6: audit history and late receipt reconciliation

After any manager action, call `GET /events` and `GET /audit` to see the recorded event, actor, and timestamps.

If a receipt arrived before a completed closing cutoff, the first receive request returns
`409 CLOSING_COUNT_CONFLICT`. Retry with a physical count for the new lot at each affected closing day:

```json
{
  "request_id": "team-demo-late-receipt",
  "quantity": "4.000",
  "received_at": "2026-02-16T10:00:00+08:00",
  "expiry_date": "2026-02-19",
  "remainder": "EXPECTED",
  "closing_counts": {"2026-02-16": "2.000"}
}
```

The receipt and the corrected daily revision commit together. Existing daily sales and prior revisions stay in
history.

## Terminal smoke test

Swagger is best for interactive testing. A terminal client must add the Origin header and store the session cookie:

```powershell
curl.exe -c cookies.txt -X POST http://localhost:8000/api/v1/auth/login `
  -H "Origin: http://localhost:8000" `
  -H "Content-Type: application/json" `
  -d '{"username":"manager","password":"<manager password>"}'

curl.exe -b cookies.txt http://localhost:8000/api/v1/auth/me
```

`cookies.txt` holds a live session. Delete it after use and never commit it.

## Repeatable testing

The scenarios add facts to the configured database. For a clean run, use a separate local database, apply
migrations, and seed it. Running `python -m src.seed` again preserves records; it does not remove deliveries,
counts, events, or audit history.
