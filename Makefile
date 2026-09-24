.PHONY: help install run test test-integration e2e lint

help: ## List the available commands
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  make %-8s %s\n", $$1, $$2}'

install: ## Install backend dependencies
	cd backend && uv sync

run: ## Serve the app at http://localhost:8000 (API docs at /docs), auto-reloading
	cd backend && uv run uvicorn app.main:create_app --factory --reload

test: ## Run the backend tests
	cd backend && uv run pytest

test-integration: ## Run the docker-compose/Postgres integration tests (requires Docker)
	cd backend && uv run pytest -m integration tests/test_integration_docker.py

e2e: ## Run the Playwright browser e2e tests against docker-compose (requires Docker + Node)
	# Drives your installed Brave browser (e2e/browser.js) instead of downloading
	# Playwright's own Chromium. No Brave found: `cd e2e && npx playwright install chromium`.
	cd e2e && npm install && npm test

lint: ## Run ruff and mypy over the backend
	cd backend && uv run ruff check app tests && uv run mypy app
