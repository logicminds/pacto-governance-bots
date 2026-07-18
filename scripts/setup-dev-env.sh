#!/usr/bin/env bash
# One-shot setup script that wires bosun to a local pacto-dev-env stack.
#
# Prerequisites:
#   - Docker and Docker Compose are running.
#   - This repo is checked out at the project root.
#   - The sibling repos pacto-dev-env and pacto-bot-api are checked out next to
#     this repo (or pointed to via PACTO_DEV_ENV_DIR / PACTO_BOT_API_DIR).
#   - The pacto-dev-env stack is already up (run 'make up' there first).
#   - The squad contracts are deployed (run 'make seed-squad' there if needed).
#
# Usage:
#   ./scripts/setup-dev-env.sh
#   FORCE_BUILD=1 ./scripts/setup-dev-env.sh
#   PACTO_DEV_ENV_DIR=/path/to/pacto-dev-env ./scripts/setup-dev-env.sh
#
# What it does:
#   1. Ensures pacto-bot-api is on the branch that has daemon-side MLS group
#      lifecycle and the wire-id -> mls-group-id fix.
#   2. Builds the pacto-bot-api image from the local sibling repo.
#   3. Restarts the daemon container with the new image.
#   4. Creates the MLS group if the artifact does not already exist.
#   5. Generates bots/bosun/.env with the group id and deployment addresses.
#   6. Restarts the bosun container.
#
# After running, verify with:
#   docker compose ps
#   docker logs --tail 20 bosun-bosun-1
#   ./scripts/health-check.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PACTO_DEV_ENV_DIR="${PACTO_DEV_ENV_DIR:-../pacto-dev-env}"
PACTO_BOT_API_DIR="${PACTO_BOT_API_DIR:-../pacto-bot-api}"
PACTO_DAEMON_BRANCH="${PACTO_DAEMON_BRANCH:-fix/mls-send-wire-id}"
FORCE_BUILD="${FORCE_BUILD:-0}"
RECIPIENT_BOT_ID="${RECIPIENT_BOT_ID:-captain}"
GROUP_NAME="${GROUP_NAME:-local-dev-squad}"
BOT_ID="${BOT_ID:-bosun}"

