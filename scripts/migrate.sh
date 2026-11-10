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
#   - tables named for what a row is: works -> library_works, user_works ->
#     library_entries, concerts -> concert_visits, museums -> museum_visits,
#     concert_people -> concert_companions, museum_people ->
#     museum_companions, person_person_types -> person_type_links (its type_id
#     to person_type_id); on Cloud SQL also the constraints, indexes and
#     sequences named after them, those of companies and person_companies
#     included. Run before deploying the version that uses
#     the new names, deploy right away, then run this again: a pair found
#     with one side empty keeps the side with rows.
#   - books: library_works.goodreads_id and simania_id (catalog ids), and
#     library_entries.image_id (the cover). Adding columns: run before the
#     deploy.
#   - people.middle_name, between the first name and the surname: adding a
#     column, run before the deploy; then scripts/tidy_names.py (through
#     scripts/with_cloud_db.sh for Cloud SQL) moves the middle names into it.
#   - people.honorific ("Dr.", "Sir"), before the first name: adding a
#     column, run before the deploy; scripts/tidy_names.py then moves a
#     title leading a whole name into it.
#   - people.is_self, the account owner's own person: adding a column, run
#     before the deploy; then scripts/import_world_cloud.sh --only-types makes
#     that person and turns the person types that are relations (Friend,
#     Co-Worker, ...) into person relations to it.
#   - a kind for every link of a person to an organization: person_organizations
#     gets relation_type_id (to person_organization_types, which create_all
#     makes), every link already there becomes "Worked at" (made for each
#     owner that has links), and the key becomes (person_id, organization_id,
#     relation_type_id), so two people-organization links may differ by kind.
#     The new code writes the kind and the old code cannot, so run this right
#     after deploying that version; then --only-types adds the other kinds.
#   - countries and cities: their tables (create_all makes them; made here too; a
#     city points to its country) and a
#     city_id on places, museum_visits and organizations (adding columns:
#     run before the deploy); then scripts/link_cities.py makes the cities
#     from the text and links every row. Only once every place and museum
#     visit that names a city is linked does this drop places.city,
#     places.country and museum_visits.city (and key a place by its city_id):
#     run it again right after deploying the version that no longer has them.
#     organizations.location stays: it says more than the city.
#   - cities.image_id and countries.image_id, with the photo's credit
#     (image_source, image_license, image_author): adding columns, run before
#     the deploy; scripts/fetch_pictures.py then fills them from Wikipedia.
#   - places: every concert's venue, city and country become a row of places
#     (one per account, name and city; a concert with a city but no venue
#     gives a place named after the city), concert_visits.place_id points to
#     it, and only then are the three columns dropped. The new code no longer
#     writes them, and they are NOT NULL, so run this right after deploying
#     that version (its create_all makes the places table).
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
    ("youtube_videos", "channel", "VARCHAR(200) NOT NULL DEFAULT ''"),
    ("youtube_videos", "category", "VARCHAR(100) NOT NULL DEFAULT ''"),
    ("youtube_videos", "duration", "INTEGER"),
    ("youtube_videos", "uploaded", "DATE"),
    ("youtube_videos", "views", "BIGINT"),
    ("youtube_videos", "unavailable", "BOOLEAN NOT NULL DEFAULT 0"),
    ("people", "middle_name", "VARCHAR(200) NOT NULL DEFAULT ''"),
    ("people", "honorific", "VARCHAR(50) NOT NULL DEFAULT ''"),
    ("people", "is_self", "BOOLEAN NOT NULL DEFAULT 0"),
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
    # a table not there yet is made by the app, with all its columns
    if existing and column not in existing:
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
# old name -> new name; the link tables first, so an empty pair is dropped before what it points at
RENAMES = [
    ("concert_people", "concert_companions"),
    ("museum_people", "museum_companions"),
    ("person_person_types", "person_type_links"),
    ("user_works", "library_entries"),
    ("museums", "museum_visits"),
    ("concerts", "concert_visits"),
    ("works", "library_works"),
]
for old, new in RENAMES:
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if old not in tables:
        continue
    if new in tables:
        # one side was made empty by create_all (an old version after the rename, or the new one before it)
        old_rows = db.execute(f"SELECT count(*) FROM {old}").fetchone()[0]
        new_rows = db.execute(f"SELECT count(*) FROM {new}").fetchone()[0]
        if old_rows and new_rows:
            raise SystemExit(f"{path}: both {old} and {new} have rows; merge them by hand")
        db.execute(f"DROP TABLE {new if old_rows else old}")
        if not old_rows:
            added.append(f"dropped the empty {old} left by an old version")
            continue
    # sqlite points the other tables' foreign keys at the new name itself
    db.execute(f"ALTER TABLE {old} RENAME TO {new}")
    indexes = db.execute("SELECT name, sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ? AND name LIKE ?", (new, f"ix_{old}_%")).fetchall()
    for name, sql in indexes:
        db.execute(f"DROP INDEX {name}")
        db.execute(sql.replace(name, f"ix_{new}_{name.removeprefix(f'ix_{old}_')}", 1))
    added.append(f"{old} -> {new}")
