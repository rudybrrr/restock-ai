# Post-purchase contingency contract — 25 September 2026

Related to [#11](https://github.com/rudybrrr/restock-ai/issues/11) and
[#10](https://github.com/rudybrrr/restock-ai/issues/10). Both retain Agent/live
acceptance work. This is Aniq's bounded Backend integration requested by
Chun Yang on 24 September and adopted by Aniq on 25 September. Approved ML v2
is the foundation, v3 supplies overrides; no full economic objective is added.

## Exact scope and authority

`POST_PURCHASE_FIXED_SUPPLY_V1` selects two explicit synthetic checkpoints of
`BOUNDED_CONTINGENCY_20260216_CASE_V1`, persisted in the existing
`contingency_case_inputs` and `contingency_policy_versions` tables. Seed inserts
missing versions without overwriting previous versions or operational facts.
No migration is needed. Existing v4 first-purchase selection remains intact.

| Version | Operational as_of, Singapore | NEW purchase domain |
| --- | --- | --- |
| 5 | 2026-02-16 10:00 | Existing rescue quote: market vegetables, 1 kg packs/MOQ, maximum 6 kg NEW capacity, arrival 11:00, expiry 17 February |
| 6 | 2026-02-16 11:00 | Explicitly empty: the quote has a 60-minute lead, so its placement window has elapsed |

Case IDs are `case-input:BOUNDED_CONTINGENCY_20260216_CASE_V1:5` / `:6`;
policy IDs are `policy:BOUNDED_CONTINGENCY_CASH_V1_DEMO:5` / `:6`.
Source revisions are `POST_PURCHASE_FIXED_SUPPLY_V1:5` / `:6`, domains are
`POST_PURCHASE_20260216_DOMAIN_V5` / `V6`. The synthetic quote reference is
`ANIQ_POST_PURCHASE_BOUNDED_DEMO_2026_09_25`, an implementation provenance label,
not evidence of a real supplier quote or another teammate's approval.

Both versions inherit `BOUNDED_CONTINGENCY_CASH_V1`,
`CONTINGENCY_CARTESIAN_V1`, `EXPLICIT_NEW_SHIPMENT_ONCE_V1`, existing FEFO/expiry/
tie policies, SGD30 new-order budget, explicit safety/storage and assessment
windows. Quote: SGD2/kg + SGD3 delivery + SGD4 exclusive emergency charge per
NEW shipment. Existing commitments do not spend this new budget or get deducted
again from NEW capacity. These are bounded demo assumptions, not production defaults.
The declared finite domain and work limit retain the numerical contract's meaning.

Selection requires the original delayed delivery and exactly one linked emergency
purchase from the approved v4 recommendation. The original is 10 kg total, 6 kg
received in opening stock, 4 kg outstanding for 17 February 09:00. The emergency
is at most 4 kg, ordered at the first checkpoint. Its partial/cancelled/received
revisions are frozen from Backend history, not inferred from approval. Selection
checks lineage, exact catalogue, complete opening coverage, receipt lots, expiry
provenance and complete fixed-supply manifest. Both IDs remain in evidence even
when a delivery has zero outstanding quantity. A newer actionable plan, extra
commitments, other clocks or promotions are outside this small rule and explicitly
incomplete; they cannot silently enter the normal calculator.

The 11:00 checkpoint requires complete observed sales coverage since opening
(the test records an explicit zero-sales 10:00–11:00 batch). Receipt stock is
included once, and only the outstanding remainder enters future supply.
Residual projected demand is 70 then 30 tofu bowls in the 11:00 and 11:30
half-hours. Other dishes explicitly have zero demand. Canonical recipes require
10 kg rice, 15 kg tofu and 10 kg vegetables. Opening rice/tofu are 20 kg each;
all other ingredient rows explicitly contain zero. The second-day forecast is
explicit zero, with the original late commitment still assessed for storage/expiry.
This rule does not extrapolate demand after those frozen windows.

## Rudy's exact entry points

All new functions/types are in `src.post_purchase_contingency`:

```python
select_post_purchase_input(run: PlanningRun) -> PostPurchaseInput | None
persist_post_purchase_result(session: Session, run_id: str) -> PostPurchaseResult
read_post_purchase_result(session: Session, run_id: str) -> PostPurchaseResult
```

`planning.claim_run` captures the input in
`run.snapshot["post_purchase_contingency_input"]`; the calculator stores the result
in `run.snapshot["post_purchase_contingency_result"]`. Both are PostgreSQL-backed,
run-bound artifacts, not Agent-supplied facts. `None` means this selector does not
apply; an input with `complete=False` means it applies but cannot be certified.

Agent-token HTTP boundary (prefix `/api/v1`):

- `GET /runs/{run_id}/post-purchase-contingency-input` → nullable `PostPurchaseInput`.
- `PUT /runs/{run_id}/post-purchase-contingency-result`, no request body → calculate
  with `search_contingency`, call `validate_contingency` independently, and persist.
- `GET /runs/{run_id}/post-purchase-contingency-result` → read verified stored result;
  409 when none exists. Manager credentials cannot invoke the PUT.

| Type | Required consumer fields |
| --- | --- |
| `PostPurchaseInput` | `contract_version`, `run_id`, `as_of`, `known_at`, `captured_state_revision`, `complete`, `findings`, `fixed_delivery_ids`, `source_plan_version_id`, nullable `case: StagedContingencyCase` |
| `PostPurchaseResult` | Same contract/clocks/revision, `id`, `input_sha256`, `complete`, `outcome`, nullable `escalation_reason`, `findings`, `fixed_delivery_ids`, nullable canonical `candidate`, `candidate_reference`, `numerical_result`, `independent_validation` |

Clocks retain different meanings: `as_of` is operational simulation time;
`known_at` is the real capture time. Only available policy/case/history revisions
may enter the frozen input. Content hashes bind result to the exact input, clocks
and revision. Repeated PUT is idempotent while the run remains RUNNING and fresh.
A later state revision rejects PUT/completion; historical GET still returns the
old evidence with its original revision, not a freshness promise.

| Result | Worker action to implement |
| --- | --- |
| Complete KEEP, empty canonical candidate, SGD0 new cash | Use the persisted result as no-addition evidence; complete KEEP_CURRENT_PLAN without a candidate body; never repurchase the old approved line |
| Complete REVISE_PLAN, independently feasible additions | Use `candidate_reference` and the exact `candidate`; existing candidate-reference validation and publication enforce fresh pending approval; do not record any Delivery |
| Complete ESCALATE, NO_FEASIBLE_SUPPLIER | Complete finite domain has no timely supply; preserve numerical reason/exclusions |
| Complete ESCALATE, POLICY_VIOLATION | Budget/storage/safety or another policy constraint blocks feasibility; do not mislabel supplier failure |
| Incomplete ESCALATE | Preserve MISSING_REQUIRED_DATA or CALCULATION_INCOMPLETE and findings; no actionable candidate, including after SEARCH_LIMIT_REACHED |

`complete=True` means a completed conditional calculation, not feasibility.
`numerical_result` can retain diagnostic evidence on incomplete search; it does
not authorize an incumbent. No full economic total is known: the canonical
candidate has `cost_scope=NEW_PURCHASE_CASH_ONLY`, decimal-string
`new_purchase_cash_cost`, and nullable expected economic costs. Existing fees
are sunk fixed commitments and are not charged again.

Backend `complete_run` requires the persisted matching result and exact candidate
for this case. It rejects contradictory KEEP/REVISE/ESCALATE, tampering and stale
inputs. The engine artifact references reuse existing candidate validation.
The PUT never writes orders, receipts, inventory or plans; existing completion
alone publishes a new pending version for a feasible addition.

Rudy should invoke this boundary before Coordinator completion and pass its
resolvable result/candidate references through his audit/adapter. This PR does
not change `assessment_worker`, Agent tools, live-model parsing or the UI.
Raw API acceptance below is not proof that the current worker consumes this
contract yet. Ordinary order/receipt recording does not automatically enqueue a
run; these tests explicitly request reassessment. Delay/short/cancel triggers
continue using the existing queue. No new trigger policy is introduced.

## Independent examples and connected evidence

| Fixed emergency state | Checkpoint | New result |
| --- | --- | --- |
| 4 kg on time, not yet received | 10:00 | 6 opening + 4 fixed covers 10: KEEP, no lines, SGD0 |
| Only 2 kg still expected | 10:00 | 2 kg additional: 2×2 + 3 + 4 = SGD11; pending approval |
| All 4 kg cancelled | 10:00 | 4 kg additional: 4×2 + 3 + 4 = SGD15; pending approval |
| 4 kg actually received at 11:00 | 11:00 | Opening10, emergency outstanding 0, original outstanding4 tomorrow: KEEP, SGD0 |
| Emergency4 also delayed until tomorrow | 11:00 | Opening6, demand7 then3: first shortage11:00–11:30; empty new domain → NO_FEASIBLE_SUPPLIER |
| 2 kg received, remaining 2 still expected at 11:00 | 11:00 | Opening 8; overdue expected supply is incomplete, not guaranteed stock |
| 2 kg received, remaining 2 cancelled | 11:00 | Opening 8, no timely new slot: complete NO_FEASIBLE_SUPPLIER |
| Missing sales coverage before 11:00 | 11:00 | Incomplete MISSING_REQUIRED_DATA; no candidate or inferred zero sales |

`tests/test_post_purchase_contingency.py` exercises those HTTP/PostgreSQL paths,
exact candidate tamper rejection, state freshness, known-at availability,
result integrity, permissions, partial receipts with pending/cancelled remainders,
search-limit versus budget failures, and unsupported
clock handling. Setup uses the existing first-case recommendation, exact approval
and linked external purchase. No real model call occurs. The first-case test now
compares typed inventory values so equivalent UTC `Z` and `+00:00` serialize
identically for the assertion; every inventory field still participates. Two
older missing-version tests used version4 even though it was already seeded on
main; they now request absent version999 and retain the 409/error assertions.
Both original failures were reproduced against unchanged main1463fcd.

Existing `tests/test_contingency.py` already covers on-time original delivery,
short/cancelled residuals, late arrival, receipt/commitment accounting, expiry,
no feasible supplier, finite search, safety/storage/budget, immutable inputs,
fees, reliability and independent tamper validation. Those kernels are reused.

For #10, `tests/fixtures/post_purchase_split_v1.json` explicitly changes the
NEW fresh/market vegetable capacities to 2 kg each, with separate shipments.
Four kg residual must split **fresh 2 + market 2**. Cash is acquisition8 + delivery6
+ emergency8 = **SGD22**. All 9 allocations (0/1/2 per supplier) are enumerated;
independent validation is complete and feasible. This is numerical fixture
acceptance, not persisted supplier-event/worker proof.

## Reproduce

From `services/api`, with locked dependencies and disposable PostgreSQL:

```powershell
$env:TEST_DATABASE_URL='postgresql://restock:restock_dev@127.0.0.1:55433/postgres'
uv run pytest -q tests/test_post_purchase_contingency.py tests/test_post_purchase_split.py
uv run pytest -q tests/test_contingency_first_case_backend.py tests/test_contingency.py
uv run pytest -q
uv run ruff check .
uv run pyright
```

Tests migrate and seed unique temporary databases twice and drop those databases.
Do not point test fixtures at an operational database. Gateway credentials are
unnecessary. Verification results are recorded in the updated shared ML handover.

Remaining integration: Rudy's worker routing and evidence mapping, a real typed
model/worker run, hosted operation, and Ethan's UI acceptance. Broader calendars,
other post-purchase states, full economics and production source-policy decisions
remain separate work. Live provenance confirmations remain in issue #16.
