# Backend review response

The supplied backendplanreview.md was reviewed as feedback, not as authority to override the backend owner's agreed scope. The original proposal includes a wider adaptive intraday demo; the planning session deliberately narrowed several behaviours. That divergence must be visible to the team before integration. No application code has been changed.

## Disposition of all review points

| Point | Assessment | Action |
| --- | --- | --- |
| 1. Ingredient schedules | Correct against the original proposal, but universal fortnightly ordering was an explicit owner decision. The proposed weekday/interval/reorder-point schedule engine is more than the bounded demo needs. | Reopen as a scope choice. Recommend simple per-ingredient interval_days plus anchor_date if restoring realistic varied cadences, without general calendar machinery. |
| 2. Scheduled/event/manual triggers | Required for the original intraday story, not for the agreed daily-submission prototype. Daily stock updates and ordering cadence are separate. | Ask which demo promise to preserve. Do not silently add POS feeds or automatic monitoring. |
| 3. Events during a run | Correct for live event feeds. Brief input blocking with bounded recovery is coherent for a single-manager daily demo, although it has a usability cost. | Keep current rule unless live/event-triggered mode is chosen; then revisit revision checks and queued follow-up assessment. |
| 4. Time-aware stock | Correct principle. Timestamped post-count activity is necessary to compute an intraday estimate. Daily totals cannot produce the review's Friday-afternoon live behaviour. | Clarify PHYSICAL/ESTIMATED/PROJECTED provenance now. Live deductions require a separately accepted input expansion. Never double-deduct a closing count. |
| 5. Optional waste | Known waste, discrepancy, expected waste, and simulator ground truth are different. Lack of manual waste measurement was explicit. | Permit simulator evidence in event payloads and preserve its origin. Do not require staff entry or claim measured waste from counts. A deduction engine is conditional on scope. |
| 6. Emergency recommendations | Strong product criticism: warning plus manual external purchase entry is simpler but weakens agent investigation/optimisation. Approval of a candidate that covers the shortage is consistent with blocking infeasible approval. | Recommend reopening: let existing tools calculate emergency lines from approved suppliers; retain separate manual execution and incoming-delivery entry. Owner decision pending. |
| 7. Post-order contingencies | Preserving commitments does not require freezing current operational recommendations forever. The original proposal supports this; the owner had approved the narrower warning-only behaviour. | Reopen together with point 6. If adopted, preserve commitments as fixed inputs and recommend only additional uncommitted purchases; never reinterpret the revised plan as ordering committed quantities again. |
| 8. Plan references | Valid omission/ambiguity in the design draft. Immutable JSON snapshots do not require removing IDs or adding a table per intermediate calculation. | Added explicit canonical fields, six cost components, snapshot identity requirements, and public approval identity mapping. |
| 9. Materiality | Partly already present: the draft allowed KEEP after deterministic reassessment. A block pending assessment is not automatically invalidation. | Clarified persistence of impact/validation outcomes and materiality. No new backend-owned decision engine. |
| 10. Outcomes | Valid contract drift: shorthand enums would confuse integration. | Restored all four canonical API/audit outcomes and made their usage explicit. Flagged the original contract's missing outcome for known infeasibility for later shared-contract resolution. |

Event-envelope and audit-field details were also added to BACKEND_DESIGN.md. Operational state and event writes must be atomic; this does not require event sourcing.

## Resolution after owner review

1. Q42 subsequently revised by the owner: successive timestamped simulated sales batches update POS-derived estimates deterministically without calling Claude for each batch. Material demand/stockout thresholds, promotions, and supplier disruptions request reassessment; routine counts/admin remain daily. No real POS integration. This supersedes the single-spike-only model and requires sales ingestion during runs, using revision checks/coalesced assessment as proposed in BACKEND_DESIGN.md. Administrative edits may still be blocked.
2. Q43: emergency/contingency recommendations accepted through existing tools and approved suppliers. Manager approval and external execution remain separate; commitments are fixed inputs.
3. Q44: interval_days and starting_date per ingredient accepted. No weekday calendars, category inheritance, or reorder-point rules.

The disposition table above records the review reasoning at the time; these accepted decisions supersede its pending scope choices. Backend documents now use the hybrid baseline. Exact sales coverage and intraday time semantics are made explicit in the design draft for integration review.

## Final four contract findings

Accepted and recorded in both architecture-contract copies: ESCALATE plus typed reason replaces ESCALATE_INSUFFICIENT_INFORMATION; explicit lifecycle transitions remove VALID from the MVP; SupplierOffer has named typed decision inputs with units and arrival timestamps; the expanded event enum covers daily submission, receipt, manual reassessment, and other implemented mutation categories. Earlier references above to preserving the old four outcome names describe the review stage and are superseded by this explicit shared-contract update.

Two refinements: a known infeasible assessment is not a crashed run, and full-day batch/daily-total equality is meaningful only for matching complete coverage. Partial coverage is reported separately. Closing counts remain authoritative regardless of sales reconciliation, and no discrepancy is silently relabelled waste.
