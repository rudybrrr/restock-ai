# Final local demo runbook — 26 September 2026

The primary story uses synthetic restaurant records in an isolated local database. It has been rehearsed through API, real deterministic worker, and manager UI. The first approved plan in this bounded contingency scenario used a **controlled typed-reasoning fixture**; the subsequent KEEP and additional-purchase assessments ran through the real worker. The separate normal/sales story used the live organiser gateway.

## Start and health

1. Use a dedicated, migrated, seeded PostgreSQL database. Keep API and `assessment_worker --loop` on its same `DATABASE_URL`. Start the Next.js frontend with `NEXT_PUBLIC_API_BASE_URL` set to that API origin. Configure the frontend origin in `ALLOWED_ORIGINS` and local HTTP cookies with `COOKIE_SECURE=false`. Keep manager password, Agent token, and gateway key only in Backend/worker environment.
2. On this machine, where a proxy is configured, add only the organiser gateway hostname to the **worker process** `NO_PROXY` and `no_proxy` before launching it. Do not put the machine-specific hostname in application code. Restart the worker after any gateway environment change.
3. Check `GET /health` → 200, load `/login`, sign in as manager, and confirm `/api/v1/auth/me` → 200. Activity → Assessments shows queued/running/completed status; a page refresh does not run the worker.

## Primary story: changed external purchase

Use the already rehearsed local contingency database behind `http://localhost:8010` and frontend `http://localhost:3010` when available. The fixed baseline was approved version `31960936-b27e-452e-9dbe-65d294683859`. It had a recorded original delivery, a partial receipt, and a separately recorded linked emergency purchase. Approval itself placed no order.

1. In **Deliveries**, show the original external purchase and emergency purchase as distinct records. **Record actual purchase** is for purchases already arranged with a supplier; selecting `EMERGENCY` records an external fact, not an Agent action.
2. In **Activity → Assessments**, open the KEEP run `ee75e457-aae2-4d08-9d17-b1a90edd4780`. Existing fixed commitments cover the need, so no additional purchase is published.
3. The emergency delivery's expected quantity was then changed from 4 kg to 2 kg through `POST /api/v1/deliveries/{id}/update`. This external shortfall autoqueued `DELIVERY_SHORT` run `ed59d0f6-ac86-4367-ac70-2faa7a92005a`. Open that run in **Activity → Assessments**. It records `REVISE_PLAN` after the worker's frozen post-purchase contingency calculation.
4. Select **View recommendation**. Version `5ff07985-3c52-4e22-95a0-f47385bd50d1` is `PENDING_APPROVAL`, `CONTINGENCY_ENGINE`, 2.000 kg additional vegetables, and `NEW_PURCHASE_CASH_ONLY` S$11. Show the acquisition, delivery, and emergency-fee pieces. Existing commitments remain listed in Deliveries and are not duplicated in the new line. The full economic cost is unavailable.
5. Point to the **Approve exact version** control and explain that approval is a manager action, does not place or record a purchase, and becomes stale after newer authoritative facts. The API's exact-version stale rejection was also exercised against invalidated version `40570204-440e-41e7-aa0e-2eec5550b04b`: HTTP 409 `PLAN_VERSION_STALE`.
6. Expand **Assessment evidence** and **Coordinator routing** in Activity. Show trigger, final outcome, fixed-commitment context, version transition, and the absence of prompts, hidden reasoning, raw model output, or Agent-created Delivery mutations.

The bounded fresh setup and policy are specified in [POST_PURCHASE_CONTINGENCY_CONTRACT.md](POST_PURCHASE_CONTINGENCY_CONTRACT.md) and exercised by `services/api/tests/test_post_purchase_contingency.py`. A fresh demo database must rebuild its approved baseline and external deliveries before the KEEP/shortfall actions; do not reuse a terminal run as though it were a new assessment.

## Short safety example: material sales after issue time

The separate clean live-gateway database behind `http://localhost:8012` recorded normal run `65de2f64-5fd4-44a8-bc1c-c0479a32e004`, producing a pending `ENGINE` version. Forty observed sales intervals then autoqueued `SALES_UPDATED` run `c5bf8405-5e5f-4659-8a84-58d75f7c7a2f`. Manager API and persisted Backend evidence show complete deterministic materiality, `material_change=true`, and the original issued-forecast provenance. Demand, Inventory, and Procurement made real typed gateway decisions; the deterministic procurement search returned `UNSUPPORTED_ISSUE_OPENING` at `issue_time`. Final outcome: `ESCALATE` / `CALCULATION_INCOMPLETE`, no fabricated normal plan. The original version became invalidated, and its exact approval attempt returned `PLAN_VERSION_STALE`.

If showing this in the manager UI, point a frontend build at API 8012 with an allowed frontend origin, then open **Activity → Assessments → sales updated → Sales and stock-correction assessments**. Explain that detecting material demand does not authorize ordering outside the approved issue window. The post-purchase contingency path is the supported additional-purchase mechanism for its declared state.

For the clearest policy wording in the UI, the separately rehearsed controlled typed-reasoning run `e73469cc-6bf2-4fd6-908e-5cc6cbc3cbfd` on isolated API 8014 shows `UNSUPPORTED_ISSUE_OPENING` in **What did ReStock conclude?**, `CALCULATION_INCOMPLETE`, and no plan version. This UI replay used fixtures for specialist routing; the API 8012 run above is the live-gateway proof. Repoint/rebuild the frontend for the chosen API origin before presenting either database.

## Evidence and claims to keep separate

- The [19 September provider-free golden evaluation](evaluation/LOCAL_RESULTS_2026-09-19.md) measured seven development scenarios. It is a fallback deterministic demonstration, not the live gateway run above.
- The contingency's initial controlled fixture, the live normal/sales worker, and the deterministic contingency worker have different evidence levels. Do not call all three “live Sonnet”.
- Synthetic quotes and costs demonstrate logic, not actual restaurant savings. Hosted operation, AWS/Bedrock, OpenClaw-as-worker, and real business outcomes are not shown.
