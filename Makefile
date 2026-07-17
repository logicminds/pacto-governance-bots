# Bosun — Pacto governance snapshot bot lifecycle helpers
# Run `make` to see available targets.

.DEFAULT_GOAL := help

PYTHON := python3
VENV := .venv
BOT_DIR := bots/bosun
SRC_DIR := $(BOT_DIR)/src/bosun

.PHONY: help venv install install-dev env link-dev-env up down logs build run-local trigger-snapshot test validate status health-check setup-dev-env secret-lint clean

PACTO_DEV_ENV_DIR := ${PACTO_DEV_ENV_DIR:-../pacto-dev-env}

help: ## Show available make targets and their descriptions
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage: make <target>\n\n"} \
		/^[a-zA-Z_-]+:.*?##/ { printf "  %-20s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

venv: $(VENV)/bin/activate ## Create a Python virtual environment

$(VENV)/bin/activate:
	$(PYTHON) -m venv $(VENV)

install: venv ## Install the bot package in editable mode
	$(VENV)/bin/pip install -e $(BOT_DIR)

install-dev: install ## Install the bot package with dev/test dependencies
	$(VENV)/bin/pip install -e $(BOT_DIR)[dev]

env: ## Generate bots/bosun/.env from the local pacto-dev-env deployment
	@PACTO_DEV_ENV_DIR="$(PACTO_DEV_ENV_DIR)" ./scripts/generate-env.sh

link-dev-env: ## Create a local symlink to the pacto-dev-env checkout
	@if [ -L ./pacto-dev-env ]; then \
		echo "./pacto-dev-env already points to: $$(readlink ./pacto-dev-env)"; \
	elif [ -e ./pacto-dev-env ]; then \
		echo "./pacto-dev-env already exists and is not a symlink"; exit 1; \
	else \
		ln -s "$(PACTO_DEV_ENV_DIR)" ./pacto-dev-env; \
		echo "Created ./pacto-dev-env -> $(PACTO_DEV_ENV_DIR)"; \
	fi

up: ## Build and start the bot container in the background
	docker compose up -d --build bosun

down: ## Stop the bot container
	docker compose down

logs: ## Tail the bot container logs
	docker logs --tail 50 -f bosun-bosun-1

build: ## Build the bot container image
	docker compose build bosun

run-local: install ## Run the bot locally using the venv
	$(VENV)/bin/python -m bosun

trigger-snapshot: install ## Post a single snapshot and exit (no cadence loop)
	$(VENV)/bin/python -m bosun --trigger-snapshot

test: install-dev ## Run the bot unit/integration test suite
	PACTO_GOVERNANCE_RPC_URL=http://localhost:8545 \
	PACTO_GOVERNANCE_BOT_ID=bosun \
	PACTO_GOVERNANCE_GROUP_ID=test-group \
	PACTO_GOVERNANCE_DAEMON_SOCKET=/tmp/pacto-test.sock \
	$(VENV)/bin/pytest $(BOT_DIR)/tests -v

validate: install-dev ## Compile source and run the full test suite
	$(VENV)/bin/python -m compileall $(SRC_DIR)
	PACTO_GOVERNANCE_RPC_URL=http://localhost:8545 \
	PACTO_GOVERNANCE_BOT_ID=bosun \
	PACTO_GOVERNANCE_GROUP_ID=test-group \
	PACTO_GOVERNANCE_DAEMON_SOCKET=/tmp/pacto-test.sock \
	$(VENV)/bin/pytest $(BOT_DIR)/tests -v

status: ## Show a concise status overview for the local workspace
	@./scripts/status.sh

health-check: ## Verify the integration against pacto-dev-env
	@./scripts/health-check.sh

setup-dev-env: ## One-shot setup of the local pacto-dev-env + bosun integration
	@./scripts/setup-dev-env.sh

secret-lint: ## Scan tracked files for leaked nsec, bunker, or hex secrets
	@# Refuse to commit if any known secret patterns appear in source files.
	@if git grep -n -E '(nsec1[ac-hj-np-z02-9]{58,})' -- ':!*.md' ':!Makefile'; then \
		echo "Found possible nsec secret in source files"; exit 1; \
	fi
	@if git grep -n -E '(bunker://[^\s]+)' -- ':!*.md' ':!Makefile'; then \
		echo "Found possible bunker URI in source files"; exit 1; \
	fi
	@if git grep -n -E '([0-9a-f]{64})' -- ':!*.md' ':!Makefile'; then \
		echo "Found possible hex secret in source files"; exit 1; \
	fi
	@echo "No obvious secrets found in source files."

clean: ## Remove the venv, pytest cache, and __pycache__ directories
	rm -rf $(VENV) .pytest_cache
	find $(BOT_DIR) -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
