# Bosun — Pacto Governance Snapshot Bot

Bosun is a Python bot handler for the [`pacto-bot-api`](https://github.com/covenant-gov/pacto-bot-api) daemon. It posts Markdown snapshots of on-chain Pacto governance state to an MLS Squad channel on demand.

## What it does

- Connects to the `pacto-bot-api` daemon over Unix socket or HTTP.
- Reads public Pacto-governance state from a configured EVM RPC endpoint (Sepolia or anvil).
- Formats a Markdown snapshot covering active proposals, upcoming crew deadlines, treasury balances, active mutinies, captain/crew state, and suggested prompts.
- Responds to `!snapshot` messages in Squad channels.
- Posts snapshots on demand via `agent.send_group_message`.

## Repository layout

```
pacto-governance-bots/
├── bots/
│   └── bosun/
│       ├── src/bosun/          # bot package
│       │   ├── __init__.py
│       │   ├── bosun.py        # entry point, command handler
│       │   ├── config.py       # env-var configuration layer
│       │   ├── contracts.py    # ABI fragments for Pacto-gov contracts
│       │   ├── reader.py       # AsyncWeb3 on-chain reader
│       │   ├── formatter.py    # Markdown snapshot formatter
│       │   ├── types.py        # snapshot data types
│       │   └── addresses.py    # canonical Sepolia addresses
│       ├── tests/
│       │   ├── test_config.py
│       │   ├── test_reader.py
│       │   ├── test_formatter.py
│       │   ├── test_bosun.py
│       │   ├── test_contract.py
│       │   └── test_handlers.py
│       ├── pyproject.toml
│       ├── README.md
│       ├── .env.example
│       ├── Dockerfile
│       └── systemd.service
├── README.md                   # this file
├── docker-compose.yml
├── AGENTS.md
└── pacto-bot-api.toml          # daemon config (generated, do not commit)
```

## Prerequisites

- Python 3.10+
- `pacto-bot-admin` CLI (from `pacto-bot-api`)
- For the complete cross-repo walkthrough, see [SETUP.md](SETUP.md).
- For local contract testing: the `pacto-dev-env` Anvil service with deployed Pacto-gov contracts (via `make seed`)

## Quick start

```bash
cd /path/to/pacto-dev-env
make up-all          # start relay + anvil + pacto-bot-api + seed
make seed-squad      # create the MLS Squad and provision the bot
```

Then, in `pacto-governance-bots`:

```bash
make env             # generate bots/bosun/.env from the local deployment
make health-check    # verify the integration is alive
```

This writes registry, Hats, RPC, and daemon-socket placeholders into
`bots/bosun/.env`. Set `PRESERVE_ENV=1 make env` to keep an existing `.env`.

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/logicminds/pacto-governance-bots.git ~/projects/pacto-governance-bots
cd ~/projects/pacto-governance-bots
```

### 2. Create the bot identity

From the repo root:

```bash
pacto-bot-admin new --scaffold bosun --backend nsec \
  --relays ws://localhost:7000 --commands snapshot
```

This generates `pacto-bot-api.toml` and the bot package. If you are working
from a fresh clone without the generated files, you can also run the scaffold
step first.

### 3. Install the bot package

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e bots/bosun
```

### 4. Configure environment variables

For local development with `pacto-dev-env`, run the generator first:

```bash
make env
```

It reads `../pacto-dev-env/data/deployments/31337/full-system.json`
(respecting `PACTO_DEV_ENV_DIR`) and writes `bots/bosun/.env` with the
deployed registry and Hats addresses, the anvil RPC endpoint, and the daemon
socket path. Set `PRESERVE_ENV=1` to keep an already-edited `.env`.

For non-local deployments, copy the example file and fill in the real values:

```bash
cp bots/bosun/.env.example bots/bosun/.env
# edit bots/bosun/.env
```

Required:

| Variable | Description |
|---|---|
| `PACTO_GOVERNANCE_RPC_URL` | JSON-RPC endpoint (Sepolia or anvil) |
| `PACTO_GOVERNANCE_BOT_ID` | Bot identity registered with the daemon (`bosun`) |
| `PACTO_GOVERNANCE_DAEMON_SOCKET` **or** `PACTO_GOVERNANCE_DAEMON_HTTP` | Daemon transport |

If using HTTP transport, also set `PACTO_GOVERNANCE_HTTP_SECRET`.

Optional variables:

| Variable | Default | Description |
|---|---|---|
| `PACTO_GOVERNANCE_SQUAD_INDEX` | `0` | Registry deployment index |
| `PACTO_GOVERNANCE_CAPTAIN` | zero address | Captain address for Hats checks |
| `PACTO_GOVERNANCE_CREW_CANDIDATES` | none | Comma-separated crew candidate addresses |
| `PACTO_GOVERNANCE_PROPOSER_CANDIDATES` | none | Comma-separated proposer candidate addresses |
| `PACTO_GOVERNANCE_REGISTRY` | Sepolia | Override NavePirataRegistry address. When using Anvil, set this to the `navePirataRegistry` value from `pacto-dev-env/data/deployments/31337/full-system.json`. |
| `PACTO_GOVERNANCE_HATS` | Sepolia | Override Hats Protocol address. When using Anvil, set this to the `hats` value from `pacto-dev-env/data/deployments/31337/full-system.json`. |

### 5. Start the bot (Docker Compose)

For local development, start the backing services in `pacto-dev-env` first:

```bash
cd /path/to/pacto-dev-env
make up          # default stack: relay + anvil + pacto-bot-api
# or, to also deploy Pacto governance contracts to Anvil:
make up-all
```

Then start the bot from this repository:

```bash
cd /path/to/pacto-governance-bots
cp bots/bosun/.env.example bots/bosun/.env
# edit bots/bosun/.env with the deployed anvil addresses if applicable

docker compose up -d --build
```

The bot container attaches to the `pacto` network from `pacto-dev-env` and
reads the daemon socket from the shared `pacto-bot-api-data` volume. It uses
service names instead of `localhost`:

- `http://anvil:8545` for the EVM RPC
- `/var/lib/pacto-bot-api/pacto-bot-api.sock` for the daemon socket

### 6. Run the bot locally (without Docker)

```bash
source .venv/bin/activate
python -m bosun
```

The bot will register with the daemon and wait for incoming commands and Squad
messages.

## Testing

Run the unit tests (no daemon, anvil, or relay required):

```bash
source .venv/bin/activate
PACTO_GOVERNANCE_RPC_URL=http://localhost:8545 \
PACTO_GOVERNANCE_BOT_ID=bosun \
PACTO_GOVERNANCE_DAEMON_SOCKET=/tmp/pacto-test.sock \
pytest bots/bosun/tests
```

For tests against a live daemon and anvil deployment, set `PACTO_DEV_ENV=1` and
run the gated integration procedure described in `bots/bosun/tests/README.md`.

## Security

- Never commit `pacto-bot-api.toml`, `.env`, or any file containing `nsec`, bunker URIs, or HTTP secrets.
- The bot rejects values that look like `nsec1...` secrets in address fields.
- Run the secret scan helper before committing:
  ```bash
  make secret-lint
  ```

## Phase 2

Phase 2 adds inbound triggers so squad members can request a snapshot without
operator access to the bot.

### `!snapshot` in a Squad channel

Any member of an MLS Squad where the bot is present can type:

```
!snapshot
```

The daemon decrypts the group message and delivers it to the bot as an
`mls_group_message_received` event. Bosun reads the message, confirms the
author is not the bot itself (when the bot's own pubkey is known), and posts a
fresh governance snapshot back to the same Squad using `event.chat_id` as the
destination. The same `snapshot()` coroutine used by the other inbound handlers
is invoked, so the output is identical.

Messages that are not exactly `!snapshot` (after whitespace trimming) are
ignored silently. If a group message arrives without a `chat_id`, the bot logs
a warning and drops it.

### Rate-limit response

The daemon enforces a per-Squad rate limit on `!snapshot` triggers. When the
limit is exceeded, the daemon sends the bot an `agent.rate_limited`
notification. Bosun posts a short Markdown message in the affected Squad:

```
> Rate limit: one snapshot per minute per Squad. Try again in ~60 seconds.
```

The retry window comes from the notification's `window_seconds` field (60
seconds by default if the daemon does not provide it). The bot does not attempt
a full snapshot in response to this notification. If the notification lacks a
`group_id`, the bot logs a warning and drops it.

### DM-triggered `!snapshot <squad-id>`

A squad member can also request a snapshot by DMing the bot with a target Squad:

```
!snapshot <squad-id>
```

Bosun verifies the sender's membership in the referenced Squad by calling
`agent.is_squad_member(bot_id, squad_id, sender_pubkey)`. Only if the sender is a
member does the bot post the snapshot to that Squad. If membership verification
fails, an error occurs, or the DM does not include a squad identifier, the bot
logs a warning and does not send a snapshot. A plain `!snapshot` DM with no squad
id is ignored.

### Configuration

No new required environment variables are introduced in Phase 2. All new behavior
works with the existing Phase 1 configuration.

## License

MIT OR Apache-2.0
