#!/usr/bin/env bash
# Print a concise status overview for the local bosun workspace.
# Usage: make status
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BOT_ENV="${REPO_ROOT}/bots/bosun/.env"
VENV="${REPO_ROOT}/.venv"

# Prefer a local symlink, then fall back to the sibling checkout.
if [ -d "${REPO_ROOT}/pacto-dev-env" ]; then
    PACTO_DEV_ENV_DIR="${PACTO_DEV_ENV_DIR:-$REPO_ROOT/pacto-dev-env}"
else
    PACTO_DEV_ENV_DIR="${PACTO_DEV_ENV_DIR:-$REPO_ROOT/../pacto-dev-env}"
fi
if [ -d "${PACTO_DEV_ENV_DIR}" ]; then
    PACTO_DEV_ENV_DIR="$(cd "$PACTO_DEV_ENV_DIR" && pwd)"
fi

DAEMON_SOCKET="/var/lib/pacto-bot-api/pacto-bot-api.sock"
DAEMON_CONFIG="/etc/pacto/pacto-bot-api.toml"

OK='\033[0;32m✔\033[0m'
FAIL='\033[0;31m✘\033[0m'
WARN='\033[1;33m!\033[0m'

status() {
    local label="$1"
    local state="$2"
    local detail="${3:-}"
    printf "%-28s %b\n" "${label}" "${state}"
    if [ -n "${detail}" ]; then
        printf "  %b\n" "${detail}"
    fi
}

container_health() {
    docker inspect --format='{{.State.Health.Status}}' "${1}" 2>/dev/null || true
}

container_running() {
    docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "${1}"
}

# Discover the pacto-bot-api daemon container by inspecting Docker labels / compose state.
# Falls back to the hardcoded name when discovery fails.
find_daemon_container() {
    if command -v docker >/dev/null 2>&1; then
        # First: Docker Compose service label (works regardless of project name).
        local id
        id=$(docker ps -q --filter "label=com.docker.compose.service=pacto-bot-api" 2>/dev/null | head -n1)
        if [ -n "$id" ]; then
            docker inspect --format '{{.Name}}' "$id" 2>/dev/null | sed 's|^/||'
            return
        fi
    fi

    # Second: ask the dev-env compose project for its container name.
    if [ -d "${PACTO_DEV_ENV_DIR}" ] && command -v jq >/dev/null 2>&1; then
        docker compose -f "${PACTO_DEV_ENV_DIR}/docker-compose.yml" ps pacto-bot-api --format json 2>/dev/null | jq -r '.Name // empty' 2>/dev/null | head -n1
    fi
}

# Inspect the running daemon container to find the config path inside it.
find_container_config_path() {
    local container="$1"
    local cmd
    cmd=$(docker inspect --format '{{json .Config.Cmd}}' "$container" 2>/dev/null || true)
    if [ -n "$cmd" ]; then
        local path
        path=$(echo "$cmd" | jq -r '. as $a | (index("--config")) as $i | if $i != null then $a[$i + 1] else empty end' 2>/dev/null || true)
        if [ -n "$path" ] && [ "$path" != "null" ]; then
            echo "$path"
            return
        fi
    fi
    echo "$DAEMON_CONFIG"
}

# Inspect the running daemon container to find the data-dir, then infer the socket path.
find_container_socket_path() {
    local container="$1"
    local cmd
    cmd=$(docker inspect --format '{{json .Config.Cmd}}' "$container" 2>/dev/null || true)
    if [ -n "$cmd" ]; then
        local data_dir
        data_dir=$(echo "$cmd" | jq -r '. as $a | (index("--data-dir")) as $i | if $i != null then $a[$i + 1] else empty end' 2>/dev/null || true)
        if [ -n "$data_dir" ] && [ "$data_dir" != "null" ]; then
            echo "${data_dir}/pacto-bot-api.sock"
            return
        fi
    fi
    echo "$DAEMON_SOCKET"
}

DAEMON_CONTAINER="${DAEMON_CONTAINER:-$(find_daemon_container)}"
if [ -z "${DAEMON_CONTAINER}" ]; then
    DAEMON_CONTAINER="pacto-dev-env-pacto-bot-api-1"
fi

