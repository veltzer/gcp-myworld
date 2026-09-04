#!/bin/bash
# Schema migrations. Tables are created by create_all on startup but never
# altered, so columns added after the first deploy need this, once, before
# deploying the version that uses them. Every statement is a no-op when its
# column already exists, so the script is safe to re-run at any time.
#
#   scripts/migrate.sh          the Cloud SQL database from .gcp.conf
#   scripts/migrate.sh --local  the local sqlite file (db.gi/myworld.sqlite or DATABASE_URL)
#
# Migrations so far:
#   - users.password_hash and a wider users.google_sub (email and OAuth sign-in)
#   - works.imdb_id, works.tmdb_id, works.rotten_tomatoes_id (film lookups)
#
# Cloud SQL is reached through the Cloud SQL Auth Proxy with your gcloud
# credentials; the database password comes from Secret Manager, the same
# secret the app uses, so there is nothing to type.

set -euo pipefail

cd "$(dirname "${0}")/.."

if [[ "${1:-}" == "--local" ]]; then
	echo "== local sqlite"
	python - <<'PY'
import os
import sqlite3

# (table, column, sqlite type); sqlite ignores VARCHAR lengths, so the wider google_sub needs nothing
COLUMNS = [
    ("users", "password_hash", "VARCHAR(300)"),
    ("works", "imdb_id", "VARCHAR(20) NOT NULL DEFAULT ''"),
    ("works", "tmdb_id", "INTEGER"),
    ("works", "rotten_tomatoes_id", "VARCHAR(200) NOT NULL DEFAULT ''"),
]

url = os.environ.get("DATABASE_URL", "sqlite:///db.gi/myworld.sqlite")
if not url.startswith("sqlite:///"):
    raise SystemExit(f"--local only handles sqlite databases, DATABASE_URL is {url}")
path = url.removeprefix("sqlite:///")
if not os.path.exists(path):
    raise SystemExit(f"{path} does not exist yet; the app creates it with all columns on first start")
db = sqlite3.connect(path)
for table, column, kind in COLUMNS:
    existing = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
    if column in existing:
        print(f"{path}: {table}.{column} already there")
    else:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
        print(f"{path}: added {table}.{column}")
db.commit()
PY
	exit 0
fi

# shellcheck source=/dev/null
source .gcp.conf
export CLOUDSDK_ACTIVE_CONFIG_NAME="${gcp_configuration_name}"

# The Cloud SQL Auth Proxy and the postgres client are not part of the base SDK.
for tool in cloud-sql-proxy psql pg_isready; do
	if ! command -v "${tool}" >/dev/null; then
		echo "${tool} not found on PATH; install it first:"
		echo "  cloud-sql-proxy: gcloud components install cloud-sql-proxy"
		echo "  psql, pg_isready: apt install postgresql-client"
		exit 1
	fi
done

echo "== Cloud SQL ${gcp_sql_instance}, database ${gcp_db_name}, user ${gcp_db_user}"
# The app's own password, from Secret Manager; nobody needs to know it.
PGPASSWORD="$(gcloud secrets versions access latest --secret "${gcp_service}-db-pass")"
export PGPASSWORD

# Run the proxy ourselves rather than through `gcloud sql connect`, which
# insists on prompting for the password on stdin, where the SQL is.
CONNECTION_NAME="$(gcloud sql instances describe "${gcp_sql_instance}" --format 'value(connectionName)')"
PORT=54329
cloud-sql-proxy --gcloud-auth --port "${PORT}" "${CONNECTION_NAME}" &
PROXY_PID="${!}"
trap 'kill "${PROXY_PID}" 2>/dev/null' EXIT
for _ in $(seq 1 30); do
	if pg_isready -h 127.0.0.1 -p "${PORT}" -q; then
		break
	fi
	sleep 1
done

psql -h 127.0.0.1 -p "${PORT}" -U "${gcp_db_user}" -d "${gcp_db_name}" -v ON_ERROR_STOP=1 <<'SQL'
\echo == before
SELECT table_name, column_name, data_type, character_maximum_length, is_nullable
FROM information_schema.columns
WHERE (table_name = 'users' AND column_name IN ('google_sub', 'password_hash'))
   OR (table_name = 'works' AND column_name IN ('imdb_id', 'tmdb_id', 'rotten_tomatoes_id'))
ORDER BY table_name, column_name;

\echo == migrating
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(300);
ALTER TABLE users ALTER COLUMN google_sub TYPE VARCHAR(400);
ALTER TABLE works ADD COLUMN IF NOT EXISTS imdb_id VARCHAR(20) NOT NULL DEFAULT '';
ALTER TABLE works ADD COLUMN IF NOT EXISTS tmdb_id INTEGER;
ALTER TABLE works ADD COLUMN IF NOT EXISTS rotten_tomatoes_id VARCHAR(200) NOT NULL DEFAULT '';

\echo == after
SELECT table_name, column_name, data_type, character_maximum_length, is_nullable
FROM information_schema.columns
WHERE (table_name = 'users' AND column_name IN ('google_sub', 'password_hash'))
   OR (table_name = 'works' AND column_name IN ('imdb_id', 'tmdb_id', 'rotten_tomatoes_id'))
ORDER BY table_name, column_name;
SQL

echo "== done, deploy with gcloud_run_deploy.sh"
