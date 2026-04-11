.PHONY: help install test lint format run dashboard clean

help: ## Show help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install in editable mode with all extras
	pip install -e ".[all]"

run: ## Run quickstart example
	python examples/quickstart.py

dashboard: ## Start Streamlit dashboard
	streamlit run dashboard/app.py --server.port 8501

test: ## Run tests
	pytest tests/ -v --cov=ecoalign_forge --cov-report=term-missing

lint: ## Lint check
	ruff check src/ tests/
	ruff format --check src/ tests/

format: ## Auto-format
	ruff check --fix src/ tests/
	ruff format src/ tests/

clean: ## Clean artifacts
	rm -rf dist/ build/ *.egg-info .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
