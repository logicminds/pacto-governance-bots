---
title: Python Governance Snapshot Bot — Phase 2 Requirements
type: feat
status: completed
date: 2026-07-08
origin: docs/2026-07-05-001-feat-python-governance-snapshot-bot-plan.md
---

# Python Governance Snapshot Bot — Phase 2 Requirements

## Summary

With `pacto-bot-api` now providing the daemon-side commands and notifications for inbound MLS group-message dispatch, the `bosun` Python governance snapshot bot should be extended to consume inbound `!snapshot` triggers and rate-limit signals. This document defines the requirements for the Phase 2 implementation in the `pacto-governance-bots` repository, limited to the Python handler work that the parent plan explicitly deferred from Phase 1.

## Parent Context

Phase 1 built the standalone Python bot in `pacto-governance-bots`. It implements the daily autonomous snapshot cadence and the `/snapshot` command handler, all driven by the same `snapshot()` coroutine. Phase 2 adds the inbound MLS path: squad members type `!snapshot` in a Squad channel, the daemon decrypts and delivers the plaintext, and the Python bot responds with a fresh snapshot or a rate-limit explanation in the same Squad. The daemon-side SDK and JSON-RPC changes are out of scope for this repo and are assumed to be available from the upstream `pacto-bot-api` plan.

## Problem Frame

Daily snapshots are useful, but users need an on-demand trigger that does not require operator access to the bot process or a CLI flag. The daemon now exposes `ReceiveGroupMessages` for inbound MLS group messages, `agent.rate_limited` for rate-limit signals, and `agent.is_squad_member` for DM-triggered membership verification. The Python bot must integrate these three primitives into the existing `snapshot()` flow.

## Requirements

### R1. Register the inbound group-message capability

The bot must declare `ReceiveGroupMessages` in its `Bot` registration so the daemon delivers decrypted group-message events. The bot must retain the existing `SendGroupMessages` capability because it posts snapshots in response.

- **Acceptance:** The `Bot` instantiation declares `capabilities=["SendGroupMessages", "ReceiveGroupMessages"]` and the daemon registration reflects it.
- **Files:** `bots/bosun/bosun.py`

### R2. Handle `mls_group_message_received` events

The bot must implement an event handler for the `agent.event` notification with `type: mls_group_message_received`. The handler must:

- Inspect the decrypted `content` field for the literal command `!snapshot`.
- Ignore any plaintext that is not exactly `!snapshot` (whitespace-insensitive trimming is allowed, but no other commands are parsed).
- Ignore messages sent by the bot itself; the daemon should already filter these, but the handler must tolerate them if delivered.

- **Acceptance:** A mock daemon notification with `content: "!snapshot"` triggers `snapshot()`, and notifications with other content are ignored.
- **Files:** `bots/bosun/bosun.py`, `bots/bosun/tests/test_bosun.py`

### R3. Route `!snapshot` to the same snapshot flow

The `!snapshot` trigger must invoke the same `snapshot()` coroutine used by the daily cadence and the `/snapshot` command handler. The event handler must pass the `chat_id` from the notification as the destination group so the snapshot is posted back to the originating Squad.

- **Acceptance:** The daily cadence, `/snapshot` command, and `!snapshot` inbound message all call the same `snapshot()` helper and produce the same formatted output.
- **Files:** `bots/bosun/bosun.py`

### R4. Respond in the originating Squad

The bot must call `agent.send_group_message` using the `chat_id` field from the `mls_group_message_received` event as the destination group. The existing snapshot formatter must not be changed; only the destination routing logic is new.

- **Acceptance:** A manual test with a running daemon and a mock squad member shows the snapshot posted to the same Squad where `!snapshot` was typed.
- **Files:** `bots/bosun/bosun.py`

### R5. Handle the `agent.rate_limited` notification

When the daemon signals a per-Squad rate limit via `agent.rate_limited`, the bot must post a short Markdown explanation in the same Squad identified by `group_id`. The explanation must state the one-minute limit and when the user can retry. The bot must not attempt a full snapshot in response to the rate-limit signal.

