#!/usr/bin/env bash
# Spin up the local MySQL container and import a PMS snapshot into it.
# Read-only development copy — NOT production.
#
# Usage: ./scripts/import_snapshot.sh path/to/snapshot.sql
set -euo pipefail

SNAPSHOT="${1:-official_project_new.sql}"
DB_NAME="${DB_NAME:-studio_pms}"
RO_USER="${DB_USER:-studio_ro}"
ROOT_PW="root_pw"

cd "$(dirname "$0")/.."

if [[ ! -f "$SNAPSHOT" ]]; then
  echo "Snapshot not found: $SNAPSHOT" >&2
  exit 1
fi

echo "==> Starting MySQL container"
docker compose up -d db

echo "==> Waiting for MySQL to be healthy"
until docker compose exec -T db mysqladmin ping -h localhost -uroot -p"$ROOT_PW" --silent >/dev/null 2>&1; do
  sleep 2
done
# Give the server a moment after first ping to accept connections fully.
sleep 2

echo "==> Importing $SNAPSHOT into \`$DB_NAME\` (this can take a while)"
# The dump has no CREATE DATABASE/USE; we target $DB_NAME explicitly.
docker compose exec -T db sh -c "exec mysql -uroot -p'$ROOT_PW' '$DB_NAME'" < "$SNAPSHOT"

echo "==> Locking the app user down to read-only (SELECT only)"
docker compose exec -T db mysql -uroot -p"$ROOT_PW" <<SQL
REVOKE ALL PRIVILEGES, GRANT OPTION ON \`$DB_NAME\`.* FROM '$RO_USER'@'%';
GRANT SELECT ON \`$DB_NAME\`.* TO '$RO_USER'@'%';
FLUSH PRIVILEGES;
SQL

echo "==> Done. Tables:"
docker compose exec -T db mysql -uroot -p"$ROOT_PW" -e "SHOW TABLES;" "$DB_NAME"
