"""Shared pytest configuration for the bosun bot test suite.

The handler imports its settings (and therefore the bot instance) at module load
time. Set sensible defaults here so tests can import ``bosun.bosun`` without
every test needing to configure the environment first.
"""

from __future__ import annotations

import os

os.environ.setdefault("PACTO_GOVERNANCE_RPC_URL", "http://localhost:8545")
os.environ.setdefault("PACTO_GOVERNANCE_BOT_ID", "bosun")
os.environ.setdefault("PACTO_GOVERNANCE_GROUP_ID", "test-group")
os.environ.setdefault("PACTO_GOVERNANCE_DAEMON_SOCKET", "/tmp/pacto-test.sock")