if "type_id" in {row[1] for row in db.execute("PRAGMA table_info(person_type_links)")}:
    db.execute("ALTER TABLE person_type_links RENAME COLUMN type_id TO person_type_id")
    added.append("person_type_links.type_id -> person_type_id")
# columns of tables that have their new names only now
for table, column, kind in [
    ("library_works", "goodreads_id", "VARCHAR(20) NOT NULL DEFAULT ''"),
    ("library_works", "simania_id", "VARCHAR(20) NOT NULL DEFAULT ''"),
    ("library_entries", "image_id", "INTEGER REFERENCES images (id) ON DELETE SET NULL"),
]:
    existing = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
    if existing and column not in existing:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
        added.append(f"{table}.{column}")
concert_columns = {row[1] for row in db.execute("PRAGMA table_info(concert_visits)")}
if "venue" in concert_columns:
    db.execute("""CREATE TABLE IF NOT EXISTS places (
        id INTEGER PRIMARY KEY,
        owner_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        name VARCHAR(300) NOT NULL, city VARCHAR(100) NOT NULL, country VARCHAR(100) NOT NULL,
        address VARCHAR(500) NOT NULL, latitude FLOAT, longitude FLOAT,
        website VARCHAR(1000) NOT NULL, remark TEXT NOT NULL,
        CONSTRAINT uq_place_name UNIQUE (owner_id, name, city))""")
    db.execute("CREATE INDEX IF NOT EXISTS ix_places_owner_id ON places (owner_id)")
    db.execute("""INSERT OR IGNORE INTO places (owner_id, name, city, country, address, website, remark)
        SELECT owner_id, coalesce(nullif(trim(venue), ''), trim(city)), trim(city), trim(country), '', '', ''
        FROM concert_visits WHERE trim(venue) <> '' OR trim(city) <> '' ORDER BY id""")
    if "place_id" not in concert_columns:
        db.execute("ALTER TABLE concert_visits ADD COLUMN place_id INTEGER REFERENCES places (id) ON DELETE SET NULL")
    db.execute("CREATE INDEX IF NOT EXISTS ix_concert_visits_place_id ON concert_visits (place_id)")
    db.execute("""UPDATE concert_visits SET place_id = (
        SELECT p.id FROM places p WHERE p.owner_id = concert_visits.owner_id
            AND p.name = coalesce(nullif(trim(concert_visits.venue), ''), trim(concert_visits.city)) AND p.city = trim(concert_visits.city))
        WHERE trim(venue) <> '' OR trim(city) <> ''""")
    for column in ("venue", "city", "country"):
        db.execute(f"ALTER TABLE concert_visits DROP COLUMN {column}")
    added.append("concert venues -> places, concert_visits.place_id")
