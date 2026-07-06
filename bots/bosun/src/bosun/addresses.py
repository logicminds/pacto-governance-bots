"""Canonical infrastructure addresses for the Pacto governance reader.

Per-squad clone addresses are discovered dynamically via the registry; only the
singleton registry and the canonical Hats contract live here.
"""

from __future__ import annotations

import os

SEPOLIA_CHAIN_ID = 11155111
ANVIL_CHAIN_ID = 31337

SEPOLIA_REGISTRY = "0x45127C1c92741C0dA38e1A73fbb97a8a2C46770f"
SEPOLIA_HATS = "0x3bc1A0Ad72417f2d411118085256fC53CBdDd137"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def _read_address_from_env(var: str) -> str | None:
    value = os.environ.get(var)
    if not value:
        return None
    stripped = value.strip()
    from eth_utils import is_address, to_checksum_address

    if not is_address(stripped):
        return None
    return to_checksum_address(stripped)


def registry_address() -> str:
    """Resolve the registry address, honoring environment overrides."""
    return _read_address_from_env("PACTO_GOVERNANCE_REGISTRY") or SEPOLIA_REGISTRY


def hats_address() -> str:
    """Resolve the Hats contract address, honoring environment overrides."""
    return _read_address_from_env("PACTO_GOVERNANCE_HATS") or SEPOLIA_HATS