- **Acceptance:** A mock `agent.rate_limited` notification with `group_id: "<squad>"` and `window_seconds: 60` produces a group message in that squad, and `snapshot()` is not called.
- **Files:** `bots/bosun/bosun.py`, `bots/bosun/tests/test_bosun.py`

### R6. DM-triggered `!snapshot` with membership verification

When the bot is addressed via DM with a `!snapshot` command that includes a Squad identifier, the bot must use `agent.is_squad_member(bot_id, group_id, member_pubkey)` to verify that the sender is a member of the referenced Squad before posting. If the sender is not a member, the bot must not post the snapshot and should log the attempt. This requirement is satisfied if the bot exposes a reusable helper; the exact DM trigger mechanism depends on the daemon delivering a DM event.

- **Acceptance:** A unit test confirms that `is_squad_member(...)` is called with the sender's pubkey and the target squad, and that the snapshot is only sent when the result is `true`.
- **Files:** `bots/bosun/bosun.py`, `bots/bosun/tests/test_bosun.py`

### R7. Preserve Phase 1 behavior

The daily cadence, the `/snapshot` command, the `--trigger-snapshot` CLI flag, and the KeyPackage publish on startup must continue to work unchanged. The bot must not break existing tests or the manual trigger flow.

- **Acceptance:** The existing `pytest` suite passes without modification, and the daily cadence still posts to the configured `PACTO_GOVERNANCE_GROUP_ID`.
- **Files:** `bots/bosun/bosun.py`, `bots/bosun/tests/test_bosun.py`

### R8. Configuration surface remains stable

No new required environment variables are introduced. Optional variables may be added for rate-limit message text or DM command handling, but the bot must start with the same Phase 1 configuration.

- **Acceptance:** The `.env.example` file is updated only with optional variables, and the bot starts successfully with the Phase 1 environment.
- **Files:** `bots/bosun/.env.example`

## Key Technical Decisions

- **KTD-1. Keep the existing `snapshot()` coroutine as the single entry point.** The inbound event handler parses `!snapshot`, then calls `snapshot(group_id=chat_id)` so that formatting, EVM reading, and sending are reused. Add an optional `group_id` parameter to `snapshot()` defaulting to `settings.group_id`, and use it for the `send_group_message` destination.
- **KTD-2. Parse plaintext in the handler, not in a new module.** The command is a single literal string; a dedicated parser is unnecessary. Use `content.strip() == "!snapshot"`.
- **KTD-3. Treat `agent.rate_limited` as a distinct notification.** It does not call `snapshot()`; it only posts a small rate-limit explanation.
- **KTD-4. DM membership verification uses the new `agent.is_squad_member` method.** A reusable async helper wraps the call and logs failures.
- **KTD-5. The `chat_id` from `mls_group_message_received` is trusted as the destination Squad.** The daemon has already validated membership and decryption.

## Scope Boundaries

### In Scope

- Updating the `Bot` registration to include `ReceiveGroupMessages`.
- Adding an `mls_group_message_received` event handler to `bosun.py`.
- Adding an `agent.rate_limited` handler.
- Adding a DM-triggered `!snapshot` path with `agent.is_squad_member` verification (if a DM event is delivered by the daemon).
- Unit tests for the new handler paths using mock `PactoClient` notifications.
- Updating the README with Phase 2 usage (`!snapshot` trigger, rate-limit behavior, DM flow).

### Out of Scope

- Any daemon-side changes (subscriptions, decryption, event types, rate-limit logic, JSON-RPC methods). Those are implemented in `pacto-bot-api` per the upstream plan.
- Changes to the EVM reader or snapshot formatter, except for wiring the destination group.
- Interactive commands other than `!snapshot`.
- TEE deployment or key custody changes.

## Implementation Units

### U1. Update `Bot` registration and event handler skeleton

**Goal:** Declare the new capability and route incoming events to dedicated handlers.

**Requirements:** R1, R2, R7