link_columns = {row[1] for row in db.execute("PRAGMA table_info(person_organizations)")}
if link_columns and "relation_type_id" not in link_columns:
    db.execute("""CREATE TABLE IF NOT EXISTS person_organization_types (
        id INTEGER PRIMARY KEY,
        owner_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        name VARCHAR(100) NOT NULL, description TEXT NOT NULL,
        CONSTRAINT uq_person_organization_type_name UNIQUE (owner_id, name))""")
    db.execute("CREATE INDEX IF NOT EXISTS ix_person_organization_types_owner_id ON person_organization_types (owner_id)")
    db.execute("""INSERT OR IGNORE INTO person_organization_types (owner_id, name, description)
        SELECT DISTINCT p.owner_id, 'Worked at', 'Was employed there' FROM person_organizations po JOIN people p ON p.id = po.person_id""")
    # sqlite cannot change a primary key: the table is made again, with the kind, and the rows copied
    db.execute("""CREATE TABLE person_organizations_new (
        person_id INTEGER NOT NULL REFERENCES people (id) ON DELETE CASCADE,
        organization_id INTEGER NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
        relation_type_id INTEGER NOT NULL REFERENCES person_organization_types (id) ON DELETE CASCADE,
        PRIMARY KEY (person_id, organization_id, relation_type_id))""")
    db.execute("""INSERT INTO person_organizations_new (person_id, organization_id, relation_type_id)
        SELECT po.person_id, po.organization_id, t.id FROM person_organizations po
        JOIN people p ON p.id = po.person_id
        JOIN person_organization_types t ON t.owner_id = p.owner_id AND t.name = 'Worked at'""")
    copied = db.execute("SELECT (SELECT count(*) FROM person_organizations) - (SELECT count(*) FROM person_organizations_new)").fetchone()[0]
    if copied:
        raise SystemExit(f"{path}: {copied} person-organization links would be lost; nothing changed")
    db.execute("DROP TABLE person_organizations")
    db.execute("ALTER TABLE person_organizations_new RENAME TO person_organizations")
    added.append("person_organizations.relation_type_id (every link Worked at)")
db.execute("""CREATE TABLE IF NOT EXISTS countries (
    id INTEGER PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL, latitude FLOAT, longitude FLOAT, remark TEXT NOT NULL,
    CONSTRAINT uq_country_name UNIQUE (owner_id, name))""")
db.execute("CREATE INDEX IF NOT EXISTS ix_countries_owner_id ON countries (owner_id)")
db.execute("""CREATE TABLE IF NOT EXISTS cities (
    id INTEGER PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL, region VARCHAR(100) NOT NULL,
    country_id INTEGER REFERENCES countries (id) ON DELETE SET NULL,
    latitude FLOAT, longitude FLOAT, remark TEXT NOT NULL,
    CONSTRAINT uq_city_name UNIQUE (owner_id, name, region, country_id))""")
db.execute("CREATE INDEX IF NOT EXISTS ix_cities_owner_id ON cities (owner_id)")
db.execute("CREATE INDEX IF NOT EXISTS ix_cities_country_id ON cities (country_id)")
for table in ("places", "museum_visits", "organizations"):
    existing = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
    if existing and "city_id" not in existing:
        db.execute(f"ALTER TABLE {table} ADD COLUMN city_id INTEGER REFERENCES cities (id) ON DELETE SET NULL")
        db.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_city_id ON {table} (city_id)")
        added.append(f"{table}.city_id")
for table in ("cities", "countries"):
    existing = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
    for column, kind in (("image_id", "INTEGER REFERENCES images (id) ON DELETE SET NULL"), ("image_source", "VARCHAR(1000) NOT NULL DEFAULT ''"),
                         ("image_license", "VARCHAR(100) NOT NULL DEFAULT ''"), ("image_author", "VARCHAR(300) NOT NULL DEFAULT ''")):
        if existing and column not in existing:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
            added.append(f"{table}.{column}")
