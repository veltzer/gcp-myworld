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
#     groups.image_id and its credit the same way, later; devices.image_id
#     and person_types.image_id (professions) too, and places.image_id.
#   - addresses in parts: street, neighbourhood and postcode on places,
#     museum_visits and organizations (adding columns: run before the
#     deploy); scripts/split_addresses.py splits the one-line address into
#     them, and with --drop (right after deploying the version without it)
#     drops the old address column.
#   - organizations.headquarters_id, the city of its headquarters (its
#     location says it in words): adding a column, run before the deploy;
#     scripts/link_cities.py then links it from the location.
#   - places: every concert's venue, city and country become a row of places
#     (one per account, name and city; a concert with a city but no venue
#     gives a place named after the city), concert_visits.place_id points to
#     it, and only then are the three columns dropped. The new code no longer
#     writes them, and they are NOT NULL, so run this right after deploying
#     that version (its create_all makes the places table).
#   - names in languages: library_works.title_locale (the language of the
#     main title) and library_entries.locale (the language the user read the
#     book in): adding columns, run before the deploy. The new tables of
#     other titles and of people's names in other languages are made by
#     create_all; scripts/import_world_cloud.sh --books then fills them, and
#     the languages, from books_read.yaml.
#   - books: library_works.isbn and openlibrary_id (adding columns, run
#     before the deploy), the ISBN copied over from library_works.external_id,
#     which is dropped by a run after deploying the version that no longer
#     reads it; scripts/fetch_book_details.py then fills them and the years.
#   - sign-in through logins (models.Login), the users being the people: run
#     before the deploy, it makes the logins table with one login per account
#     (its google_sub, a bare one Google's, with the password hash), marks an
#     account verified when a login of it is (every way but a password),
#     joins the accounts of one verified email into the oldest where the
#     others own nothing, and lets users.google_sub be empty. Run again after
#     deploying the version that signs in through logins: it gives a login to
#     an account the old version made meanwhile, joins again, and drops
#     users.google_sub and users.password_hash.
#   - only a proven email gets an account (models.User, models.EmailVerification):
#     email_verifications (the mailed links; create_all makes the table, made
#     here too) and logins.password_hash (kept, for the email login made once
#     its link was followed); users.verified and logins.verified go, and
#     users.email becomes unique. A login that was never proven (a password
#     login, or any with verified false) goes, and so does an account that is
#     unverified itself or would be left with no login. Accounts reference
#     users with ON DELETE CASCADE, so this NEVER deletes an account that
#     owns rows in any table pointing at users (other than logins): it stops,
#     changing nothing, with exit status 1 and lists each such account (id,
#     email, rows per table) for you to decide, and so it does when emails
#     are still shared by two accounts after that. Needs the logins step
#     above done (it says so when not). Run before the deploy: the old version
#     writes users.verified, which then no longer exists, so deploy right away.
#   - the locales table (models.Locale: the languages, each with its script)
#     and every locale column pointing at it with a foreign key:
#     library_works.title_locale, library_work_titles.locale,
#     library_entries.locale and person_names.locale. An entry's language not
#     known was '' and is now NULL (the column lets it be), and a work has one
#     title per language: uq_work_title (work, language, title) becomes
#     uq_work_title_locale (work, language). No row is deleted or rewritten
#     but those '' to NULL: when a language is not in the table, or a work
#     has two titles in one language (its main title's counts), this stops,
#     changing nothing, and lists them. Run before the deploy and deploy right
#     away: the old version writes '' for a language not known, which the
#     foreign key refuses.
#   - reads (models.Read, library_reads): every time a book was read, with
#     its day and its language. Each entry that was read (Done, or with a
#     finished day or a language) gets one read holding its
#     library_entries.finished_on and locale; a book read whose language was
#     not recorded gets Hebrew when it has a Hebrew title, else English when
#     it has an English one (a recorded language is never changed). Only then
#     are the two columns dropped. The new code no longer reads them, so run
#     this right after deploying that version (its create_all makes the table,
#     made here too); an entry that already has reads is left as it is.
#   - users.locale, the language an account prefers (Settings): a book with
#     titles in several languages is shown by the one in it. English for
#     every account there is, as for a new one. Adding a column that points
#     at locales, so after the locales step; run before the deploy.
#   - library_entries.review, what the user thought of a book, beside its
#     notes (the review that led an imported book's notes was moved into it).
#     The tables of a book's further covers (library_covers) and a city's
#     further photos (city_photos) are new, made by create_all.
#   - a reading has its own status, rating, review and day started
#     (library_reads.status, rating, review, started_on): those of an entry
#     (library_entries) go to the reading it went by (the latest that has a
#     day, else the last added), an entry with no reading gets one to hold
#     them, its other readings are Done, and the four columns of
#     library_entries are dropped. The new code needs the new columns and
#     the old one the old: deploy and run this right after.
#   - locales.native, what a language is called in itself in its own script
#     ("עברית"): its picture is that name, written out. The languages the
#     table starts with get theirs. Adding a column: run before the deploy.
#   - library_works.original_locale, the language a book was first written
#     in (empty while not known). Adding a column: run before the deploy.
#   - a person's name in another language has its parts, as the English one
#     has (person_names.honorific, first_name, middle_name, surname): the
#     whole name each had is split into them, the first word the first name,
#     the last the surname, what is between the middle name. A person's
#     photos (person_photos) are a new table, made by create_all. Adding
#     columns: run before the deploy.
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
import re
import sqlite3
import sys

# (table, column, sqlite type); sqlite ignores VARCHAR lengths, so the wider google_sub needs nothing
COLUMNS = [
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
    ("library_works", "title_locale", "VARCHAR(10) NOT NULL DEFAULT 'en'"),
]

# what the languages the locales table starts with are called in themselves (models.LOCALE_NATIVE)
LOCALE_NATIVE = {"en": "English", "he": "עברית", "ar": "العربية", "yi": "ייִדיש", "fr": "Français", "de": "Deutsch", "es": "Español", "it": "Italiano", "pt": "Português", "ru": "Русский", "cs": "Čeština", "el": "Ελληνικά"}

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
# a book's ISBN in a column of its own name (external_id held it), and its Open Library work
work_columns = {row[1] for row in db.execute("PRAGMA table_info(library_works)")}
if work_columns:
    for column in ("isbn", "openlibrary_id"):
        if column not in work_columns:
            db.execute(f"ALTER TABLE library_works ADD COLUMN {column} VARCHAR(20) NOT NULL DEFAULT ''")
            added.append(f"library_works.{column}")
    if "external_id" in work_columns:
        db.execute("UPDATE library_works SET isbn = substr(external_id, 1, 20) WHERE isbn = '' AND external_id <> ''")
        db.execute("ALTER TABLE library_works DROP COLUMN external_id")
        added.append("library_works.external_id -> isbn")
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
for table in ("places", "museum_visits", "organizations"):
    existing = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
    for column, kind in (("street", "VARCHAR(300) NOT NULL DEFAULT ''"), ("neighbourhood", "VARCHAR(200) NOT NULL DEFAULT ''"), ("postcode", "VARCHAR(20) NOT NULL DEFAULT ''")):
        if existing and column not in existing:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
            added.append(f"{table}.{column}")
