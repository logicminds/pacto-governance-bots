#!/usr/bin/env bash
set -euo pipefail

# Integration health check for the pacto-governance-bots → pacto-dev-env link.
#
# Verifies:
#   - daemon socket exists and responds to system.health
#   - bot identity is declared in pacto-dev-env/pacto-bot-api.toml
#   - Anvil registry has at least one Nave Pirata squad
#   - bots/bosun/.env registry/Hats addresses match the deployment artifact
#
# Usage: make health-check
#        or ./scripts/health-check.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BOT_ENV="${REPO_ROOT}/bots/bosun/.env"

PACTO_DEV_ENV_DIR="${PACTO_DEV_ENV_DIR:-$REPO_ROOT/../pacto-dev-env}"
PACTO_DEV_ENV_DIR="$(cd "$PACTO_DEV_ENV_DIR" && pwd)"

for cmd in jq cast socat python3; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "error: required command '$cmd' not found in PATH" >&2
    exit 1
  fi
done

# Load bot-local environment variables, if present.
if [ -f "$BOT_ENV" ]; then
  set -a
  # shellcheck source=/dev/null
  eval "$(grep '^PACTO_GOVERNANCE_' "$BOT_ENV" || true)"
  set +a
fi

SOCKET="${PACTO_GOVERNANCE_DAEMON_SOCKET:-/var/lib/pacto-bot-api/pacto-bot-api.sock}"
BOT_ID="${PACTO_GOVERNANCE_BOT_ID:-bosun}"
RPC_URL="${PACTO_GOVERNANCE_RPC_URL:-http://localhost:8545}"
REGISTRY="${PACTO_GOVERNANCE_REGISTRY:-}"
HATS="${PACTO_GOVERNANCE_HATS:-}"

FAIL=0

check_socket() {
  if [ -S "$SOCKET" ]; then
    echo "OK: daemon socket exists"

    local response
    response=$(printf '{"jsonrpc":"2.0","id":1,"method":"system.health","params":[]}\n' \
      | socat -t 2 - "UNIX-CONNECT:$SOCKET" 2>/dev/null | head -c 4096) || true
    if [ -z "$response" ]; then
      echo "FAIL: daemon did not respond to system.health"
      FAIL=1
      return
    fi
    if ! echo "$response" | jq -e '.result' >/dev/null 2>&1; then
      echo "FAIL: system.health returned error: $(echo "$response" | jq -c '.error // .')"
      FAIL=1
      return
    fi
    echo "OK: daemon responds to system.health"
    return
  fi

  # Fallback: the daemon may be running inside a container with the socket on a
  # Docker volume. Probe it via docker exec using the dev-env compose project.
  local daemon_container
  daemon_container=$(docker compose -f "$PACTO_DEV_ENV_DIR/docker-compose.yml" ps pacto-bot-api --format json 2>/dev/null | jq -r '.Name // empty' 2>/dev/null || true)
  if [ -z "$daemon_container" ]; then
    echo "FAIL: daemon socket not found: $SOCKET and no running pacto-bot-api container"
    FAIL=1
    return
  fi

  if docker exec "$daemon_container" pacto-bot-admin status --data-dir /var/lib/pacto-bot-api >/dev/null 2>&1; then
    echo "OK: daemon socket reachable inside container $daemon_container"
  else
    echo "FAIL: daemon socket not reachable inside container $daemon_container"
    FAIL=1
  fi
}

check_bot_identity() {
  local config_file="$PACTO_DEV_ENV_DIR/pacto-bot-api.toml"
  if [ ! -f "$config_file" ]; then
    echo "FAIL: daemon config not found: $config_file"
    FAIL=1
    return
  fi
  if python3 -c "
import tomllib, sys
with open('$config_file', 'rb') as f:
    data = tomllib.load(f)
bots = data.get('bots', [])
sys.exit(0 if any(b.get('id') == '$BOT_ID' for b in bots) else 1)
"; then
    echo "OK: bot identity '$BOT_ID' found in daemon config"
  else
    echo "FAIL: bot identity '$BOT_ID' not found in daemon config"
    FAIL=1
  fi
}

check_squads() {
  if [ -z "$REGISTRY" ]; then
    echo "FAIL: PACTO_GOVERNANCE_REGISTRY not set in $BOT_ENV"
    FAIL=1
    return
  fi

  local count
  count=$(cast call "$REGISTRY" "deploymentCount()(uint256)" --rpc-url "$RPC_URL" 2>/dev/null || true)
  if [ -z "$count" ]; then
    echo "FAIL: could not read deploymentCount from registry $REGISTRY"
    FAIL=1
    return
  fi
  if [ "$count" -ge 1 ]; then
    echo "OK: registry has $count squad deployment(s)"
  else
    echo "FAIL: registry has no squad deployments (run 'make seed-squad' in pacto-dev-env)"
    FAIL=1
  fi
}

check_env_matches_artifact() {
  local artifact="$PACTO_DEV_ENV_DIR/data/deployments/31337/full-system.json"
  if [ ! -f "$artifact" ]; then
    echo "FAIL: deployment artifact not found: $artifact"
    FAIL=1
    return
  fi

  local expected_registry expected_hats
  expected_registry=$(jq -r '.navePirataRegistry' "$artifact")
  expected_hats=$(jq -r '.hats' "$artifact")

  if [ "$REGISTRY" != "$expected_registry" ]; then
    echo "FAIL: bots/bosun/.env REGISTRY ($REGISTRY) does not match artifact ($expected_registry)"
    FAIL=1
  else
    echo "OK: bots/bosun/.env REGISTRY matches deployment artifact"
  fi
  if [ "$HATS" != "$expected_hats" ]; then
    echo "FAIL: bots/bosun/.env HATS ($HATS) does not match artifact ($expected_hats)"
    FAIL=1
  else
    echo "OK: bots/bosun/.env HATS matches deployment artifact"
  fi
}

check_socket
check_bot_identity
check_squads
check_env_matches_artifact

if [ "$FAIL" -eq 0 ]; then
  echo "All checks passed."
  exit 0
else
  echo "Health check failed."
  exit 1
fi