**Dependencies:** None

**Files:**
- `bots/bosun/bosun.py`

**Approach:** Change the `Bot` instantiation to include `capabilities=["SendGroupMessages", "ReceiveGroupMessages"]`. Add a `_handle_mls_group_message_received(event)` coroutine and an `_handle_rate_limited(event)` coroutine. Register them via the existing event-handler mechanism. The `Bot` class (or `PactoClient`) should dispatch `agent.event` and `agent.rate_limited` notifications to these methods.

**Patterns to follow:** Existing `python/examples/greeting_bot.py` for event-handler registration; Phase 1 `bosun.py` for the `snapshot()` coroutine and `send_group_message` call.

**Test scenarios:**
- Happy path: `Bot` instance registers with both capabilities.
- Error path: handler gracefully ignores unknown event types.

**Verification:** `pytest bots/bosun/tests/test_bosun.py` passes.

### U2. Implement `!snapshot` inbound trigger

**Goal:** Parse inbound group messages and route `!snapshot` to the existing snapshot flow.

**Requirements:** R2, R3, R4, R7

**Dependencies:** U1

**Files:**
- `bots/bosun/bosun.py`
- `bots/bosun/tests/test_bosun.py`

**Approach:** In `_handle_mls_group_message_received(event)`, read `event.content` and `event.chat_id`. If `event.chat_id` is missing or `None`, log a warning and drop the event without calling `snapshot()`. If `content.strip() == "!snapshot"`, call `await snapshot(bot=bot, group_id=event.chat_id)`. If the content does not match, return without logging an error. If the event author equals the bot's own pubkey (if available in the event), ignore it silently.

**Test scenarios:**
- Happy path: `!snapshot` content triggers `snapshot()` with `group_id=event.chat_id`.
- Edge case: `!snapshot\n` with trailing whitespace still triggers.
- Edge case: `Snapshot please` is ignored.
- Edge case: event from the bot's own pubkey is ignored.
- Error path: `snapshot()` raises an EVM error; the handler logs it and does not crash the dispatch loop.

**Verification:** Unit tests with mocked `PactoClient` and `agent.event` notification pass.

### U3. Implement rate-limit response handler

**Goal:** Reply to `agent.rate_limited` with a short explanation in the affected Squad.

**Requirements:** R5

**Dependencies:** U1

**Files:**
- `bots/bosun/bosun.py`
- `bots/bosun/tests/test_bosun.py`

**Approach:** In `_handle_rate_limited(event)`, read `event.bot_id`, `event.group_id`, and `event.window_seconds`. Send a Markdown message to `event.group_id` explaining the rate limit and the retry window. Example: `> Rate limit: one snapshot per minute per Squad. Try again in ~{window_seconds} seconds.` If the group id is missing or malformed, log and drop.

**Test scenarios:**
- Happy path: `agent.rate_limited` produces a `send_group_message` call to the same group.
- Edge case: missing `group_id` logs a warning and does not send.
- Edge case: `window_seconds` defaults to 60 if not provided.

**Verification:** Unit tests with mocked `PactoClient` pass.

### U4. Add DM-triggered `!snapshot` with membership verification

**Goal:** Support `!snapshot` commands delivered via DM by verifying the sender's membership in the target Squad.

**Requirements:** R6

**Dependencies:** U2

**Files:**
- `bots/bosun/bosun.py`
- `bots/bosun/tests/test_bosun.py`

**Approach:** Add an async helper `is_squad_member(group_id, member_pubkey)` that calls `bot.client.agent_is_squad_member(bot_id, group_id, member_pubkey)` and returns `response.is_member` rather than the raw response object. If the daemon delivers a DM event with `!snapshot` and a Squad identifier (in the message text or a separate metadata field), parse the target Squad, verify membership, and call `snapshot(group_id=target_group)` only on success. If membership verification fails, log a warning and do not post. If the message format does not include a squad identifier, ignore the DM.

