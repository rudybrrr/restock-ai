# Screenshot / Video Capture Checklist

Capture planning only. No screenshots or browser capture are part of the local hardening pass.

## Required states

- Active recommendation with plan status, version, line/evidence summary, and “not an order” language.
- Pending approval with exact plan ID/version and approval boundary.
- Approved exact version, showing that approval does not create a purchase.
- Supplier disruption with materiality evidence, Procurement-first routing, replacement recommendation, and validation.
- Promotion reassessment with Demand routing and conditional downstream calls.
- Delivery disruption with commitment-aware Inventory evidence.
- Stale approval error with `PLAN_VERSION_STALE` and the exact old version.
- Activity/evidence trace with trigger, route, specialist/tool summaries, validation, plan transition, approval attempt, and final outcome.
- Manager evidence showing no prompt, scratchpad, raw frozen state, evaluator truth, Agent token, or secret.
- Evaluation results showing scenario count, supported families, honest local metrics, stable repeatability, and pending/unsupported live/business metrics.

## Capture rules

- Use only local seeded/demo state and the supported five-scenario flow.
- Do not capture inventory correction, live model behavior, AWS, deployment, or unsupported business outcomes.
- Redact credentials, database URLs, tokens, and local filesystem paths.
- Label scripted local reasoning clearly; do not label it Sonnet/OpenClaw.
- Perform capture only after team approval and any final deployment/submission decisions.
