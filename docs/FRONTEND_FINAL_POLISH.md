# Final frontend polish handoff

26 September 2026 · local branch `feat/frontend-final-design` · integration base `50a78e07d5e03e21ad4bd572848a405a0abbe7a0`.

Delivery branch: `feat/frontend-final-design`, without merging to main. No backend contract changes, operational database writes or agent credentials introduced by these frontend changes.

## Completion audit

**Visual separation refresh:** The long inline onboarding block is now a compact prompt that opens a focused, keyboard-accessible side guide. Summary numbers use a compact row rather than three large empty cells. Side-by-side work sections have square-edged white surfaces, quiet tinted headers and inset content so recommendations and assessment history no longer blend into one canvas. Other standalone sections retain the flat treatment. Guide dismissal/reopening, Escape/focus restoration and desktop/mobile layout are covered by browser checks.

**Actual content subtabs:** Today now separates Summary, Daily operations and Stock overview instead of rendering them consecutively. The next-action banner stays visible in every Today view. Sales now separates Reported sales, Ingredient usage, Stock estimates and Sales assessment. Only the selected content is rendered; the sales window and refresh selection persist when switching views. Existing Stock/Purchasing/Activity/Settings task tabs and page links remain available. Browser tests verify content separation, state retention and the relocated evidence/estimate views.

**Per-area task guides:** Each area now has a collapsible three-part guide explaining what belongs where. Every local tab has optional Typical task / Keep in mind instructions. These distinguish counts from estimates, closing sales from interval reports, approval from purchase recording, and expected supply from arrived receipts. Guides are collapsed by default to keep the workspace uncluttered, use native keyboard-accessible disclosures, and stack on small screens. Browser coverage opens each area/tab guide and verifies its contents and responsive layout.

**New-user navigation refresh:** The sidebar now has five task areas: Today; Stock & sales; Purchasing; Activity; Restaurant settings. Each area has a short purpose statement, with related pages in an area navigation row and descriptions beneath local tabs. Menu/recipe references and ordering schedules sit under Restaurant settings; live stock, sales and closing tasks sit together. Existing routes and operations remain available. A dismissible/reopenable quick-start guide explains service, purchasing and closing tasks. Purchasing shows Review → Approve → Record purchase → Receive, preserving the distinction between approval and an actual order. Plan-linked purchase links retain the exact version; receipt links open outstanding purchases. Query-string destinations survive login/session expiry. Backend/Agent/ML contracts are unchanged.

**Workspace styling refresh:** Repeated cards are now open sections with divider lines; table headers and important action/warning surfaces retain emphasis. Repeated workflow strips and explanatory paragraphs were shortened or removed. Capture times, quantity methodology and plan/approval metadata remain available behind disclosures. Coverage/conflict/escalation warnings, live forms and exact-version controls remain visible. Landing-page styling is unchanged. Responsive tests now explicitly check that workspace panels are transparent, square-edged sections rather than boxed cards.

Scope: the six requested priorities plus polishing available manager workflows from `FRONTEND_USER_FEATURE_INVENTORY.md`. Existing functionality was preserved rather than replaced with demo-only screens.

| Requirement | Implemented | Evidence |
| --- | --- | --- |
| Overview/action centre | Exact run/version next-action links; assessment, escalation, pending and approved states; closing/delivery/ordering summaries; active/upcoming promotions; counted-versus-estimated stock at explicit cutoff | `final-polish-browser.cjs`: priority branches, promotions, stock/cutoff, missing/error states; rendered desktop/mobile screenshots |
| Recommendations | Normal/additional-only scope, quantities/suppliers/arrivals/type/expiry, cash-only breakdown; captured commitments with units, ordered/received/cancelled/outstanding quantities and clocks | `final-states-browser.cjs`: normal pending and +2kg/S$11; `final-polish-browser.cjs`: captured purchases; `plan-cost.test.cjs`: exact decimals/no economic fallback |
| Assessment progress/evidence | Persisted lifecycle, outcome, explanation, independent validation, bounded contingency findings, search completeness separate from candidate feasibility; expandable technical details | `assessment-flow-browser.cjs`: four lifecycle states/retry/recovery; `evidence-browser.cjs`: provenance/materiality; `final-polish-browser.cjs`: validation/incomplete search/private trace exclusion |
| Sales escalation | Reports/corrections, exact usage, coverage and estimates; latest sales assessment/materiality; direct entry handoff; unsupported result never means safe stock | `evidence-browser.cjs`, `browser-smoke.cjs`, `final-states-browser.cjs`, `final-polish-browser.cjs`, `intraday.test.cjs` |
| Approval → purchasing | Exact-version confirmation/rejection, stale409 disables approval, invalidated/superseded protection; approved allocation prefill with quantity/type/time/expiry; actual purchase and receipt remain separate | `final-states-browser.cjs`: payloads/stale/prefill/no automatic purchase; `browser-smoke.cjs`: manual purchase/partial receipts; `assessment-flow-browser.cjs`: rejection/stale statuses |
| Responsive/style/feedback | Consistent forest/ivory/charcoal styles, spacing, table scrolling hints, mobile Escape/focus, loading/empty/error/filter states, compact deferred disclosures | Nine workspace screens at1440/820/390px, broader form/responsive tests, landing/reduced-motion checks and visual inspection |

