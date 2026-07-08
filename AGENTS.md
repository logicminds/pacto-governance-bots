# Agent Instructions for bosun Project

This file guides AI assistants working on the `bosun` Pacto bot project.

## Project context

This is a Pacto bot handler project. The Rust daemon `pacto-bot-api` manages
bot identities, Nostr relay connections, and encrypted messaging. The Python
bot handler in `bots/` connects to the daemon over a Unix socket or HTTP using
the `pacto_bot_sdk` SDK.

Local development relies on the sibling [`pacto-dev-env`](https://github.com/covenant-gov/pacto-dev-env)
repository, which provides the Nostr relay, Anvil EVM testnet, optional Aztec
sandbox, optional NIP-46 bunker, and the `pacto-bot-api` daemon. This
repository's `docker-compose.yml` only defines the `bosun` bot service and
attaches to the shared `pacto` network and daemon socket volume from
`pacto-dev-env`.

## Key files

- `pacto-bot-api.toml` — daemon configuration with bot identities, relays, and
  signing backends. Created by `pacto-bot-admin` inside the `pacto-dev-env`
  repository. Treat as secret; contains or references signing material. This
  bot repository does not generate or store the daemon config.
- `docker-compose.yml` — local bot orchestration. Defines only the `bosun`
  bot service. It expects the `pacto` network and `pacto-bot-api-data` volume
  to exist (created by `pacto-dev-env`). Start `pacto-dev-env` first, then
  run `docker compose up -d` from this repo.
- `bots/bosun/.env.example` — environment variables for the bot. Fill these in
  and copy to `bots/bosun/.env` or export them before running the bot.
- `bots/bosun/bosun.py` — the bot handler entry point.
- `bots/bosun/pyproject.toml` — Python package metadata for the bot. The
  bot depends on the `pacto-bot-sdk` PyPI package.
- `.pacto/bots/bosun/scaffold.lock` — records the resolved contract,
  SDK, and template versions used to create this project. Check it into version
  control.

## Working conventions

- Use the `python-pacto-bot` skill before writing or modifying bot code.
- Keep bot logic in `bots/<bot-id>/`. Add new bots with
  `pacto-bot-admin scaffold <bot-id>` rather than hand-creating files.
- Do not edit `pacto-bot-api.toml` signing material by hand; use
  `pacto-bot-admin` for identity operations.
- Never commit real `nsec`, bunker URIs, or daemon secrets to version control.

## When asked to write a bot

1. Read the `python-pacto-bot` skill.
2. Inspect the existing handler in `bots/bosun/bosun.py` and the
   capabilities in `pacto-bot-api.toml`.
3. Add or edit command handlers using the `Bot` decorator API from the SDK.
4. Run the generated tests in `bots/bosun/tests/test_handlers.py` to verify.

## When asked to add a bot

Use `pacto-bot-admin scaffold <bot-id> --commands <cmd1,cmd2>`. If the bot
identity does not exist yet, create it first with `pacto-bot-admin new`.

## When asked to update the project

Run `pacto-bot-admin update` from the project root. The CLI will re-render the
bot from the locked template and show a diff before overwriting non-protected
files. Protected files are skipped unless you pass `--force`.
