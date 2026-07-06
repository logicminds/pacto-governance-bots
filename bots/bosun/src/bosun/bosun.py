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

from pacto_bot_sdk import Bot

from bosun.config import load_settings
from bosun.formatter import format_snapshot
from bosun.reader import GovernanceReader
from bosun.types import SnapshotData


class BosunBot(Bot):
    """Small subclass that adds a cadence loop alongside the dispatch loop."""

    def __init__(self, settings: Any, **kwargs: Any) -> None:
        self.settings = settings
        super().__init__(
            bot_id=settings.bot_id,
            capabilities=["SendGroupMessages"],
            event_types=[],
            **kwargs,
        )

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
        """Parse CLI arguments, including the bosun-specific trigger flag."""
        parser = argparse.ArgumentParser(description=f"Pacto bot: {self.bot_id}")
        parser.add_argument(
            "--socket",
            default=None,
            help="Path to the daemon Unix socket.",
        )
        parser.add_argument(
            "--data-dir",
            default=None,
            help="Data directory used to derive defaults.",
        )
        parser.add_argument(
            "--transport",
            default=None,
            help="Transport to use (unix or http). Defaults to $PACTO_TRANSPORT or unix.",
        )
        parser.add_argument(
            "--http-bind",
            default=None,
            help="HTTP bind address (default: $PACTO_HTTP_BIND or 127.0.0.1:9800).",
        )
        parser.add_argument(
            "--secret",
            default=None,
            help="HTTP secret token (default: $PACTO_SECRET_TOKEN).",
        )
        parser.add_argument(
            "--log-level",
            default=None,
            help="Set log level (debug, info, warn, error).",
        )
        parser.add_argument(
            "--trigger-snapshot",
            action="store_true",
            help="Connect, publish KeyPackage, post one snapshot, and exit.",
        )
        return parser.parse_args(argv)


# Module-level bot instance so the decorator API works and tests can import it.
settings = load_settings()
bot = BosunBot(settings=settings, **settings.to_bot_transport_kwargs())


async def setup(bot: BosunBot) -> None:
    """Publish the bot's KeyPackage so it can be invited to a Squad."""
    try:
        result = await bot.client.agent_publish_key_package(bot_id=bot.bot_id)
        bot.log(f"published KeyPackage: {result}")
    except Exception as exc:  # noqa: BLE001
        bot.log(f"warning: failed to publish KeyPackage: {exc}")


async def snapshot(bot: BosunBot) -> SnapshotData | None:
    """Read governance state, format it, and post to the configured group."""
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
            group_id=settings.group_id,
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
    start waits for the initial setup to complete.
    """
    # Wait for setup to finish before the first tick.
    await asyncio.sleep(0.5)

    while True:
        # Check whether the bot is registered with the daemon. _handler_id is set
        # by the Bot class after a successful handler.register call.
        if not getattr(bot, "_handler_id", None):
            bot.log("cadence: not registered yet, skipping tick")
        else:
            try:
                await snapshot(bot)
            except Exception as exc:  # noqa: BLE001
                bot.log(f"cadence tick failed: {exc}")
        await asyncio.sleep(bot.settings.cadence_seconds)


async def trigger_once(bot: BosunBot) -> int:
    """Connect, publish KeyPackage, post a snapshot, and exit."""
    await bot.client.connect()
    await setup(bot)
    data = await snapshot(bot)
    await bot.client.close()
    return 0 if data is not None else 1


def main() -> None:
    """Entry point for ``python -m bosun.bosun``."""
    bot.run()


if __name__ == "__main__":
    main()
