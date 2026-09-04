#!/bin/bash
# Schema migrations. Tables are created by create_all on startup but never
# altered, so columns added after the first deploy need this, once, before
# deploying the version that uses them. The script first looks at what the
# database has, applies only what is missing, and ends with one line saying
# whether anything was changed, so it is safe and cheap to run any time.
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
added = []
for table, column, kind in COLUMNS:
    existing = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
        added.append(f"{table}.{column}")
db.commit()
if added:
    print(f"{path}: added {', '.join(added)}")
else:
    print(f"{path}: up to date, nothing to migrate")
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

# The app's own password, from Secret Manager; nobody needs to know it.
PGPASSWORD="$(gcloud secrets versions access latest --secret "${gcp_service}-db-pass")"
export PGPASSWORD

# Run the proxy ourselves rather than through `gcloud sql connect`, which
# insists on prompting for the password on stdin. Its chatter goes to a log
# that is only shown if something fails.
CONNECTION_NAME="$(gcloud sql instances describe "${gcp_sql_instance}" --format 'value(connectionName)')"
PORT=54329
PROXY_LOG="$(mktemp)"
cloud-sql-proxy --gcloud-auth --port "${PORT}" "${CONNECTION_NAME}" >"${PROXY_LOG}" 2>&1 &
PROXY_PID="${!}"
cleanup() {
	kill "${PROXY_PID}" 2>/dev/null || true
	rm -f "${PROXY_LOG}"
}
trap cleanup EXIT
for _ in $(seq 1 30); do
	if pg_isready -h 127.0.0.1 -p "${PORT}" -q; then
		break
	fi
	sleep 1
done
if ! pg_isready -h 127.0.0.1 -p "${PORT}" -q; then
	echo "could not reach ${CONNECTION_NAME} through the proxy:"
	cat "${PROXY_LOG}"
	exit 1
fi

# -X skips ~/.psqlrc (timing and the like); -qtA gives bare values, one per line.
sql() {
	psql -X -q -t -A -v ON_ERROR_STOP=1 -h 127.0.0.1 -p "${PORT}" -U "${gcp_db_user}" -d "${gcp_db_name}" "${@}"
}

# What the database has now: "table.column:max_length" per line.
present="$(sql -c "
	SELECT table_name || '.' || column_name || ':' || COALESCE(character_maximum_length::text, '')
	FROM information_schema.columns
	WHERE (table_name = 'users' AND column_name IN ('google_sub', 'password_hash'))
	   OR (table_name = 'works' AND column_name IN ('imdb_id', 'tmdb_id', 'rotten_tomatoes_id'))
")"

has_column() {
	grep -qx "${1}:.*" <<<"${present}"
}

# (what, check, statement): the check passes when nothing needs doing.
changed=()
apply() {
	local what="${1}" statement="${2}"
	sql -c "${statement}" >/dev/null
	changed+=("${what}")
}
has_column users.password_hash || apply users.password_hash "ALTER TABLE users ADD COLUMN password_hash VARCHAR(300)"
grep -qx "users.google_sub:400" <<<"${present}" || apply "users.google_sub (wider)" "ALTER TABLE users ALTER COLUMN google_sub TYPE VARCHAR(400)"
has_column works.imdb_id || apply works.imdb_id "ALTER TABLE works ADD COLUMN imdb_id VARCHAR(20) NOT NULL DEFAULT ''"
has_column works.tmdb_id || apply works.tmdb_id "ALTER TABLE works ADD COLUMN tmdb_id INTEGER"
has_column works.rotten_tomatoes_id || apply works.rotten_tomatoes_id "ALTER TABLE works ADD COLUMN rotten_tomatoes_id VARCHAR(200) NOT NULL DEFAULT ''"

if (( ${#changed[@]} == 0 )); then
	echo "${gcp_sql_instance}/${gcp_db_name}: up to date, nothing to migrate"
else
	echo "${gcp_sql_instance}/${gcp_db_name}: migrated ${changed[*]}"
	echo "deploy with gcloud_run_deploy.sh"
fi
