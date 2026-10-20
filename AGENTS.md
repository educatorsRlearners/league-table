For backend, use uv for dependency management. A few useful commands: 

uv sync
uv add <PACKAGE-NAME>
uv run python <PYTHON-FILE>

Regularly commit

CI runs `make check` (lint, unit tests, compose port guard) on every pull request. Run `make check` before pushing for the quick loop, and `make test-all` (every suite, needs Docker + Node) before declaring a task done.

Use the plugins found in .claude/ 

## Project docs

League Table is a live class scoreboard: a FastAPI backend with a Postgres-backed store, and a browser frontend served from the same origin. See [README.md](README.md) for what it does and how to run it.

- [Product spec](_docs/spec.md): goals, scoring rules, data model, phasing and acceptance criteria
- [Process](_docs/process.md): task lifecycle, orchestrator and rules. Tasks are GitHub issues.
- Agent roles, one file each in [_docs/team/](_docs/team/):
  - [PM](_docs/team/pm.md): grooms issues before implementation
  - [Software engineer](_docs/team/software-engineer.md): implements one groomed issue
  - [QA engineer](_docs/team/qa-engineer.md): checks the result against the acceptance criteria
  - [UI/UX expert](_docs/team/ui_ux.md): reviews UI work
- [Task template](_docs/task_template.md): the four sections every groomed issue has
- Project skills in [.claude/skills/](.claude/skills/): `orchestrate`, `groom-issue`, `verify-task`, `ship`
- [API contract](openapi.yaml): the OpenAPI spec the backend and frontend share
- [Backend README](backend/README.md): backend setup, `DATABASE_URL`, integration tests
- `make help` lists the run, test, lint, integration and e2e commands
