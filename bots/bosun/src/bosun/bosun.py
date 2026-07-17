"""Bosun governance snapshot bot.

Registers with the daemon, responds to ``/snapshot`` commands and ``!snapshot``
text triggers, and posts on-chain governance snapshots to a configured MLS
Squad channel on demand.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from typing import Any

from pacto_bot_sdk import (
    AgentEventParams,
    AgentRateLimitedParams,
    AgentStatusParams,
    Bot,
    PactoClientError,
    validate,
)
from pacto_bot_sdk.transports import TransportDisconnected

from bosun.config import format_settings_error, load_settings
from bosun.formatter import format_snapshot
from bosun.reader import GovernanceReader
from bosun.types import SnapshotData
from bosun.version import full_version


# ---------------------------------------------------------------------------
# Command / rate-limit constants
# ---------------------------------------------------------------------------
SNAPSHOT_COMMAND = "!snapshot"
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60
MIN_RATE_LIMIT_WINDOW_SECONDS = 1
RATE_LIMIT_MESSAGE_TEMPLATE = (
    "> Rate limit: one snapshot per minute per Squad. "
    "Try again in ~{window} seconds."
)
SQUAD_JOIN_MESSAGE = (
    "Ahoy! I'm **{bot_id}**, the Pacto governance snapshot bot. "
    "I've joined this Squad and I'm ready to post on-chain governance snapshots on demand.\n\n"
    "To request a snapshot:\n"
    "- Type `!snapshot` in this Squad channel.\n"
    "- DM me `!snapshot <squad-id>`.\n\n"
    "I'll also post a snapshot automatically once per day when cadence is enabled."
)
RPC_TIMEOUT_SECONDS = 10.0
SNAPSHOT_LOCK_TIMEOUT_SECONDS = 30.0


class BosunBot(Bot):
    """Small subclass that adds a one-shot trigger flag to the base Bot."""

    def __init__(self, settings: Any, **kwargs: Any) -> None:
        self.settings = settings
        self._snapshot_lock: asyncio.Lock | None = None
        self._rate_limit_cache: dict[str, float] = {}
        super().__init__(
            bot_id=settings.bot_id,
            capabilities=[
                "ReadMessages",
                "SendMessages",
                "SendGroupMessages",
                "ReceiveGroupMessages",
            ],
            event_types=["dm_received", "mls_group_message_received"],
            version=full_version(),
            **kwargs,
        )
        # When the daemon restarts, the old handler id and reconnect token are
        # invalid. Clear them on shutdown so the next connection re-registers.
        self.status(self._on_daemon_status)

    def _get_snapshot_lock(self) -> asyncio.Lock:
        """Return the snapshot lock, creating it on first use."""
        if self._snapshot_lock is None:
            self._snapshot_lock = asyncio.Lock()
        return self._snapshot_lock

    async def _on_daemon_status(self, status: AgentStatusParams, bot: "BosunBot") -> None:
        """Clear handler registration state when the daemon is shutting down.

        The SDK keeps the handler_id and reconnect_token from the previous
        session. If the daemon restarts, those tokens are invalid and a reconnect
        attempt fails forever. Listening for the shutdown notification lets us
        fall back to a fresh handler.register on the next connection.
        """
        if status.state == "shutting_down":
            self.log("daemon shutting down; clearing handler state for re-registration")
            self._handler_id = None
            self._reconnect_token = None

    # -----------------------------------------------------------------------
    # Internal SDK dispatch hooks
    #
    # These overrides deviate from the public decorator API because the SDK
    # only routes slash commands (``/snapshot``). Text triggers like
    # ``!snapshot`` are not exposed as a decorator-managed command surface, so
    # we intercept ``agent.event`` here, handle the bosun-specific triggers,
    # and delegate everything else to the base class. See the Phase 2 plan
    # doc for the rationale and risk record.
    # -----------------------------------------------------------------------

    async def _handle_event(self, event: AgentEventParams) -> None:
        """Route inbound events to the appropriate handler.

        - ``mls_group_message_received`` with ``!snapshot`` triggers a snapshot in the
          originating Squad.
        - ``dm_received`` with ``!snapshot <squad-id>`` verifies membership before
          triggering a snapshot in that Squad.
        - All other events (including the existing ``/snapshot`` slash command)
          are delegated to the base class.
        """
        event_id = getattr(event, "event_id", None)
        if not event_id:
            self.log("warning: received event without event_id; ignoring")
            return

        if event.type == "mls_group_message_received":
            await self._handle_mls_group_message(event)
            return

        if event.type == "dm_received":
            handled = await self._handle_dm_snapshot(event)
            if handled:
                return

        await super()._handle_event(event)

    async def _handle_mls_group_message(self, event: AgentEventParams) -> None:
        """Handle an MLS group message that may request a snapshot."""
        event_id = event.event_id
        chat_id = getattr(event, "chat_id", None)
        content = (event.content or "").strip()

        if not chat_id:
            self.log(f"warning: mls_group_message_received without chat_id: event_id={event_id}")
            await self._ack(event_id, action="ignore")
            return

        if content != SNAPSHOT_COMMAND:
            await self._ack(event_id, action="ignore")
            return

        if self.own_pubkey and getattr(event, "author", None) == self.own_pubkey:
            await self._ack(event_id, action="ignore")
            return

        # The daemon already validates MLS group membership before delivering
        # the event; we rely on that trust boundary here rather than issuing a
        # redundant RPC. If that assumption changes, call _is_squad_member.
        if not self._check_rate_limit(chat_id):
            self.log(f"info: rate-limiting group snapshot request for {chat_id}")
            await self._ack(event_id, action="ignore")
            return

        try:
            data = await self._post_snapshot_with_lock(chat_id)
        except (PactoClientError, TransportDisconnected, asyncio.TimeoutError) as exc:
            self.log(
                f"warning: transport error while handling group snapshot: "
                f"event_id={event_id} group_id={chat_id} error={type(exc).__name__}: {exc}"
            )
            await self._ack(event_id, action="ignore")
            return
        except Exception as exc:  # noqa: BLE001
            self.log(
                f"error: unexpected group snapshot handler error: "
                f"event_id={event_id} group_id={chat_id} error={type(exc).__name__}: {exc}"
            )
            await self._ack(event_id, action="ignore")
            return

        if data is not None:
            self.log(
                f"info: snapshot triggered by group message: "
                f"event_id={event_id} group_id={chat_id}"
            )
        await self._ack(event_id, action="ignore")

    async def _handle_dm_snapshot(self, event: AgentEventParams) -> bool:
        """Handle a DM that may request a snapshot in a specific Squad.

        Returns ``True`` when the event was consumed here and the caller should
        not fall through to the slash-command handler.
        """
        event_id = event.event_id
        content = (event.content or "").strip()
        author = getattr(event, "author", None)
        tokens = content.split()

        if not tokens or tokens[0] != SNAPSHOT_COMMAND:
            return False

        if len(tokens) < 2:
            # No squad id: fall through to slash-command handling.
            return False

        squad_id = tokens[1]

        if not author:
            self.log(f"warning: dm_received without author: event_id={event_id}")
            await self._ack(event_id, action="ignore")
            return True

        try:
            squad_id = validate.squad_id(squad_id)
            author = validate.pubkey(author)
        except ValueError as exc:
            self.log(f"warning: invalid DM snapshot request: {exc}")
            await self._ack(event_id, action="ignore")
            return True

        try:
            is_member = await self._is_squad_member_with_timeout(squad_id, author)
        except (PactoClientError, TransportDisconnected, asyncio.TimeoutError) as exc:
            self.log(
                f"warning: membership check failed: "
                f"event_id={event_id} squad_id={squad_id} author={author} "
                f"error={type(exc).__name__}: {exc}"
            )
            await self._ack(event_id, action="ignore")
            return True
        except Exception as exc:  # noqa: BLE001
            self.log(
                f"warning: membership check failed: "
                f"event_id={event_id} squad_id={squad_id} author={author} "
                f"error={type(exc).__name__}: {exc}"
            )
            await self._ack(event_id, action="ignore")
            return True

        if not is_member:
            self.log(
                f"warning: {author} is not a member of {squad_id}: event_id={event_id}"
            )
            await self._ack(event_id, action="ignore")
            return True

        if not self._check_rate_limit(squad_id):
            self.log(f"info: rate-limiting DM snapshot request for {squad_id}")
            await self._ack(event_id, action="ignore")
            return True

        try:
            data = await self._post_snapshot_with_lock(squad_id)
        except (PactoClientError, TransportDisconnected, asyncio.TimeoutError) as exc:
            self.log(
                f"warning: transport error while handling DM snapshot: "
                f"event_id={event_id} squad_id={squad_id} author={author} "
                f"error={type(exc).__name__}: {exc}"
            )
            await self._ack(event_id, action="ignore")
            return True
        except Exception as exc:  # noqa: BLE001
            self.log(
                f"error: unexpected DM snapshot handler error: "
                f"event_id={event_id} squad_id={squad_id} author={author} "
                f"error={type(exc).__name__}: {exc}"
            )
            await self._ack(event_id, action="ignore")
            return True

        if data is not None:
            self.log(
                f"info: snapshot triggered by DM: "
                f"event_id={event_id} group_id={squad_id} author={author}"
            )
        await self._ack(event_id, action="ignore")
        return True

    async def _ack(self, event_id: str, action: str = "ignore", content: str | None = None) -> None:
        """Acknowledge an event to the daemon with a bounded RPC timeout."""
        try:
            await asyncio.wait_for(
                self._client.handler_response(
                    action=action, event_id=event_id, content=content
                ),
                timeout=RPC_TIMEOUT_SECONDS,
            )
        except (PactoClientError, TransportDisconnected, asyncio.TimeoutError) as exc:
            self.log(
                f"warning: failed to acknowledge event {event_id}: "
                f"{type(exc).__name__}: {exc}"
            )
        except Exception as exc:  # noqa: BLE001
            self.log(
                f"error: unexpected ack failure for event {event_id}: "
                f"{type(exc).__name__}: {exc}"
            )

    async def _is_squad_member_with_timeout(self, group_id: str, member_pubkey: str) -> bool:
        """Return True when ``member_pubkey`` is a member of the given Squad."""
        return await self.is_squad_member(group_id, member_pubkey)

    def _check_rate_limit(self, group_id: str) -> bool:
        """Return True if the group is allowed to trigger a new snapshot now."""
        now = time.monotonic()
        last_post = self._rate_limit_cache.get(group_id)
        if last_post is not None and now - last_post < DEFAULT_RATE_LIMIT_WINDOW_SECONDS:
            return False
        self._rate_limit_cache[group_id] = now
        return True

    def _rate_limit_window(self, group_id: str) -> int:
        """Return the remaining seconds until the group can snapshot again."""
        now = time.monotonic()
        last_post = self._rate_limit_cache.get(group_id)
        if last_post is None:
            return DEFAULT_RATE_LIMIT_WINDOW_SECONDS
        elapsed = int(now - last_post)
        return max(MIN_RATE_LIMIT_WINDOW_SECONDS, DEFAULT_RATE_LIMIT_WINDOW_SECONDS - elapsed)

    async def _post_snapshot_with_lock(self, group_id: str) -> SnapshotData | None:
        """Run ``snapshot()`` under the instance lock to prevent double-posts."""
        lock = self._get_snapshot_lock()
        async with lock:
            return await asyncio.wait_for(
                snapshot(self, group_id=group_id),
                timeout=SNAPSHOT_LOCK_TIMEOUT_SECONDS,
            )

    async def _handle_rate_limited(self, notification: AgentRateLimitedParams) -> None:
        """Post a rate-limit explanation in the affected Squad."""
        group_id = getattr(notification, "group_id", None)
        if not group_id:
            self.log("warning: agent.rate_limited without group_id")
            return

        window = getattr(notification, "window_seconds", None)
        if window is None:
            window = DEFAULT_RATE_LIMIT_WINDOW_SECONDS
        else:
            try:
                window = int(window)
            except (TypeError, ValueError):
                window = DEFAULT_RATE_LIMIT_WINDOW_SECONDS
            window = max(MIN_RATE_LIMIT_WINDOW_SECONDS, window)

        content = RATE_LIMIT_MESSAGE_TEMPLATE.format(window=window)
        try:
            await self.send_group_message(group_id, content)
        except (PactoClientError, TransportDisconnected, asyncio.TimeoutError) as exc:
            self.log(
                f"warning: failed to send rate-limit message: "
                f"group_id={group_id} error={type(exc).__name__}: {exc}"
            )
        except Exception as exc:  # noqa: BLE001
            self.log(f"error: failed to send rate-limit message: {exc}")

    async def _dispatch_loop(self) -> None:
        """Consume daemon notifications and dispatch to the right handler."""
        try:
            async for notification in self._client.notifications():
                if isinstance(notification, AgentRateLimitedParams):
                    await self._handle_rate_limited(notification)
                elif isinstance(notification, AgentEventParams):
                    await self._handle_event(notification)
                elif isinstance(notification, AgentStatusParams):
                    await super()._handle_status(notification)
                else:
                    self.log(
                        f"warning: unknown notification type: {type(notification).__name__}"
                    )
        except asyncio.CancelledError:
            pass

    async def run_async(self, argv: list[str] | None = None) -> None:
        """Run the daemon dispatch loop with the configured retry/circuit logic."""
        await self._run(argv)

    def run(self, argv: list[str] | None = None) -> None:
        """Parse CLI args, publish KeyPackage, and run dispatch + cadence."""
        try:
            sys.exit(asyncio.run(self.amain(argv)))
        except KeyboardInterrupt:
            sys.exit(130)

    async def _key_package_loop(self) -> None:
        """Publish the bot's MLS KeyPackage after each fresh registration.

        The daemon requires the handler to be registered before it can publish a
        KeyPackage. This loop watches for handler_id changes and retries on a
        short interval so a new KeyPackage is published promptly after startup,
        reconnection, or daemon restart.
        """
        last_handler_id: str | None = None
        while not self._shutdown.is_set():
            handler_id = getattr(self, "_handler_id", None)
            if handler_id and handler_id != last_handler_id:
                try:
                    await self.client.agent_publish_key_package(bot_id=self.bot_id)
                    self.log("published KeyPackage")
                    last_handler_id = handler_id
                except Exception as exc:  # noqa: BLE001
                    self.log(f"warning: failed to publish KeyPackage: {exc}")
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass

    async def amain(self, argv: list[str] | None = None) -> int:
        args = self._parse_args(argv)
        if args.log_level is not None:
            self._logger.set_level(args.log_level)

        if getattr(args, "trigger_snapshot", False):
            return await trigger_once(self)

        await setup(self)
        await asyncio.gather(self.run_async(), self._key_package_loop(), cadence_loop(self))
        return 0
    def _parse_args(self, argv: list[str] | None = None) -> argparse.Namespace:
        """Parse CLI arguments, including the bosun-specific trigger flag.

        The base ``Bot`` parser owns retry/circuit/transport options; we
        pre-parse only our custom flag so those options remain available and
        forward-compatible with SDK updates.
        """
        pre_parser = argparse.ArgumentParser(add_help=False)
        pre_parser.add_argument(
            "--trigger-snapshot",
            action="store_true",
            default=False,
            help="Connect, publish KeyPackage, post one snapshot, and exit.",
        )
        pre_args, remaining_argv = pre_parser.parse_known_args(argv)
        args = super()._parse_args(remaining_argv)
        args.trigger_snapshot = pre_args.trigger_snapshot
        return args


# Module-level bot instance so the decorator API works and tests can import it.
try:
    settings = load_settings()
    bot = BosunBot(settings=settings, **settings.to_bot_transport_kwargs())
except ValueError as exc:
    print(format_settings_error(exc), file=sys.stderr, flush=True)
    sys.exit(1)


async def is_squad_member(bot: BosunBot, group_id: str, member_pubkey: str) -> bool:
    """Return True when ``member_pubkey`` is a member of the given Squad."""
    return await bot.is_squad_member(group_id, member_pubkey)


async def snapshot(bot: BosunBot, group_id: str | None = None) -> SnapshotData | None:
    """Read governance state, format it, and post to the configured group."""
    destination = group_id if group_id is not None else bot.settings.group_id
    if not destination:
        bot.log("warning: refusing snapshot with empty group_id")
        return None
    settings = bot.settings
    reader = GovernanceReader.from_url(
        settings.rpc_url, settings.registry, settings.hats
    )
    try:
        data = await reader.snapshot(
            squad_index=settings.squad_index,
            crew_candidates=settings.crew_candidates,
            proposer_candidates=settings.proposer_candidates,
            captain=settings.captain,
        )
    except Exception as exc:  # noqa: BLE001
        bot.log(f"error: failed to read governance snapshot: {exc}")
        return None

    markdown = format_snapshot(data)
    try:
        await bot.send_group_message(destination, markdown)
        bot.log(f"posted snapshot to {destination}")
    except Exception as exc:  # noqa: BLE001
        bot.log(f"error: failed to send group message: {exc}")
        return None

    return data


async def setup(bot: BosunBot) -> None:
    """Initial setup; publish the bot's KeyPackage so it can be invited to a Squad."""
    try:
        result = await bot.client.agent_publish_key_package(bot_id=bot.bot_id)
        bot.log(f"published KeyPackage: {result}")
    except Exception as exc:  # noqa: BLE001
        bot.log(f"warning: failed to publish KeyPackage: {exc}")