organization_columns = {row[1] for row in db.execute("PRAGMA table_info(organizations)")}
if organization_columns and "headquarters_id" not in organization_columns:
    db.execute("ALTER TABLE organizations ADD COLUMN headquarters_id INTEGER REFERENCES cities (id) ON DELETE SET NULL")
    db.execute("CREATE INDEX IF NOT EXISTS ix_organizations_headquarters_id ON organizations (headquarters_id)")
    added.append("organizations.headquarters_id")
for table in ("cities", "countries", "groups", "devices", "person_types", "places"):
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
# sign-in through logins: one per way of signing in, the users being the people.
# Each account's subject becomes its login (a bare one Google's), the accounts
# of one verified email become one where all but the oldest own nothing, and
# users is made again without google_sub and password_hash (sqlite cannot drop
# a unique column)
user_columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
if "google_sub" in user_columns:
    db.execute("""CREATE TABLE IF NOT EXISTS logins (
        id INTEGER PRIMARY KEY,
        subject VARCHAR(400) NOT NULL UNIQUE,
        user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
        email VARCHAR(320) NOT NULL DEFAULT '',
        name VARCHAR(200) NOT NULL DEFAULT '',
        picture VARCHAR(1000) NOT NULL DEFAULT '',
        verified BOOLEAN NOT NULL DEFAULT 0,
        password_hash VARCHAR(300),
        created_at DATETIME NOT NULL,
        last_login DATETIME)""")
    db.execute("CREATE INDEX IF NOT EXISTS ix_logins_user_id ON logins (user_id)")
    hash_column = "password_hash" if "password_hash" in user_columns else "NULL"
    db.execute(f"""INSERT INTO logins (subject, user_id, email, name, picture, verified, password_hash, created_at)
        SELECT CASE WHEN instr(google_sub, ':') = 0 THEN 'google:' || google_sub ELSE google_sub END,
               id, lower(email), name, picture, google_sub NOT LIKE 'email:%', {hash_column}, created_at
        FROM users WHERE google_sub IS NOT NULL AND id NOT IN (SELECT user_id FROM logins)""")
    owned = [(table, column) for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT IN ('logins', 'users')")
             for column in ("owner_id", "user_id") if column in {row[1] for row in db.execute(f"PRAGMA table_info({table})")}]
    verified_users = db.execute("""SELECT id, lower(email), role FROM users
        WHERE EXISTS (SELECT 1 FROM logins WHERE logins.user_id = users.id AND logins.verified) ORDER BY id""").fetchall()
    keep: dict[str, tuple[int, str]] = {}
    for user_id, email, role in verified_users:
        if email not in keep:
            keep[email] = (user_id, role)
            continue
        kept = keep[email][0]
        owns = sum(db.execute(f"SELECT count(*) FROM {table} WHERE {column} = ?", (user_id,)).fetchone()[0] for table, column in owned)
        if owns:
            print(f"account {user_id} has the verified email of account {kept} but owns {owns} rows: both stay", file=sys.stderr)
            continue
        db.execute("UPDATE logins SET user_id = ? WHERE user_id = ?", (kept, user_id))
        if role == "admin":
            db.execute("UPDATE users SET role = 'admin' WHERE id = ?", (kept,))
        db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        added.append(f"account {user_id} joined to account {kept}")
    db.execute("""CREATE TABLE users_new (
        id INTEGER PRIMARY KEY,
        email VARCHAR(320) NOT NULL,
        verified BOOLEAN NOT NULL DEFAULT 0,
        name VARCHAR(200) NOT NULL,
        picture VARCHAR(1000) NOT NULL,
        role VARCHAR(20) NOT NULL DEFAULT 'user',
        created_at DATETIME NOT NULL,
        last_login DATETIME)""")
    db.execute("""INSERT INTO users_new (id, email, verified, name, picture, role, created_at)
        SELECT id, lower(email), EXISTS (SELECT 1 FROM logins WHERE logins.user_id = users.id AND logins.verified), name, picture, role, created_at
        FROM users""")
    db.execute("DROP TABLE users")
    db.execute("ALTER TABLE users_new RENAME TO users")
    added.append("logins (users.google_sub and password_hash in them now)")
# only a proven email gets an account: email_verifications and logins.password_hash
# made if missing; the logins that were never proven (a password login, or any with
# verified false) and the accounts that are unverified themselves or are left with no
# login go, unless one owns rows in a table pointing at users (those are deleted with
# it by ON DELETE CASCADE): then nothing is changed and this stops, naming them. Then
# users.verified and logins.verified are dropped and users.email made unique.
tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
login_columns = {row[1] for row in db.execute("PRAGMA table_info(logins)")}
user_columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
if login_columns:
    if "password_hash" not in login_columns:
        db.execute("ALTER TABLE logins ADD COLUMN password_hash VARCHAR(300)")
        added.append("logins.password_hash")
    if "email_verifications" not in tables:
        db.execute("""CREATE TABLE email_verifications (
            email VARCHAR(320) NOT NULL PRIMARY KEY,
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            sent_at DATETIME NOT NULL)""")
        added.append("email_verifications")
    if "verified" in login_columns and "verified" in user_columns:
        doomed_logins = [row[0] for row in db.execute("SELECT id FROM logins WHERE subject LIKE 'email:%' OR NOT verified")]
        marks = ",".join("?" * len(doomed_logins))
        doomed_users = [row[0] for row in db.execute(f"""SELECT id FROM users
            WHERE NOT verified OR NOT EXISTS (SELECT 1 FROM logins WHERE logins.user_id = users.id AND logins.id NOT IN ({marks}))
            ORDER BY id""", doomed_logins)]
        # every table with a foreign key to users, other than logins
        references = [(table, fk[3]) for table in sorted(tables) if table != "logins"
                      for fk in db.execute(f'PRAGMA foreign_key_list("{table}")') if fk[2] == "users"]
        owned: dict[int, list[str]] = {}
        for user_id in doomed_users:
            for table, column in references:
                rows = db.execute(f'SELECT count(*) FROM "{table}" WHERE "{column}" = ?', (user_id,)).fetchone()[0]
                if rows:
                    owned.setdefault(user_id, []).append(f"{rows} in {table}")
        if owned:
            print("not migrated: these accounts have no proven email and own rows that deleting them would delete too.", file=sys.stderr)
            print("Nothing was changed. Decide for each: give it a proven way to sign in, move its rows, or delete it by hand.", file=sys.stderr)
            for user_id, tables_owned in owned.items():
                email = db.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()[0]
                print(f"  user {user_id} ({email}): {', '.join(tables_owned)}", file=sys.stderr)
            sys.exit(1)
        db.executemany("DELETE FROM logins WHERE user_id = ?", [(user_id,) for user_id in doomed_users])
        db.executemany("DELETE FROM logins WHERE id = ?", [(login_id,) for login_id in doomed_logins])
        db.executemany("DELETE FROM users WHERE id = ?", [(user_id,) for user_id in doomed_users])
        db.execute("ALTER TABLE users DROP COLUMN verified")
        db.execute("ALTER TABLE logins DROP COLUMN verified")
        added.append(f"{len(doomed_logins)} unproven logins and {len(doomed_users)} accounts without a proven email dropped, users.verified and logins.verified")
    elif "verified" in login_columns or "verified" in user_columns:
        raise SystemExit("users.verified and logins.verified are expected together: one of them is missing, look at the database")
    email_unique = any(
        [row[2] for row in db.execute(f"PRAGMA index_info({index[1]})")] == ["email"]
        for index in db.execute("PRAGMA index_list(users)") if index[2]
    )
    if not email_unique:
        shared = db.execute("SELECT lower(email), group_concat(id) FROM users GROUP BY lower(email) HAVING count(*) > 1").fetchall()
        if shared:
            for email, ids in shared:
                print(f"{email} is the email of accounts {ids}", file=sys.stderr)
            raise SystemExit("not migrated, nothing changed: emails shared by several accounts, so users.email cannot be unique; merge or delete them by hand")
        db.execute("CREATE UNIQUE INDEX users_email_key ON users (email)")
        added.append("users.email unique")