place_columns = {row[1] for row in db.execute("PRAGMA table_info(places)")}
museum_columns = {row[1] for row in db.execute("PRAGMA table_info(museum_visits)")}
if "city" in place_columns or "city" in museum_columns:
    unlinked = 0
    if "city" in place_columns:
        unlinked += db.execute("SELECT count(*) FROM places WHERE trim(city) <> '' AND city_id IS NULL").fetchone()[0]
        # a country with no city must be in the remark before the column goes
        unlinked += db.execute("SELECT count(*) FROM places WHERE trim(city) = '' AND trim(country) <> '' AND remark NOT LIKE '%the city is not known%'").fetchone()[0]
    if "city" in museum_columns:
        unlinked += db.execute("SELECT count(*) FROM museum_visits WHERE trim(city) <> '' AND city_id IS NULL").fetchone()[0]
    if unlinked:
        print(f"{path}: {unlinked} places and museum visits name a city they are not linked to: run scripts/link_cities.py, then this again")
    else:
        if "city" in place_columns:
            # sqlite cannot drop a column its key names: the table is made again, keyed by the city's id, and the rows copied
            db.execute("""CREATE TABLE places_new (
                id INTEGER PRIMARY KEY,
                owner_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
                name VARCHAR(300) NOT NULL,
                city_id INTEGER REFERENCES cities (id) ON DELETE SET NULL,
                address VARCHAR(500) NOT NULL, latitude FLOAT, longitude FLOAT,
                website VARCHAR(1000) NOT NULL, remark TEXT NOT NULL,
                CONSTRAINT uq_place_name UNIQUE (owner_id, name, city_id))""")
            db.execute("""INSERT INTO places_new (id, owner_id, name, city_id, address, latitude, longitude, website, remark)
                SELECT id, owner_id, name, city_id, address, latitude, longitude, website, remark FROM places""")
            db.execute("DROP TABLE places")
            db.execute("ALTER TABLE places_new RENAME TO places")
            db.execute("CREATE INDEX IF NOT EXISTS ix_places_owner_id ON places (owner_id)")
            db.execute("CREATE INDEX IF NOT EXISTS ix_places_city_id ON places (city_id)")
            added.append("places.city, places.country (in cities now)")
        if "city" in museum_columns:
            db.execute("ALTER TABLE museum_visits DROP COLUMN city")
            added.append("museum_visits.city (in cities now)")
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
	   OR (table_name = 'works' AND column_name IN ('id', 'imdb_id', 'tmdb_id', 'rotten_tomatoes_id'))
	   OR (table_name IN ('museums', 'concerts') AND column_name = 'id')
	   OR (table_name = 'library_works' AND column_name IN ('id', 'goodreads_id', 'simania_id'))
	   OR (table_name = 'library_entries' AND column_name = 'image_id')
	   OR (table_name = 'people' AND column_name = 'company')
	   OR (table_name IN ('companies', 'organizations') AND column_name = 'id')
	   OR (table_name = 'organizations' AND column_name IN ('type_id', 'functions'))
	   OR (table_name = 'concerts' AND column_name = 'performers')
	   OR (table_name = 'people' AND column_name IN ('name', 'type_id', 'middle_name', 'honorific', 'is_self'))
	   OR (table_name = 'concert_visits' AND column_name = 'venue')
	   OR (table_name = 'person_organizations' AND column_name IN ('person_id', 'relation_type_id'))
	   OR (table_name IN ('places', 'museum_visits', 'organizations') AND column_name IN ('city', 'city_id'))
	   OR (table_name IN ('cities', 'countries') AND column_name IN ('id', 'image_id'))
	   OR (table_name = 'person_types' AND column_name = 'id')
	   OR (table_name IN ('museums', 'organizations') AND column_name IN ('address', 'latitude', 'longitude', 'alone'))
	   OR (table_name = 'audio_courses' AND column_name IN ('device', 'device_id', 'link'))
	   OR (table_name = 'youtube_videos' AND column_name IN ('youtube_id', 'channel', 'category', 'duration', 'uploaded', 'views', 'unavailable'))
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
# these steps use the old table names: they only apply to a database that still has them
if has "works.id:.*"; then
	has "works.imdb_id:.*" || need works.imdb_id "ALTER TABLE works ADD COLUMN imdb_id VARCHAR(20) NOT NULL DEFAULT ''"
	has "works.tmdb_id:.*" || need works.tmdb_id "ALTER TABLE works ADD COLUMN tmdb_id INTEGER"
	has "works.rotten_tomatoes_id:.*" || need works.rotten_tomatoes_id "ALTER TABLE works ADD COLUMN rotten_tomatoes_id VARCHAR(200) NOT NULL DEFAULT ''"
fi
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
located=(organizations)
if has "museums.id:.*"; then
	located+=(museums)
	has "museums.address:.*" || need museums.address "ALTER TABLE museums ADD COLUMN address VARCHAR(500) NOT NULL DEFAULT ''"
	# a museum visit made alone, told apart from one whose company is not filled in
	has "museums.alone:.*" || need museums.alone "ALTER TABLE museums ADD COLUMN alone BOOLEAN NOT NULL DEFAULT false"