# Resolve relative paths against REPO_ROOT; leave absolute paths untouched.
if [[ "${PACTO_DEV_ENV_DIR}" == /* ]]; then
    PACTO_DEV_ENV_DIR="$(cd "${PACTO_DEV_ENV_DIR}" && pwd)"
else
    PACTO_DEV_ENV_DIR="$(cd "${REPO_ROOT}/${PACTO_DEV_ENV_DIR}" && pwd)"
fi

if [[ "${PACTO_BOT_API_DIR}" == /* ]]; then
    PACTO_BOT_API_DIR="$(cd "${PACTO_BOT_API_DIR}" && pwd)"
else
    PACTO_BOT_API_DIR="$(cd "${REPO_ROOT}/${PACTO_BOT_API_DIR}" && pwd)"
fi

DEPLOYMENT_DIR="${PACTO_DEV_ENV_DIR}/data/deployments/31337"
GROUP_ARTIFACT="${DEPLOYMENT_DIR}/group-${BOT_ID}.json"
DAEMON_CONFIG="${PACTO_DEV_ENV_DIR}/pacto-bot-api.toml"

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

err() { echo -e "${RED}[setup-dev-env]${NC} $*" >&2; }
warn() { echo -e "${YELLOW}[setup-dev-env]${NC} $*"; }
ok() { echo -e "${GREEN}[setup-dev-env]${NC} $*"; }
info() { echo -e "${BLUE}[setup-dev-env]${NC} $*"; }

die() { err "$*"; exit 1; }

require_cmd() {
    if ! command -v "$1" > /dev/null 2>&1; then
        die "$1 is required but not installed"
    fi
}

require_cmd docker
require_cmd git
require_cmd jq

if [[ ! -d "${PACTO_DEV_ENV_DIR}" ]]; then
    die "pacto-dev-env not found at ${PACTO_DEV_ENV_DIR}"
fi

if [[ ! -d "${PACTO_BOT_API_DIR}" ]]; then
    die "pacto-bot-api source not found at ${PACTO_BOT_API_DIR}"
fi

if [[ ! -f "${DAEMON_CONFIG}" ]]; then
    die "daemon config not found: ${DAEMON_CONFIG}"
fi

# ---------------------------------------------------------------------------
# 1. Ensure daemon repo is on the required branch.
# ---------------------------------------------------------------------------
info "Checking daemon source branch in ${PACTO_BOT_API_DIR}..."
cd "${PACTO_BOT_API_DIR}"

CURRENT_BRANCH="$(git branch --show-current)"
if [[ "${CURRENT_BRANCH}" != "${PACTO_DAEMON_BRANCH}" ]]; then
    warn "Daemon repo is on '${CURRENT_BRANCH}'; switching to '${PACTO_DAEMON_BRANCH}'"
    git fetch origin "${PACTO_DAEMON_BRANCH}" || die "failed to fetch ${PACTO_DAEMON_BRANCH}"
    if git rev-parse --verify --quiet "${PACTO_DAEMON_BRANCH}" >/dev/null; then
        git checkout "${PACTO_DAEMON_BRANCH}"
    else
        git checkout -b "${PACTO_DAEMON_BRANCH}" "origin/${PACTO_DAEMON_BRANCH}"
    fi
fi

ok "Daemon repo on branch $(git branch --show-current) at $(git rev-parse --short HEAD)"

# ---------------------------------------------------------------------------
# 2. Build the daemon image from the local source.
# ---------------------------------------------------------------------------
info "Building pacto-bot-api image from ${PACTO_BOT_API_DIR}..."
cd "${PACTO_DEV_ENV_DIR}"

if [[ "${FORCE_BUILD}" == "1" ]]; then
    docker compose build --no-cache pacto-bot-api
else
    docker compose build pacto-bot-api
fi

ok "pacto-bot-api image built"

# ---------------------------------------------------------------------------
# 3. Restart the daemon.
# ---------------------------------------------------------------------------
info "Restarting daemon container..."
docker compose up -d --force-recreate pacto-bot-api

# Wait for daemon to be ready.
for i in {1..30}; do
    if docker exec pacto-dev-env-pacto-bot-api-1 \
        pacto-bot-admin status \
        --config /etc/pacto/pacto-bot-api.toml \
        --data-dir /var/lib/pacto-bot-api 2>/dev/null | grep -q "status: ready"; then
        break
    fi
    sleep 1
done

if ! docker exec pacto-dev-env-pacto-bot-api-1 \
    pacto-bot-admin status \
    --config /etc/pacto/pacto-bot-api.toml \
    --data-dir /var/lib/pacto-bot-api 2>/dev/null | grep -q "status: ready"; then
    die "daemon did not become ready"
fi
ok "daemon is ready"

# ---------------------------------------------------------------------------
# 4. Create the MLS group if it does not exist.
# ---------------------------------------------------------------------------
if [[ -f "${GROUP_ARTIFACT}" ]]; then
    GROUP_ID="$(jq -r '.group_id' "${GROUP_ARTIFACT}")"
    ok "MLS group already exists: ${GROUP_ID}"
else
    info "Creating MLS group '${GROUP_NAME}'..."

    RECIPIENT_NPUB="$(python3 -c "
import re, sys
cfg = open('${DAEMON_CONFIG}').read()
for block in cfg.split('[[bots]]'):
    m = re.search(r'id = \"${RECIPIENT_BOT_ID}\"', block)
    if m:
        npub = re.search(r'npub = \"([^\"]+)\"', block)
        if npub:
            print(npub.group(1))
            sys.exit(0)
print('')
")"

    if [[ -z "${RECIPIENT_NPUB}" ]]; then
        die "could not resolve npub for recipient bot '${RECIPIENT_BOT_ID}' in ${DAEMON_CONFIG}"
    fi

    cd "${PACTO_DEV_ENV_DIR}"
    BOT_ID="${BOT_ID}" GROUP_NAME="${GROUP_NAME}" RECIPIENT_NPUB="${RECIPIENT_NPUB}" \
        make create-mls-group

    GROUP_ID="$(jq -r '.group_id' "${GROUP_ARTIFACT}")"
    ok "MLS group created: ${GROUP_ID}"
fi

# ---------------------------------------------------------------------------
# 5. Generate bots/bosun/.env with the group id.
# ---------------------------------------------------------------------------
info "Generating bot environment file..."
cd "${REPO_ROOT}"
PACTO_DEV_ENV_DIR="${PACTO_DEV_ENV_DIR}" ./scripts/generate-env.sh

# ---------------------------------------------------------------------------
# 6. Restart bosun with the updated environment.
# ---------------------------------------------------------------------------
info "Restarting bosun container..."
cd "${REPO_ROOT}"
docker compose up -d --force-recreate bosun

ok "bosun restarted"

info "Setup complete. Run './scripts/health-check.sh' to verify."
