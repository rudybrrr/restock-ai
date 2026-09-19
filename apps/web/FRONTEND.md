# ReStock frontend

## Local development

The application lives in the existing Next.js workspace. Nothing in this implementation publishes or deploys the site.

Use the repository's pinned pnpm 10.28.2 and install dependencies from the repository root with `pnpm install --frozen-lockfile`. From `apps/web`, use `pnpm dev`, `pnpm build`, or `pnpm start`.

If a host-provided pnpm wrapper attempts an unrelated automatic reinstall, the installed CLI can be used directly:

```powershell
node node_modules/next/dist/bin/next dev
node node_modules/typescript/bin/tsc --noEmit
node node_modules/eslint/bin/eslint.js .
node node_modules/next/dist/bin/next build
```

Copy `.env.example` to `.env.local` if an API origin other than `http://localhost:8000` is needed. The browser calls `/api/v1` on that origin with the manager session cookie. Start the existing backend according to `services/api/README.md`; configure its allowed origin as `http://localhost:3000` and its existing local-HTTP cookie setting appropriately. Use the configured manager credentials. No agent credential belongs in frontend environment variables.

## Design and navigation

- `/`: public introduction and explicitly illustrative product preview.
- `/login`: real manager authentication; expired-session and connection feedback.
- `/workspace/overview`: current plan, assessments, closing status, ordering occasions, deliveries, and latest changes.
- `/workspace/inventory`: physical observations, timestamped estimates, ingredient totals, lot details, menu/recipes, and schedules.
- `/workspace/daily`: closing drafts, submissions, corrections, reconciliation, and complete sales interval reports.
- `/workspace/recommendations`: version history, comparison, exact-version decisions, costs, allocation links, and evidence references.
- `/workspace/deliveries`: record actual purchases, inspect receipts, update terms, receive partially, cancel remainders, and enter late-receipt count corrections.
- `/workspace/suppliers`: offers and their constraints, price/availability/status/reliability changes, promotions, cycle decisions, and holidays.
- `/workspace/activity`: event timeline, audit history, assessment requests, polling, retries, and trigger evidence.

Forest green, warm ivory, and charcoal are defined in `components/restock.css`. Source Sans 3 and its OFL license are bundled in `public/fonts`; production builds do not fetch fonts. The ReStock wordmark uses text. Visual tokens and reusable primitives remain editable.

The service date defaults explicitly to the agreed demonstration date, 16 February 2026. Simulation timestamps use Singapore time. A date selection does not retroactively turn the physical-count endpoint into a historical snapshot: its label remains “latest physical observations.”

## Capability boundaries

The frontend displays Backend-owned historical forecast inputs, estimated inventory, immutable procurement policy/domain evidence, search completeness/economic evidence where supplied, and persisted sales-materiality status. Forecast inputs remain distinct from forecast results; estimated inventory remains labelled as estimated; and missing evidence stays visible rather than being filled with sample records. Optional waste entry, live forecast outputs, and any final materiality certification not exposed by the Backend remain unavailable.

Approval does not create purchases. Existing linked allocation totals come from the server. Receipt request IDs remain stable during retries of the open receipt form. Backend errors preserve entered values. Unknown supplier constraints remain unknown. Observed, estimated, and projected quantities stay labelled separately.

## Browser verification

`tests/browser-smoke.cjs` uses Playwright and intercepts backend HTTP requests with isolated fixtures. It does not read credentials or write to a restaurant database. Start the production server on port 3000 first.

```powershell
# Set this to an installed playwright-core package when not installed in the workspace.
$env:PLAYWRIGHT_MODULE = 'C:\path\to\node_modules\playwright-core'
node tests/browser-smoke.cjs
```

The script launches installed Microsoft Edge headlessly. It checks navigation, login failures and return paths, draft-before-submit ordering, stale approvals, approval/purchase separation, partial receipts, retry payloads, mobile layout/navigation, session expiry and connection failures. Screenshots are generated under ignored `test-results/`.

These checks validate frontend behaviour against controlled response contracts. They do not establish a running PostgreSQL backend, actual ML integration, or OpenClaw end-to-end acceptance.

The suite also checks daily correction payloads, fractional-sales rejection, interval boundaries, supplier changes, promotion validation, manual purchase provenance, and all workspace routes at phone and tablet widths. Set `UI_TEST_URL` for a different preview port (for example `http://localhost:3001`). Allow that same frontend origin in the backend configuration for live API use.

## Design references

The restaurant-focused language and straightforward product presentation take inspiration from [inline](https://inline.app/), without copying its branding or interface. The “AI-looking” label is subjective, not a formal standard; [this design discussion](https://blog.interfacekit.io/what-makes-a-website-look-ai-generated) identifies interchangeable, product-unspecific presentation as a concern. ReStock uses flat surfaces, a typographic identity, restaurant-specific records, and visible capability limits; it avoids neon gradients, glass effects and invented testimonials.
