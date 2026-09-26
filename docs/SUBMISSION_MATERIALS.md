# Submission material — evidence as of 26 September 2026

## Short description

ReStock is an adaptive restaurant inventory and procurement agent that maintains a continuously valid purchasing plan within its approved domains. It does not just predict what a restaurant should order — it keeps the purchasing plan valid as reality changes. A Coordinator selects bounded Demand, Inventory, and Procurement investigations. Deterministic services calculate materiality, forecasts, stock exposure, purchase options, and feasibility. Backend owns frozen state, validation, plan publication, approval, and audit history.

## Demonstrated story

An approved synthetic purchasing plan and recorded external deliveries formed fixed commitments. After an emergency delivery shortfall, ReStock's post-purchase worker first kept the plan when commitments covered need, then recommended only 2.000 kg of additional vegetables when the commitment fell to 2 kg. The new version was `CONTINGENCY_ENGINE`, `NEW_PURCHASE_CASH_ONLY`, S$11 new cash and `PENDING_APPROVAL`; it did not duplicate the external purchases or record a delivery. The initial plan for this bounded case used a controlled typed-reasoning setup. The later contingency assessments used the real deterministic worker path.

A separate clean normal assessment used the live organiser gateway for ten valid typed specialist decisions and published an `ENGINE` recommendation pending approval. After observed sales changed materially, Backend persisted a complete deterministic materiality result before Coordinator reconsideration. The dated normal procurement issue window could not be reopened. The worker safely recorded `ESCALATE` / `CALCULATION_INCOMPLETE` and no new plan. An exact-version approval attempt against the invalidated prior plan returned `PLAN_VERSION_STALE`.

Run IDs, plan IDs, and validation limits are in [the final validation record](FINAL_VALIDATION_2026-09-26.md). The [demo runbook](LOCAL_DEMO_SCRIPT.md) gives the exact manager views and setup sequence.

## Why an agent

Restaurant changes are heterogeneous and event-driven. The Coordinator decides which bounded specialist to invoke, and specialists select investigations within separate tool permissions. Their typed decisions never supply authoritative prices, quantities, materiality, feasibility, validation, or approvals. Backend rejects stale state and ambiguous or malformed model output.

## Evidence level

| Claim | Status |
| --- | --- |
| Normal live organiser-gateway worker to validated pending plan | Proven live on isolated local PostgreSQL |
| Complete material sales detection and policy-safe escalation | Proven live on isolated local PostgreSQL |
| Additional-only post-purchase contingency and manager display | Proven locally through API, real deterministic worker, and frontend; initial plan used controlled setup |
| Seven-scenario Static/Rule/local Adaptive evaluation | Deterministic provider-free harness, measured 19 September 2026 |
| Hosted deployment, second-machine operation, AWS/Bedrock | Not yet proven |
| Real restaurant savings, waste/stockout reduction, live token/cost distributions | Not measured |

Every actionable revision remains `PENDING_APPROVAL`. Approval names the exact version and does not place an order. The manager sees evidence and a stale-version rejection rather than an Agent-controlled state mutation.

## Boundaries and limitations

- The post-purchase domain is a bounded approved synthetic case. Fixed commitments remain fixed, and its S$11 figure is new purchase cash only, not full economic cost or real-world savings.
- Late sales materiality can prove a change while the approved normal ordering window is closed. ReStock escalates instead of inventing an intraday order; the declared contingency path handles its supported additional-purchase state.
- The organiser gateway has also produced malformed responses during earlier runs. One bounded repair is allowed for malformed/schema output; ambiguity fails closed. The successful runs do not establish a provider availability guarantee.
- OpenClaw is an isolated smoke-test path, not the application worker. No hosted URL or AWS/Bedrock behavior is claimed.
- Historical engineering and numerical documents describe their dated checkpoints. Use this document and the 26 September validation record for current submission claims.
