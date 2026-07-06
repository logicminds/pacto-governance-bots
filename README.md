# Bosun — Pacto Governance Snapshot Bot

Bosun is a Python bot handler for the [`pacto-bot-api`](https://github.com/covenant-gov/pacto-bot-api) daemon. It posts a daily Markdown snapshot of on-chain Pacto governance state to an MLS Squad channel.

## What it does

- Connects to the `pacto-bot-api` daemon over Unix socket or HTTP.
- Publishes its MLS KeyPackage on startup so it can be invited to a Squad.
- Reads public Pacto-governance state from a configured EVM RPC endpoint (Sepolia or anvil).
- Formats a Markdown snapshot covering active proposals, upcoming crew deadlines, treasury balances, active mutinies, captain/crew state, and suggested prompts.
- Posts the snapshot daily to a configured MLS group via `agent.send_group_message`.
- Supports an explicit `/snapshot` command and a `--trigger-snapshot` flag for manual testing.

## Repository layout

```
pacto-governance-bots/
├── bots/
│   └── bosun/
│       ├── src/bosun/          # bot package
│       │   ├── __init__.py
│       │   ├── bosun.py        # entry point, command handler, cadence loop
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
- A running `pacto-bot-api` daemon with a configured bot identity
- For local contract testing: an anvil node with deployed Pacto-gov contracts

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

Copy the example file and fill in the real values:

```bash
cp bots/bosun/.env.example bots/bosun/.env
# edit bots/bosun/.env
```

Required:

| Variable | Description |
|---|---|
| `PACTO_GOVERNANCE_RPC_URL` | JSON-RPC endpoint (Sepolia or anvil) |
| `PACTO_GOVERNANCE_BOT_ID` | Bot identity registered with the daemon (`bosun`) |
| `PACTO_GOVERNANCE_GROUP_ID` | MLS Squad group id to post into |
| `PACTO_GOVERNANCE_DAEMON_SOCKET` **or** `PACTO_GOVERNANCE_DAEMON_HTTP` | Daemon transport |

If using HTTP transport, also set `PACTO_GOVERNANCE_HTTP_SECRET`.

Optional variables:

| Variable | Default | Description |
|---|---|---|
| `PACTO_GOVERNANCE_SQUAD_INDEX` | `0` | Registry deployment index |
| `PACTO_GOVERNANCE_CADENCE_SECONDS` | `86400` | Seconds between autonomous snapshots |
| `PACTO_GOVERNANCE_CAPTAIN` | zero address | Captain address for Hats checks |
| `PACTO_GOVERNANCE_CREW_CANDIDATES` | none | Comma-separated crew candidate addresses |
| `PACTO_GOVERNANCE_PROPOSER_CANDIDATES` | none | Comma-separated proposer candidate addresses |
| `PACTO_GOVERNANCE_REGISTRY` | Sepolia | Override NavePirataRegistry address |
| `PACTO_GOVERNANCE_HATS` | Sepolia | Override Hats Protocol address |

### 5. Start the daemon

```bash
pacto-bot-api --config pacto-bot-api.toml --data-dir ./data
```

### 6. Run the bot

```bash
source .venv/bin/activate
python -m bosun
```

The bot will publish its KeyPackage, register with the daemon, and begin the
daily cadence loop.

## Manual trigger (Phase 1 testing)

To post a single snapshot without waiting for the daily cadence:

```bash
source .venv/bin/activate
python -m bosun --trigger-snapshot
```

This connects, publishes the KeyPackage, posts one snapshot, and exits.

## Testing

Run the unit tests (no daemon, anvil, or relay required):

```bash
source .venv/bin/activate
PACTO_GOVERNANCE_RPC_URL=http://localhost:8545 \
PACTO_GOVERNANCE_BOT_ID=bosun \
PACTO_GOVERNANCE_GROUP_ID=test-group \
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

Inbound `!snapshot` invocation from the Squad channel is deferred. The
`/snapshot` handler is already implemented; Phase 2 only registers
`ReceiveGroupMessages` and routes inbound events to the existing handler.

## License

MIT OR Apache-2.0
