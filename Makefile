.PHONY: help install dev build up down logs run cycle dashboard ping test test-slow lint clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## ' Makefile | awk -F':.*?## ' '{printf "  %-12s %s\n", $$1, $$2}'

install: ## Install runtime deps with uv into a local venv
	uv sync

dev: ## Install runtime + dev deps with uv
	uv sync --all-extras

build: ## Build both container images
	docker compose build

up: ## Start chimera (HTTP MCP serve) + dashboard in the background
	docker compose up -d

down: ## Stop and remove containers
	docker compose down

logs: ## Tail logs from both services
	docker compose logs -f --tail=100

run: ## Ad-hoc chimera invocation. Pass ARGS="ping --provider both" etc.
	docker compose run --rm chimera $(ARGS)

cycle: ## One-shot cycle. Pass TASK="<task text>"
	docker compose run --rm chimera run "$(TASK)"

dashboard: ## Open the dashboard (assumes `make up` is running)
	@echo "Dashboard: http://127.0.0.1:3000"
	@command -v open >/dev/null && open http://127.0.0.1:3000 || true

ping: ## Verify both providers from inside the container
	docker compose run --rm chimera ping --provider both

test: ## Run pytest (local venv)
	uv run pytest -q

test-slow: ## Run pytest including slow integration tests
	uv run pytest -q -m "slow or not slow"

lint: ## Ruff check
	uv run ruff check chimera tests

clean: ## Remove venv and build artifacts
	rm -rf .venv build dist *.egg-info
