# Manager decision UX — 22 September 2026

Implemented locally; not pushed.

## Delivered

- Assessment lifecycle copy distinguishes waiting for a worker, claimed/running, finished and failed. Finished does not imply a feasible purchase recommendation.
- Structured manager summaries show the recorded trigger, conclusion and next action. No model call or inferred business conclusion is added.
- Recorded routing, validation, timeline and captured procurement inputs are expandable. The recommendation summary is visible outside calculation references.
- Overview/recommendation evidence links to its exact run. New manual/retry requests link to the ID returned by Backend.
- Rejected plans have a separate reassessment confirmation with an explicit Singapore operational cutoff. Rejection alone does not request a new run. Failed-run detail exposes the same action. It calls the existing run retry endpoint, preserving Backend's previous-plan association.
- Invalidated/superseded versions remain non-actionable. Pending approval, rejection and approval use recorded state; stale attempts remain inspectable. Failed and queued evidence no longer use the hardcoded success badge.
- Pending submissions disable repeat clicks; successful retries retain their returned link; errors permit correction/retry.

## Verification

- Production Next.js build and TypeScript passed.
- ESLint passed on changed components/pages.
- Existing evidence browser suite passed after adapting disclosure interactions; it retains stale-attempt, exact-version, materiality, policy, corrections, and mobile assertions.
- New assessment-flow browser suite passed: all four lifecycle states; collapsed captured evidence; failed retry then successful retry with exact cutoff; returned run link; duplicate prevention; explicit rejection instructions and version; no implicit reassessment; separate reassessment; invalidated/superseded controls; viewport overflow checks at 390/768/1440 pixels.
- Screenshots inspected. Browser suites use intercepted fixtures and do not write operational data. Backend business logic and agent/ML code are unchanged.

Automatic worker deployment, live model execution, contingency activation and multi-day projection publication remain outside this frontend change.
