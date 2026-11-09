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
#   - concert performers become people: every name in concerts.performers (a
#     JSON list of names) becomes a person of the concert's owner (one who
#     already has that name is reused) and a concert_performers row, and only
#     then is the column dropped. The new code no longer writes the column,
#     which is NOT NULL, so run this right after deploying that version.
#   - person_types (the user's own enumeration of what a person is to them)
#     and people.type_id pointing at it, made here as for organization types.
#     scripts/import_world_cloud.sh --only-types then types the people.
#   - people's names: names are no longer unique (uq_person_name goes), and
#     people.name becomes people.first_name plus a new people.surname. A name
#     that is plainly two capitalized words is split between them, the way
#     split_name in scripts/import_world.py does; any other stays whole in
#     first_name. Run before deploying the version that has these columns.
#   - a person may have several types: people.type_id is copied into the new
#     person_person_types link table, then dropped. Run right after deploying
#     the version that uses the links (its create_all makes the table).
#   - users.role ("user" or "admin"), and when no account is an admin the
#     oldest account (the site owner's, who made it) becomes one, so there is
#     always someone to delegate from. Safe before deploying: the column has a
#     server default the old version does not need to know about. On a fresh
#     database create_all makes the column; run this after the first sign-in
#     to make that account the admin.
#   - organizations.functions (a JSON list of words: teaching, consulting, ...)
#     becomes relation types, the user's own enumeration (relation_types),
#     linked to organizations through organization_relation_types: each owner
#     gets the six starting types (named as RELATION_TYPES in
#     scripts/import_world.py does) and one for any other word their
#     organizations use, every organization is linked to the types of its
#     words, and only then is the column dropped. The new code no longer
#     writes the column, which is NOT NULL, so run this right after deploying
#     that version.
#
# A table renamed here can come back empty if the old version of the app
# starts (create_all) between this and the deploy; a rename finding both
# tables drops the old one when it is empty and stops when it is not.
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
    ("users", "role", "VARCHAR(20) NOT NULL DEFAULT 'user'"),
    ("museums", "address", "VARCHAR(500) NOT NULL DEFAULT ''"),
    ("museums", "latitude", "REAL"),
    ("museums", "longitude", "REAL"),
    ("organizations", "latitude", "REAL"),
    ("organizations", "longitude", "REAL"),
    ("museums", "alone", "BOOLEAN NOT NULL DEFAULT 0"),
    ("audio_courses", "link", "VARCHAR(1000) NOT NULL DEFAULT ''"),
]

url = os.environ.get("DATABASE_URL", "sqlite:///db.gi/myworld.sqlite")
if not url.startswith("sqlite:///"):
    raise SystemExit(f"--local only handles sqlite databases, DATABASE_URL is {url}")
path = url.removeprefix("sqlite:///")
if not os.path.exists(path):
    raise SystemExit(f"{path} does not exist yet; the app creates it with all columns on first start")
# one transaction (sqlite rolls back schema changes too): a failing step leaves the file as it was
db = sqlite3.connect(path, isolation_level=None)
db.execute("BEGIN")
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
        if db.execute("SELECT (SELECT count(*) FROM companies) + (SELECT count(*) FROM person_companies)").fetchone()[0]:
            raise SystemExit(f"{path}: both companies and organizations exist and companies has rows; merge them by hand")
        # an empty pair made by an old version of the app after the rename
        db.execute("DROP TABLE person_companies")
        db.execute("DROP TABLE companies")
        tables -= {"companies", "person_companies"}
        added.append("dropped the empty companies tables left by an old version")
if "companies" in tables:
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
if "performers" in {row[1] for row in db.execute("PRAGMA table_info(concerts)")}:
    db.execute("""CREATE TABLE IF NOT EXISTS concert_performers (
        concert_id INTEGER NOT NULL REFERENCES concerts (id) ON DELETE CASCADE,
        person_id INTEGER NOT NULL REFERENCES people (id) ON DELETE CASCADE,
        PRIMARY KEY (concert_id, person_id))""")
    db.execute("""INSERT OR IGNORE INTO people (owner_id, name, description)
        SELECT DISTINCT c.owner_id, trim(p.value), '' FROM concerts c, json_each(c.performers) p
        WHERE trim(p.value) <> ''""")
    db.execute("""INSERT OR IGNORE INTO concert_performers (concert_id, person_id)
        SELECT DISTINCT c.id, pe.id FROM concerts c, json_each(c.performers) p
        JOIN people pe ON pe.owner_id = c.owner_id AND pe.name = trim(p.value)""")
    db.execute("ALTER TABLE concerts DROP COLUMN performers")
    added.append("concerts.performers -> people, concert_performers")
