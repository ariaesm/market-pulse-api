.PHONY: help install dev lint format test run data docker-build up down clean

PYTHON ?= python3

help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

install:  ## Install the package with dev and redis extras
	$(PYTHON) -m pip install -e ".[dev,redis]"

lint:  ## Run ruff lint and format checks
	ruff check .
	ruff format --check .

format:  ## Auto-format and fix lint issues
	ruff format .
	ruff check --fix .

test:  ## Run the test suite
	PYTHONPATH=src $(PYTHON) -m pytest

run:  ## Run the API locally with auto-reload
	PYTHONPATH=src uvicorn market_pulse.main:app --reload --port 8000

data:  ## Regenerate the bundled synthetic CSV data
	$(PYTHON) scripts/generate_synthetic_data.py

docker-build:  ## Build the Docker image
	docker build -t market-pulse-api:local .

up:  ## Start api + redis with docker compose
	docker compose up --build

down:  ## Stop docker compose services
	docker compose down

clean:  ## Remove caches and build artifacts
	rm -rf .pytest_cache .ruff_cache build dist *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
