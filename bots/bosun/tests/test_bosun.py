"""Unit tests for the bosun bot wiring, trigger modes, and inbound
``!snapshot`` event handlers.

Slash-command tests for ``/snapshot`` live in ``test_handlers.py``.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager

import pytest

from bosun import bot, is_squad_member, snapshot, trigger_once
from bosun.config import Settings
from pacto_bot_sdk import AgentEventParams, AgentRateLimitedParams


VALID_PUBKEY = "a" * 64


def _make_bot(monkeypatch, **kwargs):
    """Return the module-level bot instance with fresh test settings.

    The SDK's ``@bot.lock`` decorator binds the wrapped handler to the bot
    instance that was active at import time, so tests must exercise the
    module-level ``bot`` object. We use monkeypatch to swap in clean settings
    and reset per-test state so tests do not leak mutations.
    """
    settings = Settings(
        rpc_url="http://localhost:8545",
        bot_id="bosun",
        group_id="test-group",
        daemon_socket="/tmp/pacto-test.sock",
        **kwargs,
    )
    monkeypatch.setattr(bot, "settings", settings)
    monkeypatch.setattr(bot, "_handler_id", None)
    monkeypatch.setattr(bot, "_own_pubkeys", None)
    # Provide a fresh shutdown event tied to the current test loop.
    monkeypatch.setattr(bot, "_shutdown", asyncio.Event())
    return bot


@contextmanager
def _capture_handler_response(b):
    """Temporarily replace handler_response so tests can assert auto-acknowledge."""
    responses = []
    original = b._client.handler_response

    async def fake_handler_response(*args, **kwargs):
        responses.append((args, kwargs))

    b._client.handler_response = fake_handler_response
    try:
        yield responses
    finally:
        b._client.handler_response = original


class _FakeReader:
    """Returns a minimal SnapshotData without touching the network."""

    @classmethod
    def from_url(cls, *args, **kwargs):
        return cls()

    async def snapshot(self, *args, **kwargs):
        from bosun.types import CrewState, HatState, SnapshotData, SquadInfo, TreasuryBalance

        return SnapshotData(
            squad=SquadInfo(
                safe="0x1111111111111111111111111111111111111111",
                quartermaster="0x2222222222222222222222222222222222222222",
                mutiny_module="0x3333333333333333333333333333333333333333",
                treasury_authority="0x4444444444444444444444444444444444444444",
                squad_admin_proxy="0x5555555555555555555555555555555555555555",
                top_hat_id=1,
                captain_hat_id=2,
                crew_hat_id=3,
                squad_admin_hat_id=4,
                mutiny_role_hat_id=5,
                quartermaster_role_hat_id=6,
                treasury_authority_role_hat_id=7,
                deployed_at=1_700_000_000,
                deployer="0x6666666666666666666666666666666666666666",
            ),
            treasury=TreasuryBalance(eth_balance=0, tokens=[]),
            crew_state=CrewState(
                captain=HatState(wearer="", hat_id=2, active=False), crew=[]
            ),
            generated_at=1_700_000_000,
        )


class _FailingReader:
    @classmethod
    def from_url(cls, *args, **kwargs):
        return cls()

    async def snapshot(self, *args, **kwargs):
        raise RuntimeError("RPC down")


@pytest.mark.asyncio
async def test_snapshot_posts_group_message(monkeypatch):
    b = _make_bot(monkeypatch)
    sent = []

    async def fake_send(group_id, content):
        sent.append((group_id, content))
        return "snapshot-event-id"

    monkeypatch.setattr(b, "send_group_message", fake_send)
    monkeypatch.setattr("bosun.bosun.GovernanceReader", _FakeReader)

    result = await snapshot(b)
    assert result is not None
    assert len(sent) == 1
    assert sent[0][0] == "test-group"
    assert "# Pacto Governance Snapshot" in sent[0][1]


@pytest.mark.asyncio
async def test_snapshot_does_not_send_on_read_failure(monkeypatch):
    b = _make_bot(monkeypatch)
    sent = []

    async def fake_send(*args, **kwargs):
        sent.append(args)

    monkeypatch.setattr(b, "send_group_message", fake_send)
    monkeypatch.setattr("bosun.bosun.GovernanceReader", _FailingReader)

    result = await snapshot(b)
    assert result is None
    assert sent == []


@pytest.mark.asyncio
async def test_trigger_once_connects_and_posts(monkeypatch):
    b = _make_bot(monkeypatch)
    connected = []
    closed = []
    published = []
    sent = []

    async def fake_connect():
        connected.append(True)

    async def fake_close():
        closed.append(True)

    async def fake_publish(bot_id):
        published.append(bot_id)
        return "kp"

    async def fake_register(*args, **kwargs):
        return type(
            "RegisterResult",
            (),
            {
                "handler_id": "test-handler-id",
                "reconnect_token": "test-reconnect-token",
                "own_pubkeys": ["test-pubkey"],
                "registered_events": [],
            },
        )()

    async def fake_send(group_id, content):
        sent.append((group_id, content))
        return "msg"

    async def fake_register(**kwargs):
        return type("_Reg", (), {"handler_id": "hid-1", "reconnect_token": "rt-1"})()

    monkeypatch.setattr(b.client, "connect", fake_connect)
    monkeypatch.setattr(b.client, "close", fake_close)
    monkeypatch.setattr(b.client, "handler_register", fake_register)
    monkeypatch.setattr(b.client, "agent_publish_key_package", fake_publish)
    monkeypatch.setattr(b, "send_group_message", fake_send)
    monkeypatch.setattr("bosun.bosun.GovernanceReader", _FakeReader)

    code = await trigger_once(b)
    assert code == 0
    assert connected and closed
    assert published == ["bosun"]
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_trigger_once_exits_non_zero_on_send_failure(monkeypatch):
    b = _make_bot(monkeypatch)

    async def fake_connect():
        pass

    async def fake_close():
        pass

    async def fake_publish(bot_id):
        return "kp"

    async def fake_register(*args, **kwargs):
        return type(
            "RegisterResult",
            (),
            {
                "handler_id": "test-handler-id",
                "reconnect_token": "test-reconnect-token",
                "own_pubkeys": ["test-pubkey"],
                "registered_events": [],
            },
        )()

    async def fake_send(*args, **kwargs):
        raise RuntimeError("daemon error")

    async def fake_register(**kwargs):
        return type("_Reg", (), {"handler_id": "hid-1", "reconnect_token": "rt-1"})()

    monkeypatch.setattr(b.client, "connect", fake_connect)
    monkeypatch.setattr(b.client, "close", fake_close)
    monkeypatch.setattr(b.client, "handler_register", fake_register)
    monkeypatch.setattr(b.client, "agent_publish_key_package", fake_publish)
    monkeypatch.setattr(b, "send_group_message", fake_send)
    monkeypatch.setattr("bosun.bosun.GovernanceReader", _FakeReader)

    code = await trigger_once(b)
    assert code == 1


@pytest.mark.asyncio
async def test_cadence_loop_skips_when_not_registered(monkeypatch):
    from bosun.bosun import cadence_loop

    b = _make_bot()
    b.settings.cadence_seconds = 0.1
    snapshots = []

    async def fake_snapshot(bot):
        snapshots.append(True)

    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)
    # Do not set _handler_id, so cadence should skip.
    task = asyncio.create_task(cadence_loop(b))
    await asyncio.sleep(0.2)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert snapshots == []


@pytest.mark.asyncio
async def test_cadence_loop_exits_on_shutdown(monkeypatch):
    """cadence_loop returns promptly when the SDK's shutdown event is set."""
    from bosun.bosun import cadence_loop

    b = _make_bot()
    b.settings.cadence_seconds = 10.0  # long sleep that we should not wait for

    async def fake_snapshot(bot):
        return None

    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)
    b._handler_id = "registered"

    task = asyncio.create_task(cadence_loop(b))
    # Give the loop time to start its first tick, then signal shutdown.
    await asyncio.sleep(0.05)
    b._shutdown.set()

    await task
    assert True


