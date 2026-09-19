# Submission Material — Local Evidence Only

## Short description

ReStock helps restaurant managers keep purchasing recommendations current as demand, inventory, promotions, deliveries, and supplier conditions change. A Coordinator routes only the needed domain specialists; deterministic Backend/Decision Engine services calculate and validate the recommendation; managers approve the exact version before acting externally.

## Business value

The local product path makes changing assumptions visible, limits unnecessary investigation, preserves the evidence behind a recommendation, and prevents a manager from approving a stale version. Potential waste, stockout, and purchasing-cost benefits are product goals, not measured claims in this synthetic first-slice build.

## Why an Agent architecture

Restaurant changes are heterogeneous and event-driven. A Coordinator can select a bounded investigation path rather than invoking every domain for every event. Retained specialists exist because Demand, Inventory, and Procurement have separate evidence contracts, tool permissions, and failure semantics. The architecture does not delegate arithmetic or policy enforcement to prompts.

## Deterministic versus LLM responsibilities

- LLM/provider responsibility later: interpret context, select investigation order, explain evidence, and request a typed outcome.
- Deterministic responsibility now and in production: forecast/requirements/inventory/procurement calculations, materiality, constraints, state revisions, validation, lifecycle, publication, approval, and audit persistence.
- Local demonstration: scripted provider-free reasoning over the same typed Coordinator/specialist boundaries.

## Human in the loop

Every actionable plan is a new immutable `PENDING_APPROVAL` version. Approval names the exact version and never places an order. If facts change, the old approval context is rejected with `PLAN_VERSION_STALE`.

## Guardrails

Typed inputs/outputs, exact specialist allowlists, no specialist recursion, bounded rounds/calls/retries, Backend-only mutation, stale state checks, deterministic candidate validation, append-only audit history, fail-closed unknowns, prompt-injection tests, and manager-safe evidence projections are locally verified.

## Evaluation evidence

Fresh local results are in [LOCAL_RESULTS_2026-09-19.md](evaluation/LOCAL_RESULTS_2026-09-19.md). The backend suite passed 773 tests; the explicit DB-independent selection passed 681. The supported golden pass covers five scenario families across Static, Rule, and local Adaptive adapters, with two repeat runs and stable runtime evidence fingerprints.

## Limitations and pending claims

- Synthetic first-slice data is not evidence of restaurant savings or production SME outcomes.
- Live Sonnet/OpenClaw behavior, tokens, latency, cost, AWS/Bedrock, and deployment are pending.
- Business metrics are unsupported by the current harness and are not reported as zero.
- Inventory correction is blocked by the missing authoritative Backend inventory-adjustment event contract.
- Persisted human-review workflow semantics are not defined and remain open.
