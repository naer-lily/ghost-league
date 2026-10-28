#!/usr/bin/env bash
set -euo pipefail
umask 077

cd "$(dirname "$0")/.."

# Deployment-specific values belong in the environment or an untracked
# EnvironmentFile, never in this repository.
if [[ -z "${GHOST_LEAGUE_TOKEN:-}" ]]; then
  TOKEN_FILE="${GHOST_LEAGUE_TOKEN_FILE:-${XDG_CONFIG_HOME:-$HOME/.config}/ghost-league/token}"
  if [[ -r "$TOKEN_FILE" ]]; then
    export GHOST_LEAGUE_TOKEN="$(<"$TOKEN_FILE")"
  fi
fi

HOST="${GHOST_LEAGUE_API_HOST:-127.0.0.1}"
PORT="${GHOST_LEAGUE_API_PORT:-8095}"

exec python3 -m uvicorn ghost_league.api:app --host "$HOST" --port "$PORT"