# the locales table and every locale column pointing at it (see the header). sqlite
# cannot add a foreign key to a column, so each table is made again from its own
# definition with the column's changed, its rows copied over as they are.
LOCALES = [
    ("en", "English", "Latin"), ("he", "Hebrew", "Hebrew"), ("ar", "Arabic", "Arabic"), ("yi", "Yiddish", "Hebrew"),
    ("fr", "French", "Latin"), ("de", "German", "Latin"), ("es", "Spanish", "Latin"), ("it", "Italian", "Latin"),
    ("pt", "Portuguese", "Latin"), ("ru", "Russian", "Cyrillic"), ("cs", "Czech", "Latin"), ("el", "Greek", "Greek"),
]
# (table, column, the column's new definition, text of the table's definition to replace)
LOCALE_COLUMNS = [
    ("library_works", "title_locale", "VARCHAR(10) DEFAULT 'en' NOT NULL REFERENCES locales (code)", []),
    ("library_work_titles", "locale", "VARCHAR(10) NOT NULL REFERENCES locales (code)",
     [("CONSTRAINT uq_work_title UNIQUE (work_id, locale, title)", "CONSTRAINT uq_work_title_locale UNIQUE (work_id, locale)")]),
    ("library_entries", "locale", "VARCHAR(10) REFERENCES locales (code)", []),
    ("person_names", "locale", "VARCHAR(10) NOT NULL REFERENCES locales (code)", []),
]
definitions = {row[0]: row[1] for row in db.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table'")}
pending = [
    (table, column, kind, replace) for table, column, kind, replace in LOCALE_COLUMNS
    if table in definitions and re.search(rf"\b{column} VARCHAR\(10\)", definitions[table]) and not re.search(rf"\b{column} VARCHAR\(10\)[^,)]*REFERENCES locales|FOREIGN KEY ?\({column}\) REFERENCES locales", definitions[table])
]
if pending:
    if "locales" not in definitions:
        db.execute("""CREATE TABLE locales (
            code VARCHAR(10) NOT NULL PRIMARY KEY,
            name VARCHAR(100) NOT NULL UNIQUE,
            script VARCHAR(50) NOT NULL,
            position INTEGER NOT NULL)""")
    db.executemany("INSERT OR IGNORE INTO locales (code, name, script, position) VALUES (?, ?, ?, ?)",
                   [(code, name, script, position) for position, (code, name, script) in enumerate(LOCALES)])
    wrong = []
    for table, column, _, _ in pending:
        allowed = "''" if table == "library_entries" else "NULL"
        for value, rows in db.execute(f"SELECT {column}, count(*) FROM {table} WHERE {column} NOT IN (SELECT code FROM locales) AND {column} IS NOT {allowed} GROUP BY 1"):
            wrong.append(f"{table}.{column}: {rows} rows say {value!r}, which is not a language of the locales table")
    if any(table == "library_work_titles" for table, _, _, _ in pending) and "library_works" in definitions:
        for work_id, locale, titles in db.execute("""SELECT work_id, locale, group_concat(title, ' / ') FROM (
                SELECT work_id, locale, title FROM library_work_titles
                UNION ALL SELECT id, title_locale, title FROM library_works WHERE id IN (SELECT work_id FROM library_work_titles))
                GROUP BY work_id, locale HAVING count(*) > 1"""):
            wrong.append(f"work {work_id} has several titles in {locale}: {titles}")
    if wrong:
        print("not migrated, nothing changed: fix these by hand first (a work has one title per language).", file=sys.stderr)
        for line in wrong:
            print(f"  {line}", file=sys.stderr)
        sys.exit(1)
    for table, column, kind, replace in pending:
        changed, count = re.subn(rf"\b{column} VARCHAR\(10\)[^,)]*", f"{column} {kind}", definitions[table], count=1)
        for old, new in replace:
            count += old in changed
            changed = changed.replace(old, new)
        if count != 1 + len(replace):
            raise SystemExit(f"{path}: {table} is not defined as expected, look at it: {definitions[table]}")
        changed, count = re.subn(rf'^CREATE TABLE "?{table}"?', f"CREATE TABLE {table}_new", changed, count=1)
        if count != 1:
            raise SystemExit(f"{path}: {table} is not defined as expected, look at it: {definitions[table]}")
        indexes = [row[0] for row in db.execute("SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ? AND sql IS NOT NULL", (table,))]
        db.execute(changed)
        db.execute(f"INSERT INTO {table}_new SELECT * FROM {table}")
        db.execute(f"DROP TABLE {table}")
        db.execute(f"ALTER TABLE {table}_new RENAME TO {table}")
        for index in indexes:
            db.execute(index)
    if any(table == "library_entries" for table, _, _, _ in pending):
        db.execute("UPDATE library_entries SET locale = NULL WHERE locale = ''")
    added.append("locales, and " + ", ".join(f"{table}.{column}" for table, column, _, _ in pending) + " pointing at it")
# reads (see the header): a read per entry that was read, from its finished_on and locale,
# then library_entries made again without the two columns (sqlite does not drop a column
# that a foreign key names)
entry_columns = [row[1] for row in db.execute("PRAGMA table_info(library_entries)")]
if "finished_on" in entry_columns:
    # a database from before entries had a language: none recorded
    recorded = "e.locale" if "locale" in entry_columns else "NULL"
    db.execute("""CREATE TABLE IF NOT EXISTS library_reads (
        id INTEGER NOT NULL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        work_id INTEGER NOT NULL,
        read_on DATE,
        locale VARCHAR(10) REFERENCES locales (code),
        CONSTRAINT fk_library_reads_entry FOREIGN KEY (user_id, work_id) REFERENCES library_entries (user_id, work_id) ON DELETE CASCADE)""")
    db.execute("CREATE INDEX IF NOT EXISTS ix_library_reads_entry ON library_reads (user_id, work_id)")
    made = db.execute(f"""INSERT INTO library_reads (user_id, work_id, read_on, locale)
        SELECT e.user_id, e.work_id, e.finished_on, COALESCE({recorded}, CASE
            WHEN w.kind <> 'book' THEN NULL
            WHEN w.title_locale = 'he' OR EXISTS (SELECT 1 FROM library_work_titles t WHERE t.work_id = w.id AND t.locale = 'he') THEN 'he'
            WHEN w.title_locale = 'en' OR EXISTS (SELECT 1 FROM library_work_titles t WHERE t.work_id = w.id AND t.locale = 'en') THEN 'en' END)
        FROM library_entries e JOIN library_works w ON w.id = e.work_id
        WHERE (e.status = 'done' OR e.finished_on IS NOT NULL OR {recorded} IS NOT NULL)
          AND NOT EXISTS (SELECT 1 FROM library_reads r WHERE r.user_id = e.user_id AND r.work_id = e.work_id)
        ORDER BY e.user_id, e.work_id""").rowcount
    definition = db.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'library_entries'").fetchone()[0]
    changed = definition
    for gone in (r",\s*finished_on DATE[^,)]*",
                 r",\s*locale VARCHAR\(10\)(?:(?! REFERENCES)[^,)])*(?: REFERENCES locales \(code\))?[^,)]*",
                 r",\s*FOREIGN KEY ?\(locale\) REFERENCES locales \(code\)"):
        changed = re.sub(gone, "", changed, count=1)
    changed, count = re.subn(r'^CREATE TABLE "?library_entries"?', "CREATE TABLE library_entries_new", changed, count=1)
    if count != 1 or re.search(r"\b(finished_on|locale)\b", changed):
        raise SystemExit(f"{path}: library_entries is not defined as expected, look at it: {definition}")
    kept = ", ".join(column for column in entry_columns if column not in ("finished_on", "locale"))
    indexes = [row[0] for row in db.execute("SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'library_entries' AND sql IS NOT NULL")]
    db.execute(changed)
    db.execute(f"INSERT INTO library_entries_new ({kept}) SELECT {kept} FROM library_entries")
    db.execute("DROP TABLE library_entries")
    db.execute("ALTER TABLE library_entries_new RENAME TO library_entries")
    for index in indexes:
        db.execute(index)
    added.append(f"library_reads ({made} reads made from library_entries.finished_on and locale, which are dropped)")
# a reading has its own status, rating, review and day started (see the header): those of
# each entry go to the reading it went by, and library_entries is made again without them
entry_columns = [row[1] for row in db.execute("PRAGMA table_info(library_entries)")]
read_columns = [row[1] for row in db.execute("PRAGMA table_info(library_reads)")]
if "status" in entry_columns and read_columns:
    for column, kind in [
        ("status", "VARCHAR(20) NOT NULL DEFAULT 'done'"),
        ("rating", "INTEGER CHECK (rating IS NULL OR (rating >= 1 AND rating <= 10))"),
        ("started_on", "DATE"),
        ("review", "TEXT NOT NULL DEFAULT ''"),
    ]:
        if column not in read_columns:
            db.execute(f"ALTER TABLE library_reads ADD COLUMN {column} {kind}")
    made = db.execute("""INSERT INTO library_reads (user_id, work_id)
        SELECT e.user_id, e.work_id FROM library_entries e
        WHERE NOT EXISTS (SELECT 1 FROM library_reads r WHERE r.user_id = e.user_id AND r.work_id = e.work_id)
        ORDER BY e.user_id, e.work_id""").rowcount
    # a database from before entries had a review: none
    review = "e.review" if "review" in entry_columns else "''"
    for column, value in (("status", "e.status"), ("rating", "e.rating"), ("started_on", "e.started_on"), ("review", review)):
        db.execute(f"""UPDATE library_reads SET {column} = (
                SELECT {value} FROM library_entries e WHERE e.user_id = library_reads.user_id AND e.work_id = library_reads.work_id)
            WHERE id = (SELECT r.id FROM library_reads r WHERE r.user_id = library_reads.user_id AND r.work_id = library_reads.work_id
                ORDER BY r.read_on IS NULL, r.read_on DESC, r.id DESC LIMIT 1)""")
    definition = db.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'library_entries'").fetchone()[0]
    changed = definition
    for gone in (r",\s*status VARCHAR\(20\)[^,)]*",
                 r",\s*rating INTEGER[^,)]*",
                 r",\s*started_on DATE[^,)]*",
                 r",\s*review TEXT[^,)]*",
                 r",\s*CONSTRAINT ck_rating_range CHECK \(rating IS NULL OR \(rating >= \d+ AND rating <= \d+\)\)"):
        changed = re.sub(gone, "", changed, count=1)
    changed, count = re.subn(r'^CREATE TABLE "?library_entries"?', "CREATE TABLE library_entries_new", changed, count=1)
    if count != 1 or re.search(r"\b(status|rating|started_on|review)\b", changed):
        raise SystemExit(f"{path}: library_entries is not defined as expected, look at it: {definition}")
    kept = ", ".join(column for column in entry_columns if column not in ("status", "rating", "started_on", "review"))
    indexes = [row[0] for row in db.execute("SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'library_entries' AND sql IS NOT NULL")]
    db.execute(changed)
    db.execute(f"INSERT INTO library_entries_new ({kept}) SELECT {kept} FROM library_entries")
    db.execute("DROP TABLE library_entries")
    db.execute("ALTER TABLE library_entries_new RENAME TO library_entries")
    for index in indexes:
        db.execute(index)
    added.append(f"library_reads.status, rating, started_on and review (from library_entries, where they are dropped; {made} readings made for entries with none)")
# what a language is called in itself (see the header): the languages the table starts with get theirs
locale_columns = {row[1] for row in db.execute("PRAGMA table_info(locales)")}
if locale_columns and "native" not in locale_columns:
    db.execute("ALTER TABLE locales ADD COLUMN native VARCHAR(100) NOT NULL DEFAULT ''")
    for code, native in LOCALE_NATIVE.items():
        db.execute("UPDATE locales SET native = ? WHERE code = ? AND native = ''", (native, code))
    added.append("locales.native")
# the language a work was first written in (see the header)
work_columns = {row[1] for row in db.execute("PRAGMA table_info(library_works)")}
if work_columns and "original_locale" not in work_columns:
    db.execute("ALTER TABLE library_works ADD COLUMN original_locale VARCHAR(10) REFERENCES locales (code)")
    added.append("library_works.original_locale")
# a person's name in another language, in its parts (see the header)
name_columns = {row[1] for row in db.execute("PRAGMA table_info(person_names)")}
if name_columns and "first_name" not in name_columns:
    for column, size in (("honorific", 50), ("first_name", 200), ("middle_name", 200), ("surname", 200)):
        db.execute(f"ALTER TABLE person_names ADD COLUMN {column} VARCHAR({size}) NOT NULL DEFAULT ''")
    for row_id, name in db.execute("SELECT id, name FROM person_names").fetchall():
        words = name.split()
        db.execute("UPDATE person_names SET first_name = ?, middle_name = ?, surname = ? WHERE id = ?",
                   (words[0] if words else "", " ".join(words[1:-1]), words[-1] if len(words) > 1 else "", row_id))
    added.append("person_names.honorific, first_name, middle_name and surname")
# the language an account prefers: English, for every account there is
user_columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
if user_columns and "locale" not in user_columns and db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'locales'").fetchone():
    db.execute("ALTER TABLE users ADD COLUMN locale VARCHAR(10) NOT NULL DEFAULT 'en' REFERENCES locales (code)")
    added.append("users.locale")
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
	WHERE (table_name = 'users' AND column_name IN ('google_sub', 'password_hash', 'role', 'verified', 'last_login', 'locale'))
	   OR (table_name = 'logins' AND column_name IN ('subject', 'verified', 'password_hash'))
	   OR (table_name = 'email_verifications' AND column_name = 'email')
	   OR (table_name = 'works' AND column_name IN ('id', 'imdb_id', 'tmdb_id', 'rotten_tomatoes_id'))
	   OR (table_name IN ('museums', 'concerts') AND column_name = 'id')
	   OR (table_name = 'library_works' AND column_name IN ('id', 'goodreads_id', 'simania_id', 'title_locale', 'isbn', 'openlibrary_id', 'external_id', 'original_locale'))
	   OR (table_name = 'library_entries' AND column_name IN ('image_id', 'locale', 'finished_on', 'review', 'status'))
	   OR (table_name = 'library_reads' AND column_name IN ('id', 'status'))
	   OR (table_name = 'locales' AND column_name IN ('code', 'native'))
	   OR (table_name = 'person_names' AND column_name IN ('id', 'first_name'))
	   OR (table_name = 'people' AND column_name = 'company')
	   OR (table_name IN ('companies', 'organizations') AND column_name = 'id')
	   OR (table_name = 'organizations' AND column_name IN ('type_id', 'functions'))
	   OR (table_name = 'concerts' AND column_name = 'performers')
	   OR (table_name = 'people' AND column_name IN ('name', 'type_id', 'middle_name', 'honorific', 'is_self'))
	   OR (table_name = 'concert_visits' AND column_name = 'venue')
	   OR (table_name = 'person_organizations' AND column_name IN ('person_id', 'relation_type_id'))
	   OR (table_name IN ('places', 'museum_visits', 'organizations') AND column_name IN ('city', 'city_id'))
	   OR (table_name IN ('cities', 'countries', 'groups', 'devices', 'person_types', 'places') AND column_name IN ('id', 'image_id'))
	   OR (table_name IN ('places', 'museum_visits', 'organizations') AND column_name = 'street')
	   OR (table_name = 'organizations' AND column_name = 'headquarters_id')
	   OR (table_name = 'person_types' AND column_name = 'id')
	   OR (table_name IN ('museums', 'organizations') AND column_name IN ('address', 'latitude', 'longitude', 'alone'))
	   OR (table_name = 'audio_courses' AND column_name IN ('device', 'device_id', 'link'))
	   OR (table_name = 'youtube_videos' AND column_name IN ('youtube_id', 'channel', 'category', 'duration', 'uploaded', 'views', 'unavailable'))
")"
# a database that answers always has some of these: an empty answer is a connection that failed,
# not an old schema, and nothing may be migrated on its word
if [[ -z "${present}" ]]; then
	echo "${0}: could not read the schema of ${gcp_sql_instance}/${gcp_db_name}: nothing migrated, run it again" >&2
	exit 1
fi

has() {
	grep -qx "${1}" <<<"${present}"
}
# whether users.email is unique already (create_all makes it so; a migrated table needs it added)
email_unique="$(gcloud_sql_psql.sh -q -t -A -v ON_ERROR_STOP=1 -c "
	SELECT count(*) FROM pg_constraint c
	JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
	WHERE c.conrelid = to_regclass('users') AND c.contype = 'u' AND array_length(c.conkey, 1) = 1 AND a.attname = 'email'
")"

# Collect the statements for what is missing, then run them in one session.
changed=()
statements=()
need() {
	changed+=("${1}")
	statements+=("${2};")
}
# the old sign-in columns, until logins hold what they did
if ! has "logins.subject:.*" && has "users.google_sub:.*"; then
	has "users.password_hash:.*" || need users.password_hash "ALTER TABLE users ADD COLUMN password_hash VARCHAR(300)"
	has "users.google_sub:400" || need "users.google_sub (wider)" "ALTER TABLE users ALTER COLUMN google_sub TYPE VARCHAR(400)"
fi
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
# the language of a work's main title and the one the user read it in (adding columns: run before the deploy)
if has "library_works.id:.*"; then
	has "library_works.title_locale:.*" || need library_works.title_locale "ALTER TABLE library_works ADD COLUMN title_locale VARCHAR(10) NOT NULL DEFAULT 'en'"
fi
# a book's ISBN (copied from external_id) and Open Library work (adding columns: run before the deploy);
# external_id goes in a run after deploying the version that no longer reads it
if has "library_works.id:.*"; then
	if ! has "library_works.isbn:.*"; then
		copy=""
		has "library_works.external_id:.*" && copy="; UPDATE library_works SET isbn = left(external_id, 20) WHERE external_id <> ''"
		need library_works.isbn "ALTER TABLE library_works ADD COLUMN isbn VARCHAR(20) NOT NULL DEFAULT ''${copy}"
	elif has "library_works.external_id:.*"; then
		need "library_works.external_id (dropped)" "UPDATE library_works SET isbn = left(external_id, 20) WHERE isbn = '' AND external_id <> '';
			ALTER TABLE library_works DROP COLUMN external_id"
	fi
	has "library_works.openlibrary_id:.*" || need library_works.openlibrary_id "ALTER TABLE library_works ADD COLUMN openlibrary_id VARCHAR(20) NOT NULL DEFAULT ''"
fi
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
# addresses in parts (adding columns: run before the deploy; scripts/split_addresses.py fills them)
for table in places museum_visits organizations; do
	if ! has "${table}.street:.*"; then
		need "${table}.street" "ALTER TABLE ${table} ADD COLUMN street VARCHAR(300) NOT NULL DEFAULT '';
			ALTER TABLE ${table} ADD COLUMN neighbourhood VARCHAR(200) NOT NULL DEFAULT '';
			ALTER TABLE ${table} ADD COLUMN postcode VARCHAR(20) NOT NULL DEFAULT ''"
	fi
done
# an organization's headquarters city (adding a column: run before the deploy; scripts/link_cities.py fills it)
if has "organizations.street:.*" && ! has "organizations.headquarters_id:.*"; then
	need organizations.headquarters_id "ALTER TABLE organizations ADD COLUMN headquarters_id INTEGER REFERENCES cities (id) ON DELETE SET NULL;
		CREATE INDEX IF NOT EXISTS ix_organizations_headquarters_id ON organizations (headquarters_id)"
fi
# a photo for every city, country, group, device, profession and place (adding columns: run before the deploy)
for table in cities countries groups devices person_types places; do
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

# sign-in through logins, the users being the people (before the deploy, and again after it)
read -r -d '' fill_logins <<'SQL' || true
INSERT INTO logins (subject, user_id, email, name, picture, verified, password_hash, created_at)
	SELECT s.subject, u.id, lower(u.email), u.name, u.picture, u.google_sub NOT LIKE 'email:%', u.password_hash, u.created_at
	FROM users u, LATERAL (SELECT CASE WHEN position(':' in u.google_sub) = 0 THEN 'google:' || u.google_sub ELSE u.google_sub END AS subject) s
	WHERE u.google_sub IS NOT NULL
	  AND NOT EXISTS (SELECT 1 FROM logins l WHERE l.user_id = u.id)
	  AND NOT EXISTS (SELECT 1 FROM logins l WHERE l.subject = s.subject);
UPDATE users u SET verified = EXISTS (SELECT 1 FROM logins l WHERE l.user_id = u.id AND l.verified), email = lower(u.email);
-- the accounts of one verified email become the oldest of them, each that owns nothing (a row of
-- any table with an owner_id or a user_id); one that owns something stays, and is named. An
-- account left with no login (the old version made it again for a login that has moved) and
-- owning nothing goes.
DO $$
DECLARE
	account record;
	owned record;
	owns bigint;
	n bigint;
BEGIN
	FOR account IN
		SELECT u.id, u.role, (SELECT min(k.id) FROM users k WHERE k.verified AND k.email = u.email) AS keep,
		       NOT EXISTS (SELECT 1 FROM logins l WHERE l.user_id = u.id) AS bare
		FROM users u ORDER BY u.id
	LOOP
		CONTINUE WHEN NOT account.bare AND (account.keep IS NULL OR account.keep = account.id);
		owns := 0;
		FOR owned IN
			SELECT c.table_name, c.column_name FROM information_schema.columns c
			WHERE c.table_schema = current_schema() AND c.column_name IN ('owner_id', 'user_id') AND c.table_name NOT IN ('logins', 'users')
		LOOP
			EXECUTE format('SELECT count(*) FROM %I WHERE %I = $1', owned.table_name, owned.column_name) INTO n USING account.id;
			owns := owns + n;
		END LOOP;
		IF owns > 0 THEN
			RAISE NOTICE 'account % owns % rows: it stays', account.id, owns;
			CONTINUE;
		END IF;
		IF NOT account.bare THEN
			UPDATE logins SET user_id = account.keep WHERE user_id = account.id;
			IF account.role = 'admin' THEN
				UPDATE users SET role = 'admin' WHERE id = account.keep;
			END IF;
		END IF;
		DELETE FROM users WHERE id = account.id;
	END LOOP;
END
$$
SQL
if has "users.google_sub:.*"; then
	if ! has "logins.subject:.*"; then
		adds=""
		has "users.verified:.*" || adds+="ALTER TABLE users ADD COLUMN verified BOOLEAN NOT NULL DEFAULT false;"
		has "users.last_login:.*" || adds+="ALTER TABLE users ADD COLUMN last_login TIMESTAMP WITHOUT TIME ZONE;"
		need "logins (one per account), accounts of one verified email joined" "CREATE TABLE logins (
				id SERIAL PRIMARY KEY,
				subject VARCHAR(400) NOT NULL,
				user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
				email VARCHAR(320) NOT NULL DEFAULT '',
				name VARCHAR(200) NOT NULL DEFAULT '',
				picture VARCHAR(1000) NOT NULL DEFAULT '',
				verified BOOLEAN NOT NULL DEFAULT false,
				password_hash VARCHAR(300),
				created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
				last_login TIMESTAMP WITHOUT TIME ZONE,
				CONSTRAINT logins_subject_key UNIQUE (subject));
			CREATE INDEX ix_logins_user_id ON logins (user_id);
			${adds}
			ALTER TABLE users ALTER COLUMN google_sub DROP NOT NULL;
			${fill_logins}"
	else
		need "users.google_sub, users.password_hash (in logins now)" "${fill_logins};
			ALTER TABLE users DROP COLUMN google_sub, DROP COLUMN password_hash"
	fi
