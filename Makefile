.PHONY: help install dev build up run logs down test lint clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## ' Makefile | awk -F':.*?## ' '{printf "  %-12s %s\n", $$1, $$2}'

install: ## Install runtime deps with uv into a local venv
	uv venv && uv pip install -e .

dev: ## Install runtime + dev deps with uv
	uv venv && uv pip install -e '.[dev]'

build: ## Build the chimera:dev image
	docker compose build

up: ## Start chimera in the background
	docker compose up -d

run: ## One-shot run; pass ARGS="..." for CLI args
	docker compose run --rm chimera $(ARGS)

logs: ## Tail logs
	docker compose logs -f --tail=100 chimera

down: ## Stop and remove the container
	docker compose down

test: ## Run pytest inside the container
	docker compose run --rm chimera python -m pytest

lint: ## Ruff check
	uv run ruff check chimera tests

clean: ## Remove venv and build artifacts
	rm -rf .venv build dist *.egg-info