def test_bosunbot_registers_with_group_message_capabilities():
    b = _make_bot()
    assert "ReadMessages" in b.capabilities
    assert "SendMessages" in b.capabilities
    assert "SendGroupMessages" in b.capabilities
    assert "ReceiveGroupMessages" in b.capabilities
    assert "dm_received" in b.event_types
    assert "mls_group_message_received" in b.event_types


class _FakeEvent(AgentEventParams):
    """Convenience model with sensible defaults for tests."""

    def __init__(self, **kwargs):
        defaults = {
            "author": VALID_PUBKEY,
            "bot_id": "bosun",
            "chat_id": None,
            "content": "",
            "event_id": "evt-1",
            "rumor_id": "rumor-1",
            "timestamp": 0,
            "type": "mls_group_message_received",
        }
        defaults.update(kwargs)
        super().__init__(**defaults)


@pytest.mark.asyncio
async def test_mls_group_message_snapshot_triggers_snapshot(monkeypatch):
    b = _make_bot(monkeypatch)
    calls = []

    async def fake_snapshot(bot, group_id=None):
        calls.append((bot, group_id))

    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)

    event = _FakeEvent(content="!snapshot", chat_id="group-123")
    with _capture_handler_response(b) as responses:
        await b._handle_event(event)

    assert calls == [(b, "group-123")]
    assert len(responses) == 1
    assert responses[0][1].get("action") == "ignore"
    assert responses[0][1].get("event_id") == event.event_id