people_columns = {row[1] for row in db.execute("PRAGMA table_info(people)")}
tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
if people_columns and "person_types" not in tables:
    db.execute("""CREATE TABLE IF NOT EXISTS person_types (
        id INTEGER NOT NULL PRIMARY KEY,
        owner_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        name VARCHAR(100) NOT NULL,
        description TEXT NOT NULL,
        CONSTRAINT uq_person_type_name UNIQUE (owner_id, name))""")
    db.execute("CREATE INDEX IF NOT EXISTS ix_person_types_owner_id ON person_types (owner_id)")
    db.execute("ALTER TABLE people ADD COLUMN type_id INTEGER REFERENCES person_types (id) ON DELETE SET NULL")
    added.append("person_types, people.type_id")
if "name" in people_columns:
    import re
    # sqlite cannot drop a constraint: the table is made again without it
    (create,) = db.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'people'").fetchone()
    create = re.sub(r",\s*CONSTRAINT uq_person_name UNIQUE \([^)]*\)", "", create)
    create = re.sub(r"^CREATE TABLE \"?people\"?", "CREATE TABLE people_new", create)
    db.execute(create)
    db.execute("INSERT INTO people_new SELECT * FROM people")
    db.execute("DROP TABLE people")
    db.execute("ALTER TABLE people_new RENAME TO people")
    db.execute("CREATE INDEX IF NOT EXISTS ix_people_owner_id ON people (owner_id)")
    db.execute("ALTER TABLE people RENAME COLUMN name TO first_name")
    db.execute("ALTER TABLE people ADD COLUMN surname VARCHAR(200) NOT NULL DEFAULT ''")
    two_words = re.compile(r"([A-Z][^ ]*) ([A-Z][^ ]*)")
    for person_id, name in db.execute("SELECT id, first_name FROM people").fetchall():
        match = two_words.fullmatch(name)
        if match and match.group(1) != "The":
            db.execute("UPDATE people SET first_name = ?, surname = ? WHERE id = ?", (match.group(1), match.group(2), person_id))
    added.append("people.name -> first_name, surname (not unique)")
people_columns = {row[1] for row in db.execute("PRAGMA table_info(people)")}
if "type_id" in people_columns:
    import re
    db.execute("""CREATE TABLE IF NOT EXISTS person_person_types (
        person_id INTEGER NOT NULL REFERENCES people (id) ON DELETE CASCADE,
        type_id INTEGER NOT NULL REFERENCES person_types (id) ON DELETE CASCADE,
        PRIMARY KEY (person_id, type_id))""")
    db.execute("INSERT OR IGNORE INTO person_person_types (person_id, type_id) SELECT id, type_id FROM people WHERE type_id IS NOT NULL")
    # sqlite cannot drop a column a foreign key uses: the table is made again without it
    (create,) = db.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'people'").fetchone()
    create = re.sub(r",\s*type_id INTEGER(\s+REFERENCES\s+\w+\s*\(\w+\))?[^,)]*", "", create)
    create = re.sub(r",\s*FOREIGN KEY\s*\(type_id\)[^,)]*\([^)]*\)[^,)]*", "", create)
    create = re.sub(r"^CREATE TABLE \"?people\"?", "CREATE TABLE people_new", create)
    keep = ", ".join(column for column in people_columns if column != "type_id")
    db.execute(create)
    db.execute(f"INSERT INTO people_new ({keep}) SELECT {keep} FROM people")
    db.execute("DROP TABLE people")
    db.execute("ALTER TABLE people_new RENAME TO people")
    db.execute("CREATE INDEX IF NOT EXISTS ix_people_owner_id ON people (owner_id)")
    added.append("people.type_id -> person_person_types")
