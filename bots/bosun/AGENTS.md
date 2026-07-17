# Agent Instructions for bosun

This file guides AI assistants working on the `bosun` bot handler.

## Bot overview

`bots/bosun/bosun.py` is a Pacto bot handler built on the
`pacto_bot_sdk` SDK. It connects to the `pacto-bot-api` daemon and responds to
incoming events.

## Capabilities

Check `pacto-bot-api.toml` (project root) for the configured capabilities for
this bot. Common capabilities:

- `ReadMessages` — receive decrypted DMs and group messages
- `SendMessages` — send replies as the bot
- `SendGroupMessages` — post messages to MLS Squad channels
- `ReceiveGroupMessages` — receive inbound MLS group messages
- `ManageProfile` — update the bot's kind:0 profile

## SDK reference

The bot depends on the `pacto-bot-sdk` package installed from
`git+https://github.com/covenant-gov/pacto-bot-api.git#subdirectory=python`.
Use the `python-pacto-bot` skill for the SDK API and patterns.

Relevant decorators and helpers for this handler:

- `@bot.event("mls_group_message_received")` — handle inbound MLS group messages.
- `@bot.hears("!snapshot")` — handle DM messages containing `!snapshot` (the handler
  also guards on `event.type == "dm_received"` so it does not fire on group messages).
- `@bot.rate_limited` — handle daemon rate-limit notifications.
- `@bot.lock("snapshot")` — serialize concurrent snapshot executions.
- `bot.send_group_message(group_id, content)` — post a message to a Squad channel.
- `bot.is_squad_member(group_id, member_pubkey)` — check Squad membership.
- `bot.own_pubkey` — the bot's own public key (may be `None` on older daemons).


## How to modify this bot

1. Read the `python-pacto-bot` skill for the SDK API and patterns.
2. Open `bots/bosun/bosun.py`.
3. Use `@bot.command("/name")` to add slash commands or edit existing handlers.
4. Keep `@bot.default` for unrecognized commands.
5. Run tests:
   ```bash
   cd bots/bosun
   pytest
   ```

## How to add commands

Add a new handler function:

```python
@bot.command("/price")
async def price(event, bot):
    return {
        "event_id": event.event_id,
        "action": "reply",
        "content": "price placeholder response",
    }
```

For SDK-driven event handlers, use `@bot.event` and the high-level helpers:

```python
@bot.event("mls_group_message_received")
@bot.lock("snapshot")
async def handle_group_snapshot(event, bot):
    chat_id = (event.chat_id or "").strip()
    if chat_id and event.content == "!snapshot":
        await snapshot(bot, group_id=chat_id)
    return bot.ignore(event)
```

After adding commands, update the tests in `bots/bosun/tests/test_handlers.py`
if necessary.

## Packaging and deployment

- `Dockerfile` — builds a container image for this bot.
- `systemd.service` — runs the bot as a non-root `pacto-bot` service on the host.
- `README.md` — human-facing run and deploy instructions for this bot.

Do not delete or rename these files without updating the project-level
`docker-compose.yml` and `pacto-bot-api.toml`.
