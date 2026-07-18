# Cross-repo setup guide

This guide walks through the full local path from a fresh clone to a running
pacto governance bot that receives events from the daemon. It covers both the
`pacto-dev-env` orchestration repo and the `pacto-governance-bots` consumer repo.

## Prerequisites

- Docker and Docker Compose
- `make`, `cast` (Foundry), `jq`, `socat`, `python3`
- Two sibling directories side by side:
  - `pacto-dev-env`
  - `pacto-governance-bots`
  - `pacto-gov` (cloned automatically by `make seed` if missing)

## 1. Start the dev environment

```bash
cd pacto-dev-env
make dev
```

This pulls images, starts the default stack (nostr-relay, anvil, pacto-bot-api),
seeds the Pacto governance contracts on Anvil, and prints the next steps.

Optionally, create a dev bot identity automatically by setting the secrets first:

```bash
export PACTO_CREATE_DEV_BOT=1
export PACTO_BOT_NSEC=<nsec1...>
export PACTO_BOT_NPUB=<npub1...>
make dev
```

If you skip this, add a bot later with `pacto-bot-admin` (see step 2).

## 2. Create captain and candidate identities

Squad creation is identity-aware and requires two Nostr public keys. If you did
not create a dev bot in step 1, create a bot identity for the daemon first:

```bash
pacto-bot-admin new bosun --backend nsec --relays ws://localhost:7000 >> pacto-bot-api.toml
```

Then create a captain and at least one candidate for the squad:

```bash
pacto-bot-admin new captain --backend nsec --relays ws://localhost:7000
pacto-bot-admin new candidate --backend nsec --relays ws://localhost:7000
```

Export the **npubs** (or hex public keys) for the next step:

```bash
export PACTO_SQUAD_CAPTAIN_NPUB=<captain-npub>
export PACTO_SQUAD_CANDIDATE_NPUB=<candidate-npub>
```

## 3. Deploy a Nave Pirata squad

```bash
cd pacto-dev-env
make seed-squad
```

This runs `forge script` in the `pacto-gov` repo and writes the squad artifact
to `data/deployments/31337/squad.json`. If the required env vars are missing,
the script prints the commands above and exits.

## 4. Generate the governance bot environment

```bash
cd pacto-governance-bots
make env
```

This reads `../pacto-dev-env/data/deployments/31337/full-system.json` and writes
`bots/bosun/.env` with the registry, Hats, RPC, and socket values. Apply any
overrides, then start the bot:

```bash
docker compose up -d
```

## 5. Verify the integration

```bash
cd pacto-governance-bots
make health-check
```

The health check verifies that the daemon socket is reachable, the bot identity
is present in `pacto-dev-env/pacto-bot-api.toml`, Anvil has at least one squad,
and the registry/Hats addresses in `bots/bosun/.env` match the deployment
artifact.

## Shared contract

Both repos agree on the following resources:

| Resource | Value | Where declared |
|----------|-------|----------------|
| Docker network | `pacto` | `pacto-dev-env/docker-compose.yml` |
| Daemon data volume | `pacto-bot-api-data` | `pacto-dev-env/docker-compose.yml` |
| Daemon socket path | `/var/lib/pacto-bot-api/pacto-bot-api.sock` | `pacto-dev-env/docker-compose.yml`, `pacto-governance-bots/docker-compose.yml` |

## Troubleshooting

- **"no deployments in registry"**: run `make seed-squad` in `pacto-dev-env`.
- **"daemon socket not found"**: ensure `pacto-dev-env` is up (`make up`) and
the daemon finished starting.
- **".env mismatch"**: re-run `make env` in `pacto-governance-bots` after
re-seeding contracts.