if "functions" in {row[1] for row in db.execute("PRAGMA table_info(organizations)")}:
    import json
    # as RELATION_TYPES in scripts/import_world.py
    standard = {
        "teaching": ("Teaching", "I taught there"),
        "training-provider": ("Training provider", "Hired me to teach"),
        "consulting": ("Consulting", "I consulted for them"),
        "certification": ("Certification", "Certified me"),
        "publisher": ("Publisher", "I consumed media they published"),
        "education": ("Education", "I studied there"),
    }
    db.execute("""CREATE TABLE IF NOT EXISTS relation_types (
        id INTEGER NOT NULL PRIMARY KEY,
        owner_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        name VARCHAR(100) NOT NULL,
        description TEXT NOT NULL,
        CONSTRAINT uq_relation_type_name UNIQUE (owner_id, name))""")
    db.execute("CREATE INDEX IF NOT EXISTS ix_relation_types_owner_id ON relation_types (owner_id)")
    db.execute("""CREATE TABLE IF NOT EXISTS organization_relation_types (
        organization_id INTEGER NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
        relation_type_id INTEGER NOT NULL REFERENCES relation_types (id) ON DELETE CASCADE,
        PRIMARY KEY (organization_id, relation_type_id))""")
    rows = db.execute("SELECT id, owner_id, functions FROM organizations").fetchall()
    for owner_id in {owner for _, owner, _ in rows}:
        for name, description in standard.values():
            db.execute("INSERT OR IGNORE INTO relation_types (owner_id, name, description) VALUES (?, ?, ?)", (owner_id, name, description))
    for organization_id, owner_id, functions in rows:
        for word in {w.strip() for w in json.loads(functions or "[]") if w.strip()}:
            spaced = word.replace("-", " ")
            name, description = standard.get(word, (spaced[:1].upper() + spaced[1:], ""))
            db.execute("INSERT OR IGNORE INTO relation_types (owner_id, name, description) VALUES (?, ?, ?)", (owner_id, name, description))
            (type_id,) = db.execute("SELECT id FROM relation_types WHERE owner_id = ? AND name = ?", (owner_id, name)).fetchone()
            db.execute("INSERT OR IGNORE INTO organization_relation_types (organization_id, relation_type_id) VALUES (?, ?)", (organization_id, type_id))
    db.execute("ALTER TABLE organizations DROP COLUMN functions")
    added.append("organizations.functions -> relation_types, organization_relation_types")
courses = {row[1] for row in db.execute("PRAGMA table_info(audio_courses)")}
if "device" in courses:
    # the device names become the account's own devices, each course pointing to its one
    db.execute("""CREATE TABLE IF NOT EXISTS devices (
        id INTEGER NOT NULL PRIMARY KEY,
        owner_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        name VARCHAR(100) NOT NULL,
        description TEXT NOT NULL,
        CONSTRAINT uq_device_name UNIQUE (owner_id, name))""")
    db.execute("CREATE INDEX IF NOT EXISTS ix_devices_owner_id ON devices (owner_id)")
    db.execute("INSERT OR IGNORE INTO devices (owner_id, name, description) SELECT DISTINCT owner_id, device, '' FROM audio_courses WHERE device <> ''")
    if "device_id" not in courses:
        db.execute("ALTER TABLE audio_courses ADD COLUMN device_id INTEGER REFERENCES devices (id) ON DELETE SET NULL")
    db.execute("""UPDATE audio_courses SET device_id = (
        SELECT d.id FROM devices d WHERE d.owner_id = audio_courses.owner_id AND d.name = audio_courses.device) WHERE device <> ''""")
    db.execute("ALTER TABLE audio_courses DROP COLUMN device")
    added.append("audio_courses.device -> devices, audio_courses.device_id")
if not db.execute("SELECT 1 FROM users WHERE role = 'admin'").fetchone():
    oldest = db.execute("SELECT min(id) FROM users").fetchone()[0]
    if oldest is not None:
        db.execute("UPDATE users SET role = 'admin' WHERE id = ?", (oldest,))
        added.append(f"user {oldest} made the first admin")
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
	WHERE (table_name = 'users' AND column_name IN ('google_sub', 'password_hash', 'role'))
	   OR (table_name = 'works' AND column_name IN ('imdb_id', 'tmdb_id', 'rotten_tomatoes_id'))
	   OR (table_name = 'people' AND column_name = 'company')
	   OR (table_name IN ('companies', 'organizations') AND column_name = 'id')
	   OR (table_name = 'organizations' AND column_name IN ('type_id', 'functions'))
	   OR (table_name = 'concerts' AND column_name = 'performers')
	   OR (table_name = 'people' AND column_name IN ('name', 'type_id'))
	   OR (table_name = 'person_types' AND column_name = 'id')
	   OR (table_name IN ('museums', 'organizations') AND column_name IN ('address', 'latitude', 'longitude', 'alone'))
	   OR (table_name = 'audio_courses' AND column_name IN ('device', 'device_id', 'link'))
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
if has "companies.id:.*" && has "organizations.id:.*"; then
	rows="$(gcloud_sql_psql.sh -q -t -A -v ON_ERROR_STOP=1 -c "SELECT (SELECT count(*) FROM companies) + (SELECT count(*) FROM person_companies)")"
	if [[ "${rows}" != "0" ]]; then
		echo "both companies and organizations exist and companies has rows; merge them by hand" >&2
		exit 1
	fi
	# an empty pair made by an old version of the app after the rename
	need "dropped the empty companies tables left by an old version" "DROP TABLE person_companies; DROP TABLE companies"
