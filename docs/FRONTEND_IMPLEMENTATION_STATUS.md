# Frontend implementation checkpoint

Updated: 16 September 2026.

## Scope delivered

The first editable frontend is implemented in the existing `apps/web` package. Nothing was pushed or deployed; no backend or agent implementation was changed. The design uses forest green, warm ivory, charcoal, bundled Source Sans 3, and a text-only ReStock wordmark.

- [x] Public homepage and manager login.
- [x] Typed manager-session API client, protected workspace, logout and session/error feedback.
- [x] Overview with plan, assessments, closing status, ordering occasions, deliveries and recent events.
- [x] Inventory with physical/estimated distinctions, ingredient totals, lot evidence, recipes and schedules.
- [x] Closing drafts, submission, correction, revision history, reconciliation, complete sales intervals.
- [x] Supplier terms and updates, promotion revisions, ordering decisions and holiday context.
- [x] Recommendation versions, comparison, costs, exact-version approval/rejection and allocation links.
- [x] Manual/linked purchase recording, arrival filtering, delivery changes, cancellation, partial receipts and late closing corrections.
- [x] Assessment requests, polling, retry and activity/audit views.
- [x] Explicit placeholders for unavailable engine, forecast, projection, canonical policy, waste and evidence interfaces.
- [x] Responsive browser checks at desktop, phone and tablet widths; visual screenshot review.
- [x] Production build including TypeScript, full ESLint and isolated browser interaction checks.

See `FRONTEND_FEATURE_COVERAGE.md` for the feature-group mapping and `apps/web/FRONTEND.md` for local startup and tests.

## Verification and limits

Production build and ESLint pass. Browser tests use intercepted fixtures: they verify login/return paths, invalid credentials, daily validation and correction payloads, draft-before-submit ordering, stale approval handling, no purchase on approval, partial receipt, assessment retry, sales interval validation, supplier updates, promotion validation, unlinked manual purchase, mobile/tablet overflow, session expiry and API outage. Screenshots are ignored under `apps/web/test-results`.

This is not live database or ML/agent acceptance. The protected workspace needs a running API and configured manager credentials for normal use. There is deliberately no fake operational-data fallback or authentication bypass. The homepage preview alone is illustrative.

The local preview was started on port 3001 because port 3000 was occupied. For live API use, allow the actual frontend origin in the existing backend configuration. Standard startup can still use port 3000 when free.

## Next integration work, outside this frontend slice

- Verify the actual manager workflow against a running PostgreSQL/API environment.
- Replace labelled placeholders when canonical policy, engine artifacts, opportunity-domain evidence and agent explanations have stable manager-facing APIs.
- Run cross-team end-to-end acceptance for Aniq's engine, Rudy's adapter and CY's persisted records.
- Review the visual design with the user; tokens, typography, layout and page grouping remain adjustable.

## Non-negotiable boundaries

Manager cookies only; no agent token in the browser. Unknown values stay unknown. Counts are not estimates. The explicit historical service date does not make latest-count endpoints historical snapshots. Approval does not place a purchase or receive stock. Receipt retry identity remains stable within the open form. Backend validation remains authoritative.
