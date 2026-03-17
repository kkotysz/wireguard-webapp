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

# shellcheck disable=SC1091
set -a
source .env
set +a

LISTEN_PORT="${LISTEN_PORT:-8000}"
APP_UPSTREAM_PORT="${APP_UPSTREAM_PORT:-${LISTEN_PORT}}"
NGINX_LISTEN_PORT="${NGINX_LISTEN_PORT:-8080}"

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
