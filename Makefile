.PHONY: help install run test

help: ## List the available commands
	@grep -E '^[a-z]+:.*##' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  make %-8s %s\n", $$1, $$2}'

install: ## Install backend dependencies
	cd backend && uv sync

run: ## Run the API with auto-reload (docs at http://localhost:8000/api/docs)
	cd backend && uv run uvicorn app.main:create_app --factory --reload

test: ## Run the backend tests
	cd backend && uv run pytest