fi

# only a proven email gets an account (see the header). The logins that were never proven
# and the accounts that are unverified themselves or are left with no login go, unless one
# owns rows in a table with a foreign key to users (those go with it, ON DELETE CASCADE):
# then the statement raises, the one transaction rolls back and psql exits with the list.
read -r -d '' drop_unproven <<'SQL' || true
DO $$
DECLARE
	doomed_logins integer[];
	doomed_users integer[];
	reference record;
	counted record;
	found text[] := '{}';
	report text;
BEGIN
	SELECT COALESCE(array_agg(id), '{}') INTO doomed_logins FROM logins WHERE subject LIKE 'email:%' OR NOT verified;
	SELECT COALESCE(array_agg(u.id), '{}') INTO doomed_users FROM users u
		WHERE NOT u.verified
		   OR NOT EXISTS (SELECT 1 FROM logins l WHERE l.user_id = u.id AND l.id <> ALL (doomed_logins));
	FOR reference IN
		SELECT c.conrelid::regclass::text AS tbl, a.attname::text AS col
		FROM pg_constraint c JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
		WHERE c.contype = 'f' AND c.confrelid = 'users'::regclass AND c.conrelid <> 'logins'::regclass
		ORDER BY 1, 2
	LOOP
		FOR counted IN EXECUTE format('SELECT t.%1$I AS id, count(*) AS n FROM %2$s t WHERE t.%1$I = ANY ($1) GROUP BY 1', reference.col, reference.tbl) USING doomed_users
		LOOP
			found := found || format('%s|%s|%s', counted.id, reference.tbl, counted.n);
		END LOOP;
	END LOOP;
	IF cardinality(found) > 0 THEN
		SELECT string_agg(format('  user %s (%s): %s', p.uid, (SELECT u.email FROM users u WHERE u.id = p.uid), p.what), E'\n' ORDER BY p.uid) INTO report FROM (
			SELECT parts[1]::integer AS uid, string_agg(parts[3] || ' in ' || parts[2], ', ' ORDER BY parts[2]) AS what
			FROM (SELECT string_to_array(f, '|') AS parts FROM unnest(found) f) split
			GROUP BY parts[1]
		) p;
		RAISE EXCEPTION E'not migrated, nothing changed: these accounts have no proven email and own rows that deleting them would delete too. Decide for each: give it a proven way to sign in, move its rows, or delete it by hand.\n%', report;
	END IF;
	DELETE FROM logins WHERE user_id = ANY (doomed_users) OR id = ANY (doomed_logins);
	DELETE FROM users WHERE id = ANY (doomed_users);
