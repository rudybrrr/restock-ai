# Submission scope and merge review

27 September 2026 · for Ethan, Rudy, Chun Yang and Aniq.

## Recommendation

Use the verified cash-slice, additional-only contingency, normal forecast/projection, evidence and exact-version approval flows for the submission. Keep waste submission disabled and full-economic outputs non-actionable until their authoritative boundaries and policies are ready. Do not silently relabel the cash objective as full expected-cost optimisation.

This is a bounded submission scope, not proof that every original proposal feature has been delivered. Prefer honest limitations over simulated decisions or last-minute unverified runtime changes. Original documents and teammate handoffs are evidence of plans/status, not independent authorization to activate policies.

## What the supplied briefing actually requires

Source: `ShowMeYourAgent_Hackathon_Briefing_release-1.pdf`, pages 13, 15, 16, 18 and 21; all pages were text-inspected and rubric/date/submission pages visually inspected.

The seven judging areas are goal/scope, architecture/reasoning, tool integration, autonomy/HITL, safety/security, observability/evaluation and platform/tooling. The supplied briefing does **not** prescribe a restaurant waste-entry form or 21-day economic optimiser. That is not a guarantee of acceptance or a waiver of promises in the team's submitted proposal.

Page 16 requests team code, project name, GitHub URL, YouTube or downloadable MP4 video (the slide says duration 30 mins), PDF write-up and deployment evidence/URL; incomplete submissions may be rejected. Page 15 states 28 September 2026 at 9:00am for shortlisting. The briefing repeatedly directs teams to Slack for updates: no newer Slack notice or actual submitted proposal was available in this review, so verify current deadline/format there rather than assume this release is final.

Page 18 identifies Lightsail and organiser Bedrock JSON access as allowed AWS usage. Page 21 allows a custom agent/framework/language. Neither source establishes that the repository is hosted or that OpenClaw is the production worker.

## Difference from our original plan

Source: `ReStock_AI_Hackathon_Plan_v5_Data_Cadence_Clarified.md`, especially sections 6, 28, 39A, 40–42 and 49A; `docs/ML_FRONTEND_HANDOFF.md` describes the implemented numerical boundary.

- Section 28's proposed objective includes purchase, delivery, expected waste, stockout and emergency costs. The connected `CASH_SLICE_V1` / `NEW_PURCHASE_CASH_ONLY` flow is narrower.
- Section 39A requires real purchase/waste/stockout computations and real benchmark metrics; section 6 expects waste-aware purchasing. Aniq has numerical helpers/scoring/search, but numerical tests do not prove connected policy activation, waste replay or manager publication.
- Expected expiry/food-waste modelling is not the same feature as a manager observed-waste entry lifecycle. The briefing does not explicitly require that form; do not conflate disabling the form with satisfying all waste-aware economics promised in the plan.
- Section 40 asks for comparable Static/Rule/Adaptive evaluation. The historical local evaluation reports outcome/routing measurements and limitations, not proven restaurant savings. Do not present the proposed 10% operational-cost reduction or 30% intervention reduction as achieved.
- CY's PR #61 documents his selection to defer waste and full-economic activation. This is teammate scope evidence, not proof the original submitted proposal was amended. The frontend keeps them disabled under the current task; any changed submission claims require team agreement.

## Evidence to show against the rubric

