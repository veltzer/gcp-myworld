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
#   - people.company dropped: a person's companies are rows in companies, linked
#     through person_companies (both new tables, made by create_all); the column
#     is NOT NULL without a server default, so the app can no longer add people
#     while it exists. Re-run scripts/import_world_cloud.sh afterwards to link
#     the imported people to their companies.
#   - companies renamed to organizations, person_companies to
#     person_organizations (its company_id to organization_id), with their
#     index and unique constraint, keeping every row. Run it before deploying
#     the version that uses the new names: that version's create_all would
#     otherwise make empty tables under them, which this then refuses to
#     overwrite.
#   - organization_types (the user's own enumeration of what an organization
#     is) and organizations.type_id pointing at it. create_all would make the
#     table, but the column needs it to exist first, so this makes both.
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
people = {row[1] for row in db.execute("PRAGMA table_info(people)")}
if "company" in people:
    db.execute("ALTER TABLE people DROP COLUMN company")
    added.append("people.company (dropped)")
tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
if "companies" in tables:
    if "organizations" in tables:
        raise SystemExit(f"{path}: both companies and organizations exist; drop the empty one by hand")
    db.execute("ALTER TABLE companies RENAME TO organizations")
    db.execute("DROP INDEX IF EXISTS ix_companies_owner_id")
    db.execute("CREATE INDEX ix_organizations_owner_id ON organizations (owner_id)")
    db.execute("ALTER TABLE person_companies RENAME TO person_organizations")
    db.execute("ALTER TABLE person_organizations RENAME COLUMN company_id TO organization_id")
    added.append("companies -> organizations")
    tables = (tables - {"companies"}) | {"organizations"}
if "organizations" in tables and "type_id" not in {row[1] for row in db.execute("PRAGMA table_info(organizations)")}:
    db.execute("""CREATE TABLE IF NOT EXISTS organization_types (
        id INTEGER NOT NULL PRIMARY KEY,
        owner_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        name VARCHAR(100) NOT NULL,
        description TEXT NOT NULL,
        CONSTRAINT uq_organization_type_name UNIQUE (owner_id, name))""")
    db.execute("CREATE INDEX IF NOT EXISTS ix_organization_types_owner_id ON organization_types (owner_id)")
    db.execute("ALTER TABLE organizations ADD COLUMN type_id INTEGER REFERENCES organization_types (id) ON DELETE SET NULL")
    added.append("organization_types, organizations.type_id")
db.commit()
if added:
    print(f"{path}: migrated {', '.join(added)}")
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
	   OR (table_name = 'people' AND column_name = 'company')
	   OR (table_name IN ('companies', 'organizations') AND column_name = 'id')
	   OR (table_name = 'organizations' AND column_name = 'type_id')
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
! has "people.company:.*" || need "people.company (dropped)" "ALTER TABLE people DROP COLUMN company"
if has "companies.id:.*"; then
	if has "organizations.id:.*"; then
		echo "both companies and organizations exist; drop the empty one by hand" >&2
		exit 1
	fi
	need "companies -> organizations" "ALTER TABLE companies RENAME TO organizations;
		ALTER TABLE organizations RENAME CONSTRAINT uq_company_name TO uq_organization_name;
		ALTER INDEX ix_companies_owner_id RENAME TO ix_organizations_owner_id;
		ALTER TABLE person_companies RENAME TO person_organizations;
		ALTER TABLE person_organizations RENAME COLUMN company_id TO organization_id"
fi
if { has "companies.id:.*" || has "organizations.id:.*"; } && ! has "organizations.type_id:.*"; then
	need "organization_types, organizations.type_id" "CREATE TABLE IF NOT EXISTS organization_types (
			id SERIAL PRIMARY KEY,
			owner_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
			name VARCHAR(100) NOT NULL,
			description TEXT NOT NULL,
			CONSTRAINT uq_organization_type_name UNIQUE (owner_id, name));
		CREATE INDEX IF NOT EXISTS ix_organization_types_owner_id ON organization_types (owner_id);
		ALTER TABLE organizations ADD COLUMN type_id INTEGER REFERENCES organization_types (id) ON DELETE SET NULL"
fi

if (( ${#changed[@]} == 0 )); then
	echo "${gcp_sql_instance}/${gcp_db_name}: up to date, nothing to migrate"
else
	printf '%s\n' "${statements[@]}" | gcloud_sql_psql.sh -q -v ON_ERROR_STOP=1 > /dev/null
	echo "${gcp_sql_instance}/${gcp_db_name}: migrated ${changed[*]}"
	echo "deploy with gcloud_run_deploy.sh"
fi
