#!/usr/bin/env bash
# Open a READ-ONLY SSH tunnel to the production MySQL (cPanel SSH access).
# Maps localhost:<TUNNEL_LOCAL_PORT> -> server's 127.0.0.1:3306. Keep this
# terminal open while using the live profile:
#
#   ./scripts/db_tunnel.sh                 # in one terminal (stays open)
#   STUDIO_ENV_FILE=.env.live studio-web   # in another
#
# Reads SSH_* / TUNNEL_LOCAL_PORT from .env.live (override path with arg 1).
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_FILE="${1:-.env.live}"
[ -f "$ENV_FILE" ] || { echo "Missing $ENV_FILE (copy .env.live.example -> .env.live)"; exit 1; }
set -a; . "$ENV_FILE"; set +a

: "${SSH_HOST:?set SSH_HOST in $ENV_FILE}"
: "${SSH_USER:?set SSH_USER in $ENV_FILE}"
LOCAL_PORT="${TUNNEL_LOCAL_PORT:-3307}"

echo "Tunnel: localhost:${LOCAL_PORT} -> ${SSH_HOST} (mysql 3306) as ${SSH_USER}"
echo "Leave this running; Ctrl-C to close."
exec ssh -N -p "${SSH_PORT:-22}" ${SSH_KEY:+-i "${SSH_KEY/#\~/$HOME}"} \
  -L "${LOCAL_PORT}:127.0.0.1:3306" "${SSH_USER}@${SSH_HOST}"
