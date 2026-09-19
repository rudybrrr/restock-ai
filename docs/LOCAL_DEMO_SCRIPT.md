# Local Demo Script

This script uses only the supported local golden runner. It does not require live LLM access and does not exercise inventory correction.

## Setup

Use an explicitly named disposable database beginning with `restock_demo_`, migrate it, and run the existing preparation/runner commands from `services/api`. Keep the generated JSON outside the repository or under an ignored local temp directory.

## Rehearsal sequence

1. **Initial recommendation** — show the active recommendation and its `PENDING_APPROVAL` status. Explain that a recommendation is not an order.
2. **Manager approval boundary** — show exact `plan_id`/`plan_version` approval semantics and that approval does not place a purchase.
3. **Supplier disruption** — show deterministic materiality evidence, Procurement-first routing, supplier feasibility/optimisation evidence, validation, and the replacement recommendation.
4. **Promotion reassessment** — show Demand routing, promotion application/forecast comparison, conditional Inventory/Procurement follow-up, and the resulting plan decision.
5. **Delivery disruption** — show commitment-aware Inventory routing and conditional Procurement reassessment.
6. **Sales materiality** — show the persisted sales-materiality boundary and fail-closed escalation when required materiality evidence is missing.
7. **Stale approval safety** — change an authoritative input after a recommendation is shown, attempt approval of the old exact version, and show `PLAN_VERSION_STALE` plus the audit reference.
8. **Evidence trace** — open Activity and show trigger, Coordinator route, specialist/tool summaries, validation, plan transition, approval attempt, and final outcome. Confirm no prompt or scratchpad is displayed.
9. **Evaluation summary** — show the local five-scenario summary, stable repeat fingerprints, and pending/unsupported live/business metrics.

## Live-model handoff marker

At the point where the script says “local scripted path”, a future live integration may replace the scripted reasoning provider. The Backend contracts, deterministic calculations, validation, approval, audit, and manager evidence boundaries remain the same. Do not describe the local scripted path as live Sonnet behavior.

## Explicitly excluded

- Inventory-adjustment route: blocked by the missing authoritative Backend event contract.
- Persisted human-review request workflow: undefined by the current Backend contract.
- Live OpenClaw/Sonnet, AWS/Bedrock, deployment, hosted URLs, and external submission actions.
