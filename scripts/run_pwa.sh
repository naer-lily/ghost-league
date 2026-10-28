#!/usr/bin/env bash
set -euo pipefail
umask 077

cd "$(dirname "$0")/.."

CERT="${GHOST_LEAGUE_TLS_CERT:-deploy/tls/ghost-league.crt}"
KEY="${GHOST_LEAGUE_TLS_KEY:-deploy/tls/ghost-league.key}"
HOST="${GHOST_LEAGUE_WEB_HOST:-127.0.0.1}"
PORT="${GHOST_LEAGUE_WEB_PORT:-8445}"

if [[ ! -r "$CERT" || ! -r "$KEY" ]]; then
  echo "TLS certificate/key missing: $CERT $KEY" >&2
  exit 1
fi

exec python3 -m uvicorn ghost_league.pwa:app \
  --host "$HOST" \
  --port "$PORT" \
  --ssl-certfile "$CERT" \
  --ssl-keyfile "$KEY"
