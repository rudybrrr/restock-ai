# ReStock

ReStock is an adaptive restaurant inventory and procurement agent that maintains a continuously valid purchasing plan within its approved domains. It helps a manager reassess what to buy, how much, when, and from which approved supplier as demand, inventory, deliveries, promotions, and supplier conditions change.

## One-line pitch

ReStock does not just predict what a restaurant should order — it keeps the purchasing plan valid as reality changes. Bounded specialist investigation and deterministic validation produce evidence-backed recommendations for exact-version human approval.

## What is proven

The current branch contains a working local path for Procurement, Demand, and Inventory specialists; dynamic Coordinator routing; deterministic demand/inventory/procurement calculations; genuine `PENDING_APPROVAL` plan publication; supplier, promotion, delivery, and sales-materiality replanning; stale approval rejection; append-only audit history; manager evidence projections; and a provider-free evaluation/demo harness.

AI selects what needs investigation and when a plan should be reconsidered. Deterministic Python systems calculate and validate the candidate. The Backend is the only authority that validates state, publishes plan versions, applies lifecycle transitions, accepts approval, and persists audit records.

The organiser gateway has now been exercised with real typed Demand, Inventory, and Procurement calls. A fresh normal assessment published an `ENGINE` plan pending approval, and a later material sales event escalated safely at the unsupported issue opening. A separate post-purchase contingency run preserved fixed commitments and recommended only an additional purchase. [The 26 September validation record](docs/FINAL_VALIDATION_2026-09-26.md) names those runs and distinguishes controlled setup from live-model execution. Hosted deployment, AWS/Bedrock, live-model service-level reliability, restaurant savings, and production SME outcomes are not proven.

## Architecture

```mermaid
flowchart TD
    UI[Next.js manager UI] --> API[FastAPI Backend]
    API --> DB[(PostgreSQL authoritative state)]
    API --> COORD[Coordinator]
    COORD --> DEMAND[Demand Specialist]
    COORD --> INVENTORY[Inventory Specialist]
    COORD --> PROCUREMENT[Procurement Specialist]
    DEMAND --> DTOOLS[Demand tools]
    INVENTORY --> ITOOLS[Inventory tools]
    PROCUREMENT --> PTOOLS[Procurement tools]
    DTOOLS --> ENGINE[Deterministic Decision Engine adapters]
    ITOOLS --> ENGINE
    PTOOLS --> ENGINE
    ENGINE --> API
    API --> EVIDENCE[Manager evidence + append-only audit]
```

The Coordinator may invoke specialists, but specialists cannot invoke other specialists or mutate Backend state. Each specialist has a narrow domain allowlist. Backend validation, publication, lifecycle, approval, and audit persistence remain outside prompts and specialist reasoning.

The application worker uses strictly validated typed specialist decisions through the organiser gateway. OpenClaw remains an isolated smoke-test path and is not used by the application worker. The local evaluation harness uses scripted reasoning over the same contracts; its results are separate from the live gateway checks.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/AGENTS_PLAN.md](docs/AGENTS_PLAN.md), and [CONTEXT.md](CONTEXT.md) for detailed contracts and glossary terms.

## Local setup

Requirements:

- Python 3.12+
- PostgreSQL 18-compatible local server
- Node.js 24.16–24.x
- pnpm 10.28.2

Backend:

```powershell
cd services/api
uv sync
Copy-Item .env.example .env
# Set distinct local MANAGER_PASSWORD and AGENT_TOKEN in .env.
uv run alembic upgrade head
uv run python -m src.seed
uv run uvicorn src.main:app --reload --port 8000
```

The seed is insert-only and safe to repeat for an existing database. Use a new database for a clean local run. The local demo reset helper is stricter: it only accepts a database name beginning with `restock_demo_` and truncates/reseeds that explicitly dedicated database.

Frontend:

```powershell
cd apps/web
pnpm install --frozen-lockfile
pnpm dev
```

The manager UI defaults to `http://localhost:8000` for the API and `http://localhost:3000` for the frontend. No agent credential belongs in frontend environment variables.

## Demo flow

The supported provider-free golden evaluation uses these local flows:

