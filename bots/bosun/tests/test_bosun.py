"""Unit tests for the bosun bot wiring, cadence, trigger modes, and inbound
``!snapshot`` event handlers.

Slash-command tests for ``/snapshot`` live in ``test_handlers.py``.
"""

from __future__ import annotations

import asyncio

import pytest

from bosun import BosunBot, is_squad_member, setup, snapshot, trigger_once, bot
from bosun.config import Settings
from pacto_bot_sdk import AgentEventParams, AgentRateLimitedParams, AgentIsSquadMemberResponse


def _make_bot(**kwargs):
    settings = Settings(
        rpc_url="http://localhost:8545",
        bot_id="bosun",
        group_id="test-group",
        daemon_socket="/tmp/pacto-test.sock",
        **kwargs,
    )
    return BosunBot(settings=settings, transport="unix", socket_path="/tmp/pacto-test.sock")


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
async def test_setup_connects_and_publishes_key_package(monkeypatch):
    b = _make_bot()
    calls = []
    connected = []

    async def fake_connect():
        connected.append(True)

    async def fake_publish(bot_id):
        calls.append(bot_id)
        return "keypackage-event-id"

    monkeypatch.setattr(b.client, "connect", fake_connect)
    monkeypatch.setattr(b.client, "agent_publish_key_package", fake_publish)
    await setup(b)
    assert connected
    assert calls == ["bosun"]


@pytest.mark.asyncio
async def test_setup_continues_on_error(monkeypatch):
    b = _make_bot()

    async def fake_connect():
        raise RuntimeError("daemon refused")

    monkeypatch.setattr(b.client, "connect", fake_connect)
    # Should not raise.
    await setup(b)


@pytest.mark.asyncio
async def test_snapshot_posts_group_message(monkeypatch):
    b = _make_bot()
    sent = []

    async def fake_send(bot_id, content, group_id):
        sent.append((bot_id, group_id, content))
        return "snapshot-event-id"

    monkeypatch.setattr(b.client, "agent_send_group_message", fake_send)
    monkeypatch.setattr("bosun.bosun.GovernanceReader", _FakeReader)

    result = await snapshot(b)
    assert result is not None
    assert len(sent) == 1
    assert sent[0][0] == "bosun"
    assert sent[0][1] == "test-group"
    assert "# Pacto Governance Snapshot" in sent[0][2]


@pytest.mark.asyncio
async def test_snapshot_does_not_send_on_read_failure(monkeypatch):
    b = _make_bot()
    sent = []

    async def fake_send(*args, **kwargs):
        sent.append(args)

    monkeypatch.setattr(b.client, "agent_send_group_message", fake_send)
    monkeypatch.setattr("bosun.bosun.GovernanceReader", _FailingReader)

    result = await snapshot(b)
    assert result is None
    assert sent == []


@pytest.mark.asyncio
async def test_trigger_once_connects_and_posts(monkeypatch):
    b = _make_bot()
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

    async def fake_send(bot_id, content, group_id):
        sent.append((bot_id, group_id, content))
        return "msg"

    monkeypatch.setattr(b.client, "connect", fake_connect)
    monkeypatch.setattr(b.client, "close", fake_close)
    monkeypatch.setattr(b.client, "agent_publish_key_package", fake_publish)
    monkeypatch.setattr(b.client, "agent_send_group_message", fake_send)
    monkeypatch.setattr("bosun.bosun.GovernanceReader", _FakeReader)

    code = await trigger_once(b)
    assert code == 0
    assert connected and closed
    assert published == ["bosun"]
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_trigger_once_exits_non_zero_on_send_failure(monkeypatch):
    b = _make_bot()

    async def fake_connect():
        pass

    async def fake_close():
        pass

    async def fake_publish(bot_id):
        return "kp"

    async def fake_send(*args, **kwargs):
        raise RuntimeError("daemon error")

    monkeypatch.setattr(b.client, "connect", fake_connect)
    monkeypatch.setattr(b.client, "close", fake_close)
    monkeypatch.setattr(b.client, "agent_publish_key_package", fake_publish)
    monkeypatch.setattr(b.client, "agent_send_group_message", fake_send)
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
    assert "SendGroupMessages" in b.capabilities
    assert "ReceiveGroupMessages" in b.capabilities
    assert "dm_received" in b.event_types
    assert "mls_group_message_received" in b.event_types


class _FakeEvent(AgentEventParams):
    """Convenience model with sensible defaults for tests."""

    def __init__(self, **kwargs):
        defaults = {
            "author": "author-pubkey",
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
    b = _make_bot()
    calls = []

    async def fake_snapshot(bot, group_id=None):
        calls.append((bot, group_id))

    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)

    event = _FakeEvent(content="!snapshot", chat_id="group-123")
    await b._handle_event(event)
    assert calls == [(b, "group-123")]


