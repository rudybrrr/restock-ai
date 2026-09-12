# Backend implementation tickets

Published and labelled ready-for-agent. Parent specification: [#3](https://github.com/rudybrrr/restock-ai/issues/3). All nine tickets have native parent and blocking relationships in GitHub, plus visible dependency references. A ready-for-agent label does not override open blockers.

The approved primary testing boundary is FastAPI HTTP with real test PostgreSQL. Each slice includes a minimal API/user interaction and external-behaviour checks. ML and agent logic remain with their respective owners.

| Slice | GitHub issue | Blocked by |
| --- | --- | --- |
| 1 | [Connect a teammate to seeded inventory](https://github.com/rudybrrr/restock-ai/issues/4) | None |
| 2 | [Submit authoritative closing counts and daily sales](https://github.com/rudybrrr/restock-ai/issues/5) | [#4](https://github.com/rudybrrr/restock-ai/issues/4) |
| 3 | [Record incoming deliveries and receive inventory batches](https://github.com/rudybrrr/restock-ai/issues/6) | [#5](https://github.com/rudybrrr/restock-ai/issues/5) |
| 4 | [Estimate intraday stock from simulated sales batches](https://github.com/rudybrrr/restock-ai/issues/7) | [#6](https://github.com/rudybrrr/restock-ai/issues/6) |
| 5 | [Generate the first normal purchase-plan version](https://github.com/rudybrrr/restock-ai/issues/8) | [#6](https://github.com/rudybrrr/restock-ai/issues/6) |
| 6 | [Approve exact versions and record purchasing decisions](https://github.com/rudybrrr/restock-ai/issues/9) | [#8](https://github.com/rudybrrr/restock-ai/issues/8) |
| 7 | [Reassess material promotions, supplier changes, and sales risk](https://github.com/rudybrrr/restock-ai/issues/10) | [#7](https://github.com/rudybrrr/restock-ai/issues/7), [#9](https://github.com/rudybrrr/restock-ai/issues/9) |
| 8 | [Recommend emergency purchases without double-ordering](https://github.com/rudybrrr/restock-ai/issues/11) | [#10](https://github.com/rudybrrr/restock-ai/issues/10) |
| 9 | [Replay the integrated demo and verify teammate handover](https://github.com/rudybrrr/restock-ai/issues/12) | [#11](https://github.com/rudybrrr/restock-ai/issues/11) |

Tickets 4 and 5 can proceed independently after ticket 3. Ticket 1 is the initial actionable ticket. Publication did not start implementation or assign anyone.

## 01 — Connect a teammate to seeded inventory

**Issue:** [#4](https://github.com/rudybrrr/restock-ai/issues/4)

**What to build:** A teammate starts the backend, signs in, and reads the restaurant's seeded inventory and catalog through the documented API.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent; check GitHub for current state and blocker completion.

- [ ] Provide reproducible PostgreSQL migration/seed setup for five dishes, eight ingredients, three suppliers, recipes, offers, holiday data, and dated inventory batches.
- [ ] GET /health retains its current 200 response; protected inventory/catalog reads return stored data through typed models.
- [ ] Manager and agent credentials are distinct; agent access cannot invoke manager-owned mutations.
- [ ] A minimal API test interface and allowed-origin configuration let a second machine verify login and a database-backed read.
- [ ] Include HTTP/PostgreSQL acceptance checks and setup/environment documentation without production secrets.

## 02 — Submit authoritative closing counts and daily sales

**Issue:** [#5](https://github.com/rudybrrr/restock-ai/issues/5)

**What to build:** The manager enters per-batch closing quantities and dish sales, submits the day, and can read the recorded physical baseline and history.

**Blocked by:** [#4](https://github.com/rudybrrr/restock-ai/issues/4).

**Status:** ready-for-agent; check GitHub for current state and blocker completion.

- [ ] A minimal daily-entry form or interactive API flow shows batch expiry and accepts explicit zero counts/sales.
- [ ] Reject incomplete submissions while preserving drafts; persist the completed revision, cutoff, and DAILY_UPDATE_SUBMITTED event atomically.
- [ ] Retain corrected revisions and source times; never deduct that day's dish sales again from the submitted closing counts.
- [ ] Read APIs expose PHYSICAL quantities and counted_at, rather than pretending those counts are live.
- [ ] Tests cover completeness, zero versus missing, corrections, atomic submission, and double-deduction prevention.

## 03 — Record incoming deliveries and receive inventory batches

**Issue:** [#6](https://github.com/rudybrrr/restock-ai/issues/6)

**What to build:** The owner records an external purchase, tracks arrival changes, and receives actual stock into separate expiry-dated batches.

**Blocked by:** [#5](https://github.com/rudybrrr/restock-ai/issues/5).

**Status:** ready-for-agent; check GitHub for current state and blocker completion.

- [ ] Provide simple create/update/receive interaction for normal and emergency deliveries from approved suppliers; approval is not required to record an actual external fact.
- [ ] Track expected quantity/arrival, actual receipts, cancellation, and outstanding remainder explicitly.
- [ ] Partial receipts create distinct lots and leave the remainder expected or cancelled according to owner input; repeated receipt requests do not duplicate stock.
- [ ] Closing-count and delivery reads distinguish quantities already received from future supply.
- [ ] Persist typed delivery/order events and audit history atomically; test partial receipt, cancellation, retry, and receipt/count reconciliation.

## 04 — Estimate intraday stock from simulated sales batches

**Issue:** [#7](https://github.com/rudybrrr/restock-ai/issues/7)

**What to build:** A simulator submits sales batches and the manager sees dated estimated stock, expiry effects, and closing-day sales reconciliation.

**Blocked by:** [#6](https://github.com/rudybrrr/restock-ai/issues/6).

**Status:** ready-for-agent; check GitHub for current state and blocker completion.

- [ ] Accept complete incremental timestamped batches with source identity and interval coverage; reject conflicting retries, overlaps, and unsupported cutoff splits.
- [ ] Use the ML-owned recipe/inventory interface to calculate usage after the latest physical count, including subsequent receipts and optional explicit adjustments/waste.
- [ ] Expose PHYSICAL, ESTIMATED, and PROJECTED provenance where available; do not overwrite counts or certify missing sales coverage.
- [ ] Mark expired lots EXPIRED and retain history; distinguish measured waste, unexplained discrepancy, and modeled expiry loss.
- [ ] Reconcile final sales against complete batch coverage or mark INCOMPLETE_COVERAGE; final totals are used once.
- [ ] Record deterministic materiality results/pending assessment requests without invoking Claude for every sale; agent execution is connected in later slices.
- [ ] Verify actual numerical examples, retry/correction behaviour, expiry boundaries, and new-stocktake baseline reset through HTTP.

## 05 — Generate the first normal purchase-plan version

**Issue:** [#8](https://github.com/rudybrrr/restock-ai/issues/8)

**What to build:** The manager requests a normal assessment, receives a run reference, and sees a real calculated recommendation produced through the agent/tool API.

**Blocked by:** [#6](https://github.com/rudybrrr/restock-ai/issues/6).

**Status:** ready-for-agent; check GitHub for current state and blocker completion.

- [ ] Expose manual assessment and queued-run claim/status/tool/completion APIs with frozen snapshot IDs and typed contracts.
- [ ] Connect ML-owned forecasting, requirements, inventory, supplier, optimisation and validation interfaces; use real calculation outputs in slice acceptance.
- [ ] Persist per-ingredient interval_days/starting_date cycles, explicit supplier constraints, a stable purchase-plan identity, immutable version/lines, all six cost fields, and canonical snapshot/trigger references.
- [ ] Return 202 for durable accepted assessment; show status and the resulting PENDING_APPROVAL recommendation in a minimal viewer.
- [ ] Enforce one running attempt, bounded deadline, idempotent completion, and current-state checks from the first runnable implementation; do not activate an uncertified stale result.
- [ ] Report canonical outcomes and typed escalation reasons, distinguishing infeasibility from technical failure and handling no-purchase results.
- [ ] Coordinate with ML/agent owners for implementations; controlled fixtures can unblock API development but do not satisfy the real first-plan acceptance.
- [ ] Tests use HTTP and PostgreSQL to verify snapshots, outcome validation, result visibility, basic timeout/late-result rejection, and persisted calculation fields.

## 06 — Approve exact versions and record purchasing decisions

**Issue:** [#9](https://github.com/rudybrrr/restock-ai/issues/9)

**What to build:** The manager reviews a recommendation, approves or rejects that exact version, and separately marks actual ingredient ordering occasions.

**Blocked by:** [#8](https://github.com/rudybrrr/restock-ai/issues/8).

**Status:** ready-for-agent; check GitHub for current state and blocker completion.

- [ ] Provide approve/reject actions with plan_id and plan_version plus authenticated manager identity and timestamp.
- [ ] Enforce the definitive lifecycle, terminal states, current validation, and lack of inherited approval; return 409 for stale approval.
- [ ] Approval does not create a delivery or mark a cycle ordered; external purchase recording links to source version/lines where available.
- [ ] Support anchored ingredient cycles marked ordered/skipped without shifting later dates.
- [ ] Allow rejection instructions and deliberate retry, not automatic rejection loops.
- [ ] API-visible tests cover allowed/forbidden transitions, agent permission denial, stale versions, and separation of approval from external commitments.

## 07 — Reassess material promotions, supplier changes, and sales risk

**Issue:** [#10](https://github.com/rudybrrr/restock-ai/issues/10)

**What to build:** A promotion, supplier disruption, or material sales change causes a real reassessment while harmless changes preserve the current recommendation.

**Blocked by:** [#7](https://github.com/rudybrrr/restock-ai/issues/7), [#9](https://github.com/rudybrrr/restock-ai/issues/9).

**Status:** ready-for-agent; check GitHub for current state and blocker completion.

- [ ] Wire daily completion, promotions, supplier disruptions, manual triggers, and deterministic material sales thresholds into the shared run-request path.
- [ ] Persist state/events/request markers atomically; preserve harmless-change certification separately from material invalidation.
- [ ] Accept sales while the agent runs, increment input revision, and coalesce repeated material triggers into one pending reassessment.
- [ ] Reject activation/approval against uncertified newer data; revalidate current inputs without holding a database transaction across the agent call.
- [ ] Show event, validation, tool and plan-history summaries; never expose hidden chain-of-thought.
- [ ] Demonstrate a promotion replan, supplier shortage with feasible split allocation, KEEP for a harmless change, and stale-approval rejection.
- [ ] Tests cover exact trigger routing, no agent call per routine batch, request coalescing, and a controlled newer-sales race.

## 08 — Recommend emergency purchases without double-ordering

**Issue:** [#11](https://github.com/rudybrrr/restock-ai/issues/11)

**What to build:** After purchases have been arranged, a disruption produces an approvable contingency recommendation for only the additional stock needed.

**Blocked by:** [#10](https://github.com/rudybrrr/restock-ai/issues/10).

**Status:** ready-for-agent; check GitHub for current state and blocker completion.

- [ ] Treat recorded external commitments as fixed inputs while allowing operational invalidation of the historically approved plan.
- [ ] Use existing approved suppliers and ML tools to calculate emergency allocations, fees, and explicit arrival times against the residual horizon.
- [ ] New recommendation lines exclude already committed quantities; never modify external orders through agent tools.
- [ ] Escalate when quantity, timing, unknown information or policy prevents feasibility; approval remains blocked until the proposed candidate is feasible.
- [ ] After manager approval, record the external emergency delivery separately and reassess its expected/actual coverage.
- [ ] Test an on-time sufficient delivery, late/short/cancelled alternatives, preserved approval history, and no duplicate recommendation of commitments.
- [ ] Demonstrate the full normal-order → disruption → contingency → external recording sequence in the test interface.

## 09 — Replay the integrated demo and verify teammate handover

**Issue:** [#12](https://github.com/rudybrrr/restock-ai/issues/12)

**What to build:** A teammate starts a clean seeded instance and runs the complete CNY, supplier-disruption, and emergency scenario through the API and minimal UI.

**Blocked by:** [#11](https://github.com/rudybrrr/restock-ai/issues/11).

**Status:** ready-for-agent; check GitHub for current state and blocker completion.

- [ ] Provide deterministic simulation-time selection and a reset command limited to the designated demo database.
- [ ] Run the acceptance story with actual ML functions and OpenClaw orchestration, including physical counts, sales estimates, materiality, plan versions, approvals, and contingency supply.
- [ ] Complete recovery checks for crashed/expired attempts, manual retry, late completions, repeated receipts, and sales reconciliation.
- [ ] Document base URL, credentials delivered separately, /docs, sample requests, 200 health/data reads, 202 run acceptance/status polling, and deliberate 409 stale-approval testing.
- [ ] Verify browser allowed-origin behaviour and a second-machine database-backed read; health alone is not an integration pass.
- [ ] Run local verification first, then a shared hosted smoke test when deployment is available; report real results without inventing a 200 ms latency requirement.
- [ ] Keep final UI polish and production infrastructure out of this slice.