1. Prepare a seven-scenario, evaluator-truth-free sheet.
2. Run supplier replanning, promotion routing, delivery disruption, safe and material inventory correction, sales-materiality fail-closed routing, and exact-version stale approval.
3. Review the active/pending recommendation, Coordinator routing, specialist/tool summaries, validation evidence, approval boundary, and Activity evidence timeline.
4. Repeat from the same dedicated `restock_demo_...` database; the runner resets and reseeds it before each system/scenario comparison.

```powershell
cd services/api
uv run alembic upgrade head
uv run python -m src.evaluation.local_demo prepare `
  --manifest tests/fixtures/evaluation/scenarios_v1.json `
  --output .tmp/golden-demo-preparation.json
uv run python -m src.evaluation.local_demo run `
  --manifest tests/fixtures/evaluation/scenarios_v1.json `
  --database-url postgresql+psycopg://.../restock_demo_local `
  --output .tmp/golden-demo-result.json
```

The inventory-adjustment route uses Backend PR #32's canonical event/context/assessment contract. The safe case keeps the current plan without Procurement; the material case reaches the real Procurement engine and publishes a revision.

See [docs/LOCAL_DEMO_SCRIPT.md](docs/LOCAL_DEMO_SCRIPT.md) for the live contingency rehearsal and local evaluation fallback. No capture or external submission is performed by the repository.

## Approval and safety boundary

Approval accepts an exact `plan_id` and `plan_version`. A new authoritative change invalidates the old review context; attempting to approve the stale version returns `PLAN_VERSION_STALE`. Approval does not place an order, create a purchase, or add inventory.

The local safety suite covers permission boundaries, prompt-injection attempts, unknown-data fail-closed behavior, bounded rounds/calls/retries, state-revision freshness, candidate validation, audit immutability, and absence of hidden chain-of-thought persistence. Manager evidence deliberately omits private prompts, scratchpads, raw frozen state, and secrets.

## Evaluation

The checked-in manifest contains 19 runnable scenario rows. It includes development and held-out splits and keeps expected truth separate from runtime inputs. The supported golden pass measures seven development scenarios across Static, Rule, and local Adaptive ReStock adapters: 21 executions, zero failed executions, stable observed-boundary fingerprints across two runs, and stale approval evidence with a persisted audit reference.

The historical provider-free evaluation on 19 September 2026 is recorded in [docs/evaluation/LOCAL_RESULTS_2026-09-19.md](docs/evaluation/LOCAL_RESULTS_2026-09-19.md). At that checkpoint, the PostgreSQL suite passed 782 tests and the separate synthetic-history suite passed 68. Current full-suite and live-flow evidence is in [the 26 September validation record](docs/FINAL_VALIDATION_2026-09-26.md); those historical totals are not current test counts.

The local evaluation reports routing, outcome, specialist-call, tool-call, retry, latency, failure, and prompt-injection evidence only where the harness supports it. Live model calls and connected worker paths have since been demonstrated separately; live token usage, cost distributions, and business outcomes remain unmeasured. The data is synthetic and first-slice; it is not evidence of food-waste reduction, stockout reduction, lost-sales reduction, procurement savings, emergency-order savings, or real restaurant performance.

## Current open items

- Run `python -m src.assessment_worker --loop` alongside the API for queue polling; it has claimed a queued local run. A hosted process supervisor is still needed.
- Persisted human-review request workflow semantics, which remain undefined by the Backend contract.
- AWS/Bedrock verification, live token/cost metrics, and a statistically useful live-model reliability evaluation.
- Deployment, production reliability, hosted URLs, video, screenshots, and external submission actions.
- Real-world restaurant and SME outcome metrics.

The current local status is tracked in [docs/AGENTS_TASKS.md](docs/AGENTS_TASKS.md).
The exact hosted handoff is in [docs/DEPLOYMENT_HANDOFF.md](docs/DEPLOYMENT_HANDOFF.md).

## Project material

- [Architecture and routing contract](docs/ARCHITECTURE.md)
- [Local evaluation harness](docs/evaluation/LOCAL_HARNESS.md)
- [Measured local evaluation results](docs/evaluation/LOCAL_RESULTS_2026-09-19.md)
- [Local demo script](docs/LOCAL_DEMO_SCRIPT.md)
- [Submission material](docs/SUBMISSION_MATERIALS.md)
- [Backend setup and API notes](services/api/README.md)
- [Connected synthetic contingency first case](docs/BACKEND_CONTINGENCY_FIRST_CASE.md)
- [Frontend development and verification](apps/web/FRONTEND.md)
