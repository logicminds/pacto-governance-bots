---
title: feat: Refactor bosun to use the new SDK decorator/helpers surface
type: feat
status: draft
date: 2026-07-09
deepened: 2026-07-09
origin: user request / SDK usability upgrade after 2026-07-08/09 daemon plans
---

# Plan: Refactor bosun to use the new SDK decorator/helpers surface

## Summary

The `pacto-bot-api` daemon has shipped three related features:

1. Inbound MLS group-message dispatch (`ReceiveGroupMessages`, `mls_group_message_received`, `agent.rate_limited`, `agent.is_squad_member`) — see `docs/plans/2026-07-08-001-feat-inbound-mls-snapshot-plan.md`.
2. Daemon-backed MLS group administration (`agent.create_mls_group`, `agent.invite_to_mls_group`) — see `docs/plans/2026-07-09-001-feat-daemon-backed-mls-group-admin-plan.md`.
3. Python SDK usability improvements (`@bot.event`, `@bot.hears`, `@bot.dm`, `@bot.rate_limited`, guaranteed auto-acknowledgement, `bot.send_group_message`, `bot.is_squad_member`, `bot.own_pubkey`, per-request timeouts, `@bot.throttle`, `@bot.lock`, validation helpers) — see `docs/plans/2026-07-08-002-feat-sdk-usability-recommendations-plan.md`.

This plan refactors the `bosun` governance snapshot bot to adopt the SDK's high-level facade. The current `bosun.py` predates the new decorators and helpers, so it overrides `_handle_event`, overrides `_dispatch_loop`, manually acknowledges every event, wraps RPC calls with `asyncio.wait_for`, and maintains its own rate-limit cache and snapshot lock. All of that is now provided by the SDK; the refactor removes the boilerplate, makes the bot's behavior visible through decorators, and relies on the daemon's per-Squad rate limiting.

Because the SDK is installed from a git URL at Docker image build time, the container must be rebuilt after the upstream SDK changes land.

## Problem Frame

The current `bosun.py` (as of the Phase 2 implementation) works, but it was written against the pre-usability SDK:

- `BosunBot._handle_event` is overridden to branch on `event.type` and route `mls_group_message_received` and `dm_received` to private helpers.
- `BosunBot._dispatch_loop` is overridden to route `agent.rate_limited` and `AgentStatusParams` notifications.
- Every handler path calls a private `_ack` helper that wraps `handler_response` with `asyncio.wait_for`.
- RPC calls use `self.client.agent_send_group_message` and `self.client.agent_is_squad_member` directly.
- Snapshot calls are wrapped with `asyncio.wait_for` using module-level `RPC_TIMEOUT_SECONDS` and `SNAPSHOT_LOCK_TIMEOUT_SECONDS` constants.
- A `dict[str, float]` rate-limit cache and an `asyncio.Lock` are maintained in the subclass to serialize snapshots and throttle duplicate requests.

The new SDK makes all of this unnecessary. Continuing to maintain it in the handler increases the risk of missed acknowledgements, inconsistent timeouts, and behavior drift when the SDK evolves.

## Requirements

### SDK upgrade and container rebuild

- R1. The `pacto-bot-sdk` dependency is upgraded to the version that includes the new decorators, helpers, and generated methods. Because the SDK is installed from git at Docker image build time, the image must be rebuilt after the upstream changes land.
- R2. The `Dockerfile` comment that incorrectly says the SDK is installed from PyPI is corrected.

### Handler routing