fi
for table in "${located[@]}"; do
	for column in latitude longitude; do
		has "${table}.${column}:.*" || need "${table}.${column}" "ALTER TABLE ${table} ADD COLUMN ${column} DOUBLE PRECISION"
	done
done
# a page about an audio course that is not sold any more (adding a column: run before the deploy)
has "audio_courses.link:.*" || need audio_courses.link "ALTER TABLE audio_courses ADD COLUMN link VARCHAR(1000) NOT NULL DEFAULT ''"
# what YouTube says about a video (the watch history): adding columns, run before the deploy
if has "youtube_videos.youtube_id:.*"; then
	has "youtube_videos.channel:.*" || need youtube_videos.channel "ALTER TABLE youtube_videos ADD COLUMN channel VARCHAR(200) NOT NULL DEFAULT ''"
	has "youtube_videos.category:.*" || need youtube_videos.category "ALTER TABLE youtube_videos ADD COLUMN category VARCHAR(100) NOT NULL DEFAULT ''"
	has "youtube_videos.duration:.*" || need youtube_videos.duration "ALTER TABLE youtube_videos ADD COLUMN duration INTEGER"
	has "youtube_videos.uploaded:.*" || need youtube_videos.uploaded "ALTER TABLE youtube_videos ADD COLUMN uploaded DATE"
	has "youtube_videos.views:.*" || need youtube_videos.views "ALTER TABLE youtube_videos ADD COLUMN views BIGINT"
	has "youtube_videos.unavailable:.*" || need youtube_videos.unavailable "ALTER TABLE youtube_videos ADD COLUMN unavailable BOOLEAN NOT NULL DEFAULT false"
fi
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

# tables named for what a row is (renames: run before the deploy, and again after it)
read -r -d '' renames <<'SQL' || true
DO $$
DECLARE
	pair text[];
	old text;
	new text;
	old_rows bigint;
	new_rows bigint;
	r record;
BEGIN
	-- the link tables first, so an empty pair is dropped before what it points at
	FOREACH pair SLICE 1 IN ARRAY ARRAY[
		['concert_people', 'concert_companions'],
		['museum_people', 'museum_companions'],
		['person_person_types', 'person_type_links'],
		['user_works', 'library_entries'],
		['museums', 'museum_visits'],
		['concerts', 'concert_visits'],
		['works', 'library_works']
	] LOOP
		old := pair[1];
		new := pair[2];
		CONTINUE WHEN to_regclass(old) IS NULL;
		IF to_regclass(new) IS NOT NULL THEN
			-- one side was made empty by create_all (an old version after the rename, or the new one before it)
			EXECUTE format('SELECT count(*) FROM %I', old) INTO old_rows;
			EXECUTE format('SELECT count(*) FROM %I', new) INTO new_rows;
			IF old_rows > 0 AND new_rows > 0 THEN
				RAISE EXCEPTION 'both % and % have rows; merge them by hand', old, new;
			END IF;
			IF old_rows = 0 THEN
				EXECUTE format('DROP TABLE %I', old);
				CONTINUE;
			END IF;
			EXECUTE format('DROP TABLE %I', new);
		END IF;
		EXECUTE format('ALTER TABLE %I RENAME TO %I', old, new);
	END LOOP;
	IF EXISTS (SELECT 1 FROM information_schema.columns
			WHERE table_schema = current_schema() AND table_name = 'person_type_links' AND column_name = 'type_id') THEN
		ALTER TABLE person_type_links RENAME COLUMN type_id TO person_type_id;
	END IF;
	-- what Postgres named after a table keeps the old name through a rename: the
	-- constraints (renaming one renames the index behind it), the ix_ indexes and
	-- the id sequence; this also catches up with companies -> organizations
	FOREACH pair SLICE 1 IN ARRAY ARRAY[
		['person_companies_company_id_fkey', 'person_organizations_organization_id_fkey'],
		['person_person_types_type_id_fkey', 'person_type_links_person_type_id_fkey'],
		['person_type_links_type_id_fkey', 'person_type_links_person_type_id_fkey']
	] LOOP
		FOR r IN SELECT conrelid::regclass AS t FROM pg_constraint WHERE conname = pair[1] LOOP
			EXECUTE format('ALTER TABLE %s RENAME CONSTRAINT %I TO %I', r.t, pair[1], pair[2]);
		END LOOP;
	END LOOP;
	FOREACH pair SLICE 1 IN ARRAY ARRAY[
		['companies', 'organizations'],
		['person_companies', 'person_organizations'],
		['concert_people', 'concert_companions'],
		['museum_people', 'museum_companions'],
		['person_person_types', 'person_type_links'],
		['user_works', 'library_entries'],
		['museums', 'museum_visits'],
		['concerts', 'concert_visits'],
		['works', 'library_works']
	] LOOP
		old := pair[1];
		new := pair[2];
		CONTINUE WHEN to_regclass(new) IS NULL;
		FOR r IN SELECT conname FROM pg_constraint WHERE conrelid = new::regclass AND starts_with(conname, old || '_') LOOP
			EXECUTE format('ALTER TABLE %I RENAME CONSTRAINT %I TO %I', new, r.conname, new || substr(r.conname, length(old) + 1));
		END LOOP;
		FOR r IN SELECT indexname FROM pg_indexes WHERE schemaname = current_schema() AND tablename = new AND starts_with(indexname, 'ix_' || old || '_') LOOP
			EXECUTE format('ALTER INDEX %I RENAME TO %I', r.indexname, 'ix_' || new || substr(r.indexname, length(old) + 4));
		END LOOP;
		FOR r IN SELECT s.relname FROM pg_class s JOIN pg_depend d ON d.objid = s.oid
				WHERE s.relkind = 'S' AND d.refobjid = new::regclass AND starts_with(s.relname, old || '_') LOOP
			EXECUTE format('ALTER SEQUENCE %I RENAME TO %I', r.relname, new || substr(r.relname, length(old) + 1));
		END LOOP;
	END LOOP;
