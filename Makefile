# One command per thing worth doing. A reviewer who cannot run the project
# cannot judge it, so the entry points are named rather than described.

.DEFAULT_GOAL := help
.PHONY: help setup format lint types test check docker run clean check-connection live

PYTHON ?= python
IMAGE  ?= salesforce-connector

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

setup:  ## Install the connector and its development tools
	$(PYTHON) -m pip install -e ".[dev]"

format:  ## Apply the formatter
	$(PYTHON) -m ruff format .

lint:  ## Check style, and that no layer imports one above it
	$(PYTHON) -m ruff check .
	$(PYTHON) -m lint_imports

types:  ## Type-check source and tests under strict mode
	$(PYTHON) -m mypy src tests

test:  ## Run the tests that need no Salesforce org
	$(PYTHON) -m pytest

check: format lint types test  ## Everything CI runs, in the same order

check-connection:  ## Ask a real org whether the credentials work (writes nothing)
	@PYTHONPATH=src $(PYTHON) -c \
	 "import asyncio; \
	  from salesforce_connector.auth.jwt_bearer import JwtBearerAuth; \
	  from salesforce_connector.client import SalesforceClient; \
	  from salesforce_connector.config import load_settings; \
	  from salesforce_connector.connector import SalesforceConnector, load_manifest; \
	  async def main(): \
	      s = load_settings(); \
	      c = SalesforceClient.open(s, JwtBearerAuth()); \
	      print(await SalesforceConnector(c, load_manifest(s)).test_connection(s)); \
	      await c.aclose(); \
	  asyncio.run(main())"

live:  ## Run the suites that need a real org (see docs/GO-LIVE.md)
	$(PYTHON) -m pytest -m "integration or learning" -v

openapi:  ## Regenerate openapi.yaml from the action schemas
	@SF_CLIENT_ID=placeholder SF_USERNAME=placeholder@example.com \
	 SF_PRIVATE_KEY=placeholder PYTHONPATH=src $(PYTHON) -c \
	 "from pathlib import Path; \
	  from salesforce_connector.config import load_settings; \
	  from salesforce_connector.connector import load_manifest; \
	  from salesforce_connector.openapi import to_yaml; \
	  Path('openapi.yaml').write_text(to_yaml(load_manifest(load_settings())), encoding='utf-8')"
	@echo "openapi.yaml regenerated"

docker:  ## Build the image
	docker build -t $(IMAGE) .

run:  ## Run the server over stdio, as an MCP host would
	docker run -i --rm --env-file .env $(IMAGE)

clean:  ## Remove caches and build output
	rm -rf .pytest_cache .mypy_cache .ruff_cache build dist htmlcov .coverage
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