@pytest.mark.asyncio
async def test_mls_group_message_non_snapshot_ignored(monkeypatch):
    b = _make_bot()
    calls = []

    async def fake_snapshot(bot, group_id=None):
        calls.append((bot, group_id))

    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)

    event = _FakeEvent(content="hello", chat_id="group-123")
    await b._handle_event(event)
    assert calls == []


@pytest.mark.asyncio
async def test_mls_group_message_missing_chat_id_logs_warning(monkeypatch):
    b = _make_bot()
    logs = []
    monkeypatch.setattr(b, "log", lambda msg: logs.append(msg))

    calls = []

    async def fake_snapshot(bot, group_id=None):
        calls.append((bot, group_id))

    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)

    event = _FakeEvent(content="!snapshot", chat_id=None)
    await b._handle_event(event)
    assert calls == []
    assert any("without chat_id" in msg for msg in logs)


@pytest.mark.asyncio
async def test_mls_group_message_snapshot_error_does_not_propagate(monkeypatch):
    b = _make_bot()

    async def fake_snapshot(bot, group_id=None):
        raise RuntimeError("snapshot failed")

    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)

    event = _FakeEvent(content="!snapshot", chat_id="group-123")
    # Should not raise even though snapshot() raises.
    await b._handle_event(event)


@pytest.mark.asyncio
async def test_rate_limited_notification_sends_message(monkeypatch):
    b = _make_bot()
    sent = []
    snapshot_calls = []

    async def fake_send(bot_id, content, group_id):
        sent.append((bot_id, group_id, content))

    async def fake_snapshot(bot, group_id=None):
        snapshot_calls.append((bot, group_id))

    monkeypatch.setattr(b.client, "agent_send_group_message", fake_send)
    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)

    async def fake_notifications():
        yield AgentRateLimitedParams(
            bot_id="bosun", group_id="squad-1", window_seconds=60
        )
        await asyncio.Event().wait()

    monkeypatch.setattr(b._client, "notifications", fake_notifications)

    task = asyncio.create_task(b._dispatch_loop())
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(sent) == 1
    assert sent[0][0] == "bosun"
    assert sent[0][1] == "squad-1"
    assert "Rate limit" in sent[0][2]
    assert "60" in sent[0][2]
    assert snapshot_calls == []


@pytest.mark.asyncio
async def test_rate_limited_missing_group_id_logs_warning(monkeypatch):
    b = _make_bot()
    sent = []
    logs = []

    async def fake_send(*args, **kwargs):
        sent.append(args)

    monkeypatch.setattr(b.client, "agent_send_group_message", fake_send)
    monkeypatch.setattr(b, "log", lambda msg: logs.append(msg))

    await b._handle_rate_limited(
        AgentRateLimitedParams(bot_id="bosun", group_id="", window_seconds=60)
    )
    assert sent == []
    assert any("without group_id" in msg for msg in logs)


@pytest.mark.asyncio
async def test_rate_limited_defaults_window_seconds(monkeypatch):
    b = _make_bot()
    sent = []

    async def fake_send(bot_id, content, group_id):
        sent.append(content)

    monkeypatch.setattr(b.client, "agent_send_group_message", fake_send)

    # Create a notification without window_seconds to exercise the default.
    notification = AgentRateLimitedParams.model_construct(
        bot_id="bosun", group_id="squad-1"
    )
    await b._handle_rate_limited(notification)
    assert sent and "~60 seconds" in sent[0]


@pytest.mark.asyncio
async def test_is_squad_member_returns_true(monkeypatch):
    b = _make_bot()
    calls = []

    async def fake_check(bot_id, group_id, member_pubkey):
        calls.append((bot_id, group_id, member_pubkey))
        return AgentIsSquadMemberResponse(is_member=True)

    monkeypatch.setattr(b.client, "agent_is_squad_member", fake_check)
    result = await is_squad_member(b, "group-123", "author-pubkey")
    assert result is True
    assert calls == [("bosun", "group-123", "author-pubkey")]


@pytest.mark.asyncio
async def test_is_squad_member_returns_false(monkeypatch):
    b = _make_bot()

    async def fake_check(*args, **kwargs):
        return AgentIsSquadMemberResponse(is_member=False)

    monkeypatch.setattr(b.client, "agent_is_squad_member", fake_check)
    result = await is_squad_member(b, "group-123", "author-pubkey")
    assert result is False


@pytest.mark.asyncio
async def test_dm_snapshot_with_squad_id_verifies_membership(monkeypatch):
    b = _make_bot()
    checks = []
    snapshots = []

    async def fake_is_squad_member(bot_id, group_id, member_pubkey):
        checks.append((bot_id, group_id, member_pubkey))
        return AgentIsSquadMemberResponse(is_member=True)

    async def fake_snapshot(bot, group_id=None):
        snapshots.append((bot, group_id))

    monkeypatch.setattr(b.client, "agent_is_squad_member", fake_is_squad_member)
    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)

    event = _FakeEvent(
        type="dm_received", content="!snapshot group-123", chat_id="dm-chat-id"
    )
    await b._handle_event(event)
    assert checks == [("bosun", "group-123", "author-pubkey")]
    assert snapshots == [(b, "group-123")]


