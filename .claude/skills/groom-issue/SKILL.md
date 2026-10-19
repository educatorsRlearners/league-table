---
name: groom-issue
description: Groom a GitHub issue before implementation, following the PM role. Rewrites it with the task template, makes acceptance criteria checkable, and files follow-ups for anything out of scope. Use when picking up a new or ungroomed issue, or when asked to groom, refine or write a task.
---

Follow `_docs/team/pm.md` and `_docs/task_template.md`. Do not write code.

1. Read the issue: `gh issue view <n> --comments`. If none given, list candidates with `gh issue list --state open`.
2. Read the parts of `_docs/spec.md`, `openapi.yaml` and the code it touches, so the criteria match what exists.
3. Rewrite the body with the four template sections (Goal, Acceptance criteria, Out of scope, Constraints) via `gh issue edit <n> --body-file <file>`. Write the file in the scratchpad directory.
4. Make each criterion checkable by looking at the result. Add edge cases the filer missed: empty state, invalid input, wrong role, missing data.
5. For anything moved out of scope, create a follow-up issue (`gh issue create`) and link its number in Out of scope. Never drop scope silently.
6. Comment on the issue with `## PM: groomed` and a one-line summary of what changed.

Done when all four sections are filled, every criterion is yes/no checkable, and every out-of-scope item links to an issue.