if container_running "${DAEMON_CONTAINER}"; then
    DAEMON_CONFIG="$(find_container_config_path "${DAEMON_CONTAINER}")"
    DAEMON_SOCKET="$(find_container_socket_path "${DAEMON_CONTAINER}")"
fi

# .env file
if [ -f "${BOT_ENV}" ]; then
    status "bots/bosun/.env" "${OK} present"
else
    status "bots/bosun/.env" "${FAIL} missing" "run: make env"
fi

# Virtual environment
if [ -f "${VENV}/bin/activate" ]; then
    status "python venv" "${OK} ${VENV}"
else
    status "python venv" "${FAIL} missing" "run: make venv"
fi

# Bot package installed
if [ -d "${VENV}" ] && "${VENV}/bin/python" -c "import bosun" 2>/dev/null; then
    version="$($VENV/bin/python -c "import bosun; print(getattr(bosun, '__version__', 'unknown'))" 2>/dev/null || true)"
    status "bosun package" "${OK} installed (${version})"
else
    status "bosun package" "${FAIL} not installed" "run: make install"
fi

# Docker daemon availability
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    status "docker daemon" "${OK} running"
else
    status "docker daemon" "${FAIL} not available"
fi

# Bosun container
if docker compose ps --status running 2>/dev/null | grep -q 'bosun'; then
    status "bosun container" "${OK} running"
else
    status "bosun container" "${FAIL} not running" "run: make up"
fi

# Daemon transport / socket
if [ -f "${BOT_ENV}" ]; then
    # shellcheck source=/dev/null
    source "${BOT_ENV}"
fi
SOCKET="${PACTO_GOVERNANCE_DAEMON_SOCKET:-${DAEMON_SOCKET}}"
HTTP="${PACTO_GOVERNANCE_DAEMON_HTTP:-}"

if [ -n "${HTTP}" ]; then
    if command -v curl >/dev/null 2>&1 && curl -s "http://${HTTP}/health" >/dev/null 2>&1; then
        status "daemon transport" "${OK} http://${HTTP}"
    else
        status "daemon transport" "${FAIL} http://${HTTP} unreachable"
    fi
elif [ -S "${SOCKET}" ] || [ -e "${SOCKET}" ]; then
    status "daemon transport" "${OK} socket ${SOCKET}"
elif container_running "${DAEMON_CONTAINER}"; then
    health="$(container_health "${DAEMON_CONTAINER}")"
    if docker exec "${DAEMON_CONTAINER}" test -S "${DAEMON_SOCKET}" >/dev/null 2>&1; then
        if [ -n "${health}" ]; then
            status "daemon transport" "${OK} socket ${DAEMON_SOCKET} in ${DAEMON_CONTAINER} (health: ${health})"
        else
            status "daemon transport" "${OK} socket ${DAEMON_SOCKET} in ${DAEMON_CONTAINER}"
        fi
    else
        status "daemon transport" "${FAIL} socket ${DAEMON_SOCKET} not found in ${DAEMON_CONTAINER}"
    fi
else
    status "daemon transport" "${FAIL} socket ${SOCKET} missing" "ensure pacto-dev-env is running (cd ${PACTO_DEV_ENV_DIR} && make up)"
fi

# pacto-bot-admin status
if command -v pacto-bot-admin >/dev/null 2>&1; then
    status "pacto-bot-admin" "${OK} available"
    echo "---"
    echo "pacto-bot-admin status:"
    if container_running "${DAEMON_CONTAINER}"; then
        docker exec "${DAEMON_CONTAINER}" pacto-bot-admin -c "${DAEMON_CONFIG}" status || true
    elif [ -f "${PACTO_DEV_ENV_DIR}/pacto-bot-api.toml" ]; then
        pacto-bot-admin -c "${PACTO_DEV_ENV_DIR}/pacto-bot-api.toml" status || true
    elif [ -f "${REPO_ROOT}/pacto-bot-api.toml" ]; then
        pacto-bot-admin -c "${REPO_ROOT}/pacto-bot-api.toml" status || true
    else
        echo "No pacto-bot-api.toml config found"
    fi
else
    status "pacto-bot-admin" "${WARN} not in PATH" "install pacto-bot-api CLI for detailed daemon status"
fi