**Note:** The exact DM event shape and squad identifier extraction are dependent on the daemon's delivery format. If the daemon does not deliver DM events for this use case, this unit may be implemented as a tested helper that is not yet wired to an event handler.

**Test scenarios:**
- Happy path: `is_squad_member` returns `true` and `snapshot()` is called.
- Edge path: `is_squad_member` returns `false` and no snapshot is sent.
- Error path: `agent.is_squad_member` raises an error; the handler logs it and does not send.
- Edge case: DM without a squad identifier is ignored.

**Verification:** Unit tests with mocked `PactoClient` pass.

### U5. Update tests and README

**Goal:** Cover the new behavior with unit tests and document it for operators.

**Requirements:** R7, R8

**Dependencies:** U1, U2, U3, U4

**Files:**
- `bots/bosun/tests/test_bosun.py`
- `bots/bosun/.env.example`
- `README.md`

**Approach:** Extend `test_bosun.py` with tests for the event handlers using a mock `PactoClient` and a mock event model. Add optional environment variables to `.env.example` only if new behavior is configurable. Update the README with a "Phase 2" section describing how squad members can trigger a snapshot with `!snapshot`, what the rate-limit response looks like, and how DM-triggered snapshots work (if supported).

**Test scenarios:**
- Happy path: full Phase 2 test suite passes without a live daemon.
- Integration: documented manual procedure shows `!snapshot` in a Squad produces a snapshot.
- Quality: no hardcoded secrets or mock secrets in tests.

**Verification:** `pytest` passes in the default suite; the manual procedure is verified against a running daemon and Squad.

## Acceptance Criteria

- AC1. The bot registers with `SendGroupMessages` and `ReceiveGroupMessages`.
- AC2. An `mls_group_message_received` event with `content: "!snapshot"` calls `snapshot()` and posts the formatted snapshot to the Squad identified by `chat_id`.
- AC3. An `mls_group_message_received` event with any other content is ignored.
- AC4. An `agent.rate_limited` notification produces a rate-limit explanation in the same Squad and does not call `snapshot()`.
- AC5. The daily cadence, `/snapshot` command, and `--trigger-snapshot` CLI flag continue to work as in Phase 1.
- AC6. Unit tests for the new handlers pass without a live daemon.
- AC7. The README documents the `!snapshot` trigger, rate-limit behavior, and any DM-triggered flow.
- AC8. No new required environment variables are introduced.

## Risks & Dependencies

- **Dependency:** The daemon must already implement the `ReceiveGroupMessages` capability, `mls_group_message_received` event, `agent.rate_limited` notification, and `agent.is_squad_member` method. This requirement doc assumes those are available from the upstream `pacto-bot-api` plan.
- **Risk:** The exact shape of the `agent.event` notification for `mls_group_message_received` may differ slightly from the plan. The implementer must inspect the regenerated Python SDK models before finalizing the handler.
- **Risk:** The `Bot` class may not expose a direct event-handler hook for `agent.event`. If so, the implementation may need to override `Bot._handle_event` or use a client-level callback. The parent Phase 1 plan used a `Bot` subclass; this doc assumes similar subclassing is acceptable.
- **Risk:** DM-triggered squad commands require the daemon to deliver DMs with enough context to identify the target Squad. If that context is not available, U4 should be limited to a tested helper that is not wired to a live event.
- **Risk:** Concurrent inbound `!snapshot` events and daily cadence ticks could double-send. The handler should rely on the daemon's per-Squad rate limiting, but the bot should not maintain its own send queue that could bypass it.

## Open Questions

- OQ1. Does the regenerated Python SDK expose `agent_is_squad_member` on `PactoClient` or as a method on `Bot`? The implementation should follow the generated naming.
- OQ2. Does the `Bot` class route `agent.rate_limited` automatically, or does the handler need to subscribe to notifications explicitly? The implementation should inspect the SDK after regeneration.
- OQ3. Is the DM event type for a private message the same as `dm_received` from Phase 1 daemon work, or is it a new type? The DM-triggered flow cannot be fully wired until this is confirmed.