| Rubric | Suitable evidence / remaining caution |
| --- | --- |
| Goal and scope | Explain keeping procurement recommendations valid as conditions change; state the bounded cash-slice/domain and deferred economics explicitly. |
| Architecture and reasoning | Show the specialist/tool decision path, captured state, KEEP/REVISE/ESCALATE. Repository live-validation records distinguish live reasoning from controlled fixtures. |
| Tool integration | Show real forecast/BOM, expiry/stock, supplier constraints, deterministic candidate validation, and persisted manager reads. No frontend fallback arithmetic or hard-coded recommendation. |
| Autonomy and HITL | Show pending approval, approval on the exact version, additional-only purchases and preserved commitments. Approval never places an order. |
| Safety/security | Show least-privilege sessions, unknown/incomplete fail-closed behaviour, stale-approval rejection and an adversarial/guardrail case. A passing normal demo alone is insufficient. |
| Observability/evaluation | Show Activity/evidence and a documented golden plus adversarial case. Distinguish historical local evaluation, current acceptance tests and actual live-model evidence. |
| Platform/tooling | Explain the actual custom worker/framework and deployment shape. Do not claim production OpenClaw orchestration or hosted AWS/Bedrock readiness from local tests. |

`docs/FINAL_VALIDATION_2026-09-26.md` records local organiser-gateway normal/sales paths, controlled contingency setup, safe sales escalation and stale approval. `docs/evaluation/LOCAL_RESULTS_2026-09-19.md` is historical provider-free evaluation, not a fresh live-agent benchmark. Both have limitations worth preserving in the video/write-up.

## Frontend correction and PR #61 coordination

Aniq's review covered frontend commit `8c94d91`; his 1,333-test count is a teammate report on that exact earlier branch, not a new result on this update.

CY's PR #61 (`backend/manager-calculation-results`, inspected head `fd705ce`) was merged locally without conflicts as `8e509b3`. The response now includes run status/outcome/escalation. The frontend polls the selected queued/running assessment, fetches again on terminal transitions and offers manual refresh. It preserves the exact selected run and stops pending polling on terminal results, including unavailable/failed outcomes.

The connected regression selects a real QUEUED assessment with `NOT_RECORDED`, invokes the actual worker/engine in a disposable PostgreSQL database using controlled specialist reasoning, then requires the stored result to appear without reload or navigation. It retains desktop/mobile checks. This is not a hosted or live-model acceptance claim.

Focused backend verification on the combined branch: 22 PostgreSQL tests passed across `test_manager_calculations.py`, `test_manager_contingency.py` and `test_assessment_worker.py`, with two existing third-party deprecation warnings. This focused result does not replace Aniq's earlier full-suite check or claim a fresh 1,333-test run.

Final frontend gates passed: lint, production build, 12 adapter/preparation tests, real queued-to-SUCCEEDED connected regression with published plan reference and no reload, desktop/mobile overflow checks, and preparation-page browser checks retaining disabled waste/disconnected economics. No hosted deployment or new live-model call was performed.

PR #61 also adds sales issued-forecast and post-purchase multi-day projection reads. Those additions are merged as Backend contracts but are **not newly wired into the general Forecast & projections page** by this refresh fix. Normal/promotion first-slice output remains its connected scope; existing contingency recommendations/evidence remain available separately.

## Before submission / merge sign-off

1. CY/Rudy review the updated combined frontend branch against PR #61; merge ordering matters because both include shared integration commits. Do not merge blindly or force-push another person's work.
2. Provision/verify the actual HTTPS frontend, API, PostgreSQL and supervised worker. `docs/DEPLOYMENT_HANDOFF.md` is instructions, not deployment evidence. Test hosted login, queued completion, recommendations, approval/stale rejection and persistent state after restart.
3. Assemble the required video, PDF write-up, repository link and deployment evidence. Confirm current Slack format/deadline and submitted-proposal commitments. No submission was sent by this task.
4. Label numerical-only waste/economics as implemented kernels awaiting connection, not working manager features or full-horizon optimisation. Do not claim forecasts/projections cover all scenario types.

## Sign-off message

> Frontend queued-assessment refresh is fixed and has a real PostgreSQL/browser regression that completes without reloading. The branch includes CY's current PR #61 changes. Please review the updated `feat/frontend-final-design` and confirm merge ordering/sign-off. Waste submission and full-economic activation remain deferred. Cash-slice/contingency demo scope is narrower than the original economic objective, so the submission must disclose that gap. Hosted readiness still needs deployment smoke evidence.