END
$$;
ALTER TABLE users DROP COLUMN verified;
ALTER TABLE logins DROP COLUMN verified
SQL
read -r -d '' check_emails <<'SQL' || true
DO $$
DECLARE
	shared text;
BEGIN
	SELECT string_agg(format('%s: accounts %s', e, ids), E'\n  ') INTO shared FROM (
		SELECT lower(email) AS e, string_agg(id::text, ', ' ORDER BY id) AS ids FROM users GROUP BY lower(email) HAVING count(*) > 1
	) d;
	IF shared IS NOT NULL THEN
		RAISE EXCEPTION E'not migrated, nothing changed: emails shared by several accounts, so users.email cannot be unique; merge or delete them by hand:\n  %', shared;
	END IF;
END
$$
SQL
if has "logins.subject:.*" && ! has "users.google_sub:.*"; then
	has "logins.password_hash:.*" || need logins.password_hash "ALTER TABLE logins ADD COLUMN password_hash VARCHAR(300)"
	has "email_verifications.email:.*" || need email_verifications "CREATE TABLE email_verifications (
			email VARCHAR(320) NOT NULL,
			token_hash VARCHAR(64) NOT NULL,
			sent_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
			CONSTRAINT email_verifications_pkey PRIMARY KEY (email),
			CONSTRAINT email_verifications_token_hash_key UNIQUE (token_hash))"
	if has "users.verified:.*" && has "logins.verified:.*"; then
		need "unproven logins and the accounts without a proven email dropped, users.verified and logins.verified" "${drop_unproven}"
	elif has "users.verified:.*" || has "logins.verified:.*"; then
		echo "users.verified and logins.verified are expected together: one of them is missing, look at the database" >&2
		exit 1
	fi
	if [[ "${email_unique}" == "0" ]]; then
		need "users.email unique" "${check_emails};
			ALTER TABLE users ADD CONSTRAINT users_email_key UNIQUE (email)"
	fi