END
$$
SQL
# anything still under an old name: a table, or a constraint, index or sequence named after one
stale="$(gcloud_sql_psql.sh -q -t -A -v ON_ERROR_STOP=1 -c "
	SELECT count(*) FROM (
		SELECT relname AS name FROM pg_class WHERE relnamespace = current_schema()::regnamespace
		UNION ALL SELECT conname FROM pg_constraint WHERE connamespace = current_schema()::regnamespace
		UNION ALL SELECT column_name FROM information_schema.columns
			WHERE table_schema = current_schema() AND table_name = 'person_type_links' AND column_name = 'type_id'
	) AS objects
	WHERE name ~ '^(ix_)?(companies|person_companies|concert_people|museum_people|person_person_types|user_works|museums|concerts|works)(_|\$)'
	   OR name = 'type_id'
	   OR name = 'person_organizations_company_id_fkey'
")"
if [[ "${stale}" != "0" ]]; then
	need "tables renamed to what a row is, and what Postgres named after them" "${renames}"
fi
# books (adding columns: run before the deploy); after the renames, as these are the new tables
if has "works.id:.*" || has "library_works.id:.*"; then
	has "library_works.goodreads_id:.*" || need library_works.goodreads_id "ALTER TABLE library_works ADD COLUMN goodreads_id VARCHAR(20) NOT NULL DEFAULT ''"
	has "library_works.simania_id:.*" || need library_works.simania_id "ALTER TABLE library_works ADD COLUMN simania_id VARCHAR(20) NOT NULL DEFAULT ''"
	has "library_entries.image_id:.*" || need library_entries.image_id "ALTER TABLE library_entries ADD COLUMN image_id INTEGER REFERENCES images (id) ON DELETE SET NULL"
