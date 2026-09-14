# ReStock ML and Decision Engine Handover

**From:** Aniq<br>
**For:** Chun Yang, Rudy and Ethan, including their ChatGPT/Codex assistants<br>
**Version:** 1.2, 14 September 2026<br>
**Status:** Implemented numerical foundation, with live integration contracts awaiting confirmation.

## 1. Start here

ReStock helps a restaurant maintain purchasing recommendations as demand, stock and supplier conditions change. Aniq's current implementation calculates daily baseline forecasts, timed dish demand, ingredient requirements and one-day projected inventory. It does not yet generate the final purchasing recommendation or connect to the live agent workflow.

**What teammates need to do now:**

- **Chun Yang:** review the opening-stock and outstanding-supply interface, confirm the backend mapping, and identify the changes needed to export one trustworthy frozen example.
- **Rudy:** review how projected results, evidence references, Decimal quantities and incomplete findings will pass through the agent's tools and completion contract.
- **Ethan:** use the shared output semantics for future UI integration. A completed calculation can still contain shortages; an incomplete calculation must not display zero risk.

Use the same handover version for everyone. Record accepted decisions or requested corrections on [issue #16](https://github.com/rudybrrr/restock-ai/issues/16), preferably replying to the [worked integration proposal](https://github.com/rudybrrr/restock-ai/issues/16#issuecomment-5657607942). This document consolidates that proposal with implementation and usage information; it does not replace the issue's decision history.

This handover establishes what is available for integration review. It does not declare all ML work complete or establish agreement on unresolved backend/agent contracts.

## 2. GitHub access and inspected versions

**Teammates and their AI assistants should inspect Aniq's GitHub feature branch directly.** Use the same branch revision for the handover, implementation, tests and numerical documentation.

| Resource | GitHub location |
| --- | --- |
| Repository | [rudybrrr/restock-ai](https://github.com/rudybrrr/restock-ai) |
| ML feature branch | [feat/forecasting](https://github.com/rudybrrr/restock-ai/tree/feat/forecasting) |
| Intended repository handover path | [docs/ML_HANDOVER.md](https://github.com/rudybrrr/restock-ai/blob/feat/forecasting/docs/ML_HANDOVER.md) |
| Numerical interface documentation | [docs/ML_NUMERICAL_FUNCTIONS.md](https://github.com/rudybrrr/restock-ai/blob/feat/forecasting/docs/ML_NUMERICAL_FUNCTIONS.md) |
| Numerical and supporting source | [services/api/src](https://github.com/rudybrrr/restock-ai/tree/feat/forecasting/services/api/src) |
| Tests and fixtures | [services/api/tests](https://github.com/rudybrrr/restock-ai/tree/feat/forecasting/services/api/tests) |

**Publication record:** the reviewed numerical implementation is published on `origin/feat/forecasting` at [commit `e3c66b64f3bc53c7fc036c5d063222c02082d7ff`](https://github.com/rudybrrr/restock-ai/commit/e3c66b64f3bc53c7fc036c5d063222c02082d7ff). Its 15 implementation, test, fixture and documentation files were verified readable on GitHub. This handover is added in a subsequent documentation-only commit at `docs/ML_HANDOVER.md`; resolve the feature branch to that commit when reviewing the document and implementation together. Teammates can inspect the implementation, tests and handover directly on GitHub. Main remains separate, and source publication does not establish live integration or approval of #16 contracts.

| Item | Historical inspection record |
| --- | --- |
| Aniq's implementation branch | `feat/forecasting` |
| Main/base recorded during numerical review | `5827515ec48183ba908151fb0016b118cd801b1c` |
| Separate agent branch recorded in the proposal | `agent/coordinator-control-plane`, commit `764a27b9f89be86a36dd3d8dcc95079f77314239` |
| Agent branch's recorded merge base with main | `c8cc15d90a2014f3ae05a91e32c177da0d4d07d0` |

These are historical inspection records. Refresh remote refs and issue comments before review. Read the current `feat/forecasting` implementation and identify its exact commit SHA in your findings. If it differs from Aniq's published checkpoint, explain which revision you reviewed. Review backend and agent differences against their actual current branches without silently merging them.

**Reading main alone is insufficient.** A feature-branch push does not merge the numerical implementation into main. Each teammate's AI must explicitly select `feat/forecasting`, confirm that `inventory_projection.py` and the other modules below are present, and inspect the code and tests instead of relying only on this document or the issue description.

For GitHub-connected assistants, fetch files using the feature branch or its resolved commit SHA. For local Codex, inspect the remote branch in a separate review checkout/worktree if the teammate has unfinished work. Preserve their current branch, working files and staging. Do not reset, overwrite or merge their component merely to review Aniq's changes.

If the branch or required files cannot be accessed, report the exact missing resource and request repository access or confirmation that publication succeeded. Do not substitute main, infer code from the handover, or claim the review is complete.

Follow Rudy's workflow for subsequent implementation: use a feature branch based on main and do not push directly to main. Reviewing or publishing `feat/forecasting` does not itself merge, deploy or change shared contracts.

## 3. Implemented modules and remaining work

Paths below are relative to the repository root.

| Module | Implemented behaviour | Important boundary |
| --- | --- | --- |
| `services/api/src/forecasting.py` | `seasonal_baseline`: selects visible daily revisions, excludes promotional/censored observations, uses the latest four eligible matching weekdays or the documented eligible-day fallback | Normal-day baseline, not trained XGBoost; insufficient history is explicit |
| `services/api/src/requirements.py` | `calculate_requirements` and `sum_recipe_usage`: convert fractional served portions through the current recipes using exact Decimal arithmetic | No pack rounding, supplier allocation or implicit unit conversion |
| `services/api/src/service_buckets.py` | `allocate_service_buckets`: allocates a complete daily forecast into explicit dated half-hour service intervals while preserving totals | Supplied service profile is an assumption, not observed consumption |
| `services/api/src/inventory_projection.py` | `project_inventory`: consumes explicit opening stock, projected requirements and outstanding supply; calculates balances, expiry, unmet demand and first shortage intervals | One service day, fixture-based; no database reads, agent calls or purchasing decision |

The earlier `planning.py` and `sales.py` edits reuse `sum_recipe_usage`. The projector task did not modify those files or backend historical replay. No shared FEFO helper was extracted.

Tests are in `services/api/tests/test_forecasting.py`, `test_requirements.py`, `test_service_buckets.py`, `test_inventory_projection.py`, and the catalogue comparison in `test_seed_contract.py`. Fixtures are `seasonal_baseline_v3.json`, `service_profile_v2.json` and `inventory_projection_v1.json` under `services/api/tests/fixtures/`.

Read `docs/ML_NUMERICAL_FUNCTIONS.md` for detailed local Python semantics and the mapping of all twelve #15 acceptance criteria.

**Not completed by this handover:** full synthetic training dataset, trained/evaluated forecasting model, multi-day stock continuation, procurement optimiser, complete cost/policy evaluation, live input adapter, persisted projection evidence, agent business-tool integration or final application acceptance. Do not use the numerical test results as evidence that those features exist.

## 4. Shared calculation rules

- Use current catalogue IDs and base units: `kg`, `litres`, `pieces`. Do not restore older `D1` to `D5` or uppercase ingredient IDs.
- Forecast input uses final daily revisions once. Do not add intraday totals to the same final daily total. Four matching eligible weekdays support the weekday baseline; otherwise at least seven supplied eligible days support the fallback. Below coverage, expected demand is missing, not zero.
- Check for missing forecasts before allocating service buckets or converting requirements. Complete numerical vectors require explicit zeros; sparse recipe conversion is an explicit separate convention.
- Physical stocktakes, estimates from observed sales, and future projections are different facts. Never insert projected portions into observed sales/count routes.
- An already received quantity contributes through remaining opening stock only. Add only the outstanding portion of an external delivery as future supply.
- External commitments are fixed inputs. Approval does not place an order, receive stock or modify a commitment.
- Demand and stock use Decimal arithmetic. Fractional expected eggs are valid calculations; operational receipt/count scale is not a rounding rule for projected demand.
- Stock is usable through its expiry date and becomes unusable at the following Singapore midnight. Projected expiry does not prove measured waste.
- Supply at a bucket's start may cover it; supply at its end can cover a later bucket. Mid-bucket arrivals and unsupported opening cutoffs produce incomplete findings. No guessed prorating occurs.
- Unmet demand remains in its original interval. Later supply cannot retrospectively fulfil it. Ingredient-wise allocation does not prove whole dishes were served or quantify lost customer orders.

## 5. Projector input and output contract

### Existing Python interface

This is an internal numerical API, not an agreed HTTP request schema:

```python
project_inventory(
    opening_lots, buckets, menu_items, ingredients, recipes, supplies,
    *, as_of, target_date, horizon_end, known_at, captured_revision,
    opening_manifest, supply_manifest, recipe_manifest,
    service_profile, evidence, fixture_fefo,
) -> InventoryProjection
```

| Argument group | Required contents |
| --- | --- |
| `opening_lots` | Existing `EstimatedInventoryLot` records with stable identities, units, remaining Decimal quantities, receipt/count times, expiry/status, common as-of and complete observed coverage |
| `opening_manifest` | Every ingredient mapped to its complete expected lot IDs; an explicit empty list establishes zero held lots for a verified fixture |
| `menu_items`, `ingredients`, `recipes`, `recipe_manifest` | One complete resolved catalogue/recipe set; manifest contains expected dish/ingredient pairs, with quantities and units bound by recipe evidence |
| `buckets`, `service_profile` | Complete all-dish `ProjectedDemandBucket` vectors and dated `ServicePeriod` coverage; every declared interval must be represented |
| `supplies`, `supply_manifest` | Complete declared delivery set using `ExpectedSupply`, which wraps an existing `Delivery` plus expected expiry and expiry evidence; explicit empty lists when none exist |
| `as_of`, `target_date`, `horizon_end` | Aware operational opening and explicit service-day horizon; opening may be on that day or the preceding setup day; horizon end is inclusive and no later than the next midnight |
| `known_at`, `captured_revision`, `evidence` | Separate knowledge context and caller-resolved `SourceEvidence(reference, available_at, captured_revision)` for `snapshot`, `opening`, `supply`, `catalogue`, `recipe`, `forecast`, `profile`, plus positive-supply expiry assumptions |
| `fixture_fefo` | Explicit `EXPIRY_RECEIVED_ID` or `EXPIRY_ID`; no shared default is selected |

The projector validates supplied manifests and evidence consistency. It does not resolve references or independently prove that a manifest is complete. The backend must not manufacture a completeness manifest simply by listing whichever incomplete rows its reader returned.

For each receipt included with a delivery, its lot identity, ingredient, initial quantity, receipt time and expiry must agree with the opening lot. The opening lot's remaining quantity can be lower after observed consumption. Received totals must reconcile with receipt records, and expected quantity must equal received plus cancelled plus outstanding. Overdue unreceived supply remains incomplete rather than being assumed on hand.

### Returned values

`InventoryProjection` includes context, evidence, fixture ordering, `provenance="PROJECTED"`, `complete`, `findings`, and these numerical fields:

- `buckets`: dated `BucketProjection` values containing lot and ingredient balances.
- `lots`: horizon balances by namespaced lot/source key: opening, admitted supply, allocated, expired and closing.
- `ingredients`: the corresponding ingredient totals, plus required and unmet demand.
- `expiries`: dated projected unusable quantities.
- `first_shortages`: first shortage interval per ingredient.

Bucket balances are after start-boundary events and before end-boundary events. Horizon totals also include events in service gaps and at the inclusive horizon end. Do not assume every boundary arrival appears in a bucket's `admitted` field: it is already included in that bucket's opening balance and is counted in horizon admitted supply.

| Result | Meaning | Consumer behaviour |
| --- | --- | --- |
| `complete=True`, empty shortages | No shortage under the complete supplied assumptions | Still not proof of delivery certainty, forecast accuracy or purchase feasibility |
| `complete=True`, shortages present | Calculation completed and identified unmet ingredient demand | Use as evidence for purchasing investigation; no automatic Candidate is produced |
| `complete=False` | Missing/contradictory evidence or unsupported timing prevents a certified calculation | Preserve findings; numerical fields are `None`, proposed transport `null`, never zero |
| `ValueError` / validation error | Structurally invalid input | Reject with agreed diagnostics; do not fabricate a result |

Wrong evidence-object types may raise `TypeError`. Adapter error and outcome mapping still requires agreement.

## 6. Concrete example for both teammates

This is the compact version of the [published worked proposal](https://github.com/rudybrrr/restock-ai/issues/16#issuecomment-5657607942), which contains the full catalogue, JSON delivery example and complete interface mapping. It is a synthetic example, not a backend export.

Operational opening: **16 February 2026, 10:00 Singapore time**. Horizon ends at 17 February 00:00. The separate synthetic knowledge cutoff is 14 September 2026, 10:00 Singapore time. Source evidence is available at 09:59 on the knowledge clock; each independent alternative has its own capture token. Do not compare September recording time blindly with February operational time.

Opening stock is explicitly 6 kg vegetables, 20 kg rice and 20 kg tofu. The other five ingredients have verified zero held lots and zero demand. The three opening lots have complete count coverage at 10:00, zero historical deficit and usable-through dates of 18 February.

A 10 kg external vegetable delivery was ordered at 08:00. A 6 kg receipt at 09:00 is linked to the vegetable opening lot, leaving 4 kg outstanding. The outstanding shipment has a separately evidenced synthetic usable-through date of 19 February. That date is an explicit assumption, not inferred from the earlier receipt or a later actual receipt.

Projected demand is 100 tofu-bowl portions, split into 70 at 11:00–11:30 and 30 at 11:30–12:00. The actual recipe requires 0.100 kg vegetables, 0.100 kg rice and 0.150 kg tofu per portion. Each vector still includes all five dishes and all eight ingredients, with explicit zeros elsewhere. The small 70/30 profile is specific to this example, not a replacement for the existing 40/60 full-service fixture.

| Variant | First bucket: vegetable allocated / unmet / closing | Second bucket: allocated / unmet / closing | Horizon allocated / unmet / closing |
| --- | --- | --- | --- |
| 4 kg arrives at 11:00 | 7 / 0 / 3 kg | 3 / 0 / 0 kg | 10 / 0 / 0 kg |
| 4 kg arrives at 11:30 | 6 / 1 / 0 kg | 3 / 0 / 1 kg | 9 / 1 / 1 kg |
| Outstanding 4 kg cancelled | 6 / 1 / 0 kg | 0 / 3 / 0 kg | 6 / 4 / 0 kg |

The late and cancelled variants first run short at 11:00–11:30. Rice closes at 10 kg and tofu at 5 kg in every variant. This independent ingredient calculation does not claim the bowls were actually served when vegetables were unavailable.

The variants are independent frozen alternatives. A cancellation recorded after the receipt changes the current cancelled/outstanding quantities; it does not rewrite the earlier receipt's historical `remainder=EXPECTED` entry.

Two negative examples:

- Arrival at 11:15 gives `UNSUPPORTED_MID_BUCKET_ARRIVAL` and incomplete output.
- Missing the remaining shipment's expected expiry gives `MISSING_EXPECTED_EXPIRY` and incomplete output.

The local Codex reported scratch execution of all three alternatives and these two negative cases against the existing functions. The arithmetic above was also checked during review. This is not evidence that the backend can already export the bundle.

## 7. Chun Yang: requested backend confirmations

Use your [backend handover](https://github.com/rudybrrr/restock-ai/blob/5827515ec48183ba908151fb0016b118cd801b1c/docs/BACKEND_HANDOVER.md) and current code as the integration starting point. These are the concrete gaps to resolve, not a request to implement Aniq's engine again.

| Area | Existing seam | Confirmation or required change |
| --- | --- | --- |
| Opening state | `sales.estimated_inventory(session, as_of)`; `GET /api/v1/inventory/estimated?as_of=...`; `planning._snapshot["inventory"]` | Supply a common cutoff, complete expected lot/ingredient coverage, explicit zero-stock evidence and unchanged coverage/deficit findings |
| Time and revisions | Run `as_of`, `claimed_at`, integer `input_revision`; currently selected records | Define operational scope, knowledge cutoff and revision membership. An event count or frozen JSON alone does not establish historical selection correctness |
| Catalogue and recipes | Current catalogue models and snapshot ingredients/recipes | Capture the menu too; provide one resolved complete recipe/catalogue artifact and authoritative manifest/version, without another live read during calculation |
| Commitments | `deliveries.read_delivery`, `Delivery` and `Receipt` | Export the 10/6/4 and cancellation cases at the same capture; preserve receipt links and select only the applicable versions |
| Expected expiry | Actual receipt expiry and supplier offer shelf-life fields exist | Establish commitment-specific expected expiry and its captured source/assumption; unknown stays unknown |
| Projection dates/profile | Local explicit target/horizon/profile inputs | Agree their request/capture mapping. Do not infer a purchasing horizon from the one-day example |
| Precision | Observed quantities use `Numeric(12,3)`; projected outputs can be finer | Agree lossless Decimal-string transport and range handling separately from observed storage |
| FEFO | Backend uses expiry then lot ID; v2 specifies expiry, receipt time, ID | Confirm non-tied first-example compatibility. Agree tied ordering and identity mapping before claiming shared parity or changing historical replay |

**CY-001 remains an unresolved audit finding in the inspected code.** Current readers combine operational cutoffs with current active records and mutable supply/offer state. A caller can therefore supply a frozen set that already contains incorrectly selected history. The projector cannot fix that.

Required live evidence includes a captured bundle that remains stable after later backdated counts, sales corrections, receipts or cancellations, and a new capture that selects the correct eligible versions. Include explicit-zero, missing-lot, missing-interval, positive-deficit and receipt-retry cases. A byte-stable bundle alone is insufficient unless its original membership was correct.

**Please reply in #16** with the accepted mapping or precise alternatives, a representative export/example, remaining backend changes and their verification status. Input adapter work can begin against an agreed representative bundle while backend implementation proceeds. Live correctness testing requires those backend changes to be available.

## 8. Rudy: requested agent confirmations

The projector provides inventory evidence. It does not return a purchase Candidate, select suppliers or approve anything. Connect it through thin tools/adapters and preserve the same result for expiry and shortage investigations.

| Area | Required decision |
| --- | --- |
| Evidence identity | Agree how separate ESTIMATED opening and PROJECTED result artifacts are persisted/resolved and linked to the captured revision |
| Revision mapping | Reconcile main's integer `input_revision` with the agent's string `captured_state_revision`; a string conversion must still refer to the same actual frozen bundle |
| Complete results | A calculated shortage supports a further investigation. It is not automatically a feasible purchase or proof that no supplier can help |
| Incomplete results | Retain `None`/`null` numerical fields and findings. Do not turn them into zero risk, KEEP, an approval request or an actionable Candidate |
| Precision | Preserve projected Decimal strings through adapters; do not round through JavaScript numbers or observed-stock precision |
| Outcome and publication | Reconcile main's embedded Candidate with the agent's `candidate_result_ref` and evidence references; the projector itself supplies neither candidate representation |

The proposal suggests reusing the agent's `EvidenceRef` inventory category with distinct source/provenance and references for opening and projected artifacts. **That category choice and resolver are still proposed.** Do not fabricate an evidence ID or treat a generated run-derived string as a stored calculation artifact.

Proposed incomplete mapping for confirmation:

- Missing required coverage/evidence: `ESCALATE / MISSING_REQUIRED_DATA`.
- Unsupported timing: `ESCALATE / CALCULATION_INCOMPLETE`, preserving the finding code and evidence; not `SEARCH_LIMIT_REACHED`, because the projector performs no search.
- Mixed/stale revision evidence: reject the inconsistent bundle and route through agreed freshness handling.
- Structural invalidity: existing error envelope with diagnostics; actual execution failure remains distinct.

Main and the inspected agent branch do not yet expose the same completion vocabulary. These proposals must be reconciled with Chun Yang before publication. Existing policies about physical purchases and manager approval remain unchanged.

**Please reply in #16** with the chosen reference/resolver and outcome mapping, adapter locations and positive/negative contract examples. These decisions can proceed alongside Chun Yang's input work; the full agent does not have to be finished before the input adapter is developed.

## 9. Verification and how to review locally

| Evidence | Result and limitation |
| --- | --- |
| Local Codex numerical suite | 193 passed, including 84 projector cases |
| Independent review execution | The same 193 numerical tests passed in an isolated review environment; this did not run PostgreSQL integration fixtures |
| Local Codex full backend suite | Reported 241 passed with two existing dependency warnings; not independently rerun in this review |
| Local Codex static checks | Reported Ruff, Pyright, formatting and diff checks passed |
| Reviewed source continuity | Earlier numerical source/tests were unchanged during the projector task; publication should preserve those reviewed changes or explicitly identify later differences |
| Contract-proposal scratch checks | Local Codex reported three supply variants and two incomplete cases passed; no full application suite rerun for that task |

These checks establish supplied-input numerical behaviour, not real forecast quality, trustworthy live provenance, agent publication, hosted deployment or completion of the hackathon application. Earlier numerical count 109 and backend counts 157/107/47 describe older checkpoints.

After checking out the verified feature-branch revision in a compatible review environment, use the repository's documented dependency setup. From `services/api`:

```powershell
uv run pytest -q tests/test_forecasting.py tests/test_requirements.py tests/test_service_buckets.py tests/test_inventory_projection.py
uv run ruff check .
uv run pyright
```

The complete backend suite requires the API README's isolated test PostgreSQL setup. Do not point database-creating/dropping test fixtures at a shared demo or production database. Test the complete repository at the inspected feature-branch revision with its declared dependencies. A source-only review does not constitute a test run.

### Instructions for each teammate's AI

Read this handover from `docs/ML_HANDOVER.md` on `feat/forecasting`, then inspect that branch's actual numerical modules, relevant tests, fixtures and `docs/ML_NUMERICAL_FUNCTIONS.md`. Resolve the branch to a commit SHA and use that revision consistently for the review. Read applicable repository instructions and current #15/#16 discussions.

Compare Aniq's interface with the teammate's actual current implementation: Chun Yang's backend snapshot, delivery, inventory and schema code, or Rudy's agent contracts, tool adapters and completion handling. Use the relevant owner section in this handover as a checklist, not as proof that the named fields or contracts already exist.

Return the inspected commits, compatible fields, concrete gaps, proposed amendments and the decisions requiring owner confirmation. Distinguish current behaviour from proposed changes and tests actually executed from historical test reports. Do not implement cross-component changes merely because this document describes them. If required files or repository access are missing, say exactly what could not be checked.

Record the teammate's accepted decisions explicitly in #16. An AI recommendation alone is not a shared agreement.

## 10. Completion boundaries and next sequence

1. Chun Yang and Rudy review their sections and record accepted decisions or corrections in #16. No separate Ethan review is required to circulate this handover.
2. Aniq reconciles those decisions into the interface mapping. Preserve which items are agreed, implemented and actually tested.
3. Aniq implements the thin input adapter once its required input contract is settled. Chun Yang supplies the corresponding authoritative backend behaviour. Do not invent absent values to make the example pass.
4. Run the agreed backend-export-to-projector example and negative cases. Test actual state selection, receipt/cancellation handling, quantity preservation and incomplete output.
5. Connect persisted projection evidence and Rudy's consumer/completion mapping when their contracts and implementations are ready.

Fixture implementation under [#15](https://github.com/rudybrrr/restock-ai/issues/15) is the implementation to inspect on `feat/forecasting` after publication verification in section 2. Shared equal-expiry parity remains deferred, and helper extraction was not performed. Do not close #15 as fully integrated merely because numerical tests pass. [#16](https://github.com/rudybrrr/restock-ai/issues/16) remains the contract and live-evidence coordination point.

Broader backend issues retain their own acceptance: [#7](https://github.com/rudybrrr/restock-ai/issues/7) inventory/materiality, [#8](https://github.com/rudybrrr/restock-ai/issues/8) genuine first purchase plan, [#9](https://github.com/rudybrrr/restock-ai/issues/9) exact-version approvals, [#10](https://github.com/rudybrrr/restock-ai/issues/10) reassessment, [#11](https://github.com/rudybrrr/restock-ai/issues/11) contingency/no-double-ordering and [#12](https://github.com/rudybrrr/restock-ai/issues/12) integrated demo and handover verification. Closing a narrow numerical task does not close those workflows.

Aniq can continue independent approved forecasting-data/evaluation work while these specific contracts are resolved. The team does not need to wait for entire components to finish before coordinating interfaces.

## 11. Source precedence and maintenance

This handover is based on the reviewed projector implementation, numerical documentation, Chun Yang's backend handover, the supplied team decisions and the published #16 proposal. The approved ML planning basis is `ReStock_ML_Decision_Engine_Plan_v2_Review_Reconciled.md` plus Ethan-approved `ReStock_ML_Decision_Engine_Plan_v3_Integration_Amendment.md`, subject to subsequent explicit decisions. Numbered filename suffixes may identify downloaded copies rather than newer content.

Use current code for existing interfaces, approved plans for intended scope, and explicit later team decisions for resolved changes. Report conflicts. In particular, the old backend specification's claim that only health checking exists is stale, and older escalation lists must not silently override later contract discussions.

At the original handover check on 14 September 2026, #16 contained the published proposal and no owner replies. This access-method revision does not establish whether further replies have since been added. No shared-contract approval is inferred. If newer replies or code exist when you read this, reconcile them and identify the new source/commit.

Keep one shared document. For each subsequent revision, record date, affected interface, accepted decision and evidence link. The repository copy is `docs/ML_HANDOVER.md` on `feat/forecasting`; share its GitHub link and the verified implementation commit with teammates. Editing this document does not itself publish code, change issues, grant repository access or implement any adapter.

### Revision history

| Version | Date | Change |
| --- | --- | --- |
| 1.0 | 14 September 2026 | Initial shared ML implementation and integration handover |
| 1.1 | 14 September 2026 | Changed teammate/AI review access to GitHub `feat/forecasting`; added branch, source, test and handover links, commit verification and direct AI-review instructions. Numerical scope, test evidence and unresolved contracts are unchanged. |
| 1.2 | 14 September 2026 | Added the repository handover and verified implementation commit permalink; corrected the pending-publication record. Numerical scope and unresolved contracts are unchanged. |
