# ReStock ML and Decision Engine Handover

## Current handover — v1.18, 25 September 2026

Aniq's post-purchase Backend slice is on
[feat/ml-post-purchase-contingency](https://github.com/rudybrrr/restock-ai/tree/feat/ml-post-purchase-contingency),
based on main `1463fcdbea381a51e78d30cc3fc12e7f14ae9d01`.
Read **[POST_PURCHASE_CONTINGENCY_CONTRACT.md](POST_PURCHASE_CONTINGENCY_CONTRACT.md)**
for Rudy's exact persisted types, selector/readers, HTTP routes, evidence and routing.
The PR records review/publication status; no merge or live-worker claim is made here.

Implemented `POST_PURCHASE_FIXED_SUPPLY_V1`: versioned synthetic case/policy 5 at
16 February 10:00 SGT and version 6 at 11:00, with original delayed order and linked
emergency purchase frozen as fixed supply. Version 4 first purchase is preserved.
Existing tables store authority; the claimed run snapshot stores immutable input
and a hash-bound result. Search and independent validation are reused, with
stale inputs and contradictory completion rejected. No Delivery is created or
changed by the calculation. Normal procurement, Agent code and UI are unchanged.

Connected examples: recorded 4 kg rescue gives KEEP/SGD0; only 2 kg expected gives new 2 kg/
SGD11; cancelled 4 kg gives new 4 kg/SGD15; received 4 kg gives opening 10, emergency outstanding 0,
KEEP/SGD0. At 11:00 the quote's placement window has elapsed: late supply produces
typed NO_FEASIBLE_SUPPLIER within the declared empty new-order domain. Missing
coverage/search exhaustion is incomplete; budget failure is POLICY_VIOLATION.
New candidates have pending exact-version approval, new-purchase cash and null
full economic costs. Actual purchase recording remains a separate manager action.

For #10, the explicit split fixture changes fresh/market NEW capacity to 2 kg
each: fresh 2 + market 2, cash 8 + 6 + 8 = **SGD22**, all 9 allocations enumerated,
independent validation complete/feasible. This is numerical evidence, not a claim
that the supplier-event worker path is integrated.

Verification on 25 September: Windows new acceptance **14 passed** (109.97s);
Linux final focused API/PostgreSQL + split/case/policy acceptance **24 passed**
(135.33s). Full locked Linux Python3.12/PostgreSQL18 regression before test-only
corrections: **1,110 passed, 2 failed** (751.01s). Both failures were obsolete
unknown-version assertions reproduced on unchanged main1463fcd (2 failed,8.49s):
version4 already exists. They now request absent version999; all9 case/policy
tests pass on Windows (60.24s), and both are included in the final24 Linux passes.
No observed failure is left unresolved or waived. The full suite was not repeated
after those test-only corrections and two added partial-receipt assertions; all
production source/configuration hashes match the completed full gate. Whole-API
Ruff/Pyright and all12 changed-Python format checks pass on Windows and Linux;
diff checks pass. Two dependency deprecation warnings remain. No live gateway,
worker integration, browser, deployment or operational database acceptance claimed.

The bounded contract requires two known checkpoints, one original delivery and
one emergency delivery linked to v4, exact catalogue and complete observed
coverage. Other clocks, additional commitments, promotions and newer actionable
plans fail explicitly. Synthetic quote assumptions are versioned demo values,
not live supplier evidence or general business policy. Production calendar,
full economic costing and broader post-purchase states remain separate.

**Rudy:** consume `PostPurchaseInput` / `PostPurchaseResult` through
`select_post_purchase_input`, `persist_post_purchase_result` and
`read_post_purchase_result`; carry result/candidate references and keep incomplete,
supplier-infeasible and policy-infeasible outcomes distinct. Wire this before
Coordinator completion; do not recalculate or modify recorded orders. Worker/model
changes and a real typed gateway run remain yours. **Chun Yang:** review the
bounded persistence/completion changes and deploy the approved seed increment
through the existing workflow. **Ethan:** UI remains outside this PR.
Continue live provenance/freshness decisions in
[issue #16](https://github.com/rudybrrr/restock-ai/issues/16).

Revision 1.18 adds the connected post-purchase slice and split fixture. Entries
below describe historical checkpoints; v1.17's NORMAL_ONLY statement predates
the approved first-case activation in PR57.

## Historical numerical-only checkpoint — v1.17, 22 September 2026

Aniq's bounded contingency numerical policy is implemented on
[feat/ml-contingency-procurement](https://github.com/rudybrrr/restock-ai/tree/feat/ml-contingency-procurement),
based on main `843efe59b8217d7ba23c15ff02fd5ad978a7720a`.
The normal PR records publication/merge status; this document does not activate a
Backend policy. Read **[ML_CONTINGENCY_CONTRACT.md](ML_CONTINGENCY_CONTRACT.md)** for
the exact input/output mapping and acceptance examples.

New `src.contingency.search_contingency` and independently callable
`validate_contingency` reuse multi-day projection, canonical forecast/recipe/stock/
delivery/offer models and exact cash arithmetic. They preserve fixed commitments,
consume only future demand, recommend additional quantities only, account for
explicit new-shipment fees, and return validated additions plus a diagnostic
no-new-purchase projection. The normal search and its pruning guards are unchanged.

Frozen numerical tags: `BOUNDED_CONTINGENCY_CASH_V1`,
`CONTINGENCY_CARTESIAN_V1`, `EXPLICIT_NEW_SHIPMENT_ONCE_V1`, with existing cash,
FEFO, expiry, semantic tie and CONTEXT_ONLY reliability policies. Business amounts,
windows and evidence are explicit authorised inputs, not guessed defaults. Scope:
current-instant placement in a complete finite domain, residual one/multi-day
protection, complete assessment of supplied late originals; no continuation or
full economic objective. Complete search, candidate feasibility and finite-domain
optimality are separate. Search-limit incumbents are never actionable.

Synthetic example: 100 remaining tofu bowls need 10 kg vegetables. Original10kg
has6 received in opening and4 delayed until next day. Rescue4kg at S$2/kg plus
deliveryS$3 and exclusive emergencyS$4 gives **S$15**, no protected shortage,
and the original4kg remains in later stock. On-time original remainder gives
**no addition/S$0**. No timely slot gives typed supplier infeasibility; budgetS$14
gives policy infeasibility. Missing expiry or interrupted search is incomplete.

Fresh verification: **48 new contingency tests and 797 total numerical regressions
passed** (34.09s). Locked Linux Python 3.12 / isolated disposable PostgreSQL 18:
**1,067 full Backend tests passed** in 486.35s, two dependency warnings, no failures.
Whole-API Ruff/Pyright and changed-Python formatting passed on Windows and Linux;
diff checks passed. All source/tests/fixtures match the isolated gate snapshot;
only handover documentation changed afterwards. No failure waiver was used.
No live provider, normal worker, hosted deployment or
activated contingency API workflow is claimed.

Current source reconciliation: multi-day projection merged via #35; the old
decimal-string assertion was fixed in #36; Agent/control-plane adapters merged
via #37. Historical failure waivers below do not apply to this increment.
Backend still freezes `NORMAL_ONLY` / normal first-slice transport. Chun Yang's
latest #11 comment explicitly requests this numerical policy before changing that.
Rudy's current adapter maps all finite-domain infeasibility to supplier failure;
the contract specifies the required discriminating contingency mapping.

**Chun Yang:** persist/map/activate the new policy and complete residual-window,
shipment, commitment, forecast and evidence inputs; preserve freshness and exact
approval/version rules. **Rudy:** consume that frozen contract, call both kernels,
persist resolvable results, preserve incomplete/policy/supplier distinctions, and
complete the external-emergency recording/reassessment story with Backend.
Continue live evidence/freshness confirmations in
[issue #16](https://github.com/rudybrrr/restock-ai/issues/16), and contingency
activation/acceptance in [issue #11](https://github.com/rudybrrr/restock-ai/issues/11).
Neither issue is closed by the numerical increment. Full economic OPEN-02 and
production dataset/calendar decisions remain separate.

Revision 1.17 adds this bounded implementation and the focused contract; previous
commits, tests and task-specific exceptions below are **historical records**.

## Historical multi-day checkpoint — v1.16

**From:** Aniq<br>
**For:** Chun Yang, Rudy and Ethan, including their ChatGPT/Codex assistants<br>
**Version:** 1.16, 20 September 2026<br>
**Status:** Ingredient-specific multi-day coverage and projected inventory are
implemented on [feat/ml-multiday-coverage](https://github.com/rudybrrr/restock-ai/tree/feat/ml-multiday-coverage),
based on main `32a01213da64009c603eae8d7061980bcdb71fdc` (PR #34).
The feature branch contains the reviewable implementation; its pull request records merge status.

### Multi-day numerical increment

`src.coverage.calculate_coverage` calculates protected ingredient windows from
explicit anchored dispositions and feasible routine opportunities.
`src.multiday_projection.project_multiday` consumes existing ForecastVersion,
canonical recipes, estimated opening and fixed commitments through the reused
forward-depletion kernel. It returns per-ingredient coverage, dated balances,
unmet demand/first shortages, expiry, safety/storage breaches and completeness.
The public one-day projector remains compatible. No Backend, Agent or UI contract
is changed; no new orders, multi-day purchase optimiser or final economic score.

Worked fixture: issue 15 Feb 2026 22:00 SGT; chicken protects to 17 Feb 10:00
(1.500 kg), oil to 23 Feb 10:00 (.700 litres), rice to 2 Mar 10:00 (28.000 kg).
The union forecast end does not extend the shorter ingredients' demand windows.
Uncommitted future opportunities add zero inventory. A partial 10 kg rice receipt
with 6 already in opening and 4 arriving 20 Feb 22:00 allocates only 10 of 28 kg;
18 kg unmet, first shortage 19 Feb 11:00–11:30. Later supply does not erase it.
A missing later forecast retains an earlier verified shortage plus incomplete
findings. Neither complete-with-shortage nor incomplete means an approvable plan.

Inputs, commands, 18-group acceptance map, fixture assumptions and examples are in
[ML_NUMERICAL_FUNCTIONS.md](ML_NUMERICAL_FUNCTIONS.md). Production OPEN-at-decision
semantics are not established by the inspected contracts: the supported convention
and 21-day cap are explicit fixture inputs only. No terminal/continuation/economic
policy is approved by this increment.

Chun Yang must supply authoritative frozen schedules/domains/forecasts/opening/
commitments and confirm production boundary/assessment policy. Rudy must preserve
per-ingredient scope, source evidence and known risk alongside incomplete results.
Continue shared confirmations in [issue #16](https://github.com/rudybrrr/restock-ai/issues/16).
Next ML work: separately scoped multi-day procurement feasibility/search; full
costing, adaptive driving and evaluation remain separate.

Verification on 20 September: **749 numerical tests passed**, including 67 new
coverage/projection cases and both physical simulators. Locked Linux Python 3.12 /
disposable PostgreSQL 18 full suite: **822 passed, 1 failed**, 248.20 seconds, two
dependency warnings. The exact sole failure reproduces on unchanged main `32a0121`
in the same environment (4.72 seconds). Whole-API Ruff/Pyright and changed-Python
format checks pass on Windows/Linux; diff checks pass. No Actions workflows or
required status checks are configured; normal PR protection still applies.

After the full run, the test-only supplier ID was aligned from the synthetic
`fresh-market` to canonical `fresh`. All 67 focused cases and static checks were
rerun; application source/configuration stayed byte-identical to the full-suite
snapshot. No Backend assertion was changed. No browser, Bedrock or live workflow
acceptance is claimed; shared PostgreSQL/API/frontend remain stopped.

The user's **task-specific exception is applied** for ONLY the unchanged-main
inventory-adjustment string assertion (expected "0.5", actual "0.500"). No other
failure or setup error remains. This does not waive required checks or reviews.
Chun Yang owns the correction; the assertion remains unchanged and prevents
subsequent KEEP assertions from executing.

Revision 1.16 adds coverage/projection and its bounded handoff; prior implementation
commits and checks below remain historical.

### Historical seven-day checkpoint (v1.15)

**Version:** 1.15, 20 September 2026<br>
**Status:** Continuous seven-day physical execution is implemented on
[feat/ml-seven-day-simulator](https://github.com/rudybrrr/restock-ai/tree/feat/ml-seven-day-simulator),
based on main `f5199256d0c9e65fe9c94ed473ff3c4f91ac4ae2` (merged PR #33).
See [PR #34](https://github.com/rudybrrr/restock-ai/pull/34) for merge status.
Aniq explicitly authorized its normal merge on 20 September after reviewing the
one unchanged-main test failure below. This exception applies only to PR #34.

### Seven-day physical execution

`src.physical_scenario.simulate_scenario(PhysicalScenario, Catalogue)` carries
true lot stock and commitments through seven consecutive SGT calendar days,
including overnight arrivals, midnight expiry, cancellation, new explicit external
commitments, hidden losses, scheduled counts and explicit disposal. It shares
the one-day executor's recipe/FEFO/event operations; the one-day API is preserved.
Daily state snapshots are not new stocktakes. Expired stock is retained until
explicit removal and never repeatedly counted as new expiry.

`scenario_observations_at(result.observations, known_at=...)` supplies only available
observations, separately from attempted demand, hidden losses and evaluator results.
Counts do not reset physical state; daily final sales replace batches and are not
another consumption movement. These offline types are not new Backend contracts.

The explicit development fixture covers **16–22 February 2026**: **15 attempted,
11 served, 4 unmet; 7 paid + 4 free; S$35 revenue**. Chicken conservation is
0.600 opening + 1.350 new receipts = 1.650 consumed + 0.150 hidden loss +
0.100 disposal + 0.050 retained expired. The original commitment and an additional
external purchase remain distinct. See [numerical inputs, outputs, independent
arithmetic and runnable command](ML_NUMERICAL_FUNCTIONS.md#continuous-seven-day-physical-simulator--20-september-2026).

Verification from the implementation turn on 20 September 2026 (not rerun for
this documentation-only approval record):

- **682 numerical tests passed**, including 54 seven-day and 76 one-day cases,
  plus 552 forecasting/recipe/bucket/projector/history/procurement/promotion/
  materiality/policy regressions. The local invocation also included three seed
  integration tests without TEST_DATABASE_URL: those three stopped at setup;
  they were subsequently covered by the isolated full suite below.
- Full locked Linux Python 3.12/PostgreSQL 18 gate: **755 passed, 1 failed**.
  Exact summary: `1 failed, 755 passed, 2 warnings in 252.16s (0:04:12)`.
- The sole failure is
  `tests/test_inventory_adjustment_contract.py::test_safe_inventory_correction_can_certify_keep_current_plan:64`:
  expected `"0.5"`, actual `"0.500"`. The same test fails on unchanged current
  main `f5199256d0c9e65fe9c94ed473ff3c4f91ac4ae2` in the same isolated environment
  (3.81 seconds). Quantities are numerically equal, but the assertion prevents
  the subsequent KEEP checks. Chun Yang owns the serialization/test correction.
  No Backend assertion or implementation was weakened or modified.
- Whole-API Ruff and Pyright passed on Windows and Linux; changed-file formatting
  and diff checks passed. The isolated API snapshot matches the tested checkout,
  except a final test-format-only change with an identical parsed AST. No runtime
  or dependency configuration changed. The repository has no Actions workflows
  or required status checks; normal PR protection still applies.
- CLI repeated output/hash verification passed. Two existing dependency warnings
  remain. No browser, Bedrock or live-agent acceptance was run. Project PostgreSQL
  stayed stopped; only disposable test databases were used.

**PR #34 specific exception accepted:** on 20 September, Aniq instructed:
"You can merge. If you need to, update the documentation for this failed test."
This authorizes normal PR #34 merge despite the recorded unchanged-main failure.
The failed test remains failed and Backend-owned; no assertion was weakened and
no general test waiver is granted. The exact failure and its impact remain above.
Application/test content is unchanged from tested implementation commit
`f4f2f827e59a38cdc0b1d49b8815664c1fc6291b`; only these documentation records changed.

Remaining work: Aniq's adaptive scenario/policy driver, multi-day procurement and
full economics/evaluation; reporting-error generation and final history-calendar
approval remain separate. Chun Yang owns authoritative snapshots/ingestion,
revisions and persistence; Rudy owns agent driving and observation/result adapters.
Backend PR #31/#32 contracts are on main, but this fixture execution does not prove
live Agent integration. Preserve owner confirmations through issue #16.

### Historical PR #33 verification and one-day interface

The paragraphs below preserve PR #33's original results and its specific accepted
failure. They are historical, not the current seven-day gate.

### One-day physical execution core

`src.physical_simulator.simulate_day(PhysicalDay, Catalogue)` executes explicit
integer attempted orders against true lot stock. It enforces atomic promotional
pairs, receipt-aware FEFO, expiry and exact Decimal conservation; reconciles actual
receipts/cancellations against fixed opening commitments; and returns served/unmet
portions, physical ledgers and separately accessible observation records.
`observations_at(result.observations, known_at=...)` exposes only available facts.
The existing recipe helper, dated allocator and canonical models are reused.
No Backend historical replay, Agent adapter or transport contract is changed.

The synthetic `physical_day_v1.json` fixture has 9 attempted portions, 5 served,
4 unmet and SGD 19 revenue, with one atomic pair, partial receipt/cancellation,
expired stock and a hidden rice loss. See [callable semantics and reproduction](
ML_NUMERICAL_FUNCTIONS.md#one-day-physical-simulator--20-september-2026).
Tests include independent reference arithmetic and the full five-dish 320-portion
recipe oracle. Missing manifests and inconsistent inputs are rejected, not defaulted.

Fresh pre-merge verification: **628 numerical tests passed**, including 76 physical
simulator cases (25.86 seconds). Whole-API Ruff and Pyright, changed-file formatting
and diff checks passed. The full locked Linux Python 3.12/PostgreSQL 18 suite:
**701 passed, 1 failed** (254.19 seconds; two dependency warnings). The sole failure,
`test_safe_inventory_correction_can_certify_keep_current_plan`, expects `"0.5"`
but receives `"0.500"` at `tests/test_inventory_adjustment_contract.py:64`.
It also fails on unchanged main `550d39b` in the same environment (3.78 seconds).
The old three snapshot-history failures now pass. No test assertion was weakened.
Aniq explicitly accepted this specific unchanged-main failure on 20 September:
"Merge with this specific failure recorded." Normal PR #33 merge is authorized;
the failure remains Backend follow-up, not a pass or a blanket test exception.

Review reproduced and fixed a simulator receipt-retry identity collision: use
the `(delivery_id, request_id)` pair, not colon-joined text. Independent regression
tests accept distinct colon-containing IDs and still reject actual retries.
The documented library fixture remains 5 served, 4 unmet, SGD 19.00. No browser,
Bedrock or live-agent tests were run. PostgreSQL was isolated from the project DB.

Historical PR #33 completed the bounded one-day physical core, not the random event generator,
multi-day manager/policy scenario driver, reporting-error/correction generator,
full economic scorer or live publication. Opening counts are exact; hidden losses
remain evaluator-only until their physical effect appears in counts/sales. Existing
full-history dates, supplier enrichment and economic policies still need their
respective decisions. The seven-day execution increment is now implemented above;
Aniq owns later horizon/evaluation work. Chun Yang owns authoritative ingestion/revision semantics; Rudy owns routing and publication
adapters. Preserve owner coordination in issue #16; this change closes no issue.

Historical sales-policy merge verification (18 September; superseded by the
current full gate above for the three snapshot-history tests):
Aniq explicitly authorized proceeding with the normal merge of
[PR #29](https://github.com/rudybrrr/restock-ai/pull/29) despite the three
snapshot-replay failures reproduced on unchanged main at that time. That historical
failed result is preserved below; the current gate verifies those tests now pass.

## Current frozen sales policy

Aniq approved the reviewed recommendation on 18 September: **SALES_MATERIALITY_V1**
requires >=20 expected served portions per dish AND >=2 completed half-hour
buckets, with every elapsed service interval covered. Both limits are inclusive,
cumulative within one day. The deviation rule remains inclusive
`abs(observed - expected) >= max(5, 0.2 * expected)`. This is the authoritative
numerical definition for the current one-day demo, not restaurant calibration.

Implementation base is main `a3aae33ae6650f9ed46880fb28c6a8059ca833ef`;
focused branch [feat/ml-sales-policy](https://github.com/rudybrrr/restock-ai/tree/feat/ml-sales-policy).
See the [exact contract and call](ML_NUMERICAL_FUNCTIONS.md#frozen-sales-materiality-policy--18-september-2026).
The earlier request for numerical approval is resolved by Aniq's explicit
"Proceed as you suggested", following the recommendation and limitation review.

`src.materiality.SALES_MATERIALITY_V1` is an immutable definition with no evidence.
`resolve_sales_threshold_policy(policy, *, known_at, captured_revision)`
returns a complete resolution only for the exact approved values and compatible
supplied evidence. Missing policy, unknown/fixture versions, conflicting parameters
or missing/late/wrong-capture evidence return findings and no resolved policy.
Malformed quantities raise ValueError/TypeError. The existing assessment calls
the resolver internally too; there is no fixture fallback or bypass through
arbitrary nonempty version strings. Changed values require a new approved version.

The current 100/60/80/40/40 first-slice forecast and 40% lunch/60% dinner profile
give first eligibility at 12:30 chicken-rice, 13:00 chicken-noodles, 13:30
fried-rice and **18:00 tofu/vegetable noodles**, provided all required observations
and evidence are available. Aniq accepted this limitation. Before then even a
large sales deviation for a low-volume dish may remain insufficient exposure.
Known inventory/safety risk is assessed independently and can still be material.
At 18:00 tofu expected 22: actual 26 is non-material, 27/17 material with other
checks complete; missing coverage is unknown. Its future demand remains 18.
Zero expected demand does not gain sales exposure from actual sales alone.

**Chun Yang:** persist/expose the selected definition/version and values, effective
applicability and recording/capture references, issued forecast/original input,
plan/safety evidence and exact request/result. Preserve frozen replay, freshness
and lifecycle checks. A constant is not a persisted run selection.
**Rudy:** translate that authoritative selection into the existing typed call;
preserve True-with-incomplete, None and complete False, retain findings/references
and forward only future demand. Never fill missing values from fixture or code
defaults, or turn incomplete findings into KEEP/approval. Both should retain
mapping responses in [#16](https://github.com/rudybrrr/restock-ai/issues/16).

No Backend schema, persistence, migration, queue or Agent code changed. Rudy's
supplier-only get_materiality and sales-supported flag are his reported newer
state, not independently verified on the accessible Agent remote branch.
Policy agreement/implementation does not mean the live sales route is connected.

Fresh verification: **552 numerical passes**, including 124 focused materiality/
policy cases (79 existing +45 policy). The final 45 policy cases also passed in
Linux after the test-only immutability expression was made type/lint compatible.
Whole-API Ruff and Pyright, three Python formatting checks and diff checks pass.
Full locked Linux Python 3.12/PostgreSQL 18 gate: **616 passed, 3 failed**, two
dependency warnings, 664.86 seconds. The same three snapshot-history failures
freshly reproduced on unchanged base a3aae33 in 22.71 seconds: captured revisions
1→3, 1→8 and 1→2 despite replaying original as_of/known_at. No new failures.
Aniq's existing exception for these exact three failures is retained; no blanket
waiver, assertion changes or protection bypass. They remain Backend follow-up.
The focused feature branch/PR records publication; original work/staging remain
preserved. This is not an end-to-end sales-route test or deployment.

Draft reply for Aniq to send Rudy (not sent automatically):

> I have approved and implemented SALES_MATERIALITY_V1: >=20 expected portions
> per dish AND >=2 complete half-hour buckets, with complete elapsed coverage;
> deviation is >=max(5,20%) in either direction. src.materiality exposes the
> immutable definition and resolve_sales_threshold_policy; assessment enforces
> the version too, rejecting fixture/unknown/conflicting policies. The numerical
> contract and tests are on feat/ml-sales-policy; use its PR for merge status.
> Chun Yang still needs to persist the authoritative selected policy and frozen
> request/result references. Your adapter must preserve unknown/incomplete and
> independent stock-risk results. Policy completion does not mean the sales route
> is connected.

## Previously merged sales-driven replanning handoff

Base main: `e179c758bba0c7d7d9db582ba98a0abae44fac6e`, including PR #27
promotion functions and PR #28 activity/commitment contracts. See
[the callable numerical contract](ML_NUMERICAL_FUNCTIONS.md#authoritative-sales-materiality-and-frozen-remainder)
and [focused implementation branch](https://github.com/rudybrrr/restock-ai/tree/feat/ml-sales-materiality).
This section supersedes earlier statements that those Backend inputs are absent.
The original checkout and unpublished `feat/ml-materiality` draft remain preserved.

**Rudy:** call `src.materiality.assess_sales_materiality` with the canonical
claimed-run `ProcurementContract`, resolved pre-service promotion-aware
`ForecastVersion`, its original `ForecastInputArtifact` and catalogue, snapshot
evidence, explicit `SalesThresholdPolicy` and `RiskSnapshot`. The latter reuses
the existing projector input bundle; do not recalculate an expectation from the
same triggering sales. Use current frozen rows' `recorded_at` as well as batch
identity/revision and bounds. Preserve actuals separately and forward only
`result.remainder.future_buckets`, using the issued full-day profile, to future
recipe/projection/procurement calculations. A missing remainder is not zero demand.

- Material True establishes a deviation or hard risk even if another check is
  incomplete. Inspect `material_findings`, `findings`, first shortage/safety
  intervals, affected IDs and evidence references.
- Material False requires the complete declared sales/inventory/safety scope.
  It never independently chooses KEEP_CURRENT_PLAN or grants approval.
- Material None or any incomplete required evidence calls for missing-data
  follow-up. Keep calculation completeness separate from tool execution and Agent
  outcome. Persist the request/result and references before lifecycle decisions.
- `select_sales_revisions` and `select_daily_history` are independently callable
  pure helpers. Corrections replace; authoritative daily totals never add batches;
  the original versioned forecast input remains unchanged.

**Chun Yang:** PR #28 already supplies frozen operational activity, immutable
baseline-history semantics and complete outstanding-commitment transport.
Remaining mappings are precise: persisted issued forecast/result and original
input references; authoritative materiality policy/version and exposure values;
complete opening/recipe manifests including explicit zeros; resolved plan/safety
evidence; and a persisted materiality request/result reference accepted through
freshness/completion checks. Supply the existing frozen rows, not current facts.
No schemas, persistence, queue or publication endpoints were changed here.

**Both:** record remaining contract/mapping responses in
[issue #16](https://github.com/rudybrrr/restock-ai/issues/16). The inspected remote
Agent branch remains `764a27b`; Rudy's newer unpublished Pass 6 work was not
available for verification. Its existing MATERIALITY / FORECAST_RESULT /
INVENTORY_SNAPSHOT evidence categories are documented as the consumer mapping,
not falsely described as merged main schemas. The current main Completion schema
does not carry a numerical materiality result directly.

Source traceability: v2 §§6.3, 7, 9, as qualified by v3 §§5–7 and the current
`FORECAST_ACTIVITY_V1` contract. The supported demo threshold is
`max(5, 0.2 * expected-to-date)` in either direction. Adequate exposure and
policy identity are explicit inputs. At PR #29 the 20-portion/two-bucket policy
was fixture-only; the approved frozen policy above now supersedes that limitation.
No clipped intraday demand adjustment is enabled.

Worked synthetic example: two elapsed lunch buckets total expected 20 portions
per dish. With complete risk evidence, chicken-rice actual 24 is non-material;
25 is material at the exact five-portion threshold; 15 is also material.
A missing second batch makes observed/deviation and materiality unknown and
returns no remainder. Missing risk prevents non-material certification even if
the observed deviation is only four. Known stockout remains material despite
missing exposure policy. Original 150 daily portions per dish leave 130 future
portions per dish; chicken requirement is exactly 35.100 kg, excluding actuals.
Daily correction 20 →21 selects 21, never 41 or 61.

Verification: 80 focused cases and 508 numerical regressions pass; the full
same-clock Linux/PostgreSQL gate is 572 passed, 3 failed. Failures concern replayed
capture revisions in `test_snapshot_history.py`, detailed in the numerical
document, and all three reproduce on unchanged main `e179c75`. Chun Yang owns
the replay contract/test resolution. Aniq's explicit 18 September instruction
waives these three failures as a blocker for this merge; the earlier timestamp
discussion is not the basis for proceeding. Application code and tests are
unchanged from the verified implementation; this waiver update is documentation-only.
Synthetic fixture correctness
does not prove real restaurant demand accuracy or the completed Agent sales route.

## Historical promotion handoff

Use [feat/ml-promotion-forecast](https://github.com/rudybrrr/restock-ai/tree/feat/ml-promotion-forecast)
for this focused change based on main `40876fc20270bc3426e15c65a36c60578c66ac80`.
The [numerical interface and traceability](ML_NUMERICAL_FUNCTIONS.md#promotion-forecast-application-and-comparison--18-september-2026)
define `src.promotion_forecasting.apply_promotions` and
`compare_forecast_versions`, their internal immutable artifacts, frozen evidence
requirements, worked examples and tests. This section supersedes historical next
actions below; it does not reactivate deferred policy questions already confirmed.

- **Rudy:** use an identifiable unadjusted baseline, explicit canonical promotion
  events and frozen evidence. Consume only future projected buckets downstream;
  elapsed actual sales are returned separately. `complete=False` means no forecast,
  never zero risk or an actionable candidate. Comparison is a diff, not reforecasting;
  `NO_PREVIOUS_VERSION` does not invalidate the first forecast. Preserve evidence
  and findings through your adapters; this numerical change does not implement them.
- **Chun Yang:** supply/persist complete promotion revision history with recording
  times and manager/scenario assumption source, future-effective known changes,
  immutable original forecast and catalogue/recipe/model/profile/policy references,
  and resolved actual-batch coverage. Current selected promotion rows and the
  baseline-only first-slice input do not provide all this evidence. Activity-capable
  snapshots, receipt/commitment handling and reassessment routing were pending
  at this historical handoff; PR #28 now provides them as described above.
- Record remaining mapping/contract responses in [issue #16](https://github.com/rudybrrr/restock-ai/issues/16).
  Accepted FEFO/expiry/search/tie policies are preserved, with no renewed approval request.

Worked synthetic example: explicit 1.2 multiplier on chicken-rice changes 100 to
120 portions, leaving other dishes unchanged. Current recipes require chicken
27.600 kg, rice 22.000 kg, noodles 18.000 kg, eggs 60 pieces, tofu 6.000 kg,
vegetables 11.800 kg, oil 1.000 litres and soy-sauce 2.000 litres. A 1-for-1 name
does not cause a second multiplier. Overlapping promotions on the same dish/bucket
return incomplete rather than a guessed stacking rule. A 14:00 intraday example
preserves 42 actual lunch portions and projects only 72 dinner portions.

Verification for this contribution: 428 numerical tests passed, including 61
promotion/comparison cases; Ruff, Pyright and two-file formatting passed.
The full isolated Linux/PostgreSQL gate passed **494 tests** (611.49 s).
An initial Windows/Docker run had five existing timing-sensitive failures;
unchanged-main reproduction and measured host/database clock skew are recorded
in the numerical document. The same unchanged tests all passed with Python and
PostgreSQL sharing the Linux clock. No claim of real forecast accuracy or
connected Agent publication.
The older `feat/ml-materiality` draft remains isolated; this task reuses compatible
logic in the current sales component without publishing its unrelated draft content.

## Historical Pass 3E handoff

Read [Pass 3E numerical compatibility](ML_NUMERICAL_FUNCTIONS.md#pass-3e-numerical-compatibility--17-september-2026)
first. It supersedes historical policy proposals and waiting instructions below.
This contribution uses [feat/ml-pass3e-compatibility](https://github.com/rudybrrr/restock-ai/tree/feat/ml-pass3e-compatibility),
based on main `86abb37cb12eaee8296c2418e88f2f7b9bdef0ba`. Older branch links and
commit records below identify historical publications, not this contribution.

Implemented corrected/versioned expiry, receipt-aware projection FEFO, guarded
complete minimum-pack search and semantic supplier/ingredient ties. Exact tags:
`EXPIRY_ARRIVAL_PLUS_SHELF_LIFE_MINUS_ONE_V1`,
`FEFO_EXPIRY_RECEIVED_LOT_ID_V1`, `COMPLETE_PRUNED_DOMAIN_V1`, and
`SUPPLIER_ID_THEN_INGREDIENT_ID_V1`. Complete definitions, identity mapping, search
proof and guards are in the numerical document. Five-day shelf life arriving
16 February expires 20 February; the legacy plus-days tag is rejected.

The complete backend supplier fixture retains all 24 offers/opportunities at
capacity 200 and explicit nine-lot v3 stock. Forecast/recipe kernels derive
Fresh chicken 8 kg and noodles 3 kg: **SGD 55.50 +5 delivery =60.50**. Search
evaluates 450 proved-sufficient allocations, using 748 generation/evaluation work
units. Expected results are assertions, not runtime inputs. Unsupported scope
and work exhaustion never produce actionable candidates.

**Verification update:** Docker is now available. The full PostgreSQL-backed suite
on implementation commit `8aefe36b51d166c86f94c9eddc8eb45a570fad98` finished with
**426 passed, 2 failed, 2 warnings** (788.92 s), including all 367 passing numerical
cases. The two `test_procurement_contract.py` failures also reproduce on unchanged
main `86abb37cb12eaee8296c2418e88f2f7b9bdef0ba` (2 failed, 28.50 s): endpoint
opportunity timestamps and frozen-contract `as_of` use UTC strings while tests
expect Singapore-offset strings. The instants are equivalent. No backend code or
tests were changed. Ruff, Pyright and four-file formatting checks passed again.
See the numerical document for commands and the isolated database setup.
On 17 September, Aniq relayed Chun Yang's response that the Singapore timestamp
issue can be fixed later and explicitly authorized proceeding. This supersedes
the earlier instruction to hold [PR #22](https://github.com/rudybrrr/restock-ai/pull/22)
for those two failures. They remain documented backend follow-up work, not passing
tests. Normal GitHub protections still apply; no GitHub review approval is implied.
This does not establish real backend/agent publication or deployed operation.

Current backend update: PR #23 made the timestamp assertions timezone-agnostic.
The subsequent FEFO replay alignment also passes the full PostgreSQL suite: 429
tests, with Ruff and Pyright clean. The historical 426-pass/2-fail result above
remains the result from Aniq's implementation commit, not the current main gate.

Chun Yang already confirmed merged policy/domain authority in
[#16](https://github.com/rudybrrr/restock-ai/issues/16#issuecomment-5700645096).
The backend registers these exact tags; no repeat FEFO approval or tag activation
is requested. Current backend replay orders equal-expiry lots by receipt time and
then lot ID, matching `FEFO_EXPIRY_RECEIVED_LOT_ID_V1`. Remaining backend work
includes live source-coverage verification.
Nonempty commitments need explicit projected lot identities. Rudy owns the thin
adapter, immutable evidence and result mapping, with independent validation before
backend freshness/publication. Record remaining mapping responses in #16.

## Historical implementation and coordination record

The dated material below is retained for provenance. The current section above
overrides stale policy/owner waiting statements. Full training data, multi-day
economics and live integration remain incomplete.

## 1. Start here

ReStock helps a restaurant maintain purchasing recommendations as demand, stock and supplier conditions change. This revision includes seasonal forecasting, timed dish demand, recipe conversion, one-day inventory projection, reproducible development history and a pure one-day cash procurement search with independent candidate validation. Live backend and agent adapters remain pending.

**15 September update for Rudy's integration request:** this branch incorporates main's audit-safeguard commit `411527d327114f29cf1dd5a46e6e76faeae2024b` into the published ML implementation at `4f1d4c3de8c80d50c6c90012cb81ce5b3a2533ac`. The sales merge retains `sales_at(session, as_of, known_at)` and recording-time filtering alongside the ML recipe helper. Historical snapshot selection, correction identity, supersession and audit logic remain backend-owned. This is a merge update, not rewritten feature-branch history.

`search_procurement()` is the real deterministic **one-day cash-stage** optimiser for the first bounded MVP connection. It is not the disabled backend development calculator or the final multi-day economic scorer. `validate_candidate()` is the numerical validator to call before backend freshness/publication checks. The [15 September integration boundary](ML_NUMERICAL_FUNCTIONS.md#15-september-integration-boundary) specifies supported policies, result handling and the remaining transport decisions. The shared contract is still a proposal; Aniq's numerical confirmation does not assert Chun Yang's or Rudy's agreement.

Use the [feature branch](https://github.com/rudybrrr/restock-ai/tree/feat/forecasting) for the complete source, tests and this handover. The historical commit below covers the earlier foundation only. For a consistent review, use the same resolved feature-branch commit for source, tests and documentation.

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

**Historical publication record:** [e3c66b64f3bc53c7fc036c5d063222c02082d7ff](https://github.com/rudybrrr/restock-ai/commit/e3c66b64f3bc53c7fc036c5d063222c02082d7ff) published the earlier 15-file numerical foundation. Documentation updates followed through `d298c658cae302c2aa19ea7ba53ecbd1c864ef00`. Neither commit contains the subsequent synthetic-history or procurement implementation. Use the feature-branch links above for this revision's modules and documentation. Source publication does not establish live integration or approval of #16 contracts.

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
| [synthetic_history.py](https://github.com/rudybrrr/restock-ai/blob/feat/forecasting/services/api/src/synthetic_history.py) | Configurable deterministic fully supplied development history, independent random streams, CSV/JSON manifests and offline validation including configuration/service-interval consistency | No physical stockout simulator or agreed full training dataset; generated data stays outside Git/database paths |
| [history_dataset.py](https://github.com/rudybrrr/restock-ai/blob/feat/forecasting/services/api/src/history_dataset.py) | Validates observations, loads issue-time-visible daily revisions/promotions, and selects chronological target partitions | Observation reader never loads evaluator truth/configuration; no model fitting or multi-horizon feature builder |
| [procurement.py](https://github.com/rudybrrr/restock-ai/blob/feat/forecasting/services/api/src/procurement.py) | `search_procurement` and independently callable `validate_candidate`: finite one-day cash search, timed feasibility, shared capacity and explicit constraints | Fixture policies, opening-time order placement, no live adapter, multi-day or full economic objective |

The `planning.py` and `sales.py` edits reuse `sum_recipe_usage`. The 15 September merge preserves main's newer historical replay and audit semantics while retaining that arithmetic reuse. No shared FEFO helper was extracted; existing backend tie ordering remains unchanged.

Tests are in `services/api/tests/test_forecasting.py`, `test_requirements.py`, `test_service_buckets.py`, `test_inventory_projection.py`, and the catalogue comparison in `test_seed_contract.py`. Fixtures are `seasonal_baseline_v3.json`, `service_profile_v2.json` and `inventory_projection_v1.json` under `services/api/tests/fixtures/`.

Additional tests are `test_synthetic_history.py` and `test_procurement.py`, with intentional small configurations `history_development_v1.json` and `procurement_v1.json`. Generated observations and evaluator outputs are reproducible artifacts excluded from Git.

`test_procurement.py` now also declares explicit two- and three-supplier domains over the same five dishes, eight ingredients and fourteen service buckets. These capacity/pack overrides are synthetic test inputs, not pruning or replacement of current seed offers. Their complete domains contain 36 and 216 combinations respectively; expected cash is S$68 and S$81.50. Both force split sourcing, retain independent candidate validation, and test incomplete search despite a feasible incumbent.

Read `docs/ML_NUMERICAL_FUNCTIONS.md` for detailed Python semantics and the mapping of all twelve #15 acceptance criteria.

**Not completed by this handover:** full synthetic training dataset, trained/evaluated forecasting model, multi-day stock continuation/procurement, complete economic cost/policy evaluation, live input adapter, persisted projection evidence, agent business-tool integration or final application acceptance. Do not use the numerical test results as evidence that those features exist.

### Development historical dataset

The tracked configuration defines **84 fully supplied synthetic days, 1 September–23 November 2025**, in Singapore time. All five dishes share these target-date partitions:

| Partition | Inclusive dates | Days |
|---|---|---:|
| Warm-up | 1–28 September 2025 | 28 |
| Train | 29 September–26 October 2025 | 28 |
| Validation | 27 October–9 November 2025 | 14 |
| Test | 10–23 November 2025 | 14 |

The declared development simulation start is 25 November 2025 at 08:00 +08:00; no simulation is executed. Generation produces 840 daily-revision rows, 5,880 batch rows and two published promotion rows. Evaluator-only outputs contain 420 attempted-demand and 672 ingredient-usage rows. Those generated outputs are not committed. The configuration, generator, tests and reproduction commands are included.

This **development dataset is not the final approved training/evaluation dataset**. The full historical calendar, simulation start, catalogue pins and generation assumptions still require explicit confirmation. Current catalogue/recipes are used counterfactually throughout development history. Separate demand/timing/error seeds, weekday effects, mild trend, BOGO atomic pairs and full supply are declared assumptions, not empirical restaurant estimates.

Daily reports become available at 22:00; next-day corrections replace complete submissions. Missing observations remain missing and explicit zero remains zero. The reader filters effective and available times, exposes promotions only after publication, and never adds batches to final totals. It reads only the observation directory, not hidden parameters or attempted-demand truth. Offline validation additionally checks evaluator accounting and uses the existing dated allocator to compare normalized configuration service intervals with the observation manifest. Lunch-only/shifted mismatches are rejected even after hashes are refreshed; reordered equivalent periods pass. Sampled transaction shares need not exactly match profile weights.

### Procurement interfaces and examples

`search_procurement(ProcurementInputs)` enumerates all pack counts up to supplied new-capacity bounds for each declared opportunity. `validate_candidate(inputs, PurchaseCandidate)` checks supplied lines and claimed cash without invoking search. They reuse existing catalogue/offer models, recipe conversion and the inventory projector.

Inputs explicitly supply issue/opening and one-day coverage, projected dish buckets plus cross-checked dated ingredient requirements, complete opening/commitment manifests, knowledge/revision evidence, approved offers, ordering opportunities, budget/storage/safety, fee/expiry/tie policies and search work limits. Outputs distinguish candidate feasibility, completed enumeration and optimality within the supplied finite domain. Missing evidence and unsupported timing/precision are incomplete; a search-limit incumbent is diagnostic only.

The small reference domain supplies only Fresh chicken/noodles with capacities 8/3 and one arrival. All **36 combinations** are checked. Chicken need 24.6 minus opening 17 leaves 7.6 kg, rounded to 8 purchase packs; noodles need 18 minus 15 leaves 3 kg. Acquisition `8×4.50+3×6.50=55.50`, plus one supplier/arrival fee of S$5 gives **S$60.50**, with no unmet demand. This is not an optimum over omitted suppliers. Both lines emergency add one exclusive S$12 fee, giving S$72.50.

A separate vegetable fixture needs 2.5 kg with 2 kg opening, capacity 2, pack size 1, price S$9.50 and fee S$5. Work limit 2 checks quantities 0 and 1 and finds a feasible S$14.50 incumbent, but returns **INCOMPLETE / SEARCH_LIMIT_REACHED (2/3)** with no actionable candidate. Budget-zero complete enumeration instead reports domain infeasibility with budget/shortage evidence, not a generic supplier failure.

Fee grouping applies to new lines by supplier/arrival; it does not infer co-shipping discounts with fixed commitments. Fixture expiry is usable-through arrival date plus supplied shelf-life days; tie order is cash, fewer lines, stable IDs. New purchases use the existing Delivery model's 12-digit/3-decimal bounds without rounding finer projected demand. Only orders placed at opening/issue time are supported. These fixture policies are not shared production agreements; reliability remains context-only. Full semantics and executable checks are in the [numerical documentation](https://github.com/rudybrrr/restock-ai/blob/feat/forecasting/docs/ML_NUMERICAL_FUNCTIONS.md).

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

Use the [backend handover](BACKEND_HANDOVER.md), [shared integration proposal](SHARED_INTEGRATION_CONTRACT.md) and current code as the integration starting point. Main's PR #17 is included in this branch. These are the remaining mapping questions, not a request to implement Aniq's engine or repeat the merged backend fixes.

| Area | Existing seam | Confirmation or required change |
| --- | --- | --- |
| Opening state | `sales.estimated_inventory(session, as_of, known_at)`; frozen `planning._snapshot["inventory"]` | Use the frozen result, with complete expected lot/ingredient coverage, explicit zero-stock evidence and unchanged coverage/deficit findings |
| Time and revisions | Snapshot `as_of`, `known_at`, `offer_version_ids`, integer run `input_revision` | Preserve operational and recording cutoffs; bind the integer-to-string numerical revision to this exact saved bundle and its resolvable source versions |
| Catalogue and recipes | Current catalogue models and snapshot ingredients/recipes | Capture the menu too; provide one resolved complete recipe/catalogue artifact and authoritative manifest/version, without another live read during calculation |
| Commitments | `fact_history.commitments_at`, frozen snapshot commitments, `Delivery` and `Receipt` | Export the 10/6/4 and cancellation cases from the same capture; do not replace them with a current-state `read_delivery` call |
| Expected expiry | Actual receipt expiry and supplier offer shelf-life fields exist | Establish commitment-specific expected expiry and its captured source/assumption; unknown stays unknown |
| Projection dates/profile | Local explicit target/horizon/profile inputs | Agree their request/capture mapping. Do not infer a purchasing horizon from the one-day example |
| Precision | Observed quantities use `Numeric(12,3)`; projected outputs can be finer | Agree lossless Decimal-string transport and range handling separately from observed storage |
| FEFO | Backend uses expiry then lot ID; v2 specifies expiry, receipt time, ID | Confirm non-tied first-example compatibility. Agree tied ordering and identity mapping before claiming shared parity or changing historical replay |

**The old unqualified CY-001 finding is superseded by PR #17's backend changes.** Main now contains historical offer/promotion/delivery selection, recording-time filters, explicit missing-history handling and replay regressions. This update retains those changes. It does not independently certify the entire live export or claim the combined PostgreSQL suite passed. Required coverage/provenance mapping and pre-migration missing-history limitations remain. Never substitute current mutable rows when an earlier snapshot lacks evidence.

Required live evidence includes a captured bundle that remains stable after later backdated counts, sales corrections, receipts or cancellations, and a new capture that selects the correct eligible versions. Include explicit-zero, missing-lot, missing-interval, positive-deficit and receipt-retry cases. A byte-stable bundle alone is insufficient unless its original membership was correct.

**Please reply in #16** with the accepted mapping or precise alternatives, a representative export/example, remaining backend changes and their verification status. Input adapter work can begin against an agreed representative bundle while backend implementation proceeds. Live correctness testing requires those backend changes to be available.

## 8. Rudy: requested agent confirmations

The projector provides inventory evidence. It does not return a purchase Candidate, select suppliers or approve anything. Connect it through thin tools/adapters and preserve the same result for expiry and shortage investigations.

For purchasing, call `src.procurement.search_procurement` and then `src.procurement.validate_candidate` on the same resolved `ProcurementInputs`. The returned `PurchaseCandidate` is an internal numerical value, distinct from the backend's persisted `Candidate` schema. Use the documented opportunity-to-offer mapping; do not reconstruct quantities or infer absent policy values. Search completion is required even when a diagnostic incumbent independently validates. The numerical documentation's integration boundary gives the exact existing fields and proposed artifact metadata for backend-owned transport.

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

**15 September combined-tree verification:** `uv sync --locked` succeeded with the
unchanged lockfile. All **333 numerical tests passed** (193 foundation, 68 dataset,
72 procurement), including the four new two-/three-supplier cases, in 13.16 seconds.
Ruff passed API-wide; Pyright reported zero errors/warnings; formatting passed for
`planning.py`, `sales.py` and `test_procurement.py`; Git diff checks passed. Full
suite collection succeeded with **390 tests**, which is collection only, not 390
executed tests. The two existing dependency deprecation warnings remain.

The combined PostgreSQL suite was **not executed**: this environment has no
PostgreSQL service/binaries, and package-manager setup failed on environment
permissions. No shared database was used. Preserve the new main audit/replay tests
and run `uv run --locked pytest -q` with the README's disposable test database
before merging to main. Bedrock, frontend, real engine publication and deployment
were not tested. Numerical checks alone do not establish merge readiness.

The merge resolution was reviewed against main: the only retained differences in
`planning.py` and `sales.py` are the existing recipe-helper reuse and typed recipe
conversion. All seven existing numerical source modules are unchanged from
`4f1d4c3`; no backend migrations, publication logic, historical fact selectors,
agent modules or frontend files were newly edited in this update.

Historical publication verification on 14 September 2026: **329 numerical tests passed**
(193 foundation + 68 dataset + 68 procurement), two existing dependency warnings,
10.97 seconds. API-wide Ruff and Pyright passed (zero type errors/warnings); all
five new Python source/test files passed formatting. The portable development
generation and offline-validation commands in the numerical documentation passed,
producing the 84-day row counts above in a temporary directory outside the checkout.
No database, Bedrock, frontend or end-to-end suite was run. Historical results follow.

| Evidence | Result and limitation |
| --- | --- |
| Historical projector suite | 193 passed, including 84 projector cases; predates dataset/procurement work |
| Independent review execution | The same 193 numerical tests passed in an isolated review environment; this did not run PostgreSQL integration fixtures |
| Historical full backend suite | Reported 241 passed with two existing dependency warnings; not independently rerun in this review |
| Historical projector static checks | Reported Ruff, Pyright, formatting and diff checks passed |
| Reviewed source continuity | Earlier numerical source/tests were unchanged during the projector task; publication should preserve those reviewed changes or explicitly identify later differences |
| Contract-proposal scratch checks | Local Codex reported three supply variants and two incomplete cases passed; no full application suite rerun for that task |

These checks establish supplied-input numerical behaviour, not real forecast quality, trustworthy live provenance, agent publication, hosted deployment or completion of the hackathon application. Earlier numerical count 109 and backend counts 157/107/47 describe older checkpoints.

After checking out the verified feature-branch revision in a compatible review environment, use the repository's documented dependency setup. From `services/api`:

```powershell
uv run pytest -q tests/test_forecasting.py tests/test_requirements.py tests/test_service_buckets.py tests/test_inventory_projection.py tests/test_synthetic_history.py tests/test_procurement.py
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
3. Chun Yang implements the backend input adapter once its required contract is settled; Aniq supplies the numerical semantics and validation. Include the explicit offer, ordering-opportunity and procurement-policy evidence. Do not invent absent values to make the example pass.
4. Run the agreed backend-export-to-projector example and negative cases. Test actual state selection, receipt/cancellation handling, quantity preservation and incomplete output.
5. Connect persisted projection evidence and Rudy's consumer/completion mapping when their contracts and implementations are ready.

Fixture implementation under [#15](https://github.com/rudybrrr/restock-ai/issues/15) is the implementation to inspect on `feat/forecasting` after publication verification in section 2. Shared equal-expiry parity remains deferred, and helper extraction was not performed. Do not close #15 as fully integrated merely because numerical tests pass. [#16](https://github.com/rudybrrr/restock-ai/issues/16) remains the contract and live-evidence coordination point.

Broader backend issues retain their own acceptance: [#7](https://github.com/rudybrrr/restock-ai/issues/7) inventory/materiality, [#8](https://github.com/rudybrrr/restock-ai/issues/8) genuine first purchase plan, [#9](https://github.com/rudybrrr/restock-ai/issues/9) exact-version approvals, [#10](https://github.com/rudybrrr/restock-ai/issues/10) reassessment, [#11](https://github.com/rudybrrr/restock-ai/issues/11) contingency/no-double-ordering and [#12](https://github.com/rudybrrr/restock-ai/issues/12) integrated demo and handover verification. Closing a narrow numerical task does not close those workflows.

Aniq can continue independent approved forecasting-data/evaluation work while these specific contracts are resolved. The team does not need to wait for entire components to finish before coordinating interfaces.

## 11. Source precedence and maintenance

This handover is based on the reviewed projector implementation, numerical documentation, Chun Yang's backend handover, the supplied team decisions and the published #16 proposal. The approved ML planning basis is `ReStock_ML_Decision_Engine_Plan_v2_Review_Reconciled.md` plus Ethan-approved `ReStock_ML_Decision_Engine_Plan_v3_Integration_Amendment.md`, subject to subsequent explicit decisions. Numbered filename suffixes may identify downloaded copies rather than newer content.

Use current code for existing interfaces, approved plans for intended scope, and explicit later team decisions for resolved changes. Report conflicts. In particular, the old backend specification's claim that only health checking exists is stale, and older escalation lists must not silently override later contract discussions.

On the 15 September check, #16 still contained the original proposal comment and no Chun Yang/Rudy confirmation replies. Main now also contains `docs/SHARED_INTEGRATION_CONTRACT.md`, explicitly proposed rather than frozen. The supplied 15 September WhatsApp request authorizes preparing this branch for integration and records Ethan's approval to proceed in principle. It does not settle fee grouping, canonical artifact transport or final economic policies. Record subsequent agreements explicitly; do not infer them from silence.

Keep one shared document. For each subsequent revision, record date, affected interface, accepted decision and evidence link. The repository copy is `docs/ML_HANDOVER.md` on `feat/forecasting`; share its GitHub link and the verified implementation commit with teammates. Editing this document does not itself publish code, change issues, grant repository access or implement any adapter.

### Revision history

| Version | Date | Change |
| --- | --- | --- |
| 1.15 | 20 September 2026 | Recorded Aniq's explicit PR #34 merge exception for the unchanged-main decimal-string failure; preserved failed-test evidence and Backend follow-up. No application/test changes. |
| 1.14 | 20 September 2026 | Continuous seven-day physical execution, explicit counts/disposal, independent oracles and reproducible report. Current verification/merge status is recorded above; PR #33 results are historical. |
| 1.13 | 20 September 2026 | Recorded Aniq's explicit acceptance of the one unchanged-main decimal-string test failure for normal PR #33 merge; failed-test evidence and Backend follow-up retained. |
| 1.12 | 20 September 2026 | Added one-day physical execution, independent fixture/oracles and observation-only access; corrected receipt retry identity; recorded 628 numerical passes and full gate 701/1 with unchanged-main reproduction. Merge and live integration remain separate. |
| 1.10 | 18 September 2026 | Recorded Aniq's explicit waiver of the three snapshot-replay failures reproduced on unchanged main, authorizing normal PR #29 merge. Preserved failed-test evidence, Backend follow-up and integration limits; no application or test changes. |
| 1.11 | 18 September 2026 | Aniq approved SALES_MATERIALITY_V1 after reviewing exposure delays. Added immutable definition/resolver, assessment enforcement, contract tests and explicit Backend/Agent evidence dependencies. |
| 1.8 | 18 September 2026 | Added pure promotion application, immutable comparison, exact portion/recipe and intraday examples, frozen evidence requirements and owner handoff. Preserved unfinished materiality and accepted Pass 3E policies. |
| 1.9 | 18 September 2026 | Added authoritative sales materiality, explicit policy/exposure, immutable forecast/history and future-only remainder semantics, canonical PR #28 contract tests and Backend/Agent consumer mapping. Preserved owner integration boundaries. |
| 1.7 | 17 September 2026 | Recorded Aniq's explicit proceed instruction following Chun Yang's relayed acceptance of deferred timestamp correction; preserved actual failing-test evidence and normal PR protections. |
| 1.6 | 17 September 2026 | Ran full isolated PostgreSQL suite: 426 passed, 2 existing backend timestamp failures reproduced on main; refreshed static checks. Replaces the Docker-unavailable blocker; PR #22 remains open. |
| 1.5 | 17 September 2026 | Pass 3E FEFO/expiry compatibility, guarded complete reduction, semantic ties, canonical backend-domain fixture tests and outstanding combined-test/live integration gates. |
| 1.0 | 14 September 2026 | Initial shared ML implementation and integration handover |
| 1.1 | 14 September 2026 | Changed teammate/AI review access to GitHub `feat/forecasting`; added branch, source, test and handover links, commit verification and direct AI-review instructions. Numerical scope, test evidence and unresolved contracts are unchanged. |
| 1.2 | 14 September 2026 | Added the repository handover and verified implementation commit permalink; corrected the pending-publication record. Numerical scope and unresolved contracts are unchanged. |
| 1.3 | 14 September 2026 | Added development history/partitions, observation-only loading, service-profile validation and one-day cash procurement with independent validation; expanded verification commands and separated historical publication records from current feature-branch scope. Shared #16 decisions remain unresolved. |
| 1.4 | 15 September 2026 | Incorporated main's historical replay/audit safeguards, retained the recipe helper, added two-/three-supplier numerical acceptance, confirmed callable optimiser/validator scope and documented policy/artifact mapping for teammate integration. Shared agreement and combined PostgreSQL verification remain separate. |
