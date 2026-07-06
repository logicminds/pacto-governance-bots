"""Unit tests for the bosun bot wiring, cadence, and trigger modes."""

from __future__ import annotations

import asyncio

import pytest

from bosun import BosunBot, setup, snapshot, trigger_once
from bosun.config import Settings


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
async def test_setup_publishes_key_package(monkeypatch):
    b = _make_bot()
    calls = []

    async def fake_publish(bot_id):
        calls.append(bot_id)
        return "keypackage-event-id"

    monkeypatch.setattr(b.client, "agent_publish_key_package", fake_publish)
    await setup(b)
    assert calls == ["bosun"]


@pytest.mark.asyncio
async def test_setup_continues_on_error(monkeypatch):
    b = _make_bot()

    async def fake_publish(_bot_id):
        raise RuntimeError("daemon refused")

    monkeypatch.setattr(b.client, "agent_publish_key_package", fake_publish)
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
