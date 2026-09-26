# Frontend feature coverage

September 26 navigation update: the manager workspace is now grouped into Today, Stock & sales, Purchasing, Activity and Restaurant settings. Existing page routes still work; menu/recipe and ordering schedule references now appear under Restaurant settings. See `FRONTEND_FINAL_POLISH.md` for the current completion audit and verified scope. Older placeholder/deferred wording below is historical: unfinished Forecast/Projections/waste screens are hidden, while working workflows and supported evidence remain visible.

**Final frontend polish:** [26 September handoff and completion audit](FRONTEND_FINAL_POLISH.md) supersedes older UI-pending statements below. It records the connected flows, verification and remaining backend-dependent placeholders.

This maps the workspace-root `FRONTEND_USER_FEATURE_INVENTORY.md` to the implementation. “Connected” means a frontend request uses the inspected backend route, not a claim that the complete ML/agent workflow has passed live acceptance.

**26 September update:** The current [validation record](FINAL_VALIDATION_2026-09-26.md) supersedes older pending statements for the live organiser gateway, deterministic sales materiality, and bounded post-purchase contingency. The manager UI now labels `CONTINGENCY_ENGINE` and `NEW_PURCHASE_CASH_ONLY` costs explicitly. This table remains the 17 September feature inventory, not the final evidence ledger.

Local 17 September additions and their completed browser/PostgreSQL verification are documented in [FRONTEND_EVIDENCE_ADDITIONS.md](FRONTEND_EVIDENCE_ADDITIONS.md).

| Inventory group | Frontend destination | Treatment |
| --- | --- | --- |
| A1–A3 Authentication/access | Login; workspace session gate and logout | Manager cookie API; session expiry and return path; no registration or agent credential |
| B1–B3 Home/actions | Workspace shell and Overview | Navigation, current plan, closing status, delivery list, ordering occasions, assessments, recent events; actions link to their workflows |
| C1–C3 Catalogue/menu/recipes | Inventory tabs | Connected ingredient, menu and recipe reads; policy fields deferred visibly |
| C4 Holidays | Suppliers → Holidays | Connected dates and provenance; no inferred demand effects |
| D1 Physical stock | Inventory → Physical counts | Batch observations, units, expiry, count times, totals; historical-count caveat |
| D2 Estimates | Inventory → Estimates | Selected as-of time, FEFO/expiry status, incomplete coverage, uncovered usage; separate from counts |
| D3 Projections | Inventory → Projections; Recommendations → Forecast | Explicit integration placeholder |
| D4–D6 Expiry/FEFO/warnings | Inventory details; Overview expiry count; Recommendations policy | Shared expiry/receipt/lot-ID order explained; persisted FEFO policy shown; forecast projections remain deferred |
| E1–E3 Closing entry/revisions | Daily Update → Closing update | Save draft, submit, correct with original cutoff, view revision and reconciliation history |
| E4 Waste | Daily Update | Explicit placeholder; no unsupported waste payload or discrepancy-as-waste inference |
| E5–E6 Sales batches/corrections | Daily Update → Sales intervals; Intraday sales | Entry/corrections plus reporting-window monitoring, exact recipe usage, coverage warnings and backend estimate snapshots |
| E7 Reconciliation | Daily Update history | Per-dish daily/batch totals, signed differences, incomplete coverage and period |
| E8 Materiality | Daily Update explanatory state; assessment views | Deterministic estimate request supported; ML certification deferred |
| F1–F2 Ordering | Inventory schedules; Suppliers → Ordering occasions | Anchored schedules, date-selected occasions, ordered/skipped decisions with effective time and note |
| F3–F6 Suppliers | Suppliers → Supplier offers | Ingredient filter/comparison, all current offer constraints, manager updates; historical events in Activity |
| F7 Promotions | Suppliers → Promotions | Create/update revisions, dates, dishes, explicit multiplier, active state |
| G1–G3 Forecast/allocation/requirements | Recommendations → Forecast | Explicit placeholders for persisted engine evidence |
| G4–G6 Policy/domain | Recommendations → Policy | Read-only canonical persisted versions, constraints, frozen offers/opportunities and forecast input history via manager boundary; verified against PostgreSQL and in a live browser read |
| G7–G8 Search/completeness | Recommendations; Activity outcomes | Display actual results and error messages; engine search evidence deferred |
| G9 Costs | Recommendation detail | Stored cost components, distinction from immediate cash, fee grouping/ledger placeholder |
| H1–H3 Assessment lifecycle | Activity → Assessments | Manual request, status, active polling, retry with explicit time, triggers |
| H4–H5 Agent investigation/explanation | Assessment detail and recommendation evidence | Stored outcomes explained; operational/knowledge cutoffs, revisions, readiness and exact frozen policy evidence; unavailable tool narrative not fabricated |
| I1–I4 Recommendation/history | Recommendations → Purchase plans | Identity/version/status, lines, mode, references, prior-version comparison |
| I5–I7 Decisions/invalidation | Recommendation detail | Exact-version approval/rejection confirmation, instructions, stale-error feedback; live certification remains backend/engine responsibility |
| J1–J2 Actual purchasing | Deliveries; recommendation allocation links | Manual or approved-line purchase recording; server-enforced allocation; remaining quantities shown |
| J3–J5 Deliveries/receipt | Deliveries | Outstanding/closed filters, terms changes, cancellation, partial receipt, expiry, lot references, stable receipt retry identity, late-count corrections |
| J6 Commitments | Deliveries and linked recommendation quantities | Actual/outstanding separated; contingency engine behaviour remains pending |
| K1–K4 History/audit | Activity tabs; recommendation references | Actors, recorded/operational times, events, run references, concise evidence; no hidden reasoning or secrets |
| L1–L5 Feedback | Shared notice/status components and forms | Loading, empty, unavailable, validation, conflict, expiry, connection and calculation states; mobile table scrolling |

## Deferred backend-dependent details

General historical-offer browsing beyond frozen domains, full projection charts, persisted agent tool narratives, materiality certification, complete economic ledgers and validated emergency/contingency outputs still require their final backend contracts. Forecast input history is not a forecast result. The manager UI preserves a visible place for unavailable capabilities.
