"""Bosun governance snapshot bot.

Registers with the daemon, publishes its MLS KeyPackage on startup, responds to
``/snapshot`` commands and ``!snapshot`` text triggers, and posts a daily
on-chain governance snapshot to a configured MLS Squad channel.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

from pacto_bot_sdk import (
    AgentRateLimitedParams,
    Bot,
    validate,
)

from bosun.config import format_settings_error, load_settings
from bosun.formatter import format_snapshot
from bosun.reader import GovernanceReader
from bosun.types import SnapshotData


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


@bot.event("mls_group_message_received")
@bot.lock("snapshot")
async def handle_mls_group_message(event, bot):
    """Handle an MLS group message that requests a snapshot."""
    chat_id = (event.chat_id or "").strip()
    content = (event.content or "").strip()
    if not chat_id:
        bot.log(f"warning: mls_group_message_received without chat_id: event_id={event.event_id}")
        return bot.ignore(event)
    try:
        chat_id = validate.squad_id(chat_id)
    except ValueError as exc:
        bot.log(f"warning: invalid chat_id in mls_group_message_received: {exc}")
        return bot.ignore(event)
    if bot.own_pubkey and getattr(event, "author", None) == bot.own_pubkey:
        return bot.ignore(event)
    if content != SNAPSHOT_COMMAND:
        return bot.ignore(event)
    try:
        await snapshot(bot, group_id=chat_id)
    except Exception as exc:  # noqa: BLE001
        bot.log(f"error: group snapshot handler failed: {exc}")
    return bot.ignore(event)


@bot.hears("!snapshot")
@bot.lock("snapshot")
async def handle_dm_snapshot(event, bot):
    """Handle a DM that requests a snapshot in a specific Squad."""
    if event.type != "dm_received":
        return bot.ignore(event)
    content = (event.content or "").strip()
    author = getattr(event, "author", None)
    tokens = content.split()
    if len(tokens) < 2:
        return bot.ignore(event)
    squad_id = tokens[1]
    if not author:
        bot.log(f"warning: dm_received without author: event_id={event.event_id}")
        return bot.ignore(event)
    try:
        squad_id = validate.squad_id(squad_id)
        author = validate.pubkey(author)
    except ValueError as exc:
        bot.log(f"warning: invalid DM snapshot request: {exc}")
        return bot.ignore(event)
    try:
        is_member = await bot.is_squad_member(squad_id, author)
    except Exception as exc:  # noqa: BLE001
        bot.log(
            f"warning: membership check failed: "
            f"event_id={event.event_id} squad_id={squad_id} author={author} "
            f"error={exc}"
        )
        return bot.ignore(event)
    if not is_member:
        bot.log(f"warning: {author} is not a member of {squad_id}")
        return bot.ignore(event)
    try:
        await snapshot(bot, group_id=squad_id)
    except Exception as exc:  # noqa: BLE001
        bot.log(f"error: DM snapshot handler failed: {exc}")
    return bot.ignore(event)


@bot.rate_limited
async def handle_rate_limited(notification: AgentRateLimitedParams, bot):
    """Post a rate-limit explanation in the affected Squad."""
    group_id = getattr(notification, "group_id", None)
    if not group_id:
        bot.log("warning: agent.rate_limited without group_id")
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
        await bot.send_group_message(group_id, content)
    except Exception as exc:  # noqa: BLE001
        bot.log(f"warning: failed to send rate-limit message: {exc}")


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
                await snapshot(bot, bot.settings.group_id)
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
