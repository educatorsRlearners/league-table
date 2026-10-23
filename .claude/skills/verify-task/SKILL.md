---
name: verify-task
description: Verify an implemented GitHub issue against its acceptance criteria as the QA engineer, and post a PASS or FAIL comment. Use after an engineer finishes a task, or when asked to QA, verify or review an issue. Does not fix code.
---

Follow `_docs/team/qa-engineer.md`. You never edit code.

1. Read the issue and its criteria: `gh issue view <n> --comments`.
2. Run the checks and record exact commands and results:
   - `make test` and `make lint` always.
   - `make test-integration` and `make e2e` when the task touches the API, database or UI flow. They need Docker and free ports 8000 and 5433.
3. Check each criterion against the running app or code, not the engineer's description. For API work use `curl` with a Bearer token (see _docs/api.md, Auth). For UI work, use the `run` skill and the Playwright tools to click through it.
4. Look for cases the criteria describe that the tests do not cover.
5. Post the verdict with `gh issue comment <n> --body-file <file>`, in the format in `qa-engineer.md`: `## QA: PASS` or `## QA: FAIL`, one line per criterion, every FAIL saying what you did and what happened, and the test commands with results.

One failing criterion means FAIL. If the issue touches the UI, tell the orchestrator that a UI/UX review is also needed.