elif has "companies.id:.*"; then
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

if has "concerts.performers:.*"; then
	need "concerts.performers -> people, concert_performers" "CREATE TABLE IF NOT EXISTS concert_performers (
			concert_id INTEGER NOT NULL REFERENCES concerts (id) ON DELETE CASCADE,
			person_id INTEGER NOT NULL REFERENCES people (id) ON DELETE CASCADE,
			PRIMARY KEY (concert_id, person_id));
		INSERT INTO people (owner_id, name, description)
			SELECT DISTINCT c.owner_id, btrim(p.name), '' FROM concerts c, json_array_elements_text(c.performers::json) AS p (name)
			WHERE btrim(p.name) <> ''
			ON CONFLICT ON CONSTRAINT uq_person_name DO NOTHING;
		INSERT INTO concert_performers (concert_id, person_id)
			SELECT DISTINCT c.id, pe.id FROM concerts c
			CROSS JOIN LATERAL json_array_elements_text(c.performers::json) AS p (name)
			JOIN people pe ON pe.owner_id = c.owner_id AND pe.name = btrim(p.name)
			ON CONFLICT DO NOTHING;
		ALTER TABLE concerts DROP COLUMN performers"
fi

if ! has "person_types.id:.*"; then
	need "person_types, people.type_id" "CREATE TABLE IF NOT EXISTS person_types (
			id SERIAL PRIMARY KEY,
			owner_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
			name VARCHAR(100) NOT NULL,
			description TEXT NOT NULL,
			CONSTRAINT uq_person_type_name UNIQUE (owner_id, name));
		CREATE INDEX IF NOT EXISTS ix_person_types_owner_id ON person_types (owner_id);
		ALTER TABLE people ADD COLUMN type_id INTEGER REFERENCES person_types (id) ON DELETE SET NULL"
fi
if has "people.name:.*"; then
	need "people.name -> first_name, surname (not unique)" "ALTER TABLE people DROP CONSTRAINT IF EXISTS uq_person_name;
		ALTER TABLE people RENAME COLUMN name TO first_name;
		ALTER TABLE people ADD COLUMN surname VARCHAR(200) NOT NULL DEFAULT '';
		UPDATE people
			SET first_name = substring(first_name from '^([A-Z][^ ]*) [A-Z][^ ]*\$'),
				surname = substring(first_name from '^[A-Z][^ ]* ([A-Z][^ ]*)\$')
			WHERE first_name ~ '^[A-Z][^ ]* [A-Z][^ ]*\$' AND first_name NOT LIKE 'The %'"
fi
if has "people.type_id:.*" || ! has "person_types.id:.*"; then
	need "people.type_id -> person_person_types" "CREATE TABLE IF NOT EXISTS person_person_types (
			person_id INTEGER NOT NULL REFERENCES people (id) ON DELETE CASCADE,
			type_id INTEGER NOT NULL REFERENCES person_types (id) ON DELETE CASCADE,
			PRIMARY KEY (person_id, type_id));
		INSERT INTO person_person_types (person_id, type_id)
			SELECT id, type_id FROM people WHERE type_id IS NOT NULL
			ON CONFLICT DO NOTHING;
		ALTER TABLE people DROP COLUMN type_id"
fi