elif has "users.google_sub:.*"; then
	echo "the logins step above is not done yet: run this again for the proven-email step" >&2
fi

# the locales table and every locale column pointing at it (see the header): how many of the
# tables with a locale column there are, of the three that keep theirs how many point at locales
# (a table may point at it twice: library_works.original_locale does too)
# (library_entries.locale goes into the reads, below), and whether a work
# has one title per language. Every statement is safe to run again.
locale_state="$(gcloud_sql_psql.sh -q -t -A -v ON_ERROR_STOP=1 -c "
	SELECT (SELECT count(*) FROM information_schema.tables WHERE table_name IN ('library_works', 'library_work_titles', 'library_entries', 'person_names'))
		|| ':' || (SELECT count(DISTINCT conrelid) FROM pg_constraint WHERE contype = 'f' AND confrelid = to_regclass('locales')
			AND conrelid IN (to_regclass('library_works'), to_regclass('library_work_titles'), to_regclass('person_names')))
		|| ':' || (SELECT count(*) FROM pg_constraint WHERE conname = 'uq_work_title_locale')
")"
read -r -d '' point_at_locales <<'SQL' || true
CREATE TABLE IF NOT EXISTS locales (
	code VARCHAR(10) NOT NULL,
	name VARCHAR(100) NOT NULL,
	script VARCHAR(50) NOT NULL,
	position INTEGER NOT NULL,
	CONSTRAINT locales_pkey PRIMARY KEY (code),
	CONSTRAINT locales_name_key UNIQUE (name));
