#!/usr/bin/env bash
# Spin up a LOCAL MySQL and import a PMS snapshot into it.
# Read-only development copy — NOT production.
#
# Usage:   ./scripts/import_snapshot.sh [path/to/snapshot.sql]
# Backend: BACKEND=brew|docker (default: auto — brew if mysql@8.0 is installed,
#          else docker). On this machine Docker Hub pulls are blocked by the
#          Docker Desktop hub-proxy, so the brew backend is the working default.
set -euo pipefail

SNAPSHOT="${1:-official_project_new.sql}"
DB_NAME="${DB_NAME:-studio_pms}"
RO_USER="${DB_USER:-studio_ro}"
RO_PW="${DB_PASSWORD:-studio_ro_pw}"
BACKEND="${BACKEND:-auto}"

cd "$(dirname "$0")/.."

[[ -f "$SNAPSHOT" ]] || { echo "Snapshot not found: $SNAPSHOT" >&2; exit 1; }

BREW_PREFIX="$(brew --prefix 2>/dev/null || echo /opt/homebrew)"
BREW_MYSQL_BIN="$BREW_PREFIX/opt/mysql@8.0/bin"

if [[ "$BACKEND" == "auto" ]]; then
  if [[ -x "$BREW_MYSQL_BIN/mysql" ]]; then BACKEND=brew; else BACKEND=docker; fi
fi
echo "==> Backend: $BACKEND"

if [[ "$BACKEND" == "brew" ]]; then
  export PATH="$BREW_MYSQL_BIN:$PATH"
  brew services start mysql@8.0 >/dev/null
  echo "==> Waiting for MySQL"
  until mysqladmin ping -uroot --silent >/dev/null 2>&1; do sleep 1; done

  echo "==> Creating database + read-only user"
  mysql -uroot <<SQL
CREATE DATABASE IF NOT EXISTS \`$DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$RO_USER'@'127.0.0.1' IDENTIFIED BY '$RO_PW';
CREATE USER IF NOT EXISTS '$RO_USER'@'localhost' IDENTIFIED BY '$RO_PW';
GRANT SELECT ON \`$DB_NAME\`.* TO '$RO_USER'@'127.0.0.1';
GRANT SELECT ON \`$DB_NAME\`.* TO '$RO_USER'@'localhost';
FLUSH PRIVILEGES;
SQL

  echo "==> Importing $SNAPSHOT into \`$DB_NAME\` (can take a while)"
  mysql -uroot "$DB_NAME" < "$SNAPSHOT"

  echo "==> Done. Tables:"
  mysql -uroot -e "SHOW TABLES;" "$DB_NAME"

elif [[ "$BACKEND" == "docker" ]]; then
  ROOT_PW="root_pw"
  echo "==> Starting MySQL container"
  docker compose up -d db
  echo "==> Waiting for MySQL to be healthy"
  until docker compose exec -T db mysqladmin ping -h localhost -uroot -p"$ROOT_PW" --silent >/dev/null 2>&1; do sleep 2; done
  sleep 2
  echo "==> Importing $SNAPSHOT into \`$DB_NAME\`"
  docker compose exec -T db sh -c "exec mysql -uroot -p'$ROOT_PW' '$DB_NAME'" < "$SNAPSHOT"
  echo "==> Locking app user down to SELECT only"
  docker compose exec -T db mysql -uroot -p"$ROOT_PW" <<SQL
REVOKE ALL PRIVILEGES, GRANT OPTION ON \`$DB_NAME\`.* FROM '$RO_USER'@'%';
GRANT SELECT ON \`$DB_NAME\`.* TO '$RO_USER'@'%';
FLUSH PRIVILEGES;
SQL
  echo "==> Done. Tables:"
  docker compose exec -T db mysql -uroot -p"$ROOT_PW" -e "SHOW TABLES;" "$DB_NAME"
else
  echo "Unknown BACKEND: $BACKEND (use brew or docker)" >&2
  exit 1
fi
