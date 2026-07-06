---
title: Python Governance Snapshot Bot — Standalone Repo Requirements
date: 2026-07-05
topic: python-governance-snapshot-bot
type: feat
origin: ce-brainstorm dialogue and docs/plans/2026-07-03-001-feat-governance-snapshot-mls-tee-bot-plan.md
---

# Python Governance Snapshot Bot — Standalone Repo Requirements

## Summary

Create a standalone Python governance snapshot bot named **bosun** in a new public repository `logicminds/pacto-governance-bots`, cloned locally at `~/projects/pacto-governance-bots`. The project is scaffolded by `pacto-bot-admin new --scaffold bosun`, using the generated Python SDK for daemon JSON-RPC and its built-in retry/circuit primitives. The bot implements Phase 1 of the existing governance snapshot plan: periodic on-chain reads from Sepolia/anvil Pacto-gov contracts, Markdown formatting, and autonomous posting to an MLS Squad channel via `agent.send_group_message`. Phase 2 (`!snapshot` interactive command) is deferred with a short write-up.

## Problem Frame

The existing governance snapshot bot is a Rust example crate (`crates/governance-bot/`) inside `pacto-bot-api`. It proves the daemon's MLS send-only path and the Pacto-gov reader pattern, but it ties the bot's release cadence to the daemon's Rust crate and requires Rust tooling to run or modify. The Python SDK is the intended first-class authoring surface for bot handlers, and the admin CLI already scaffolds Python projects. A separate Python repository makes the governance snapshot bot easier to clone, configure, and iterate on without touching the daemon, and it validates the scaffold-to-SDK workflow end-to-end.

## Key Decisions

- **Python-native, standalone repo.** The bot is written in Python for the Python SDK runtime, lives in its own repository, and is not a migration that removes the Rust governance crate.
- **Scaffolded by `pacto-bot-admin`.** New projects are created with `pacto-bot-admin new --scaffold <bot-id>`, then the governance-specific snapshot logic is added on top of the scaffolded base.
- **SDK-provided retry and backoff.** Reconnection and failure retry are handled by the Python SDK's `Bot` / `RetryCircuit` primitives rather than a custom bot-level loop.
- **Phase 1 only.** The initial implementation covers autonomous daily snapshot posts. Inbound MLS decryption and the `!snapshot` command are deferred.
- **Named repo and bot identity.** The repository is `logicminds/pacto-governance-bots` (public), the local clone lives at `~/projects/pacto-governance-bots`, and the bot identity is `bosun`.

## Requirements

### Functional behavior (Phase 1)

R1. The bot identity is `bosun`. It is created and configured with `pacto-bot-admin` (`pacto-bot-admin new` or `pacto-bot-admin new --scaffold`) and exists in `pacto-bot-api.toml` before the Python bot starts.

R2. On startup, the bot publishes its MLS KeyPackage by calling `agent.publish_key_package` so an existing squad member can invite it. It is not responsible for creating the squad or issuing the Welcome; it only accepts the Welcome once delivered.

R3. The bot reads public on-chain governance and treasury state from a configurable RPC endpoint. Target chains are Sepolia (chain ID 11155111) for live use and anvil (chain ID 31337) for local development. Per-squad clone addresses are discovered via `NavePirataRegistry.deploymentCount()` / `deploymentAt(i)` / `deployment(topHatId)`.

R4. The bot formats a Markdown snapshot covering the sections defined in the original governance plan: active proposals, upcoming crew deadlines, treasury/Safe balances, active mutinies, captain/crew state, and suggested discussion prompts derived from the data.

R5. The bot posts the formatted snapshot to a configured MLS Squad channel by calling `agent.send_group_message` on a configurable cadence (default daily).

R6. The bot posts autonomously. There is no human-paste fallback for delivering the snapshot.

R7. The handler owns the snapshot cadence timer and the RPC endpoint configuration, not the daemon. These settings live in the Python bot's configuration, not in `pacto-bot-api.toml`.

### Python SDK integration

R8. The bot is built on the generated Python SDK's `Bot` class (`python/src/pacto_bot_sdk/bot.py`). It registers with the daemon using `Bot`'s internal `handler.register` flow, and it calls `bot.client.agent_publish_key_package` and `bot.client.agent_send_group_message` through the underlying `PactoClient`.

R9. Reconnection, retry, and circuit-breaker behavior are provided by the `Bot` class's built-in `RetryCircuit` / reconnection loop. The bot itself does not implement a separate retry/backoff wrapper.

R10. The bot implements a `/snapshot` command handler using the `Bot` decorator API (`@bot.command("/snapshot")`). The handler calls the same read-format-send flow used by the daily cadence. Phase 2 enables inbound `!snapshot` invocation from the Squad channel; Phase 1 tests the handler via an external trigger.

### Scaffolding and repository structure

R11. A new project can be created by running `pacto-bot-admin new --scaffold <bot-id>` with the appropriate language/template selection, producing a runnable Python handler base.

R12. The governance-specific code is layered on top of the scaffolded base in a separate repository. That repo contains a complete, runnable bot project, not just a template.

R13. The repository is created as `logicminds/pacto-governance-bots` on GitHub, public, and cloned locally to `~/projects/pacto-governance-bots`.

R14. The project is scaffolded with `pacto-bot-admin new --scaffold bosun` (or `pacto-bot-admin scaffold bosun --project-dir .`) so the generated Python SDK and base handler structure are present in the repository.