INSERT INTO locales (code, name, script, position) VALUES
	('en', 'English', 'Latin', 0), ('he', 'Hebrew', 'Hebrew', 1), ('ar', 'Arabic', 'Arabic', 2), ('yi', 'Yiddish', 'Hebrew', 3),
	('fr', 'French', 'Latin', 4), ('de', 'German', 'Latin', 5), ('es', 'Spanish', 'Latin', 6), ('it', 'Italian', 'Latin', 7),
	('pt', 'Portuguese', 'Latin', 8), ('ru', 'Russian', 'Cyrillic', 9), ('cs', 'Czech', 'Latin', 10), ('el', 'Greek', 'Greek', 11)
	ON CONFLICT (code) DO NOTHING;
DO $$
DECLARE
	wrong text;
BEGIN
	SELECT string_agg(line, E'\n  ') INTO wrong FROM (
		SELECT 'library_works.title_locale: ' || count(*) || ' rows say ' || quote_literal(title_locale) AS line
			FROM library_works WHERE title_locale NOT IN (SELECT code FROM locales) GROUP BY title_locale
		UNION ALL SELECT 'library_work_titles.locale: ' || count(*) || ' rows say ' || quote_literal(locale)
			FROM library_work_titles WHERE locale NOT IN (SELECT code FROM locales) GROUP BY locale
		UNION ALL SELECT 'library_entries.locale: ' || count(*) || ' rows say ' || quote_literal(locale)
			FROM library_entries WHERE locale <> '' AND locale NOT IN (SELECT code FROM locales) GROUP BY locale
		UNION ALL SELECT 'person_names.locale: ' || count(*) || ' rows say ' || quote_literal(locale)
			FROM person_names WHERE locale NOT IN (SELECT code FROM locales) GROUP BY locale
		UNION ALL SELECT 'work ' || work_id || ' has several titles in ' || locale || ': ' || string_agg(title, ' / ')
			FROM (SELECT work_id, locale, title FROM library_work_titles
				UNION ALL SELECT id, title_locale, title FROM library_works WHERE id IN (SELECT work_id FROM library_work_titles)) titles
			GROUP BY work_id, locale HAVING count(*) > 1
	) problems;
	IF wrong IS NOT NULL THEN
		RAISE EXCEPTION E'not migrated, nothing changed: fix these by hand first (a language of the locales table, one title per language):\n  %', wrong;
	END IF;
END
$$;
ALTER TABLE library_entries ALTER COLUMN locale DROP NOT NULL, ALTER COLUMN locale DROP DEFAULT;
UPDATE library_entries SET locale = NULL WHERE locale = '';
ALTER TABLE library_works DROP CONSTRAINT IF EXISTS library_works_title_locale_fkey,
	ADD CONSTRAINT library_works_title_locale_fkey FOREIGN KEY (title_locale) REFERENCES locales (code);
ALTER TABLE library_work_titles DROP CONSTRAINT IF EXISTS library_work_titles_locale_fkey,
	ADD CONSTRAINT library_work_titles_locale_fkey FOREIGN KEY (locale) REFERENCES locales (code);
ALTER TABLE library_entries DROP CONSTRAINT IF EXISTS library_entries_locale_fkey,
	ADD CONSTRAINT library_entries_locale_fkey FOREIGN KEY (locale) REFERENCES locales (code);
ALTER TABLE person_names DROP CONSTRAINT IF EXISTS person_names_locale_fkey,
	ADD CONSTRAINT person_names_locale_fkey FOREIGN KEY (locale) REFERENCES locales (code);
ALTER TABLE library_work_titles DROP CONSTRAINT IF EXISTS uq_work_title, DROP CONSTRAINT IF EXISTS uq_work_title_locale,
	ADD CONSTRAINT uq_work_title_locale UNIQUE (work_id, locale)
SQL
if [[ "${locale_state}" == 4:* && "${locale_state}" != "4:3:1" ]]; then
	need "locales, and the four locale columns pointing at it; one title per language" "${point_at_locales}"
fi

# reads (see the header): a read per entry that was read, from its finished_on and locale,
# and then the two columns go. After the locales step, which the reads' language points at.
read -r -d '' entries_to_reads <<'SQL' || true
CREATE TABLE IF NOT EXISTS library_reads (
	id SERIAL NOT NULL,
	user_id INTEGER NOT NULL,
	work_id INTEGER NOT NULL,
	read_on DATE,
	locale VARCHAR(10),
	CONSTRAINT library_reads_pkey PRIMARY KEY (id),
	CONSTRAINT fk_library_reads_entry FOREIGN KEY (user_id, work_id) REFERENCES library_entries (user_id, work_id) ON DELETE CASCADE,
	CONSTRAINT library_reads_locale_fkey FOREIGN KEY (locale) REFERENCES locales (code));
