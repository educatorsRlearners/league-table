---
name: ship
description: Commit finished, QA-passed work, open a pull request that links the issue, and wait for CI. Use when a task has passed review and is ready to merge, or when asked to ship, commit and push, or open a PR.
---

1. Confirm the issue has `## QA: PASS` (and `## UX: PASS` if it ran). If not, stop and say so.
2. Run `make test` and `make lint`. Do not continue if either fails.
3. Work on a branch, not `main`. Commit with a message like `Feature: <summary>` and end it with the Co-Authored-By line from the session's attribution reminder.
4. Push and open a PR with `gh pr create`. The body states what changed, lists the acceptance criteria and links the issue with `Closes #<n>`. End it with the attribution line from the reminder.
5. Check CI with `gh pr checks` once a workflow exists (`.github/workflows/`). Report failures; do not merge red.
6. Merge only if the user asked for it. Deploys to production are always manual and need explicit approval.
