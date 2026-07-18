"""Unit tests for the bosun default slash handler fallback.

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
async def test_version_command_registered():
    assert "version" in bot._commands


@pytest.mark.asyncio
async def test_version_command_replies():
    event = FakeEvent()
    event.content = "/version"
    handler = bot._commands["version"]
    result = await handler(event, bot)
    assert result["action"] == "reply"
    assert result["event_id"] == event.event_id
    assert result["content"].startswith("bosun v")
    assert "(commit" in result["content"]


@pytest.mark.asyncio
async def test_info_command_alias_replies():
    event = FakeEvent()
    event.content = "/info"
    handler = bot._commands["info"]
    result = await handler(event, bot)
    assert result["action"] == "reply"
    assert result["event_id"] == event.event_id
    assert result["content"].startswith("bosun v")
    assert "(commit" in result["content"]


