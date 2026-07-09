"""Unit tests for the bosun configuration layer."""

from __future__ import annotations

import os

import pytest

from bosun.config import SEPOLIA_HATS, SEPOLIA_REGISTRY, Settings, load_settings


def _set_required(monkeypatch, **extra):
    base = {
        "PACTO_GOVERNANCE_RPC_URL": "http://localhost:8545",
        "PACTO_GOVERNANCE_BOT_ID": "bosun",
        "PACTO_GOVERNANCE_GROUP_ID": "test-group",
        "PACTO_GOVERNANCE_DAEMON_SOCKET": "/tmp/pacto-test.sock",
        # Pin optional defaults so a local .env file does not make the test flaky.
        "PACTO_GOVERNANCE_REGISTRY": SEPOLIA_REGISTRY,
        "PACTO_GOVERNANCE_HATS": SEPOLIA_HATS,
    }
    base.update(extra)
    for key, value in base.items():
        monkeypatch.setenv(key, value)
    # Remove any optional env vars that might leak from the test environment.
    for key in [
        "PACTO_GOVERNANCE_HTTP_SECRET",
        "PACTO_GOVERNANCE_DAEMON_HTTP",
        "PACTO_GOVERNANCE_CAPTAIN",
        "PACTO_GOVERNANCE_CREW_CANDIDATES",
        "PACTO_GOVERNANCE_PROPOSER_CANDIDATES",
    ]:
        if key not in base:
            monkeypatch.delenv(key, raising=False)


def test_settings_loads_from_env(monkeypatch):
    _set_required(monkeypatch)
    settings = Settings()
    assert settings.rpc_url == "http://localhost:8545"
    assert settings.bot_id == "bosun"
    assert settings.group_id == "test-group"
    assert settings.daemon_socket == "/tmp/pacto-test.sock"
    assert settings.squad_index == 0
    assert settings.cadence_seconds == 86_400
    assert settings.registry == SEPOLIA_REGISTRY
    assert settings.hats == SEPOLIA_HATS


def test_settings_defaults_match_rust(monkeypatch):
    _set_required(monkeypatch)
    settings = Settings()
    assert settings.squad_index == 0
    assert settings.cadence_seconds == 86_400
    assert settings.captain == "0x0000000000000000000000000000000000000000"
    assert settings.crew_candidates == []
    assert settings.proposer_candidates == []


def test_settings_registry_hats_override(monkeypatch):
    registry = "0x0000000000000000000000000000000000000001"
    hats = "0x0000000000000000000000000000000000000002"
    _set_required(
        monkeypatch,
        PACTO_GOVERNANCE_REGISTRY=registry,
        PACTO_GOVERNANCE_HATS=hats,
    )
    settings = Settings()
    assert settings.registry == registry
    assert settings.hats == hats


def test_settings_address_lists_parse(monkeypatch):
    a1 = "0x0000000000000000000000000000000000000001"
    a2 = "0x0000000000000000000000000000000000000002"
    _set_required(
        monkeypatch,
        PACTO_GOVERNANCE_CREW_CANDIDATES=f"{a1},{a2}",
        PACTO_GOVERNANCE_PROPOSER_CANDIDATES=a2,
    )
    settings = Settings()
    assert settings.crew_candidates == [a1, a2]
    assert settings.proposer_candidates == [a2]


def test_settings_invalid_address_raises(monkeypatch):
    _set_required(
        monkeypatch,
        PACTO_GOVERNANCE_CAPTAIN="not-an-address",
    )
    with pytest.raises(ValueError):
        Settings()


def test_settings_optional_transport_empty_string_is_unset(monkeypatch):
    """Empty optional transport env vars are treated as not set."""
    _set_required(monkeypatch)
    # daemon_socket is already set by _set_required; empty daemon_http becomes None.
    monkeypatch.setenv("PACTO_GOVERNANCE_DAEMON_HTTP", "  ")
    settings = Settings()
    assert settings.daemon_http is None

    # Conversely, empty daemon_socket becomes None while daemon_http is valid.
    monkeypatch.setenv("PACTO_GOVERNANCE_DAEMON_SOCKET", "")
    monkeypatch.setenv("PACTO_GOVERNANCE_DAEMON_HTTP", "http://127.0.0.1:9800")
    monkeypatch.setenv("PACTO_GOVERNANCE_HTTP_SECRET", "secret")
    settings = Settings()
    assert settings.daemon_socket is None
    assert settings.daemon_http == "http://127.0.0.1:9800"


def test_settings_missing_required_raises(monkeypatch):
    # Set an empty RPC URL so the env file (if present) is overridden and the
    # non-empty URL validator fires.
    monkeypatch.setenv("PACTO_GOVERNANCE_RPC_URL", "")
    monkeypatch.setenv("PACTO_GOVERNANCE_BOT_ID", "bosun")
    monkeypatch.setenv("PACTO_GOVERNANCE_GROUP_ID", "test-group")
    monkeypatch.setenv("PACTO_GOVERNANCE_DAEMON_SOCKET", "/tmp/pacto-test.sock")
    with pytest.raises(ValueError):
        Settings()


def test_settings_http_requires_secret(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.delenv("PACTO_GOVERNANCE_DAEMON_SOCKET", raising=False)
    monkeypatch.setenv("PACTO_GOVERNANCE_DAEMON_HTTP", "http://127.0.0.1:9800")
    monkeypatch.delenv("PACTO_GOVERNANCE_HTTP_SECRET", raising=False)
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_nsec_like_address(monkeypatch):
    _set_required(
        monkeypatch,
        PACTO_GOVERNANCE_CAPTAIN="nsec1deadbeef000000000000000000000000000000",
    )
    with pytest.raises(ValueError):
        Settings()


def test_settings_to_bot_transport_kwargs_unix(monkeypatch):
    _set_required(monkeypatch)
    settings = Settings()
    kwargs = settings.to_bot_transport_kwargs()
    assert kwargs == {"transport": "unix", "socket_path": "/tmp/pacto-test.sock"}


def test_settings_to_bot_transport_kwargs_http(monkeypatch):
    _set_required(
        monkeypatch,
        PACTO_GOVERNANCE_DAEMON_HTTP="http://127.0.0.1:9800",
        PACTO_GOVERNANCE_HTTP_SECRET="secret",
    )
    monkeypatch.delenv("PACTO_GOVERNANCE_DAEMON_SOCKET", raising=False)
    settings = Settings()
    kwargs = settings.to_bot_transport_kwargs()
    assert kwargs == {
        "transport": "http",
        "http_bind": "http://127.0.0.1:9800",
        "secret": "secret",
    }


def test_load_settings_applies_config_file(monkeypatch, tmp_path):
    _set_required(monkeypatch)
    config_file = tmp_path / "config.json"
    config_file.write_text('{"cadence_seconds": 3600}')
    monkeypatch.setenv("PACTO_GOVERNANCE_CONFIG_FILE", str(config_file))
    settings = load_settings()
    assert settings.cadence_seconds == 3600
    assert settings.bot_id == "bosun"
