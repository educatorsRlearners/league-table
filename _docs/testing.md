# Testing

Every automated suite and the command that runs it.

- **Everything:** `make test-all` is the single command for every automated suite. It runs, in order, `make test`, `make check-ports`, `make test-integration`, and `make e2e`, and stops at the first failure. It needs Docker running and Node installed (the first two steps do not). Expect about 1 minute (the first two steps take a few seconds) with images already built; the first run is slower while images build and `npm install` runs. The browser-only frontend tests (`Tests.dc.html`) are not included (#62). `make check` is the fast, Docker-free subset CI runs.
- **Before you push:** `make check` runs lint, the backend tests, and the compose port guard (`make lint`, `make test`, `make check-ports`), stopping at the first failure. CI runs the same `make check` steps on every pull request and on every push to `main`.
- **Backend:** `make test` runs the pytest suite, covering every endpoint, the scoring and adjustment rules, privacy scoping, the risk engine and digest, notes, the seeded edge cases, and the OpenAPI contract.
- **Lint:** `make lint` runs ruff and mypy over the backend (both are dev dependencies).
- **Frontend:** the scoring, risk, and mock-client tests run in the browser at <http://localhost:8000/Tests.dc.html> while the app is running (no headless runner yet, so there is no `make` target for them). These exercise the reference `scoring.js`/`risk.js`/`api.js` logic, not `httpApi.js`; the shipped page's real HTTP integration is covered by the backend's own endpoint tests plus manual/browser verification.
