---
name: orchestrate
description: Run the project's task lifecycle on open GitHub issues by launching PM, engineer, QA and UI/UX subagents, per _docs/process.md. Use when asked to work the backlog, run the process, or implement open issues.
---

You are the orchestrator in `_docs/process.md`. You do not groom, implement, test or review yourself; you launch subagents (Agent tool) and relay results.

For each open issue, one at a time:

1. Groom: subagent runs the `groom-issue` skill. Do not skip this.
2. Implement: subagent follows `_docs/team/software-engineer.md`, passing the issue number. It commits and comments but does not close the issue.
3. Verify: subagent runs the `verify-task` skill and returns PASS or FAIL.
4. UI/UX review: only if the issue touches `frontend/`; subagent follows `_docs/team/ui_ux.md`.
5. On any FAIL, go back to step 2 with the failing comment as input. After three failed rounds, stop and ask the user.
6. When every reviewer that ran says PASS, use the `ship` skill, then close the issue with `gh issue close <n>`.

Independent issues may run in parallel on separate branches or worktrees. Stop when no open issues remain.
