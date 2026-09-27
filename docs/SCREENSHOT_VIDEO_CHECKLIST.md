# Screenshot / Video Capture Checklist

Capture planning only. No screenshots or browser capture were generated in the final validation pass. Use [the final validation record](FINAL_VALIDATION_2026-09-26.md) to label each scene by its actual evidence level.

## Required states

- Active recommendation with plan status, version, line/evidence summary, and “not an order” language.
- Pending approval with exact plan ID/version and approval boundary.
- Approved exact version, showing that approval does not create a purchase.
- Supplier disruption with materiality evidence, Procurement-first routing, replacement recommendation, and validation.
- Promotion reassessment with Demand routing and conditional downstream calls.
- Delivery disruption with commitment-aware Inventory evidence.
- Post-purchase contingency: original and emergency purchases remain fixed; a shortfall leads to only 2.000 kg additional vegetables, `CONTINGENCY_ENGINE`, S$11 `NEW_PURCHASE_CASH_ONLY`, `PENDING_APPROVAL`.
- Material sales change: deterministic complete materiality followed by `CALCULATION_INCOMPLETE` / `UNSUPPORTED_ISSUE_OPENING`, with no fabricated normal plan.
- Stale approval error with `PLAN_VERSION_STALE` and the exact old version.
- Activity/evidence trace with trigger, route, specialist/tool summaries, validation, plan transition, approval attempt, and final outcome.
- Manager evidence showing no prompt, scratchpad, raw frozen state, evaluator truth, Agent token, or secret.
- Evaluation results showing the dated provider-free scenario count separately from live worker evidence and unmeasured business metrics.

## Capture rules

- Use only isolated synthetic demo state and actual recorded results. Show live-model behavior only from the proven normal/sales runs; label the contingency baseline as controlled setup.
- Do not portray AWS/Bedrock, hosted deployment, or unsupported business outcomes as demonstrated.
- Redact credentials, database URLs, tokens, and local filesystem paths.
- Label scripted local reasoning clearly; OpenClaw is not the application worker.
- Capture only when explicitly requested for the actual submission.