async def cadence_loop(bot: BosunBot) -> None:
    """Fire the snapshot routine at the configured interval.

    Skips ticks when the bot is not yet registered/connected, and exits
    promptly when the SDK's shutdown event is set (e.g. on SIGINT/SIGTERM).
    """
    await asyncio.sleep(0.5)

    while not bot._shutdown.is_set():
        if not getattr(bot, "_handler_id", None):
            bot.log("cadence: not registered yet, skipping tick")
        else:
            try:
                await snapshot(bot)
            except Exception as exc:  # noqa: BLE001
                bot.log(f"cadence tick failed: {exc}")
        try:
            await asyncio.wait_for(
                bot._shutdown.wait(), timeout=bot.settings.cadence_seconds
            )
        except asyncio.TimeoutError:
            pass


@bot.command("/snapshot")
async def snapshot_handler(event, bot):
    """Handle an explicit ``/snapshot`` command."""
    bot.log(f"received /snapshot: event_id={event.event_id}")
    await snapshot(bot)
    return bot.reply(event, "Snapshot posted to the squad channel.")


@bot.default
async def unknown(event, bot):
    bot.log(f"ignoring unknown command: event_id={event.event_id}")
    return bot.ignore(event)


@bot.on_squad_join
async def squad_join_handler(event, bot):
    """Announce the bot when it joins a Squad."""
    chat_id = getattr(event, "chat_id", None)
    if not chat_id:
        bot.log(
            f"warning: mls_welcome_received without chat_id: event_id={event.event_id}"
        )
        return bot.ignore(event)

    try:
        content = SQUAD_JOIN_MESSAGE.format(bot_id=bot.bot_id)
    except Exception as exc:  # noqa: BLE001
        bot.log(f"error: failed to format squad join message: {exc}")
        return bot.ignore(event)

    try:
        await bot.send_group_message(chat_id, content)
        bot.log(f"info: announced join to {chat_id}")
    except (PactoClientError, TransportDisconnected, asyncio.TimeoutError) as exc:
        bot.log(
            f"warning: failed to send squad join announcement: "
            f"group_id={chat_id} error={type(exc).__name__}: {exc}"
        )
    except Exception as exc:  # noqa: BLE001
        bot.log(f"error: unexpected squad join announcement failure: {exc}")

    return bot.ignore(event)


async def trigger_once(bot: BosunBot) -> int:
    """Connect, register, publish KeyPackage, post a snapshot, and exit."""
    await bot.client.connect()
    try:
        result = await bot.client.handler_register(
            bot_ids=[bot.bot_id],
            event_types=bot.event_types,
            capabilities=bot.capabilities,
        )
        bot._handler_id = result.handler_id
        bot._reconnect_token = result.reconnect_token
        bot.log(f"registered handler_id={result.handler_id}")
    except (PactoClientError, TimeoutError, asyncio.TimeoutError) as exc:
        bot.log(f"error: failed to register handler: {exc}")
        return 1

    try:
        kp_result = await bot.client.agent_publish_key_package(bot_id=bot.bot_id)
        bot.log(f"published KeyPackage: {kp_result}")
    except Exception as exc:  # noqa: BLE001
        bot.log(f"warning: failed to publish KeyPackage: {exc}")

    data = await snapshot(bot)
    await bot.client.close()
    return 0 if data is not None else 1


def main() -> None:
    """Entry point for ``python -m bosun.bosun``."""
    bot.run()


if __name__ == "__main__":
    main()
