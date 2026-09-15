# Backend / Aniq / Rudy integration contract proposal

Status: proposed for teammate review, not a claim of agreement or completed integration. The backend-owned safeguards are implemented separately. Aniq and Rudy should confirm the items marked **agree before integration** before treating this as a frozen v1 contract.

## Facts and ownership

Backend owns versioned operational inputs, time-correct frozen snapshots, publication, permissions and audit. Aniq owns deterministic forecast, inventory projection, supplier feasibility, materiality and optimisation. Rudy owns investigation and tool orchestration. No component may silently default a missing decision-policy input or call a development fixture an engine result.

Use the backend's frozen `as_of` (operational time), `known_at` (real recording cutoff), supplier version IDs and historical facts. Do not fetch current mutable offers or deliveries to fill an earlier snapshot. `missing_offer_history` means required history is unavailable, not zero supply or proven infeasibility. Existing saved snapshots are the replay artifacts; recording history cannot restore facts already overwritten before the migration.

Sales batches are explicitly complete incremental interval reports. Omitted dishes mean zero. Empty reports explicitly assert no sales during the interval. Partial reports are unsupported. Corrections retain source, batch ID and exact bounds; a replacement increments the revision. This resolves CY-002 and CY-011 without introducing a new POS integration.

## CY-004: linked purchases

New linked purchases use `source_plan_line_id` only for the current APPROVED version, matching ingredient and supplier. Cumulative linked quantities, including receipts but excluding cancellations, must not exceed that line. Partial allocation is permitted and the line-read API exposes linked and uncommitted quantities. Approval remains separate from actual purchases.

Actual deviations remain recordable as **unlinked manual purchases**. They must not claim approved allocation provenance. Existing pre-fix links are labelled `LEGACY_REFERENCE`; they are not retroactively certified. New checked links are `APPROVED_ALLOCATION`; unlinked facts are `MANUAL`. Later operational changes remain audited facts and do not transfer approval to a replacement version.

## CY-006: fee charging unit — agree before integration

Current development-fixture policy: `PER_LINE_V1`, consistent with the existing architecture. Do not infer consolidation from equal supplier and arrival values.

Proposed real-engine policy if Aniq's first fixture needs S$60.50: `PER_SHIPMENT_V1`. Every line references an explicit `shipment_group_id`; each group records supplier, arrival, one ordinary delivery charge and a distinct emergency charge. Different arrivals or suppliers require different groups. S$55.50 acquisition plus one S$5 group fee equals S$60.50 only under this agreed grouping. Reject inconsistent group terms; do not silently select the largest or smallest fee.

The request and result must carry `fee_policy_version`. Choose one policy for the integrated demo and update both fixtures and validators together. Current fixture results remain labelled DEVELOPMENT_FIXTURE until replaced.

## CY-007 / CY-015: objective and policy — agree before integration

Inputs must include explicit versions of objective, valuation, continuation, feasibility and fee policies; currency and units; budget and its cash/time scope; per-ingredient safety quantity, storage limit and coverage window; frozen supplier constraints; dated outstanding commitments; and the planning horizon. A required missing value is missing data, not zero or unlimited capacity.

Output separates immediate cash from the optimisation score. Preserve the six existing cost fields, plus a versioned ledger assigning each term a unique ID, value, unit and whether it contributes to cash, the objective, or context only. Do not add acquisition-valued inventory loss to acquisition cost again unless the agreed valuation policy specifically defines a separate incremental cost. Continuation/end-of-horizon stock valuation must be explicit.

Aniq supplies the ledger definition and hand-calculated expected fixtures before the backend expands its validator. Backend checks each declared included term exactly once, non-finite/invalid values, ledger/version consistency and all relevant feasibility constraints. A complete projected score is not automatically purchase plus delivery. Legitimate waste, disposal or emergency terms cannot simply be discarded to make that equality pass.

## CY-008 / CY-009 / CY-013: reliability and materiality — agree before integration

Proposed v1 reliability policy: `CONTEXT_ONLY`. Historical on-time rate may be displayed as context but must not affect supplier ranking, costs or trigger reassessment by itself. The current backend still triggers rate-only updates under its old policy; change this with the agreed engine policy, not silently in only one component.

Every accepted sale updates deterministic inventory. A cheap deterministic impact result evaluates sales, receipts, external commitments, expiry and adjustments against current certified inputs. Results distinguish harmless/certified, material-invalid, and incomplete/uncertified, and carry event IDs, input/policy versions, concise reasons and affected version IDs. Only certified harmless changes preserve approval eligibility. Missing certification blocks approval; it is not automatically a proven invalidation. Material invalidation preserves historical approvals and fixed external commitments.

## CY-014: outcomes — agree before integration

Keep top-level outcomes KEEP_CURRENT_PLAN, REVISE_PLAN, REQUEST_HUMAN_APPROVAL and ESCALATE. Rudy's agent branch additionally declares CALCULATION_INCOMPLETE and CALL_LIMIT_REACHED alongside the existing escalation reasons. Adopt that vocabulary in both schemas together:

- CALCULATION_INCOMPLETE: no certified answer within the engine's computation/search bound; optional detail SEARCH_LIMIT_REACHED.
- CALL_LIMIT_REACHED: coordinator exhausted its tool-call budget.
- TOOL_FAILURE: an actual tool execution failure.
- NO_FEASIBLE_SUPPLIER / UNRESOLVED_SHORTAGE: proven infeasibility under complete stated inputs, not a timeout.
- MISSING_REQUIRED_DATA / POLICY_VIOLATION: explicit missing inputs or failed policy.

Only ESCALATE has escalation fields. A completed business escalation is distinct from a crashed/expired run. Only certified feasible actionable results create pending versions; no-purchase results create no fictitious order.

## Integration gate

CY-003, CY-009, CY-013 and complete cost validation remain open until the real engine and agent are connected. Minimum shared fixtures: timely versus late outstanding supply; partial receipts; no double-ordering under contingency; agreed fee groups; emergency and valuation costs; harmless versus material changes; search exhaustion versus proven infeasibility; exact-version approval and historical replay. Then run the full normal plan → approval → external purchase → disruption → contingency story.

Passing backend tests or freezing this proposal does not establish that the backend or integrated product is complete.
