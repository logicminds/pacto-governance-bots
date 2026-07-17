---
title: Bosun Dev-Env Integration
type: ops
status: completed
date: 2026-07-13
origin: local
---

# Bosun Dev-Env Integration

This document describes how to wire the `bosun` Python governance snapshot bot to a local [`pacto-dev-env`](https://github.com/covenant-gov/pacto-dev-env) stack, and why a specific daemon branch is required.

## Overview

Running bosun against the shared dev-env stack requires:

1. A deployed Pacto governance squad in the dev-env anvil instance.
2. A daemon image built from a branch that has daemon-side MLS group lifecycle **and** the wire-id → mls-group-id resolution fix.
3. An MLS group created by the daemon, with `bosun` as a member.
4. `PACTO_GOVERNANCE_GROUP_ID` populated in `bots/bosun/.env`.
5. The `bosun` container restarted with that environment.

The full flow is automated by `scripts/setup-dev-env.sh`.

## Why a special daemon branch is needed

The released `pacto-bot-api` v0.6.0 does not expose the `pacto-bot-admin mls-group` subcommand, so the MLS group cannot be created.

v0.7.0 (current `main`) adds the `mls-group` subcommand, but `agent.send_group_message` passes the hex wire-id bytes directly to the MLS engine instead of resolving them to the internal MLS group id. This causes every group send to fail with `MLS group not found`.

The fix lives in the upstream branch `origin/fix/mls-send-wire-id` (commit `8b86a49`). The automation script checks out that branch in the sibling `pacto-bot-api` repo and builds the daemon image from it.

## Prerequisites

- Docker and Docker Compose running.
- This repo (`pacto-governance-bots`) checked out.
- Sibling repos next to it (or set via environment variables):
  - `../pacto-dev-env` (the dev-env stack)
  - `../pacto-bot-api` (the daemon source)
- The dev-env stack is up (`make up` in `pacto-dev-env`).
- The squad contracts are deployed (`make seed-squad` in `pacto-dev-env` if `squad.json` is missing).

## Quick start

```bash
make setup-dev-env
```

This is equivalent to running `scripts/setup-dev-env.sh` with the defaults.

The script will:

1. Switch `../pacto-bot-api` to `origin/fix/mls-send-wire-id`.
2. Build the daemon image from the local source.
3. Restart the `pacto-dev-env` daemon container.
4. Create the MLS group (if the artifact does not exist) using `bosun` as owner and `captain` as the other initial member.
5. Write the resulting group id into `bots/bosun/.env`.
6. Restart the `bosun` container and wait for a snapshot to confirm the wiring.

## Environment variables

The setup script honors these overrides:

| Variable | Default | Description |
|----------|---------|-------------|
| `PACTO_DEV_ENV_DIR` | `../pacto-dev-env` | Path to the dev-env checkout. |
| `PACTO_BOT_API_DIR` | `../pacto-bot-api` | Path to the daemon source checkout. |
| `PACTO_DAEMON_BRANCH` | `fix/mls-send-wire-id` | Daemon branch to build from. |
| `RECIPIENT_BOT_ID` | `captain` | Bot identity from `pacto-bot-api.toml` to invite into the group. |
| `GROUP_NAME` | `local-dev-squad` | Human-readable name for the MLS group. |
| `BOT_ID` | `bosun` | Bot identity that owns the group. |
| `FORCE_BUILD` | `0` | Set to `1` to rebuild the daemon image without cache. |

Examples:

```bash
# Use custom sibling paths
PACTO_DEV_ENV_DIR=/src/pacto-dev-env PACTO_BOT_API_DIR=/src/pacto-bot-api make setup-dev-env

# Force a clean daemon rebuild
FORCE_BUILD=1 make setup-dev-env
```

## Manual fallback

If you prefer to run the steps manually:

```bash
cd ../pacto-bot-api
git fetch origin fix/mls-send-wire-id
git checkout -b fix/mls-send-wire-id origin/fix/mls-send-wire-id

cd ../pacto-dev-env
docker compose build --no-cache pacto-bot-api
docker compose up -d --force-recreate pacto-bot-api

# Wait for daemon status: ready
BOT_ID=bosun GROUP_NAME=local-dev-squad \
  RECIPIENT_NPUB=npub1vlfehx28h2a6jcamng0pmz3qvph2rjpuhuccea59y9f2ee99l3rqmwvxzc \
  make create-mls-group

cd ../pacto-governance-bots
./scripts/generate-env.sh
export PACTO_GOVERNANCE_GROUP_ID=36c46e644b293affde04732a981502a9911b98352f4489f0ff498c025849e74b
docker compose up -d --force-recreate bosun
```

## Verification

After setup, run:

```bash
./scripts/health-check.sh
```

You should also see a successful snapshot in the bosun logs:

```bash
docker logs --tail 20 bosun-bosun-1
```

Expected output includes:

```text
[bosun] INFO: registered handler_id=... events=['dm_received']
[bosun] INFO: posted snapshot: <event-id>
[bosun] INFO: published KeyPackage
```

## Artifacts

- `pacto-dev-env/data/deployments/31337/squad.json` — on-chain squad deployment info.
- `pacto-dev-env/data/deployments/31337/group-bosun.json` — created MLS group metadata, including the `group_id` wire id used by `PACTO_GOVERNANCE_GROUP_ID`.
- `bots/bosun/.env` — generated bot environment (gitignored, never commit).

## Known limitations

- The v0.7.0 daemon image from `ghcr.io/covenant-gov/pacto-bot-api:main` is not sufficient; the `fix/mls-send-wire-id` fix is required until it is merged and released.
- The `pacto-dev-env/pacto-bot-api.toml` must grant `bosun` the `Admin` capability and an `mls_db_path`, and the recipient bot (e.g. `captain`) must have `SendGroupMessages` and an `mls_db_path`. The dev-env config already contains these settings for the default setup.

## Related files

- `scripts/setup-dev-env.sh` — one-shot automation.
- `scripts/generate-env.sh` — generates `bots/bosun/.env`, now including the group id from the artifact.
- `scripts/health-check.sh` — post-setup verification.
- `bots/bosun/docker-compose.yml` — compose service for the bot.
- `bots/bosun/src/bosun/bosun.py` — bot handler including the `--trigger-snapshot` fix.
