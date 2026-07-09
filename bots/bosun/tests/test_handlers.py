"""Unit tests for the bosun ``/snapshot`` slash handler and default fallback.

Inbound ``!snapshot`` event tests (group message and DM) live in
``test_bosun.py``.
"""

from __future__ import annotations

import pytest

from bosun import bot


class FakeEvent:
    event_id = "test-event-id-123"
    content = ""


@pytest.mark.asyncio
async def test_default_handler_ignores():
    result = await bot._default_handler(FakeEvent(), bot)
    assert result == {"event_id": "test-event-id-123", "action": "ignore"}


@pytest.mark.asyncio
async def test_snapshot_command_registered():
    assert "snapshot" in bot._commands


@pytest.mark.asyncio
async def test_snapshot_command_replies(monkeypatch):
    calls = []

    async def fake_snapshot(b, group_id=None):
        calls.append(b)

    monkeypatch.setattr("bosun.bosun.snapshot", fake_snapshot)

    event = FakeEvent()
    event.content = "/snapshot"
    handler = bot._commands["snapshot"]
    result = await handler(event, bot)

    assert result["action"] == "reply"
    assert result["event_id"] == event.event_id
    assert "Snapshot posted" in result["content"]
    assert calls == [bot]