fi
# people.middle_name (adding a column: run before the deploy)
has "people.middle_name:.*" || need people.middle_name "ALTER TABLE people ADD COLUMN middle_name VARCHAR(200) NOT NULL DEFAULT ''"
# people.honorific ("Dr.", "Sir"; adding a column: run before the deploy)
has "people.honorific:.*" || need people.honorific "ALTER TABLE people ADD COLUMN honorific VARCHAR(50) NOT NULL DEFAULT ''"
# people.is_self, the account owner's own person (adding a column: run before the deploy)
has "people.is_self:.*" || need people.is_self "ALTER TABLE people ADD COLUMN is_self BOOLEAN NOT NULL DEFAULT false"
# concert venues become places (right after deploying the version that has them)
if has "concert_visits.venue:.*"; then
	need "concert venues -> places, concert_visits.place_id" "CREATE TABLE IF NOT EXISTS places (
			id SERIAL PRIMARY KEY,
			owner_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
			name VARCHAR(300) NOT NULL, city VARCHAR(100) NOT NULL, country VARCHAR(100) NOT NULL,
			address VARCHAR(500) NOT NULL, latitude DOUBLE PRECISION, longitude DOUBLE PRECISION,
			website VARCHAR(1000) NOT NULL, remark TEXT NOT NULL,
			CONSTRAINT uq_place_name UNIQUE (owner_id, name, city));
		CREATE INDEX IF NOT EXISTS ix_places_owner_id ON places (owner_id);
		INSERT INTO places (owner_id, name, city, country, address, website, remark)
			SELECT DISTINCT ON (owner_id, coalesce(nullif(btrim(venue), ''), btrim(city)), btrim(city))
				owner_id, coalesce(nullif(btrim(venue), ''), btrim(city)), btrim(city), btrim(country), '', '', ''
			FROM concert_visits WHERE btrim(venue) <> '' OR btrim(city) <> ''
			ORDER BY owner_id, coalesce(nullif(btrim(venue), ''), btrim(city)), btrim(city), id
			ON CONFLICT ON CONSTRAINT uq_place_name DO NOTHING;
		ALTER TABLE concert_visits ADD COLUMN IF NOT EXISTS place_id INTEGER REFERENCES places (id) ON DELETE SET NULL;
		CREATE INDEX IF NOT EXISTS ix_concert_visits_place_id ON concert_visits (place_id);
		UPDATE concert_visits c SET place_id = p.id FROM places p
			WHERE p.owner_id = c.owner_id AND p.name = coalesce(nullif(btrim(c.venue), ''), btrim(c.city)) AND p.city = btrim(c.city);
		ALTER TABLE concert_visits DROP COLUMN venue, DROP COLUMN city, DROP COLUMN country"
fi
# a kind for every person-organization link (right after deploying the version that has them)
if has "person_organizations.person_id:.*" && ! has "person_organizations.relation_type_id:.*"; then
	need "person_organizations.relation_type_id (every link Worked at)" "CREATE TABLE IF NOT EXISTS person_organization_types (
			id SERIAL PRIMARY KEY,
			owner_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
			name VARCHAR(100) NOT NULL, description TEXT NOT NULL,
			CONSTRAINT uq_person_organization_type_name UNIQUE (owner_id, name));
		CREATE INDEX IF NOT EXISTS ix_person_organization_types_owner_id ON person_organization_types (owner_id);
		INSERT INTO person_organization_types (owner_id, name, description)
			SELECT DISTINCT p.owner_id, 'Worked at', 'Was employed there' FROM person_organizations po JOIN people p ON p.id = po.person_id
			ON CONFLICT ON CONSTRAINT uq_person_organization_type_name DO NOTHING;
		ALTER TABLE person_organizations ADD COLUMN relation_type_id INTEGER REFERENCES person_organization_types (id) ON DELETE CASCADE;
		UPDATE person_organizations po SET relation_type_id = t.id FROM people p, person_organization_types t
			WHERE p.id = po.person_id AND t.owner_id = p.owner_id AND t.name = 'Worked at';
		ALTER TABLE person_organizations ALTER COLUMN relation_type_id SET NOT NULL;
		DO \$\$
		DECLARE pk text;
		BEGIN
			SELECT conname INTO pk FROM pg_constraint WHERE conrelid = 'person_organizations'::regclass AND contype = 'p';
			EXECUTE format('ALTER TABLE person_organizations DROP CONSTRAINT %I', pk);
		END
		\$\$;
		ALTER TABLE person_organizations ADD CONSTRAINT person_organizations_pkey PRIMARY KEY (person_id, organization_id, relation_type_id)"
