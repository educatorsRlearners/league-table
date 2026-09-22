.PHONY: help install run test lint

help: ## List the available commands
	@grep -E '^[a-z]+:.*##' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  make %-8s %s\n", $$1, $$2}'

install: ## Install backend dependencies
	cd backend && uv sync

run: ## Serve the app at http://localhost:8000 (API docs at /docs), auto-reloading
	cd backend && uv run uvicorn app.main:create_app --factory --reload

test: ## Run the backend tests
	cd backend && uv run pytest

lint: ## Run ruff and mypy over the backend
	cd backend && uv run ruff check app tests && uv run mypy app