@pytest.mark.asyncio
async def test_dm_snapshot_with_squad_id_not_member(monkeypatch):
    b = _make_bot()
    snapshots = []
    logs = []

    async def fake_is_squad_member(*args, **kwargs):
        return AgentIsSquadMemberResponse(is_member=False)

    async def fake_snapshot(bot, group_id=None):
        snapshots.append((bot, group_id))

    monkeypatch.setattr(b.client, "agent_is_squad_member", fake_is_squad_member)
    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)
    monkeypatch.setattr(b, "log", lambda msg: logs.append(msg))

    event = _FakeEvent(
        type="dm_received", content="!snapshot group-123", chat_id="dm-chat-id"
    )
    await b._handle_event(event)
    assert snapshots == []
    assert any("not a member" in msg for msg in logs)


@pytest.mark.asyncio
async def test_dm_snapshot_membership_error_logs_warning(monkeypatch):
    b = _make_bot()
    snapshots = []
    logs = []

    async def fake_is_squad_member(*args, **kwargs):
        raise RuntimeError("RPC error")

    async def fake_snapshot(bot, group_id=None):
        snapshots.append((bot, group_id))

    monkeypatch.setattr(b.client, "agent_is_squad_member", fake_is_squad_member)
    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)
    monkeypatch.setattr(b, "log", lambda msg: logs.append(msg))

    event = _FakeEvent(
        type="dm_received", content="!snapshot group-123", chat_id="dm-chat-id"
    )
    await b._handle_event(event)
    assert snapshots == []
    assert any("membership check failed" in msg for msg in logs)


@pytest.mark.asyncio
async def test_dm_snapshot_without_squad_id_falls_through(monkeypatch):
    b = _make_bot()
    snapshots = []
    responses = []

    async def fake_snapshot(bot, group_id=None):
        snapshots.append((bot, group_id))

    async def fake_handler_response(*args, **kwargs):
        responses.append((args, kwargs))

    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)
    monkeypatch.setattr(b.client, "handler_response", fake_handler_response)

    event = _FakeEvent(
        type="dm_received", content="!snapshot", chat_id="dm-chat-id"
    )
    await b._handle_event(event)
    assert snapshots == []
    assert len(responses) == 1
    assert responses[0][1].get("action") == "ignore"


@pytest.mark.asyncio
async def test_snapshot_empty_group_id_skips_send(monkeypatch):
    b = _make_bot()
    sent = []
    logs = []

    async def fake_send(*args, **kwargs):
        sent.append(args)

    monkeypatch.setattr(b.client, "agent_send_group_message", fake_send)
    monkeypatch.setattr(b, "log", lambda msg: logs.append(msg))
    monkeypatch.setattr("bosun.bosun.GovernanceReader", _FakeReader)

    result = await snapshot(b, group_id="")
    assert result is None
    assert sent == []
    assert any("empty group_id" in msg for msg in logs)


@pytest.mark.asyncio
async def test_snapshot_empty_group_id_none_destination(monkeypatch):
    b = _make_bot()
    b.settings.group_id = ""
    sent = []

    async def fake_send(*args, **kwargs):
        sent.append(args)

    monkeypatch.setattr(b.client, "agent_send_group_message", fake_send)
    monkeypatch.setattr("bosun.bosun.GovernanceReader", _FakeReader)

    result = await snapshot(b)
    assert result is None
    assert sent == []


@pytest.mark.asyncio
async def test_mls_group_message_acknowledges_event(monkeypatch):
    b = _make_bot()
    responses = []
    calls = []

    async def fake_handler_response(*args, **kwargs):
        responses.append((args, kwargs))

    async def fake_snapshot(bot, group_id=None):
        calls.append((bot, group_id))

    monkeypatch.setattr(b.client, "handler_response", fake_handler_response)
    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)

    event = _FakeEvent(content="!snapshot", chat_id="group-123")
    await b._handle_event(event)
    assert len(responses) == 1
    assert responses[0][1].get("action") == "ignore"
    assert responses[0][1].get("event_id") == event.event_id


