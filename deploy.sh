#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is not installed or not in PATH."
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "ERROR: docker compose is not available."
  exit 1
fi

if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example .env
    echo "INFO: .env was missing, created from .env.example."
  else
    echo "ERROR: .env not found and .env.example is missing."
    exit 1
  fi
fi

get_env_value() {
  local key="$1"
  local default_value="$2"
  local raw

  raw="$(
    awk -v key="${key}" '
      /^[[:space:]]*#/ { next }
      /^[[:space:]]*$/ { next }
      {
        line = $0
        sub(/^[[:space:]]+/, "", line)
        if (index(line, key "=") == 1) {
          value = substr(line, length(key) + 2)
          gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
          # Strip optional wrapping quotes.
          if (value ~ /^".*"$/ || value ~ /^'\''.*'\''$/) {
            value = substr(value, 2, length(value) - 2)
          }
          out = value
        }
      }
      END { print out }
    ' .env
  )"

  if [[ -n "${raw}" ]]; then
    printf '%s' "${raw}"
  else
    printf '%s' "${default_value}"
  fi
}

LISTEN_PORT="$(get_env_value "LISTEN_PORT" "8000")"
APP_UPSTREAM_PORT="$(get_env_value "APP_UPSTREAM_PORT" "${LISTEN_PORT}")"
NGINX_LISTEN_PORT="$(get_env_value "NGINX_LISTEN_PORT" "8080")"

for port in "${LISTEN_PORT}" "${APP_UPSTREAM_PORT}" "${NGINX_LISTEN_PORT}"; do
  if [[ ! "${port}" =~ ^[0-9]+$ ]]; then
    echo "ERROR: Invalid port value '${port}' in .env."
    exit 1
  fi
done

if [[ "${LISTEN_PORT}" == "${NGINX_LISTEN_PORT}" ]]; then
  echo "ERROR: LISTEN_PORT (${LISTEN_PORT}) cannot be the same as NGINX_LISTEN_PORT (${NGINX_LISTEN_PORT})."
  exit 1
fi

if [[ "${APP_UPSTREAM_PORT}" != "${LISTEN_PORT}" ]]; then
  echo "WARN: APP_UPSTREAM_PORT (${APP_UPSTREAM_PORT}) differs from LISTEN_PORT (${LISTEN_PORT})."
  echo "WARN: This may break nginx -> app proxying if intentional mapping is not configured."
fi

echo "Deploy configuration:"
echo "  LISTEN_PORT=${LISTEN_PORT}"
echo "  APP_UPSTREAM_PORT=${APP_UPSTREAM_PORT}"
echo "  NGINX_LISTEN_PORT=${NGINX_LISTEN_PORT}"
echo

echo "[1/4] Stopping old stack..."
docker compose down --remove-orphans

echo "[2/4] Building and starting new stack..."
docker compose up -d --build --force-recreate --remove-orphans

echo "[3/4] Service status:"
docker compose ps

echo "[4/4] Health check:"
if command -v curl >/dev/null 2>&1; then
  HEALTH_URL="http://127.0.0.1:${NGINX_LISTEN_PORT}/health"
  for i in {1..20}; do
    if curl -fsS "${HEALTH_URL}" >/dev/null 2>&1; then
      echo "OK: ${HEALTH_URL}"
      break
    fi
    sleep 1
    if [[ "${i}" == "20" ]]; then
      echo "WARN: Health check failed for ${HEALTH_URL}."
      echo "Run: docker compose logs --tail=120 app nginx"
      exit 1
    fi
  done
else
  echo "INFO: curl not found, skipping health check."
fi

echo
echo "Done."
