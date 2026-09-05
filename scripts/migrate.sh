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
# Cloud SQL is reached with gcloud_sql_psql.sh (utils-bash): the Cloud SQL
# Auth Proxy with your gcloud credentials and the app's own password from
# Secret Manager, so there is nothing to type.

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

# shellcheck source=.gcp.conf
source .gcp.conf

# What the database has now: "table.column:max_length" per line.
present="$(gcloud_sql_psql.sh -q -t -A -v ON_ERROR_STOP=1 -c "
	SELECT table_name || '.' || column_name || ':' || COALESCE(character_maximum_length::text, '')
	FROM information_schema.columns
	WHERE (table_name = 'users' AND column_name IN ('google_sub', 'password_hash'))
	   OR (table_name = 'works' AND column_name IN ('imdb_id', 'tmdb_id', 'rotten_tomatoes_id'))
")"

has() {
	grep -qx "${1}" <<<"${present}"
}

# Collect the statements for what is missing, then run them in one session.
changed=()
statements=()
need() {
	changed+=("${1}")
	statements+=("${2};")
}
has "users.password_hash:.*" || need users.password_hash "ALTER TABLE users ADD COLUMN password_hash VARCHAR(300)"
has "users.google_sub:400" || need "users.google_sub (wider)" "ALTER TABLE users ALTER COLUMN google_sub TYPE VARCHAR(400)"
has "works.imdb_id:.*" || need works.imdb_id "ALTER TABLE works ADD COLUMN imdb_id VARCHAR(20) NOT NULL DEFAULT ''"
has "works.tmdb_id:.*" || need works.tmdb_id "ALTER TABLE works ADD COLUMN tmdb_id INTEGER"
has "works.rotten_tomatoes_id:.*" || need works.rotten_tomatoes_id "ALTER TABLE works ADD COLUMN rotten_tomatoes_id VARCHAR(200) NOT NULL DEFAULT ''"

if (( ${#changed[@]} == 0 )); then
	echo "${gcp_sql_instance}/${gcp_db_name}: up to date, nothing to migrate"
else
	printf '%s\n' "${statements[@]}" | gcloud_sql_psql.sh -q -v ON_ERROR_STOP=1 > /dev/null
	echo "${gcp_sql_instance}/${gcp_db_name}: migrated ${changed[*]}"
	echo "deploy with gcloud_run_deploy.sh"
fi