CREATE INDEX IF NOT EXISTS ix_library_reads_entry ON library_reads (user_id, work_id);
INSERT INTO library_reads (user_id, work_id, read_on, locale)
	SELECT e.user_id, e.work_id, e.finished_on, COALESCE(e.locale, CASE
		WHEN w.kind <> 'book' THEN NULL
		WHEN w.title_locale = 'he' OR EXISTS (SELECT 1 FROM library_work_titles t WHERE t.work_id = w.id AND t.locale = 'he') THEN 'he'
		WHEN w.title_locale = 'en' OR EXISTS (SELECT 1 FROM library_work_titles t WHERE t.work_id = w.id AND t.locale = 'en') THEN 'en' END)
	FROM library_entries e JOIN library_works w ON w.id = e.work_id
	WHERE (e.status = 'done' OR e.finished_on IS NOT NULL OR e.locale IS NOT NULL)
	  AND NOT EXISTS (SELECT 1 FROM library_reads r WHERE r.user_id = e.user_id AND r.work_id = e.work_id)
	ORDER BY e.user_id, e.work_id;
ALTER TABLE library_entries DROP COLUMN locale, DROP COLUMN finished_on
SQL
if has "library_entries.finished_on:.*" && has "library_entries.locale:.*"; then
	need "library_reads (a read per entry read, from library_entries.finished_on and locale, which are dropped)" "${entries_to_reads}"
fi

# the language an account prefers: English, for every account there is. After the locales
# step above (in the same transaction), which makes the table it points at.
has "users.locale:.*" || need users.locale "ALTER TABLE users ADD COLUMN locale VARCHAR(10) NOT NULL DEFAULT 'en' CONSTRAINT users_locale_fkey REFERENCES locales (code)"

# what the user thought of a book, beside its notes; not once it went to the readings (below)
has "library_entries.review:.*" || has "library_reads.status:.*" || need library_entries.review "ALTER TABLE library_entries ADD COLUMN review TEXT NOT NULL DEFAULT ''"

# a reading has its own status, rating, review and day started (see the header): those of
# each entry go to the reading it went by, and then the four columns go. After the reads
# step and the review above, in the same transaction. Deploy first, run this right after.
read -r -d '' entries_into_reads <<'SQL' || true
ALTER TABLE library_reads
	ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'done',
	ADD COLUMN rating INTEGER,
	ADD COLUMN started_on DATE,
	ADD COLUMN review TEXT NOT NULL DEFAULT '',
	ADD CONSTRAINT ck_read_rating_range CHECK (rating IS NULL OR (rating >= 1 AND rating <= 10));
INSERT INTO library_reads (user_id, work_id)
	SELECT e.user_id, e.work_id FROM library_entries e
	WHERE NOT EXISTS (SELECT 1 FROM library_reads r WHERE r.user_id = e.user_id AND r.work_id = e.work_id)
	ORDER BY e.user_id, e.work_id;
UPDATE library_reads r SET status = e.status, rating = e.rating, started_on = e.started_on, review = e.review
	FROM library_entries e
	WHERE r.user_id = e.user_id AND r.work_id = e.work_id
	  AND r.id = (SELECT r2.id FROM library_reads r2 WHERE r2.user_id = e.user_id AND r2.work_id = e.work_id
		ORDER BY r2.read_on IS NULL, r2.read_on DESC, r2.id DESC LIMIT 1);
ALTER TABLE library_entries DROP COLUMN status, DROP COLUMN rating, DROP COLUMN started_on, DROP COLUMN review
SQL
if has "library_entries.status:.*" && ! has "library_reads.status:.*"; then
	need "library_reads.status, rating, started_on and review (from library_entries, where they are dropped)" "${entries_into_reads}"
fi

# what a language is called in itself (see the header): adding a column, run before the deploy
if has "locales.code:.*" && ! has "locales.native:.*"; then
	need locales.native "ALTER TABLE locales ADD COLUMN native VARCHAR(100) NOT NULL DEFAULT ''; UPDATE locales SET native = 'English' WHERE code = 'en' AND native = ''; UPDATE locales SET native = 'עברית' WHERE code = 'he' AND native = ''; UPDATE locales SET native = 'العربية' WHERE code = 'ar' AND native = ''; UPDATE locales SET native = 'ייִדיש' WHERE code = 'yi' AND native = ''; UPDATE locales SET native = 'Français' WHERE code = 'fr' AND native = ''; UPDATE locales SET native = 'Deutsch' WHERE code = 'de' AND native = ''; UPDATE locales SET native = 'Español' WHERE code = 'es' AND native = ''; UPDATE locales SET native = 'Italiano' WHERE code = 'it' AND native = ''; UPDATE locales SET native = 'Português' WHERE code = 'pt' AND native = ''; UPDATE locales SET native = 'Русский' WHERE code = 'ru' AND native = ''; UPDATE locales SET native = 'Čeština' WHERE code = 'cs' AND native = ''; UPDATE locales SET native = 'Ελληνικά' WHERE code = 'el' AND native = ''"
fi

# the language a work was first written in (see the header): adding a column, run before the deploy
if has "library_works.id:.*" && ! has "library_works.original_locale:.*"; then
	need library_works.original_locale "ALTER TABLE library_works ADD COLUMN original_locale VARCHAR(10) REFERENCES locales (code)"
fi

# a person's name in another language, in its parts (see the header): adding columns, run before the deploy
read -r -d '' name_parts <<'SQL' || true
ALTER TABLE person_names
	ADD COLUMN honorific VARCHAR(50) NOT NULL DEFAULT '',
	ADD COLUMN first_name VARCHAR(200) NOT NULL DEFAULT '',
	ADD COLUMN middle_name VARCHAR(200) NOT NULL DEFAULT '',
	ADD COLUMN surname VARCHAR(200) NOT NULL DEFAULT '';
UPDATE person_names SET
	first_name = split_part(name, ' ', 1),
	middle_name = CASE WHEN name ~ '^[^ ]+ .+ [^ ]+$' THEN regexp_replace(name, '^[^ ]+ (.*) [^ ]+$', '\1') ELSE '' END,
	surname = CASE WHEN name LIKE '% %' THEN regexp_replace(name, '^.* ', '') ELSE '' END
SQL
if has "person_names.id:.*" && ! has "person_names.first_name:.*"; then
	need "person_names.honorific, first_name, middle_name and surname" "${name_parts}"
fi

if (( ${#changed[@]} == 0 )); then
	echo "${gcp_sql_instance}/${gcp_db_name}: up to date, nothing to migrate"
else
	# one transaction: a failing statement stops psql and leaves the database as it was
	printf '%s\n' "BEGIN;" "${statements[@]}" "COMMIT;" | gcloud_sql_psql.sh -q -v ON_ERROR_STOP=1 > /dev/null
	echo "${gcp_sql_instance}/${gcp_db_name}: migrated ${changed[*]}"
	echo "deploy with gcloud_deploy.sh"
fi