- R3. The `mls_group_message_received` handler is registered with `@bot.event("mls_group_message_received")` instead of being routed through a `_handle_event` override.
- R4. The DM `!snapshot <squad-id>` command is registered with `@bot.hears("!snapshot")` (or `@bot.event("dm_received")` if the SDK's `@bot.hears` cannot be restricted to DM events).
- R5. The `agent.rate_limited` handler is registered with `@bot.rate_limited` and the `_dispatch_loop` override is removed.
- R6. The slash-command `/snapshot` handler and `@bot.default` handler remain unchanged.

### Acknowledgement and response helpers

- R7. `BosunBot` is constructed with `auto_acknowledge=True` (the SDK default) so decorated handlers no longer need to call `handler_response` manually.
- R8. The slash-command handler returns `bot.reply(event, ...)` and all other handlers return `None` (implicit `ignore`) or call `bot.ignore(event)` explicitly.
- R9. The existing `_ack` helper is removed.

### High-level RPC helpers

- R10. All calls to `self.client.agent_send_group_message` are replaced with `await bot.send_group_message(group_id, content)`.
- R11. All calls to `self.client.agent_is_squad_member` are replaced with `await bot.is_squad_member(group_id, member_pubkey)`.
- R12. The module-level `is_squad_member(bot, ...)` and `snapshot(bot, ...)` helpers are kept for backwards compatibility but delegate to the new `Bot` methods.

### Concurrency and rate-limiting

- R13. The manual per-group rate-limit cache (`_rate_limit_cache`) is removed; the daemon's per-Squad rate limiting and `agent.rate_limited` notification are authoritative.
- R14. The manual `asyncio.Lock` for snapshot serialization is replaced with `@bot.lock("snapshot")` on the snapshot handler.
- R15. The `RPC_TIMEOUT_SECONDS` and `SNAPSHOT_LOCK_TIMEOUT_SECONDS` constants are removed; timeouts are handled by the generated client's `timeout` parameter/default.

### Validation and identity

- R16. The `bot.own_pubkey` property is used for the self-message guard in the group-message handler, with a safe fallback when the daemon omits it.
- R17. SDK validation helpers (`validate.squad_id`, `validate.pubkey`) are used to validate the group id and member pubkey before RPC calls.

### Backwards compatibility

- R18. Phase 1 behavior (daily cadence, `/snapshot` slash command, `--trigger-snapshot` CLI, KeyPackage publish on startup) continues to work unchanged.
- R19. No new required environment variables are introduced.
- R20. The `BosunBot` subclass is retained only to host the `cadence_loop` and CLI argument parsing; it no longer overrides dispatch.

### Tests and documentation

- R21. `test_bosun.py` and `test_handlers.py` are updated to use the new decorators and helpers.
- R22. Tests verify that the slash command still works, that group and DM `!snapshot` still trigger `snapshot()`, and that `agent.rate_limited` still posts a rate-limit message.
- R23. The README is updated to mention the SDK-driven `!snapshot` handlers and the container rebuild requirement.

## Key Technical Decisions

- KTD-1. **Use the SDK decorator API instead of `_handle_event` overrides.** The bot's behavior is declared through decorators, which is the SDK's intended pattern and matches the conventions in `bots/bosun/AGENTS.md`.
- KTD-2. **Trust the daemon for per-Squad rate limiting.** The bot removes its own rate-limit cache. The daemon signals over-limit cases via `agent.rate_limited`; the bot only responds to that signal. A local `@bot.throttle` may be kept as optional defense-in-depth but is not required.
- KTD-3. **Use `@bot.lock("snapshot")` for snapshot serialization.** The lock prevents concurrent snapshot executions (e.g., a cadence tick overlapping with an inbound `!snapshot`) without manual `asyncio.Lock` bookkeeping.
- KTD-4. **Use the generated client's default timeout.** Pass `timeout=30.0` through `to_bot_transport_kwargs` or the `Bot` constructor so `asyncio.wait_for` wrappers can be removed from the handler code.
- KTD-5. **Self-message guard uses `bot.own_pubkey` opportunistically.** The daemon already filters own-messages, but if an event leaks through, the bot compares `event.author` to `bot.own_pubkey`. If `own_pubkey` is `None` (older daemon), the guard is skipped rather than failing closed.
- KTD-6. **Module-level helpers remain for tests.** `snapshot(bot, ...)` and `is_squad_member(bot, ...)` keep their existing signatures so tests can import them; they delegate to `bot.send_group_message` / `bot.is_squad_member`.
- KTD-7. **Do not adopt `Bot.create_mls_group` / `Bot.invite_to_mls_group`.** Bosun is a group message consumer, not a group admin. Those methods are out of scope for this refactor; they are surfaced only by the daemon-backed MLS group admin plan and are not needed for snapshot delivery.
- KTD-8. **Remove the custom `_dispatch_loop` override.** The base `Bot._dispatch_loop` dispatches notifications to the `@bot.rate_limited` and `@bot.status` decorators; the subclass only needs to add `cadence_loop` to the asyncio gather.

## Scope Boundaries

### In scope

- Refactoring `bots/bosun/src/bosun/bosun.py` to use the new SDK facade.
- Removing manual overrides and helpers that are now provided by the SDK.
- Updating tests to match the new implementation.
- Rebuilding the Docker image after the SDK upgrade.
- Updating README and `.env.example` if needed.

### Out of scope

- Daemon-side changes of any kind.
- Adding group-creation or invitation flows to Bosun.
- Changing the EVM reader, snapshot formatter, or contract types.
- Persistent throttle/lock state across restarts.
- Regex-based `@bot.hears` patterns.

### Deferred

- Multi-bot capability changes (Bosun is a single-bot handler today).
- Rich group metadata beyond the squad id.

## Implementation Units

### U1. SDK upgrade and container rebuild

**Goal:** Ensure the bot depends on the SDK version that includes the new methods and helpers.

**Requirements:** R1, R2

**Dependencies:** Upstream `pacto-bot-api` must have merged the SDK changes.

**Files:**
- `bots/bosun/pyproject.toml`
- `bots/bosun/Dockerfile`

**Approach:**
- `pyproject.toml` already references `pacto-bot-sdk @ git+https://github.com/covenant-gov/pacto-bot-api.git#subdirectory=python`, so it will pick up the latest main on the next install. No source change is required, but record the rebuild requirement in the plan and README.
- Correct the `Dockerfile` comment that says the SDK is installed from PyPI; it is installed from the git checkout via the `COPY` + `pip install .` flow.
- Document the rebuild command: `docker compose build --no-cache` or `docker compose up --build`.

**Verification:**
- `docker compose build --no-cache` succeeds.
- The installed SDK exposes `Bot.send_group_message`, `Bot.is_squad_member`, `Bot.own_pubkey`, `@bot.event`, `@bot.hears`, `@bot.rate_limited`, and the generated client has per-request `timeout`.

---

### U2. Refactor event routing to decorators

**Goal:** Remove the `_handle_event` override and route group/DM events through decorators.

**Requirements:** R3, R4, R5, R6, R7, R8, R9

**Dependencies:** U1

**Files:**
- `bots/bosun/src/bosun/bosun.py`

**Approach:**
- Remove `BosunBot._handle_event` entirely.
- Remove the private helpers `_handle_mls_group_message` and `_handle_dm_snapshot`.
- Add a module-level handler:

```python
@bot.event("mls_group_message_received")
async def handle_mls_group_message(event, bot):
    chat_id = (event.chat_id or "").strip()
    content = (event.content or "").strip()
    if not chat_id:
        bot.log(f"warning: mls_group_message_received without chat_id: event_id={event.event_id}")
        return bot.ignore(event)
    if bot.own_pubkey and getattr(event, "author", None) == bot.own_pubkey:
        return bot.ignore(event)
    if content != "!snapshot":
        return bot.ignore(event)
    await bot._post_snapshot_with_lock(chat_id)
    return bot.ignore(event)
```

- Add a DM handler. Prefer `@bot.hears("!snapshot")` if it can be restricted to `dm_received` events; otherwise use `@bot.event("dm_received")` and parse the first token:

```python
@bot.hears("!snapshot")
async def handle_dm_snapshot(event, bot):
    # If the SDK's @bot.hears is not event-type-specific, guard with:
    if event.type != "dm_received":
        return bot.ignore(event)
    author = getattr(event, "author", None)
    tokens = (event.content or "").strip().split()
    if len(tokens) < 2:
        return bot.ignore(event)
    squad_id = tokens[1]
    if not author:
        bot.log(f"warning: dm_received without author: event_id={event.event_id}")
        return bot.ignore(event)
    if not await bot.is_squad_member(squad_id, author):
        bot.log(f"warning: {author} is not a member of {squad_id}")
        return bot.ignore(event)
    await bot._post_snapshot_with_lock(squad_id)
    return bot.ignore(event)
```

- The `BosunBot` constructor should still declare `event_types=["dm_received", "mls_group_message_received"]`.
- Remove the `_ack` helper.

**Verification:**
- Existing tests for group message and DM snapshot pass after updating mocks.

---

### U3. Replace raw RPC calls with high-level helpers

**Goal:** Use `bot.send_group_message` and `bot.is_squad_member` everywhere.

**Requirements:** R10, R11, R12

**Dependencies:** U1

**Files:**
- `bots/bosun/src/bosun/bosun.py`

**Approach:**
- Replace `self.client.agent_send_group_message(...)` with `await bot.send_group_message(group_id, content)`.
- Replace `self.client.agent_is_squad_member(...)` with `await bot.is_squad_member(group_id, member_pubkey)`.
- Update the module-level `snapshot` helper to use `bot.send_group_message`.
- Update the module-level `is_squad_member` helper to use `bot.is_squad_member`.

**Verification:**
- Tests that previously mocked `client.agent_send_group_message` now mock `bot.send_group_message`.
- Tests that previously mocked `client.agent_is_squad_member` now mock `bot.is_squad_member`.

---

### U4. Remove manual acknowledgement and custom dispatch loop

**Goal:** Use `auto_acknowledge` and `@bot.rate_limited`.

**Requirements:** R7, R8, R9, R5

**Dependencies:** U2

**Files:**
- `bots/bosun/src/bosun/bosun.py`

**Approach:**
- Construct `BosunBot` with `auto_acknowledge=True` (or rely on the SDK default). If the SDK default is `True`, no explicit argument is needed.
- Remove the `_ack` helper.
- Remove the `_dispatch_loop` override.
- Add a rate-limited handler:

```python
@bot.rate_limited
async def handle_rate_limited(notification, bot):
    group_id = getattr(notification, "group_id", None)
    if not group_id:
        bot.log("warning: agent.rate_limited without group_id")
        return
    window = getattr(notification, "window_seconds", None)
    try:
        window = max(MIN_RATE_LIMIT_WINDOW_SECONDS, int(window or DEFAULT_RATE_LIMIT_WINDOW_SECONDS))
    except (TypeError, ValueError):
        window = DEFAULT_RATE_LIMIT_WINDOW_SECONDS
    content = RATE_LIMIT_MESSAGE_TEMPLATE.format(window=window)
    await bot.send_group_message(group_id, content)
```

- The slash command handler returns `bot.reply(event, "Snapshot posted to the squad channel.")`.

**Verification:**
- Tests assert that decorated handlers send `handler_response` automatically for `None` returns.
- Rate-limit handler still posts the explanation message.

---

### U5. Replace manual locking and timeouts with SDK helpers

**Goal:** Remove `asyncio.wait_for` wrappers and the snapshot lock.

**Requirements:** R13, R14, R15

**Dependencies:** U2, U3

**Files:**
- `bots/bosun/src/bosun/bosun.py`
- `bots/bosun/src/bosun/config.py` (for `to_bot_transport_kwargs` if timeouts are passed there)

**Approach:**
- Pass `timeout=30.0` to the `Bot` constructor (or through `to_bot_transport_kwargs`) so the generated client uses it as the default.
- Remove `RPC_TIMEOUT_SECONDS` and `SNAPSHOT_LOCK_TIMEOUT_SECONDS` constants.
- Remove `_snapshot_lock` and `_get_snapshot_lock`.
- Add `@bot.lock("snapshot")` to the snapshot handlers. The group-message handler should look like:

```python
@bot.event("mls_group_message_received")
@bot.lock("snapshot")
async def handle_mls_group_message(event, bot):
    ...
    await snapshot(bot, group_id=chat_id)
    return bot.ignore(event)
```

- Remove `_rate_limit_cache`, `_check_rate_limit`, and `_rate_limit_window`.
- Remove any remaining `asyncio.wait_for(..., timeout=...)` calls around RPC or snapshot.

**Verification:**
- Concurrent inbound snapshot tests still serialize.
- Timeout tests use the generated client's `timeout` parameter.

---

### U6. Use validation helpers and `bot.own_pubkey`

**Goal:** Use `pacto_bot_sdk.validate` and `bot.own_pubkey` for safety.

**Requirements:** R16, R17

**Dependencies:** U1

**Files:**
- `bots/bosun/src/bosun/bosun.py`

**Approach:**
- Import `validate` from `pacto_bot_sdk`.
- In the DM handler, validate `squad_id = validate.squad_id(tokens[1])` and `author = validate.pubkey(author)` before use. Catch `ValueError` and log a warning.
- In the group-message handler, validate `chat_id = validate.squad_id(chat_id)` before calling `snapshot`.
- Add the self-message guard using `bot.own_pubkey`:

```python
if bot.own_pubkey and getattr(event, "author", None) == bot.own_pubkey:
    return bot.ignore(event)
```

**Verification:**
- Invalid squad ids / pubkeys raise `ValueError` and are logged without crashing the loop.
- Valid inputs pass through unchanged.

---

### U7. Update tests

**Goal:** Make the test suite reflect the new implementation.

**Requirements:** R21, R22

**Dependencies:** U2, U3, U4, U5, U6

**Files:**
- `bots/bosun/tests/test_bosun.py`
- `bots/bosun/tests/test_handlers.py`

**Approach:**
- Update `_make_bot` to include `auto_acknowledge=True` if needed.
- Update mocks to target `bot.send_group_message` and `bot.is_squad_member` instead of `client.agent_*`.
- Assert that event handlers auto-acknowledge via the base `Bot` mechanism rather than calling `_ack`.
- Add tests for `bot.own_pubkey` population after registration.
- Add tests for validation helpers rejecting invalid inputs.
- Keep tests for the slash command, cadence, trigger-once, and KeyPackage publish unchanged except for any mock target changes.
- Remove tests that asserted manual `_ack` behavior if now covered by SDK tests.

**Verification:**
- `make test` passes.

---

### U8. Update README and `.env.example`

**Goal:** Document the new SDK-driven handlers and the container rebuild requirement.

**Requirements:** R23

**Dependencies:** U7

**Files:**
- `bots/bosun/README.md`
- `bots/bosun/.env.example`

**Approach:**
- Update README "Commands" section to mention:
  - `!snapshot` in a Squad channel triggers a fresh snapshot.
  - `!snapshot <squad-id>` via DM triggers a snapshot if the sender is a member.
  - The bot responds to daemon rate-limit signals with a one-minute explanation.
- Add a "SDK upgrades" note that `docker compose build --no-cache` is required after upstream SDK changes because the dependency is installed from git at image build time.
- `.env.example` needs no new required variables; optionally add a comment about rate-limit behavior.

**Verification:**
- README examples are consistent with the refactored code.
- No new required variables are introduced.

---

### U9. Verification

**Goal:** Prove the refactor works end-to-end.

**Approach:**
- Run `make test`.
- Run `docker compose build --no-cache`.
- Run a manual trigger: `python -m bosun --trigger-snapshot`.
- If a live daemon is available, run a Squad test: post `!snapshot` and verify the bot replies with a snapshot; post twice within one minute and verify the rate-limit explanation.

**Verification:**
- `make validate` passes.
- Docker image builds successfully.
- Manual trigger posts a snapshot.

## System-Wide Impact

- `bots/bosun/src/bosun/bosun.py`: significant simplification; removal of `_handle_event`, `_dispatch_loop`, `_ack`, `_rate_limit_cache`, `_snapshot_lock`, and most `asyncio.wait_for` calls.
- `bots/bosun/tests/test_bosun.py`: mocks change from `client.agent_*` to `bot.*` helpers; tests assert auto-acknowledge.
- `bots/bosun/Dockerfile`: image rebuild required; comment corrected.
- `bots/bosun/README.md`: documentation refresh.
- `bots/bosun/AGENTS.md`: optionally update the capability list to include `SendGroupMessages` and `ReceiveGroupMessages`.

## Risks & Dependencies

- **Risk:** The SDK's `@bot.hears` might not be filtered by event type, causing the DM handler to also fire on group messages.
  - **Mitigation:** Use `@bot.event("dm_received")` and parse the first token manually if `@bot.hears` cannot be restricted. Alternatively, branch on `event.type` inside a `@bot.hears` handler.
- **Risk:** `auto_acknowledge=True` changes the meaning of `None` returns from "no response" to `handler_response(action="ignore")`. The current code already calls `_ack` for every path, so this is safe, but any new handler that intentionally wants no response must be explicit.
  - **Mitigation:** Set `auto_acknowledge=False` only if a legacy transition is needed; otherwise keep the default.
- **Risk:** Removing the bot-side rate-limit cache could allow a burst if the daemon's rate limiter is misconfigured.
  - **Mitigation:** Keep `@bot.throttle(key=lambda e: e.chat_id, window_seconds=60)` on the group-message handler as optional defense-in-depth if the daemon's signal is not trusted. This plan removes it by default because the daemon is authoritative.
- **Risk:** The generated client's default timeout might differ from the current `30.0` seconds.
  - **Mitigation:** Explicitly pass `timeout=30.0` to the `Bot` constructor.
- **Risk:** `bot.own_pubkey` may be `None` if the daemon omits `own_pubkeys` in the registration response.
  - **Mitigation:** Guard self-message checks with `if bot.own_pubkey and ...`.
- **Dependency:** The upstream `pacto-bot-api` repo must have merged the SDK changes (regenerated `client.py`, `models.py`, and `bot.py`) before this refactor is exercised.
- **Dependency:** The `pacto-dev-env` daemon must be rebuilt/restarted with the new daemon capabilities if live testing is performed.

## Acceptance Examples

- **AE1. Group `!snapshot` triggers a snapshot**
  - Given: a registered `BosunBot` with `@bot.event("mls_group_message_received")`.
  - When: an `mls_group_message_received` event with `content: "!snapshot"` and `chat_id: "squad-1"` is delivered.
  - Then: `snapshot(bot, group_id="squad-1")` is called, the snapshot is posted to `squad-1`, and the handler auto-acknowledges with `ignore`.

- **AE2. DM `!snapshot <squad-id>` verifies membership**
  - Given: a registered `BosunBot` with `@bot.hears("!snapshot")` on DM events.
  - When: a `dm_received` event with `content: "!snapshot squad-1"` and `author: "npub1..."` is delivered.
  - Then: `bot.is_squad_member("squad-1", "npub1...")` is called; on `True`, `snapshot(bot, group_id="squad-1")` is called and the snapshot is posted.

- **AE3. Non-member DM is ignored**
  - Given: a registered `BosunBot` and a DM with `content: "!snapshot squad-1"` from a non-member.
  - When: the handler runs.
  - Then: `snapshot()` is not called and the handler returns `ignore`.

- **AE4. Rate-limit notification posts explanation**
  - Given: a `@bot.rate_limited` handler.
  - When: `agent.rate_limited` is delivered for `group_id: "squad-1"` with `window_seconds: 60`.
  - Then: `bot.send_group_message("squad-1", "...")` is called with the rate-limit explanation and `snapshot()` is not called.

- **AE5. Slash command still works**
  - Given: `@bot.command("/snapshot")`.
  - When: a slash command event is delivered.
  - Then: `snapshot()` is called and the handler returns `bot.reply(event, "Snapshot posted to the squad channel.")`.