R15. The repository includes a `README.md` with setup steps: clone the repo, install the scaffolded Python SDK dependency, run `pacto-bot-admin` to create the bot identity, configure environment variables, publish the KeyPackage, accept the Welcome, and run the bot.

R16. For local development, the active directory is `~/projects/pacto-governance-bots`; all `pacto-bot-admin` commands and Python invocations are documented relative to that path.

### Configuration compatibility

R17. Where the Rust governance bot uses environment variables (`PACTO_GOVERNANCE_RPC_URL`, `PACTO_GOVERNANCE_BOT_ID`, `PACTO_GOVERNANCE_GROUP_ID`, `PACTO_GOVERNANCE_DAEMON_SOCKET`, `PACTO_GOVERNANCE_DAEMON_HTTP`, `PACTO_GOVERNANCE_HTTP_SECRET`, `PACTO_GOVERNANCE_SQUAD_INDEX`, `PACTO_GOVERNANCE_CADENCE_SECONDS`, `PACTO_GOVERNANCE_CAPTAIN`, `PACTO_GOVERNANCE_CREW_CANDIDATES`, `PACTO_GOVERNANCE_PROPOSER_CANDIDATES`), the Python bot uses the same names and semantics. Additional Python-native conveniences (e.g., `.env` loading, `pydantic-settings`) are allowed but must not change the env var surface.

### Testing and quality

R18. The repository includes unit tests for the on-chain reader and the Markdown formatter that run without a live daemon, anvil, or relay. Mock or stub EVM responses are acceptable for the default test suite.

R19. The repository includes an integration test or documented manual procedure that exercises the full flow against a running daemon and a deployed squad. This test is gated (e.g., `PACTO_DEV_ENV=1` or a separate CI job) and does not run in the default test suite.

R20. No production secrets (`nsec`, bunker URI, HTTP token, or MLS group state/key material) are committed, logged, or returned in error messages.

## Scope Boundaries

### Deferred for later

- Phase 2 `!snapshot` interactive command. See the write-up below.
- TEE deployment architecture. The original plan already covers this in `docs/plans/2026-07-03-001-feat-governance-snapshot-mls-tee-bot-plan.md`; the Python bot repo does not reproduce that brief.
- PyPI publication of the Python SDK. The SDK is currently distributed through the scaffold; this repo assumes the SDK reaches the project via `pacto-bot-admin new --scaffold`, not `pip install pacto-bot-sdk`.

### Outside this product's identity

- Replacing or removing the Rust governance crate (`crates/governance-bot/`). The Python bot is a new implementation; the Rust crate remains.
- Modifying the daemon's MLS extension or JSON-RPC contract. The Python bot consumes the existing contract; it does not change `pacto-bot-api` itself.
- A general-purpose no-code bot builder or non-Pacto chat integrations.

## Phase 2 Deferral: `!snapshot` Interactive Command

Phase 2 adds inbound MLS group-message handling so squad members can type `!snapshot` in the channel and trigger an on-demand snapshot post. The `/snapshot` command handler is already implemented in Phase 1; Phase 2 only changes how it is invoked. Phase 2 requires:

- A new `ReceiveGroupMessages` capability in the daemon, distinct from `SendGroupMessages`.
- A `Kind::MlsGroupMessage` (kind:445) subscription in the daemon, separate from the GiftWrap subscription that carries Welcomes.
- Daemon-side decryption of inbound MLS messages via `engine.process_message()` and delivery to handlers as a new `agent.event` notification type.
- Adding `ReceiveGroupMessages` to the bot's registration and wiring the inbound `!snapshot` event to the existing `/snapshot` handler.

Phase 2 is intentionally excluded from this initial Python bot implementation. It is gated on Phase 1 success in the original plan, and the Python bot should first prove the send-only daily snapshot path before adding inbound decryption. The repository's README may note Phase 2 as a planned follow-up.

## Dependencies and Assumptions

- The daemon MLS extension described in `docs/plans/2026-07-03-001-feat-governance-snapshot-mls-tee-bot-plan.md` (units U1–U7) is already implemented, so `agent.send_group_message` and `agent.publish_key_package` are available and authorized via the `SendGroupMessages` capability.
- The Python SDK supports `handler_register`, `agent_publish_key_package`, and `agent_send_group_message` through generated Pydantic models and the `PactoClient` / `Bot` API.
- `pacto-bot-admin` can scaffold a Python handler project with a compatible SDK/template triple.
- The active project clone lives at `~/projects/pacto-governance-bots` and the remote is `https://github.com/logicminds/pacto-governance-bots` (public). The bot identity is `bosun`.
- The Python bot performs EVM reads using a Python-native Ethereum library (e.g., `web3.py` or `eth-abi` with raw RPC calls). The exact library is left to implementation planning.
- The SDK's retry/circuit primitives are sufficient for the bot's reconnection needs; if gaps are found, the SDK is the right place to fix them, not the bot.

## Sources and Research

- `docs/plans/2026-07-03-001-feat-governance-snapshot-mls-tee-bot-plan.md` — original governance snapshot plan, including requirements R1–R7 and Phase 2 R21–R25.
- `crates/governance-bot/` — existing Rust example implementation, including env var surface and README setup.
- `python/src/pacto_bot_sdk/` — generated Python SDK with `handler_register`, `agent_publish_key_package`, and `agent_send_group_message`.
- `src/admin.rs` and `src/scaffold/` — admin CLI scaffolding flow and `cargo-generate` template resolution.
- `python/examples/greeting_bot.py` and `python/examples/joke_bot.py` — reference Python bots using the SDK decorator API.