@pytest.mark.asyncio
async def test_mls_group_message_non_snapshot_ignored(monkeypatch):
    b = _make_bot(monkeypatch)
    calls = []

    async def fake_snapshot(bot, group_id=None):
        calls.append((bot, group_id))

    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)

    event = _FakeEvent(content="hello", chat_id="group-123")
    with _capture_handler_response(b) as responses:
        await b._handle_event(event)

    assert calls == []
    assert len(responses) == 1
    assert responses[0][1].get("action") == "ignore"


@pytest.mark.asyncio
async def test_mls_group_message_missing_chat_id_logs_warning(monkeypatch):
    b = _make_bot(monkeypatch)
    logs = []
    monkeypatch.setattr(b, "log", lambda msg: logs.append(msg))

    calls = []

    async def fake_snapshot(bot, group_id=None):
        calls.append((bot, group_id))

    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)

    event = _FakeEvent(content="!snapshot", chat_id=None)
    with _capture_handler_response(b) as responses:
        await b._handle_event(event)

    assert calls == []
    assert any("without chat_id" in msg for msg in logs)
    assert len(responses) == 1
    assert responses[0][1].get("action") == "ignore"


@pytest.mark.asyncio
async def test_mls_group_message_snapshot_error_does_not_propagate(monkeypatch):
    b = _make_bot(monkeypatch)

    async def fake_snapshot(bot, group_id=None):
        raise RuntimeError("snapshot failed")

    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)

    event = _FakeEvent(content="!snapshot", chat_id="group-123")
    # Should not raise even though snapshot() raises.
    with _capture_handler_response(b) as responses:
        await b._handle_event(event)

    assert len(responses) == 1
    assert responses[0][1].get("action") == "ignore"


@pytest.mark.asyncio
async def test_mls_group_message_ignores_own_pubkey(monkeypatch):
    b = _make_bot(monkeypatch)
    calls = []

    async def fake_snapshot(bot, group_id=None):
        calls.append((bot, group_id))

    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)
    b._own_pubkeys = {"bosun": VALID_PUBKEY}

    event = _FakeEvent(content="!snapshot", chat_id="group-123", author=VALID_PUBKEY)
    with _capture_handler_response(b) as responses:
        await b._handle_event(event)

    assert calls == []
    assert len(responses) == 1
    assert responses[0][1].get("action") == "ignore"


@pytest.mark.asyncio
async def test_rate_limited_notification_sends_message(monkeypatch):
    b = _make_bot(monkeypatch)
    sent = []
    snapshot_calls = []

    async def fake_send(group_id, content):
        sent.append((group_id, content))

    async def fake_snapshot(bot, group_id=None):
        snapshot_calls.append((bot, group_id))

    monkeypatch.setattr(b, "send_group_message", fake_send)
    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)

    notification = AgentRateLimitedParams(
        bot_id="bosun", group_id="squad-1", window_seconds=60
    )
    await b._handle_rate_limited(notification)

    assert len(sent) == 1
    assert sent[0][0] == "squad-1"
    assert "Rate limit" in sent[0][1]
    assert "60" in sent[0][1]
    assert snapshot_calls == []


@pytest.mark.asyncio
async def test_rate_limited_missing_group_id_logs_warning(monkeypatch):
    b = _make_bot(monkeypatch)
    sent = []
    logs = []

    async def fake_send(*args, **kwargs):
        sent.append(args)

    monkeypatch.setattr(b, "send_group_message", fake_send)
    monkeypatch.setattr(b, "log", lambda msg: logs.append(msg))

    await b._handle_rate_limited(
        AgentRateLimitedParams(bot_id="bosun", group_id="", window_seconds=60)
    )
    assert sent == []
    assert any("without group_id" in msg for msg in logs)


