.PHONY: help install run test test-frontend test-integration e2e check-ports lint check test-all

help: ## List the available commands
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  make %-16s %s\n", $$1, $$2}'

install: ## Install backend dependencies
	cd backend && uv sync

run: ## Serve the app at http://localhost:8000 (API docs at /docs), auto-reloading
	cd backend && uv run uvicorn app.main:create_app --factory --reload

test: ## Run the backend tests
	cd backend && uv run pytest

test-frontend: ## Run the frontend scoring, risk and mock-client tests headlessly (requires Node)
	node scripts/run-frontend-tests.mjs

test-integration: ## Run the docker-compose/Postgres integration tests (requires Docker)
	cd backend && uv run pytest -m integration tests/test_integration_docker.py

e2e: ## Run the Playwright browser e2e tests against docker-compose (requires Docker + Node)
	# Drives your installed Brave browser (e2e/browser.js) instead of downloading
	# Playwright's own Chromium. No Brave found: `cd e2e && npx playwright install chromium`.
	cd e2e && npm install && npm test

check-ports: ## Fail if a test compose override re-publishes the dev stack's host ports (needs only the docker CLI)
	python3 scripts/check-compose-ports.py

lint: ## Run ruff and mypy over the backend
	cd backend && uv run ruff check app tests && uv run mypy app

check: lint test check-ports ## Run lint, the unit tests and the port guard, as CI does on every pull request

test-all: ## Run every test suite: unit, frontend, port guard, integration, e2e (requires Docker + Node)
	$(MAKE) test
	$(MAKE) test-frontend
	$(MAKE) check-ports
	$(MAKE) test-integration
	$(MAKE) e2e