fi
# cities: the table and the links (adding: run before the deploy)
for table in places museum_visits organizations; do
	if ! has "${table}.city_id:.*"; then
		need "${table}.city_id" "CREATE TABLE IF NOT EXISTS countries (
				id SERIAL PRIMARY KEY,
				owner_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
				name VARCHAR(100) NOT NULL, latitude DOUBLE PRECISION, longitude DOUBLE PRECISION, remark TEXT NOT NULL,
				CONSTRAINT uq_country_name UNIQUE (owner_id, name));
			CREATE INDEX IF NOT EXISTS ix_countries_owner_id ON countries (owner_id);
			CREATE TABLE IF NOT EXISTS cities (
				id SERIAL PRIMARY KEY,
				owner_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
				name VARCHAR(100) NOT NULL, region VARCHAR(100) NOT NULL,
				country_id INTEGER REFERENCES countries (id) ON DELETE SET NULL,
				latitude DOUBLE PRECISION, longitude DOUBLE PRECISION, remark TEXT NOT NULL,
				CONSTRAINT uq_city_name UNIQUE (owner_id, name, region, country_id));
			CREATE INDEX IF NOT EXISTS ix_cities_owner_id ON cities (owner_id);
			CREATE INDEX IF NOT EXISTS ix_cities_country_id ON cities (country_id);
			ALTER TABLE ${table} ADD COLUMN city_id INTEGER REFERENCES cities (id) ON DELETE SET NULL;
			CREATE INDEX IF NOT EXISTS ix_${table}_city_id ON ${table} (city_id)"
	fi
done
# a photo for every city and country (adding columns: run before the deploy)
for table in cities countries; do
	if has "${table}.id:.*" && ! has "${table}.image_id:.*"; then
		need "${table}.image_id" "ALTER TABLE ${table} ADD COLUMN image_id INTEGER REFERENCES images (id) ON DELETE SET NULL;
			ALTER TABLE ${table} ADD COLUMN image_source VARCHAR(1000) NOT NULL DEFAULT '';
			ALTER TABLE ${table} ADD COLUMN image_license VARCHAR(100) NOT NULL DEFAULT '';
			ALTER TABLE ${table} ADD COLUMN image_author VARCHAR(300) NOT NULL DEFAULT ''"
	fi
done
# the old city text goes once every row that names a city is linked (right after deploying the version without it)
if { has "places.city:.*" || has "museum_visits.city:.*"; } && has "places.city_id:.*" && has "museum_visits.city_id:.*"; then
	unlinked="$(gcloud_sql_psql.sh -q -t -A -v ON_ERROR_STOP=1 -c "
		SELECT $(has "places.city:.*" && echo "(SELECT count(*) FROM places WHERE (btrim(city) <> '' AND city_id IS NULL) OR (btrim(city) = '' AND btrim(country) <> '' AND remark NOT LIKE '%the city is not known%'))" || echo 0)
			+ $(has "museum_visits.city:.*" && echo "(SELECT count(*) FROM museum_visits WHERE btrim(city) <> '' AND city_id IS NULL)" || echo 0)")"
	if [[ "${unlinked}" != "0" ]]; then
		echo "${unlinked} places and museum visits name a city they are not linked to: run scripts/link_cities.py, then this again" >&2
	else
		if has "places.city:.*"; then
			need "places.city, places.country (in cities now)" "ALTER TABLE places DROP CONSTRAINT IF EXISTS uq_place_name;
				ALTER TABLE places DROP COLUMN city, DROP COLUMN country;
				ALTER TABLE places ADD CONSTRAINT uq_place_name UNIQUE (owner_id, name, city_id)"
		fi
		if has "museum_visits.city:.*"; then
			need "museum_visits.city (in cities now)" "ALTER TABLE museum_visits DROP COLUMN city"
		fi
	fi
fi

if (( ${#changed[@]} == 0 )); then
	echo "${gcp_sql_instance}/${gcp_db_name}: up to date, nothing to migrate"
else
	# one transaction: a failing statement stops psql and leaves the database as it was
	printf '%s\n' "BEGIN;" "${statements[@]}" "COMMIT;" | gcloud_sql_psql.sh -q -v ON_ERROR_STOP=1 > /dev/null
	echo "${gcp_sql_instance}/${gcp_db_name}: migrated ${changed[*]}"
	echo "deploy with gcloud_run_deploy.sh"
fi