@pytest.mark.asyncio
async def test_rate_limited_defaults_window_seconds(monkeypatch):
    b = _make_bot(monkeypatch)
    sent = []

    async def fake_send(group_id, content):
        sent.append(content)

    monkeypatch.setattr(b, "send_group_message", fake_send)

    # Create a notification without window_seconds to exercise the default.
    notification = AgentRateLimitedParams.model_construct(
        bot_id="bosun", group_id="squad-1"
    )
    await b._handle_rate_limited(notification)
    assert sent and "~60 seconds" in sent[0]


@pytest.mark.asyncio
async def test_is_squad_member_returns_true(monkeypatch):
    b = _make_bot(monkeypatch)
    calls = []

    async def fake_check(group_id, member_pubkey):
        calls.append((group_id, member_pubkey))
        return True

    monkeypatch.setattr(b, "is_squad_member", fake_check)
    result = await is_squad_member(b, "group-123", VALID_PUBKEY)
    assert result is True
    assert calls == [("group-123", VALID_PUBKEY)]


@pytest.mark.asyncio
async def test_is_squad_member_returns_false(monkeypatch):
    b = _make_bot(monkeypatch)

    async def fake_check(*args, **kwargs):
        return False

    monkeypatch.setattr(b, "is_squad_member", fake_check)
    result = await is_squad_member(b, "group-123", VALID_PUBKEY)
    assert result is False


@pytest.mark.asyncio
async def test_dm_snapshot_with_squad_id_verifies_membership(monkeypatch):
    b = _make_bot(monkeypatch)
    checks = []
    snapshots = []

    async def fake_is_squad_member(group_id, member_pubkey):
        checks.append((group_id, member_pubkey))
        return True

    async def fake_snapshot(bot, group_id=None):
        snapshots.append((bot, group_id))

    monkeypatch.setattr(b, "is_squad_member", fake_is_squad_member)
    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)

    event = _FakeEvent(
        type="dm_received", content="!snapshot group-123", chat_id="dm-chat-id"
    )
    with _capture_handler_response(b) as responses:
        await b._handle_event(event)

    assert checks == [("group-123", VALID_PUBKEY)]
    assert snapshots == [(b, "group-123")]
    assert len(responses) == 1
    assert responses[0][1].get("action") == "ignore"


@pytest.mark.asyncio
async def test_dm_snapshot_with_squad_id_not_member(monkeypatch):
    b = _make_bot(monkeypatch)
    snapshots = []
    logs = []

    async def fake_is_squad_member(*args, **kwargs):
        return False

    async def fake_snapshot(bot, group_id=None):
        snapshots.append((bot, group_id))

    monkeypatch.setattr(b, "is_squad_member", fake_is_squad_member)
    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)
    monkeypatch.setattr(b, "log", lambda msg: logs.append(msg))

    event = _FakeEvent(
        type="dm_received", content="!snapshot group-123", chat_id="dm-chat-id"
    )
    with _capture_handler_response(b) as responses:
        await b._handle_event(event)

    assert snapshots == []
    assert any("not a member" in msg for msg in logs)
    assert len(responses) == 1
    assert responses[0][1].get("action") == "ignore"


@pytest.mark.asyncio
async def test_dm_snapshot_membership_error_logs_warning(monkeypatch):
    b = _make_bot(monkeypatch)
    snapshots = []
    logs = []

    async def fake_is_squad_member(*args, **kwargs):
        raise RuntimeError("RPC error")

    async def fake_snapshot(bot, group_id=None):
        snapshots.append((bot, group_id))

    monkeypatch.setattr(b, "is_squad_member", fake_is_squad_member)
    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)
    monkeypatch.setattr(b, "log", lambda msg: logs.append(msg))

    event = _FakeEvent(
        type="dm_received", content="!snapshot group-123", chat_id="dm-chat-id"
    )
    with _capture_handler_response(b) as responses:
        await b._handle_event(event)

    assert snapshots == []
    assert any("membership check failed" in msg for msg in logs)
    assert len(responses) == 1
    assert responses[0][1].get("action") == "ignore"


@pytest.mark.asyncio
async def test_dm_snapshot_without_squad_id_falls_through(monkeypatch):
    b = _make_bot(monkeypatch)
    snapshots = []

    async def fake_snapshot(bot, group_id=None):
        snapshots.append((bot, group_id))

    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)

    event = _FakeEvent(
        type="dm_received", content="!snapshot", chat_id="dm-chat-id"
    )
    with _capture_handler_response(b) as responses:
        await b._handle_event(event)

    assert snapshots == []
    assert len(responses) == 1
    assert responses[0][1].get("action") == "ignore"


