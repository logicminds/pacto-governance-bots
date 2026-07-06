.PHONY: test validate secret-lint install clean

PYTHON := python3
VENV := .venv
BOT_DIR := bots/bosun

$(VENV)/bin/activate:
	$(PYTHON) -m venv $(VENV)

install: $(VENV)/bin/activate
	$(VENV)/bin/pip install -e $(BOT_DIR)

test:
	$(VENV)/bin/pip install -e $(BOT_DIR)[dev]
	PACTO_GOVERNANCE_RPC_URL=http://localhost:8545 \
	PACTO_GOVERNANCE_BOT_ID=bosun \
	PACTO_GOVERNANCE_GROUP_ID=test-group \
	PACTO_GOVERNANCE_DAEMON_SOCKET=/tmp/pacto-test.sock \
	$(VENV)/bin/pytest $(BOT_DIR)/tests

validate:
	$(VENV)/bin/pip install -e $(BOT_DIR)[dev]
	$(VENV)/bin/python -m compileall $(BOT_DIR)/src/bosun
	PACTO_GOVERNANCE_RPC_URL=http://localhost:8545 \
	PACTO_GOVERNANCE_BOT_ID=bosun \
	PACTO_GOVERNANCE_GROUP_ID=test-group \
	PACTO_GOVERNANCE_DAEMON_SOCKET=/tmp/pacto-test.sock \
	$(VENV)/bin/pytest $(BOT_DIR)/tests

secret-lint:
	@# Refuse to commit if any known secret patterns appear in tracked files.
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

clean:
	rm -rf $(VENV) .pytest_cache
	find $(BOT_DIR) -type d -name __pycache__ -exec rm -rf {} +