@pytest.mark.asyncio
async def test_dm_snapshot_acknowledges_event(monkeypatch):
    b = _make_bot()
    responses = []

    async def fake_handler_response(*args, **kwargs):
        responses.append((args, kwargs))

    async def fake_is_squad_member(*args, **kwargs):
        return AgentIsSquadMemberResponse(is_member=True)

    monkeypatch.setattr(b.client, "handler_response", fake_handler_response)
    monkeypatch.setattr(b.client, "agent_is_squad_member", fake_is_squad_member)
    monkeypatch.setattr("bosun.bosun.snapshot", lambda *args, **kwargs: None)

    event = _FakeEvent(type="dm_received", content="!snapshot group-123", chat_id="dm-chat-id")
    await b._handle_event(event)
    assert len(responses) == 1
    assert responses[0][1].get("action") == "ignore"
    assert responses[0][1].get("event_id") == event.event_id


@pytest.mark.asyncio
async def test_dm_snapshot_loose_prefix_ignored(monkeypatch):
    b = _make_bot()
    snapshots = []
    responses = []

    async def fake_snapshot(bot, group_id=None):
        snapshots.append((bot, group_id))

    async def fake_handler_response(*args, **kwargs):
        responses.append((args, kwargs))

    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)
    monkeypatch.setattr(b.client, "handler_response", fake_handler_response)

    event = _FakeEvent(type="dm_received", content="!snapshotfoo", chat_id="dm-chat-id")
    await b._handle_event(event)
    assert snapshots == []
    assert len(responses) == 1
    assert responses[0][1].get("action") == "ignore"


@pytest.mark.asyncio
async def test_dm_snapshot_extra_spaces(monkeypatch):
    b = _make_bot()
    snapshots = []

    async def fake_is_squad_member(*args, **kwargs):
        return AgentIsSquadMemberResponse(is_member=True)

    async def fake_snapshot(bot, group_id=None):
        snapshots.append((bot, group_id))

    monkeypatch.setattr(b.client, "agent_is_squad_member", fake_is_squad_member)
    monkeypatch.setattr(b.client, "handler_response", lambda *args, **kwargs: None)
    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)

    event = _FakeEvent(type="dm_received", content="!snapshot  group-123", chat_id="dm-chat-id")
    await b._handle_event(event)
    assert snapshots == [(b, "group-123")]


@pytest.mark.asyncio
async def test_dm_snapshot_rate_limit_blocked(monkeypatch):
    b = _make_bot()
    snapshots = []
    logs = []

    async def fake_is_squad_member(*args, **kwargs):
        return AgentIsSquadMemberResponse(is_member=True)

    async def fake_snapshot(bot, group_id=None):
        snapshots.append((bot, group_id))

    monkeypatch.setattr(b.client, "agent_is_squad_member", fake_is_squad_member)
    monkeypatch.setattr(b.client, "handler_response", lambda *args, **kwargs: None)
    monkeypatch.setattr(b, "log", lambda msg: logs.append(msg))
    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)

    event = _FakeEvent(type="dm_received", content="!snapshot group-123", chat_id="dm-chat-id")
    await b._handle_event(event)
    assert snapshots == [(b, "group-123")]

    # Second request within the rate-limit window should be ignored.
    await b._handle_event(event)
    assert snapshots == [(b, "group-123")]
    assert any("rate-limiting" in msg for msg in logs)


@pytest.mark.asyncio
async def test_rate_limited_window_zero_clamped(monkeypatch):
    b = _make_bot()
    sent = []

    async def fake_send(bot_id, content, group_id):
        sent.append(content)

    monkeypatch.setattr(b.client, "agent_send_group_message", fake_send)

    await b._handle_rate_limited(
        AgentRateLimitedParams(bot_id="bosun", group_id="squad-1", window_seconds=0)
    )
    assert sent and "~1 second" in sent[0]


@pytest.mark.asyncio
async def test_rate_limited_window_negative_clamped(monkeypatch):
    b = _make_bot()
    sent = []

    async def fake_send(bot_id, content, group_id):
        sent.append(content)

    monkeypatch.setattr(b.client, "agent_send_group_message", fake_send)

    await b._handle_rate_limited(
        AgentRateLimitedParams(bot_id="bosun", group_id="squad-1", window_seconds=-10)
    )
    assert sent and "~1 second" in sent[0]


@pytest.mark.asyncio
async def test_dm_snapshot_slash_command_still_works(monkeypatch):
    snapshots = []
    responses = []

    async def fake_snapshot(bot, group_id=None):
        snapshots.append((bot, group_id))

    async def fake_handler_response(*args, **kwargs):
        responses.append((args, kwargs))

    b = _make_bot()
    # Copy the module-level command/default registrations so the test is
    # isolated from the global bot instance and environment variables.
    b._commands = dict(bot._commands)
    b._default_handler = bot._default_handler

    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)
    monkeypatch.setattr(b.client, "handler_response", fake_handler_response)

    event = _FakeEvent(type="dm_received", content="/snapshot", chat_id="dm-chat-id")
    await b._handle_event(event)
    assert len(snapshots) == 1
    assert snapshots[0][1] is None
    assert len(responses) == 1
    assert responses[0][1].get("action") == "reply"