@pytest.mark.asyncio
async def test_dm_snapshot_invalid_pubkey_logs_warning(monkeypatch):
    b = _make_bot(monkeypatch)
    logs = []
    monkeypatch.setattr(b, "log", lambda msg: logs.append(msg))

    event = _FakeEvent(
        type="dm_received", content="!snapshot group-123", chat_id="dm-chat-id", author="bad-pubkey"
    )
    with _capture_handler_response(b) as responses:
        await b._handle_event(event)

    assert any("invalid DM snapshot request" in msg for msg in logs)
    assert len(responses) == 1
    assert responses[0][1].get("action") == "ignore"


@pytest.mark.asyncio
async def test_snapshot_empty_group_id_skips_send(monkeypatch):
    b = _make_bot(monkeypatch)
    sent = []
    logs = []

    async def fake_send(*args, **kwargs):
        sent.append(args)

    monkeypatch.setattr(b, "send_group_message", fake_send)
    monkeypatch.setattr(b, "log", lambda msg: logs.append(msg))
    monkeypatch.setattr("bosun.bosun.GovernanceReader", _FakeReader)

    result = await snapshot(b, group_id="")
    assert result is None
    assert sent == []
    assert any("empty group_id" in msg for msg in logs)


@pytest.mark.asyncio
async def test_snapshot_empty_group_id_none_destination(monkeypatch):
    b = _make_bot(monkeypatch)
    b.settings.group_id = ""
    sent = []

    async def fake_send(*args, **kwargs):
        sent.append(args)

    monkeypatch.setattr(b, "send_group_message", fake_send)
    monkeypatch.setattr("bosun.bosun.GovernanceReader", _FakeReader)

    result = await snapshot(b)
    assert result is None
    assert sent == []


@pytest.mark.asyncio
async def test_dm_snapshot_loose_prefix_ignored(monkeypatch):
    b = _make_bot(monkeypatch)
    snapshots = []

    async def fake_snapshot(bot, group_id=None):
        snapshots.append((bot, group_id))

    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)

    event = _FakeEvent(type="dm_received", content="!snapshotfoo", chat_id="dm-chat-id")
    with _capture_handler_response(b) as responses:
        await b._handle_event(event)

    assert snapshots == []
    assert len(responses) == 1
    assert responses[0][1].get("action") == "ignore"


@pytest.mark.asyncio
async def test_dm_snapshot_extra_spaces(monkeypatch):
    b = _make_bot(monkeypatch)
    snapshots = []

    async def fake_is_squad_member(*args, **kwargs):
        return True

    async def fake_snapshot(bot, group_id=None):
        snapshots.append((bot, group_id))

    monkeypatch.setattr(b, "is_squad_member", fake_is_squad_member)
    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)

    event = _FakeEvent(type="dm_received", content="!snapshot  group-123", chat_id="dm-chat-id")
    with _capture_handler_response(b) as responses:
        await b._handle_event(event)

    assert snapshots == [(b, "group-123")]


@pytest.mark.asyncio
async def test_rate_limited_window_zero_clamped(monkeypatch):
    b = _make_bot(monkeypatch)
    sent = []

    async def fake_send(group_id, content):
        sent.append(content)

    monkeypatch.setattr(b, "send_group_message", fake_send)

    await b._handle_rate_limited(
        AgentRateLimitedParams(bot_id="bosun", group_id="squad-1", window_seconds=0)
    )
    assert sent and "~1 second" in sent[0]


@pytest.mark.asyncio
async def test_rate_limited_window_negative_clamped(monkeypatch):
    b = _make_bot(monkeypatch)
    sent = []

    async def fake_send(group_id, content):
        sent.append(content)

    monkeypatch.setattr(b, "send_group_message", fake_send)

    await b._handle_rate_limited(
        AgentRateLimitedParams(bot_id="bosun", group_id="squad-1", window_seconds=-10)
    )
    assert sent and "~1 second" in sent[0]


@pytest.mark.asyncio
async def test_dm_snapshot_slash_command_still_works(monkeypatch):
    snapshots = []

    async def fake_snapshot(bot, group_id=None):
        snapshots.append((bot, group_id))

    b = _make_bot(monkeypatch)
    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)

    event = _FakeEvent(type="dm_received", content="/snapshot", chat_id="dm-chat-id")
    with _capture_handler_response(b) as responses:
        await b._handle_event(event)

    assert len(snapshots) == 1
    assert snapshots[0][1] is None
    assert len(responses) == 1
    assert responses[0][1].get("action") == "reply"
    assert "Snapshot posted" in responses[0][1].get("content", "")