## Available feature inventory coverage

- A: configured manager login/logout, sessions, return path, expired-session and outage messages. No signup or agent credential.
- B: Overview/action centre and navigation, counts/estimates/expiry, closing/orders/deliveries, promotions and recent changes.
- C–D: ingredient/menu/recipe/holiday reads, schedules, lot observations/totals, receipt provenance, selected-time FEFO/expiry estimates and coverage warnings.
- E: closing draft/submit/correct/revisions/reconciliation, explicit zeroes/cutoffs; interval sales/retries/corrections/overlap safety and persisted materiality/stock-adjustment evidence.
- F: supplier terms/comparison/updates, promotion revisions and ordering decisions, with loading/empty/error treatment.
- G: frozen policy/domain/offer/opportunity and forecast-input history, commitment projection evidence, stored validation/search diagnostics, scope-specific cash breakdown. No invented policy effects.
- H–I: manual request/status/polling/retry, explanations, exact versions/history/comparison, approval/rejection/stale handling.
- J: actual purchases, approved allocations, updates/delays/shortfalls/cancellation, partial receipts, expiry and receipt lots; commitments separate from additions.
- K–L: manager activity, technical audit, exact references, clocks/revisions, whitelisted evidence and distinct unknown/loading/empty/error/conflict states.

## Existing backend-dependent placeholders retained

**Demo presentation update:** Unfinished Forecast and Projections tabs, the Overview future-projection panel and optional waste-entry disclosure are now hidden from the manager UI. No mock features/data were added. Working Policy input history and frozen commitment evidence remain accessible, along with all completed operations. Backend/engine implementations remain unchanged; this is presentation scope, not a claim that unavailable outputs are complete.

General forecast-result/service-interval/stock-projection charts do not have a general persisted manager result feed. Policy reads expose forecast inputs; existing frozen commitment projection evidence is displayed. Agent-only staged endpoints are not called using manager credentials.

Optional waste has no supported manager write contract. General live replanning/contingency and the final21-day economic scorer are not established by bounded cases. No browser optimiser or fallback policy was introduced. External POS, checkout, payments, notifications, signup and additional account roles remain outside the MVP.

## Verification

From `apps/web`:

```powershell
pnpm --config.verify-deps-before-run=false run lint
pnpm --config.verify-deps-before-run=false run build
```

Both pass. With the production preview running at3025, set `PLAYWRIGHT_MODULE` to installed `playwright-core` and `UI_TEST_URL=http://localhost:3025`, then run:

```powershell
node tests/final-polish-browser.cjs
node tests/final-states-browser.cjs
node tests/browser-smoke.cjs
node tests/evidence-browser.cjs
node tests/assessment-flow-browser.cjs
node tests/landing-browser.cjs
node tests/motion-smoke.cjs
node --test tests/intraday.test.cjs tests/plan-cost.test.cjs
```

All seven browser suites and seven unit tests pass. The navigation refresh additionally checks all five area selections, descriptions on each local tab, stock/settings sub-navigation, quick-start persistence/reopening and pending/approved purchasing stages with receipt navigation. Screenshots in ignored `apps/web/test-results` were visually reviewed for overview, daily, inventory, sales, recommendations, deliveries, suppliers and assessment layouts, including the quick-start guide on desktop/mobile. Activity also has responsive checks. `git diff --check` passes.

Browser tests intercept isolated manager API fixtures and verify rendering/interactions/payloads; they are not a fresh live Backend/Agent/ML acceptance run. Backend/PostgreSQL were subsequently started, and real local login, session, inventory/plan reads, logout and frontend-origin CORS were verified. No fresh full PostgreSQL suite is claimed.

Frontend preview: http://localhost:3025. Handoff target: `feat/frontend-final-design`; merging to main requires separate review. `pnpm-workspace.yaml` has only a line-ending status difference, no content diff, and is excluded from this frontend commit; lockfile and Backend/Agent/ML source unchanged.
