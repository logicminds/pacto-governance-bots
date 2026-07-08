"""Bosun governance snapshot bot.

Registers with the daemon, publishes its MLS KeyPackage on startup, responds to
``/snapshot`` commands, and posts a daily on-chain governance snapshot to a
configured MLS Squad channel.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from typing import Any

from pacto_bot_sdk import AgentEventParams, AgentRateLimitedParams, AgentStatusParams, Bot

from bosun.config import format_settings_error, load_settings
from bosun.formatter import format_snapshot
from bosun.reader import GovernanceReader
from bosun.types import SnapshotData


class BosunBot(Bot):
    """Small subclass that adds a cadence loop alongside the dispatch loop."""

    def __init__(self, settings: Any, **kwargs: Any) -> None:
        self.settings = settings
        super().__init__(
            bot_id=settings.bot_id,
            capabilities=["SendGroupMessages", "ReceiveGroupMessages"],
            event_types=["dm_received", "mls_group_message_received"],
            **kwargs,
        )

    async def _handle_event(self, event: AgentEventParams) -> None:
        """Route inbound events to the appropriate handler.

        - ``mls_group_message_received`` with ``!snapshot`` triggers a snapshot in the
          originating Squad.
        - ``dm_received`` with ``!snapshot <squad-id>`` verifies membership before
          triggering a snapshot in that Squad.
        - All other events (including the existing ``/snapshot`` slash command)
          are delegated to the base class.
        """
        content = event.content.strip()

        if event.type == "mls_group_message_received":
            if getattr(self, "own_pubkey", None) and event.author == self.own_pubkey:
                return
            if event.chat_id is None:
                self.log("warning: mls_group_message_received without chat_id")
                return
            if content == "!snapshot":
                try:
                    await snapshot(self, group_id=event.chat_id)
                except Exception as exc:  # noqa: BLE001
                    self.log(f"error: snapshot handler failed: {exc}")
            return

        if event.type == "dm_received":
            if content.startswith("!snapshot"):
                tokens = content.split()
                if len(tokens) >= 2:
                    squad_id = tokens[1]
                    try:
                        is_member = await is_squad_member(self, squad_id, event.author)
                    except Exception as exc:  # noqa: BLE001
                        self.log(f"warning: membership check failed: {exc}")
                        return
                    if is_member:
                        try:
                            await snapshot(self, group_id=squad_id)
                        except Exception as exc:  # noqa: BLE001
                            self.log(f"error: snapshot handler failed: {exc}")
                    else:
                        self.log(
                            f"warning: {event.author} is not a member of {squad_id}"
                        )
                    return
                # No squad id: fall through to slash-command handling.

        await super()._handle_event(event)

    async def _handle_rate_limited(self, notification: AgentRateLimitedParams) -> None:
        """Post a rate-limit explanation in the affected Squad."""
        group_id = notification.group_id
        window = getattr(notification, "window_seconds", 60)
        if not group_id:
            self.log("warning: agent.rate_limited without group_id")
            return

        content = (
            f"> Rate limit: one snapshot per minute per Squad. "
            f"Try again in ~{window} seconds."
        )
        try:
            await self.client.agent_send_group_message(
                bot_id=self.bot_id,
                content=content,
                group_id=group_id,
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

    async def amain(self, argv: list[str] | None = None) -> int:
        args = self._parse_args(argv)
        if args.log_level is not None:
            self._logger.set_level(args.log_level)

        if getattr(args, "trigger_snapshot", False):
            return await trigger_once(self)

        await setup(self)
        await asyncio.gather(self.run_async(), cadence_loop(self))
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


async def setup(bot: BosunBot) -> None:
    """Connect to the daemon and publish the bot's KeyPackage so it can be invited to a Squad."""
    try:
        await bot.client.connect()
        result = await bot.client.agent_publish_key_package(bot_id=bot.bot_id)
        bot.log(f"published KeyPackage: {result}")
    except Exception as exc:  # noqa: BLE001
        bot.log(f"warning: failed to publish KeyPackage: {exc}")


async def is_squad_member(bot: BosunBot, group_id: str, member_pubkey: str) -> bool:
    """Return True when ``member_pubkey`` is a member of the given Squad."""
    response = await bot.client.agent_is_squad_member(
        bot_id=bot.bot_id,
        group_id=group_id,
        member_pubkey=member_pubkey,
    )
    return response.is_member


async def snapshot(bot: BosunBot, group_id: str | None = None) -> SnapshotData | None:
    """Read governance state, format it, and post to the configured group."""
    destination = group_id if group_id is not None else bot.settings.group_id
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
        result = await bot.client.agent_send_group_message(
            bot_id=bot.bot_id,
            content=markdown,
            group_id=destination,
        )
        bot.log(f"posted snapshot: {result}")
    except Exception as exc:  # noqa: BLE001
        bot.log(f"error: failed to send group message: {exc}")
        return None

    return data


@bot.command("/snapshot")
async def snapshot_handler(event, bot):
    """Handle an explicit ``/snapshot`` command."""
    bot.log(f"received /snapshot: event_id={event.event_id}")
    await snapshot(bot)
    return {
        "event_id": event.event_id,
        "action": "reply",
        "content": "Snapshot posted to the squad channel.",
    }


@bot.default
async def unknown(event, bot):
    bot.log(f"ignoring unknown command: event_id={event.event_id}")
    return {"event_id": event.event_id, "action": "ignore"}


async def cadence_loop(bot: BosunBot) -> None:
    """Fire the snapshot routine at the configured interval.

    Skips ticks when the bot is not yet registered/connected, and on first
    start waits for the initial setup to complete. Exits promptly when the
    SDK's shutdown event is set (e.g. on SIGINT/SIGTERM).
    """
    # Wait for setup to finish before the first tick.
    await asyncio.sleep(0.5)

    while not bot._shutdown.is_set():
        # Check whether the bot is registered with the daemon. _handler_id is set
        # by the Bot class after a successful handler.register call.
        if not getattr(bot, "_handler_id", None):
            bot.log("cadence: not registered yet, skipping tick")
        else:
            try:
                await snapshot(bot)
            except Exception as exc:  # noqa: BLE001
                bot.log(f"cadence tick failed: {exc}")

        try:
            # Sleep, but wake immediately if the SDK signals shutdown.
            await asyncio.wait_for(
                bot._shutdown.wait(), timeout=bot.settings.cadence_seconds
            )
        except asyncio.TimeoutError:
            pass


async def trigger_once(bot: BosunBot) -> int:
    """Connect, publish KeyPackage, post a snapshot, and exit."""
    await setup(bot)
    data = await snapshot(bot)
    await bot.client.close()
    return 0 if data is not None else 1


def main() -> None:
    """Entry point for ``python -m bosun.bosun``."""
    bot.run()


if __name__ == "__main__":
    main()