if has "organizations.functions:.*"; then
	# relation_words: every word to its type name (the six of RELATION_TYPES in
	# scripts/import_world.py, any other capitalized), standard for those six
	need "organizations.functions -> relation_types, organization_relation_types" "CREATE TABLE IF NOT EXISTS relation_types (
			id SERIAL PRIMARY KEY,
			owner_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
			name VARCHAR(100) NOT NULL,
			description TEXT NOT NULL,
			CONSTRAINT uq_relation_type_name UNIQUE (owner_id, name));
		CREATE INDEX IF NOT EXISTS ix_relation_types_owner_id ON relation_types (owner_id);
		CREATE TABLE IF NOT EXISTS organization_relation_types (
			organization_id INTEGER NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
			relation_type_id INTEGER NOT NULL REFERENCES relation_types (id) ON DELETE CASCADE,
			PRIMARY KEY (organization_id, relation_type_id));
		CREATE TEMP TABLE relation_words (word TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL, standard BOOLEAN NOT NULL) ON COMMIT DROP;
		INSERT INTO relation_words VALUES
			('teaching', 'Teaching', 'I taught there', true),
			('training-provider', 'Training provider', 'Hired me to teach', true),
			('consulting', 'Consulting', 'I consulted for them', true),
			('certification', 'Certification', 'Certified me', true),
			('publisher', 'Publisher', 'I consumed media they published', true),
			('education', 'Education', 'I studied there', true);
		INSERT INTO relation_words
			SELECT DISTINCT w, upper(left(replace(w, '-', ' '), 1)) || substr(replace(w, '-', ' '), 2), '', false
			FROM (SELECT btrim(f) AS w FROM organizations, json_array_elements_text(functions::json) AS f) AS words
			WHERE w <> ''
			ON CONFLICT (word) DO NOTHING;
		INSERT INTO relation_types (owner_id, name, description)
			SELECT DISTINCT o.owner_id, r.name, r.description FROM organizations o
			JOIN relation_words r ON r.standard OR r.word IN (SELECT btrim(f) FROM json_array_elements_text(o.functions::json) AS f)
			ON CONFLICT ON CONSTRAINT uq_relation_type_name DO NOTHING;
		INSERT INTO organization_relation_types (organization_id, relation_type_id)
			SELECT DISTINCT o.id, t.id FROM organizations o
			CROSS JOIN LATERAL json_array_elements_text(o.functions::json) AS f (word)
			JOIN relation_words r ON r.word = btrim(f.word)
			JOIN relation_types t ON t.owner_id = o.owner_id AND t.name = r.name
			ON CONFLICT DO NOTHING;
		ALTER TABLE organizations DROP COLUMN functions"
fi
if ! has "users.role:.*"; then
	need users.role "ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'user'"
fi
# no admin (the column is new, or every admin was removed by hand): the oldest account becomes one
if ! has "users.role:.*" || [[ "$(gcloud_sql_psql.sh -q -t -A -v ON_ERROR_STOP=1 -c "SELECT count(*) FROM users WHERE role = 'admin'")" == "0" ]]; then
	need "the oldest account made the first admin" "UPDATE users SET role = 'admin'
		WHERE id = (SELECT min(id) FROM users) AND NOT EXISTS (SELECT 1 FROM users WHERE role = 'admin')"
fi
# where a museum or an organization is (adding columns: run before the deploy)
has "museums.address:.*" || need museums.address "ALTER TABLE museums ADD COLUMN address VARCHAR(500) NOT NULL DEFAULT ''"
for table in museums organizations; do
	for column in latitude longitude; do
		has "${table}.${column}:.*" || need "${table}.${column}" "ALTER TABLE ${table} ADD COLUMN ${column} DOUBLE PRECISION"
	done
done
# a museum visit made alone, told apart from one whose company is not filled in
has "museums.alone:.*" || need museums.alone "ALTER TABLE museums ADD COLUMN alone BOOLEAN NOT NULL DEFAULT false"
# a page about an audio course that is not sold any more (adding a column: run before the deploy)
has "audio_courses.link:.*" || need audio_courses.link "ALTER TABLE audio_courses ADD COLUMN link VARCHAR(1000) NOT NULL DEFAULT ''"
# an audio course's device name -> the account's own devices (drops the name
# column the new code no longer has: deploy first, then run this right away)
if has "audio_courses.device:.*"; then
	need "audio_courses.device -> devices, audio_courses.device_id" "CREATE TABLE IF NOT EXISTS devices (
			id SERIAL PRIMARY KEY,
			owner_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
			name VARCHAR(100) NOT NULL,
			description TEXT NOT NULL,
			CONSTRAINT uq_device_name UNIQUE (owner_id, name));
		CREATE INDEX IF NOT EXISTS ix_devices_owner_id ON devices (owner_id);
		INSERT INTO devices (owner_id, name, description)
			SELECT DISTINCT owner_id, device, '' FROM audio_courses WHERE device <> ''
			ON CONFLICT DO NOTHING;
		ALTER TABLE audio_courses ADD COLUMN IF NOT EXISTS device_id INTEGER REFERENCES devices (id) ON DELETE SET NULL;
		UPDATE audio_courses c SET device_id = d.id FROM devices d
			WHERE d.owner_id = c.owner_id AND d.name = c.device AND c.device <> '';
		ALTER TABLE audio_courses DROP COLUMN device"
fi

if (( ${#changed[@]} == 0 )); then
	echo "${gcp_sql_instance}/${gcp_db_name}: up to date, nothing to migrate"
else
	# one transaction: a failing statement stops psql and leaves the database as it was
	printf '%s\n' "BEGIN;" "${statements[@]}" "COMMIT;" | gcloud_sql_psql.sh -q -v ON_ERROR_STOP=1 > /dev/null
	echo "${gcp_sql_instance}/${gcp_db_name}: migrated ${changed[*]}"
	echo "deploy with gcloud_run_deploy.sh"
fi
