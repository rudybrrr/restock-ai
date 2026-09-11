# Issue tracker: GitHub

Specs and tickets live in GitHub Issues for rudybrrr/restock-ai, matching the origin remote. This choice was approved with the backend specification and ticket breakdown.

- Use connected GitHub tools when their permissions allow; gh CLI may be used when available. No gh executable was available during setup. The connector could read but returned HTTP 403 for issue creation; publication succeeded through GitHub REST using the existing local Git credential-manager login. Never log or persist credentials.
- Search for matching issues before creating duplicates. Use structured Markdown body arguments or a body file, not shell-interpolated multiline text.
- Apply ready-for-agent to approved specs and implementation tickets. A blocked ticket is not actionable merely because it has that label.
- Publish tickets in dependency order. Each ticket links its parent spec and lists direct blocking issues.
- Prefer native dependency/sub-issue relationships when exposed by the available tools. If unavailable, use explicit linked Parent and Blocked by sections; do not claim native links were created.
- The backend spec and its nine tickets have native GitHub parent/sub-issue and blocking relationships, as well as visible body links. Keep both consistent when changing dependencies.
- Do not close or modify a parent spec while publishing its tickets. Do not assign teammates or post separate messages without user instruction.
- PRs as a request surface: no.

The triage skill is not installed, so no separate triage-label configuration is needed. ready-for-agent is the required publication label for to-spec and to-tickets.
