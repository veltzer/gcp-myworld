"""
The migrations (scripts/migrations/, run by scripts/migrate.sh): they make
the tables the models declare, the app marks a database it made as being at
the newest of them, and one the migrations keep is changed by them alone.
"""

import datetime
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from myworld import admin
from myworld.models import (
    ROLE_ADMIN,
    SCHEMA_REVISION,
    Base,
    City,
    User,
    UserWork,
    Work,
    make_engine,
)

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / "scripts" / "migrations" / "run.py"


def run(url: str, *arguments: str, script: Path = RUN) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(script), *arguments] if script.suffix == ".py" else [str(script), *arguments]
    return subprocess.run(command, cwd=ROOT, env={**os.environ, "DATABASE_URL": url}, capture_output=True, text=True, check=False)


def tables(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def revision(url: str) -> str | None:
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    finally:
        engine.dispose()


@pytest.fixture(name="url")
def fixture_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'db.sqlite'}"


def test_the_models_are_at_the_newest_migration() -> None:
    versions = sorted(path.stem.split("_")[0] for path in (ROOT / "scripts" / "migrations" / "versions").glob("*.py"))
    assert versions and versions[-1] == SCHEMA_REVISION
    # numbered in order, each once
    assert versions == [f"{n:04d}" for n in range(1, len(versions) + 1)]


def test_the_migrations_make_what_the_models_declare(url: str) -> None:
    assert run(url, "state").stdout.strip() == "empty"
    made = run(url, "upgrade")
    assert made.returncode == 0, made.stderr
    assert made.stdout.strip() == f"migrated from empty to {SCHEMA_REVISION}"
    assert run(url, "state").stdout.strip() == SCHEMA_REVISION
    assert tables(url) == set(Base.metadata.tables) | {"alembic_version"}
    # a change to the models without a migration for it shows here
    drift = run(url, "drift")
    assert drift.returncode == 0, drift.stderr
    assert drift.stdout.strip() == "0 differences between the database and the models", drift.stdout
    assert run(url, "upgrade").stdout.strip() == f"nothing to migrate: the database is at {SCHEMA_REVISION}"


def test_a_database_the_app_makes_is_at_the_newest_migration(url: str) -> None:
    make_engine(url).dispose()
    assert revision(url) == SCHEMA_REVISION
    assert tables(url) == set(Base.metadata.tables) | {"alembic_version"}
    assert run(url, "upgrade").stdout.strip() == f"nothing to migrate: the database is at {SCHEMA_REVISION}"
    assert run(url, "drift").stdout.strip() == "0 differences between the database and the models"
    # started again, it is left as it is
    make_engine(url).dispose()
    assert revision(url) == SCHEMA_REVISION


def test_a_database_the_migrations_keep_is_changed_by_them_alone(url: str) -> None:
    make_engine(url).dispose()
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE city_photos"))
    engine.dispose()
    # the app does not put back a table of a database that has a revision: a migration would
    make_engine(url).dispose()
    assert "city_photos" not in tables(url)
    drift = run(url, "drift").stdout
    # the table and its index
    assert "city_photos" in drift and drift.splitlines()[-1] == "2 differences between the database and the models"


def test_a_database_from_before_the_migrations(url: str) -> None:
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE city_photos"))
    engine.dispose()
    assert run(url, "state").stdout.strip() == "legacy"
    # it is not upgraded as it is: the legacy script brings it up to date first
    refused = run(url, "upgrade")
    assert refused.returncode != 0 and "before the migrations kept count" in refused.stderr
    # the app gives it the tables it lacks, as it always did, and does not mark it
    make_engine(url).dispose()
    assert "city_photos" in tables(url) and "alembic_version" not in tables(url)
    # brought up to date, it is marked as being at the first migration
    marked = run(url, "baseline")
    assert marked.returncode == 0, marked.stderr
    assert marked.stdout.splitlines()[0] == "marked as being at 0001"
    assert run(url, "state").stdout.strip() == SCHEMA_REVISION
    # and only once
    again = run(url, "baseline")
    assert again.returncode != 0 and "only a database from before" in again.stderr


def test_a_step_is_named() -> None:
    for arguments in ((), ("sideways",), ("upgrade", "0001", "twice"), ("drift", "0001")):
        bare = run("sqlite://", *arguments)
        assert bare.returncode == 2
        assert [line.split()[0] for line in bare.stderr.splitlines()[1:]] == ["state", "upgrade", "baseline", "drift"]


def test_migrate_sh(url: str) -> None:
    script = ROOT / "scripts" / "migrate.sh"
    first = run(url, "--local", script=script)
    assert first.returncode == 0, first.stderr
    assert first.stdout.strip() == f"migrated from empty to {SCHEMA_REVISION}"
    assert run(url, "--local", script=script).stdout.strip() == f"nothing to migrate: the database is at {SCHEMA_REVISION}"
    assert run(url, "--local", "--drift", script=script).stdout.strip() == "0 differences between the database and the models"
    # stopped at a step on the way, then taken to the end
    assert run(url, "--local", "--to", "0002", script=script).stdout.strip() == f"nothing to migrate: the database is at {SCHEMA_REVISION}"
    wrong = run(url, "--sideways", script=script)
    assert wrong.returncode == 2 and "usage:" in wrong.stderr


def test_the_oldest_account_is_the_first_admin(url: str) -> None:
    engine = make_engine(url)
    # no account yet: no one to make an admin
    assert run(url, "upgrade").stdout.strip() == f"nothing to migrate: the database is at {SCHEMA_REVISION}"
    with Session(engine) as session:
        session.add_all([User(email="first@example.com"), User(email="second@example.com")])
        session.commit()
    assert run(url, "upgrade").stdout.strip() == f"nothing to migrate: the database is at {SCHEMA_REVISION}; user 1 made the first admin"
    # once there is one, nobody else is made one
    assert run(url, "upgrade").stdout.strip() == f"nothing to migrate: the database is at {SCHEMA_REVISION}"
    with Session(engine) as session:
        assert [(user.id, user.role) for user in session.scalars(select(User).order_by(User.id))] == [(1, ROLE_ADMIN), (2, "user")]
    engine.dispose()


def test_the_table_the_migrations_keep_is_no_drift(url: str) -> None:
    engine = make_engine(url)
    inspector = inspect(engine)
    kept = admin.table_json(inspector, "alembic_version", 1)
    assert (kept["in_model"], kept["only_in_database"], kept["only_in_model"]) == (True, [], [])
    assert [column["name"] for column in kept["columns"]] == ["version_num"]
    # a table nobody knows is still told as one the code does not have
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE leftovers (id INTEGER PRIMARY KEY)"))
    assert admin.table_json(inspect(engine), "leftovers", 0)["in_model"] is False
    engine.dispose()


def test_a_column_the_code_dropped_goes(url: str) -> None:
    """ 0002: library_entries.not_owned, which a database at the baseline has. """
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE library_entries ADD COLUMN not_owned BOOLEAN DEFAULT 0 NOT NULL"))
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
        connection.execute(text("INSERT INTO alembic_version VALUES ('0001')"))
    with Session(engine) as session:
        user = User(email="a@example.com", role=ROLE_ADMIN)
        session.add(user)
        session.flush()
        work = Work(owner_id=user.id, kind="book", title="Dune", creator="Frank Herbert")
        session.add(work)
        session.flush()
        session.add(UserWork(owner_id=user.id, work_id=work.id, notes="kept"))
        session.commit()
    with engine.begin() as connection:
        connection.execute(text("UPDATE library_entries SET not_owned = 1"))
    engine.dispose()
    assert run(url, "upgrade").stdout.strip() == f"migrated from 0001 to {SCHEMA_REVISION}"
    engine = create_engine(url)
    assert "not_owned" not in {column["name"] for column in inspect(engine).get_columns("library_entries")}
    # the row is as it was
    with engine.connect() as connection:
        assert connection.execute(text("SELECT owner_id, work_id, notes FROM library_entries")).all() == [(1, 1, "kept")]
    engine.dispose()
    assert run(url, "drift").stdout.strip() == "0 differences between the database and the models"


def alembic(url: str, *arguments: str) -> None:
    """ Alembic itself, to stop at a step on the way: what run.py never does. """
    done = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ROOT / "scripts" / "migrations" / "alembic.ini"), *arguments],
        cwd=ROOT, env={**os.environ, "DATABASE_URL": url}, capture_output=True, text=True, check=False,
    )
    assert done.returncode == 0, done.stderr


def test_regions_become_rows(url: str) -> None:
    """ 0003 and 0004: the text a city named its region by becomes a row it points at. """
    alembic(url, "upgrade", "0002")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO locales (code, name, script, position) VALUES ('en', 'English', 'Latin', 0)"))
        for user in (1, 2):
            connection.execute(text("INSERT INTO users (id, email, name, picture, created_at) VALUES (:id, :email, '', '', '2026-01-01')"), {"id": user, "email": f"{user}@example.com"})
        for country, owner, name in ((1, 1, "USA"), (2, 1, "Israel"), (3, 2, "USA")):
            connection.execute(text("INSERT INTO countries (id, owner_id, name, remark) VALUES (:id, :owner, :name, '')"), {"id": country, "owner": owner, "name": name})
        for city, owner, name, region, country in (
            (1, 1, "Austin", "Texas", 1), (2, 1, "Dallas", " Texas ", 1), (3, 1, "Portland", "Oregon", 1), (4, 1, "Tel Aviv", "", 2),
            # another account's Texas is its own, and a region with no country is one too
            (5, 2, "Houston", "Texas", 3), (6, 1, "Atlantis", "The Deep", None),
        ):
            connection.execute(
                text("INSERT INTO cities (id, owner_id, name, region, country_id, remark) VALUES (:id, :owner, :name, :region, :country, '')"),
                {"id": city, "owner": owner, "name": name, "region": region, "country": country},
            )
    # 0003, before the deploy: the rows are there, and the text still is, for the code still running
    assert run(url, "--local", "--to", "0003", script=ROOT / "scripts" / "migrate.sh").stdout.strip() == "migrated from 0002 to 0003; user 1 made the first admin"
    with engine.begin() as connection:
        regions = connection.execute(text("SELECT owner_id, name, country_id FROM regions ORDER BY owner_id, name")).all()
        assert regions == [(1, "Oregon", 1), (1, "Texas", 1), (1, "The Deep", None), (2, "Texas", 3)]
        linked = connection.execute(text("SELECT cities.name, regions.name, regions.owner_id FROM cities LEFT JOIN regions ON regions.id = cities.region_id ORDER BY cities.id")).all()
        assert linked == [("Austin", "Texas", 1), ("Dallas", "Texas", 1), ("Portland", "Oregon", 1), ("Tel Aviv", None, None), ("Houston", "Texas", 2), ("Atlantis", "The Deep", 1)]
        # the old code can still add a city, without the new column and without the text
        connection.execute(text("INSERT INTO cities (id, owner_id, name, country_id, remark) VALUES (7, 1, 'Haifa', 2, '')"))
    engine.dispose()
    # 0004, after it: the text goes (and 0011 makes the two accounts' USA, and their Texas, one)
    assert run(url, "upgrade").stdout.strip().splitlines() == [
        "0011: countries ('USA',) kept once (row 1; row 3 merged into it)",
        "0011: regions ('Texas', 1) kept once (row 1; row 4 merged into it)",
        f"migrated from 0003 to {SCHEMA_REVISION}",
    ]
    engine = create_engine(url)
    assert "region" not in {column["name"] for column in inspect(engine).get_columns("cities")}
    with Session(engine) as session:
        assert [(city.name, city.region) for city in session.scalars(select(City).order_by(City.id))] == [
            ("Austin", "Texas"), ("Dallas", "Texas"), ("Portland", "Oregon"), ("Tel Aviv", ""), ("Houston", "Texas"), ("Atlantis", "The Deep"), ("Haifa", ""),
        ]
    engine.dispose()
    assert run(url, "drift").stdout.strip() == "0 differences between the database and the models"


def test_a_work_is_its_accounts_own(url: str) -> None:
    """ 0005: user_id is owner_id everywhere, and a work two accounts have becomes one for each, with all that hangs on its entry. """
    alembic(url, "upgrade", "0004")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO locales (code, name, script, position) VALUES ('en', 'English', 'Latin', 0), ('he', 'Hebrew', 'Hebrew', 1)"))
        for user in (1, 2):
            connection.execute(text("INSERT INTO users (id, email, name, picture, created_at) VALUES (:id, :email, '', '', '2026-01-01')"), {"id": user, "email": f"{user}@example.com"})
            connection.execute(text("INSERT INTO logins (subject, user_id, email, name, picture, created_at) VALUES (:subject, :id, '', '', '', '2026-01-01')"), {"id": user, "subject": f"google:{user}"})
            connection.execute(text("INSERT INTO people (id, owner_id, first_name, surname, description) VALUES (:id, :id, 'Frank', 'Herbert', '')"), {"id": user})
            connection.execute(text("INSERT INTO images (id, owner_id, filename, content_type, sha256, data) VALUES (:id, :id, 'cover.jpg', 'image/jpeg', 'abc', x'00')"), {"id": user})
        connection.execute(text("INSERT INTO disabled_checks (user_id, check_name) VALUES (1, 'logos')"))
        # Dune is in both libraries, Emma in the first only, Solaris in the second only, and nobody has Ubik any more
        for work, title, isbn in ((1, "Dune", "9780441013593"), (2, "Emma", ""), (3, "Solaris", ""), (4, "Ubik", "")):
            connection.execute(
                text("INSERT INTO library_works (id, kind, title, creator, year, isbn, imdb_id, rotten_tomatoes_id, goodreads_id, simania_id) VALUES (:id, 'book', :title, 'Someone', 1965, :isbn, '', '', '', '')"),
                {"id": work, "title": title, "isbn": isbn},
            )
        connection.execute(text("INSERT INTO library_work_titles (work_id, locale, title) VALUES (1, 'he', 'חולית')"))
        for user, work, notes in ((1, 1, "mine"), (2, 1, "theirs"), (1, 2, ""), (2, 3, "")):
            connection.execute(text("INSERT INTO library_entries (user_id, work_id, notes, image_id, updated_at) VALUES (:user, :work, :notes, :user, '2026-01-01')"), {"user": user, "work": work, "notes": notes})
        for user, rating in ((1, 9), (2, 4)):
            ids = {"user": user, "rating": rating}
            connection.execute(text("INSERT INTO library_reads (user_id, work_id, locale, rating) VALUES (:user, 1, 'en', :rating)"), ids)
            connection.execute(text("INSERT INTO library_covers (user_id, work_id, image_id) VALUES (:user, 1, :user)"), ids)
            connection.execute(text("INSERT INTO library_ownings (user_id, work_id, locale) VALUES (:user, 1, 'he')"), ids)
            connection.execute(text("INSERT INTO library_entry_authors (user_id, work_id, person_id) VALUES (:user, 1, :user)"), ids)
    engine.dispose()
    assert run(url, "upgrade").stdout.strip() == f"migrated from 0004 to {SCHEMA_REVISION}; user 1 made the first admin"
    engine = create_engine(url)
    with engine.connect() as connection:
        for table in ("logins", "disabled_checks", "library_entries", "library_reads", "library_covers", "library_ownings", "library_entry_authors", "library_works"):
            names = {column["name"] for column in inspect(engine).get_columns(table)}
            assert "owner_id" in names and "user_id" not in names, table
        assert connection.execute(text("SELECT subject, owner_id FROM logins ORDER BY id")).all() == [("google:1", 1), ("google:2", 2)]
        assert connection.execute(text("SELECT owner_id, check_name FROM disabled_checks")).all() == [(1, "logos")]
        # the second account's Dune is a row of its own (5), as the first's is, and the work nobody had is the oldest account's
        works = connection.execute(text("SELECT id, owner_id, title, isbn FROM library_works ORDER BY id")).all()
        assert works == [(1, 1, "Dune", "9780441013593"), (2, 1, "Emma", ""), (3, 2, "Solaris", ""), (4, 1, "Ubik", ""), (5, 2, "Dune", "9780441013593")]
        assert connection.execute(text("SELECT work_id, locale, title FROM library_work_titles ORDER BY work_id")).all() == [(1, "he", "חולית"), (5, "he", "חולית")]
        # each entry, and all that hangs on it, is at its own account's work
        assert connection.execute(text("SELECT owner_id, work_id, notes, image_id FROM library_entries ORDER BY owner_id, work_id")).all() == [(1, 1, "mine", 1), (1, 2, "", 1), (2, 3, "", 2), (2, 5, "theirs", 2)]
        assert connection.execute(text("SELECT owner_id, work_id, rating FROM library_reads ORDER BY owner_id")).all() == [(1, 1, 9), (2, 5, 4)]
        assert connection.execute(text("SELECT owner_id, work_id, image_id FROM library_covers ORDER BY owner_id")).all() == [(1, 1, 1), (2, 5, 2)]
        assert connection.execute(text("SELECT owner_id, work_id, locale FROM library_ownings ORDER BY owner_id")).all() == [(1, 1, "he"), (2, 5, "he")]
        assert connection.execute(text("SELECT owner_id, work_id, person_id FROM library_entry_authors ORDER BY owner_id")).all() == [(1, 1, 1), (2, 5, 2)]
    # as the models read it
    with Session(engine) as session:
        entry = session.get(UserWork, (2, 5))
        assert entry is not None and (entry.work.owner_id, entry.work.title, entry.rating, entry.owned, entry.cover_ids) == (2, "Dune", 4, ["he"], [2, 2])
    engine.dispose()
    assert run(url, "drift").stdout.strip() == "0 differences between the database and the models"
    # run again, it finds nothing to do
    assert run(url, "upgrade").stdout.strip() == f"nothing to migrate: the database is at {SCHEMA_REVISION}"


def test_a_default_is_written_for_every_database() -> None:
    """
    The tests run the migrations on sqlite, which takes 0 for false; PostgreSQL,
    which the site runs on, does not: a column of true and false says its
    default as sa.false() or sa.true(), which each database writes its own way.
    """
    for path in sorted((ROOT / "scripts" / "migrations" / "versions").glob("*.py")):
        for number, line in enumerate(path.read_text(encoding="UTF8").splitlines(), 1):
            if "sa.Boolean()" in line and "server_default" in line:
                assert "server_default=sa.false()" in line or "server_default=sa.true()" in line, f"{path.name}:{number}: {line.strip()}"


def test_museums_become_places_and_their_visits_visits(url: str) -> None:
    """ 0011 and 0012: countries, cities and places are everyone's; a museum is a place of the kind Museum, a museum visit a visit. """
    alembic(url, "upgrade", "0010")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO locales (code, name, script, position) VALUES ('en', 'English', 'Latin', 0)"))
        for user in (1, 2):
            connection.execute(text("INSERT INTO users (id, email, name, picture, created_at, role) VALUES (:id, :email, '', '', '2026-01-01', 'user')"), {"id": user, "email": f"{user}@example.com"})
        connection.execute(text("INSERT INTO people (id, owner_id, first_name, surname, description) VALUES (1, 1, 'Dana', '', '')"))
        # both accounts have France and Paris; the first a club with a remark and a concert there, and the Louvre, visited twice
        for country, owner in ((1, 1), (2, 2)):
            connection.execute(text("INSERT INTO countries (id, owner_id, name, remark) VALUES (:id, :owner, 'France', '')"), {"id": country, "owner": owner})
            connection.execute(text("INSERT INTO cities (id, owner_id, name, country_id, remark) VALUES (:id, :owner, 'Paris', :id, '')"), {"id": country, "owner": owner})
        connection.execute(text(
            "INSERT INTO places (id, owner_id, name, city_id, website, remark, street, neighbourhood, postcode, image_source, image_license, image_author)"
            " VALUES (1, 1, 'New Morning', 1, '', 'Location approximate.', '', '', '', '', '', '')"
        ))
        connection.execute(text(
            "INSERT INTO concert_visits (id, owner_id, name, event, genre, place_id, broadcast, alone, review, remark, image_source, image_license, image_author, date_my, date_timezone)"
            " VALUES (1, 1, 'Jarrett', '', '', 1, false, true, '', 'Great', '', '', '', '', '')"
        ))
        connection.execute(text(
            "INSERT INTO museum_sites (id, owner_id, name, city_id, url, street, neighbourhood, postcode) VALUES (1, 1, 'Louvre', 1, 'https://louvre.fr', 'Rue de Rivoli', '', '')"
        ))
        for visit, rating in ((1, 9), (2, 7)):
            connection.execute(text(
                "INSERT INTO museum_visits (id, museum_id, rating, review, remark, alone, date_y, date_my, date_timezone) VALUES (:id, 1, :rating, '', 'mine', false, 2010, '', '')"
            ), {"id": visit, "rating": rating})
        connection.execute(text("INSERT INTO museum_companions (museum_id, person_id) VALUES (1, 1)"))
    engine.dispose()
    said = run(url, "upgrade").stdout.strip().splitlines()
    assert said == [
        "0011: countries ('France',) kept once (row 1; row 2 merged into it)",
        "0011: cities ('Paris', None, 1) kept once (row 1; row 2 merged into it)",
        f"migrated from 0010 to {SCHEMA_REVISION}; user 1 made the first admin",
    ]
    engine = create_engine(url)
    with engine.connect() as connection:
        places = connection.execute(text(
            "SELECT p.name, p.website, k.name FROM places p JOIN place_kind_links l ON l.place_id = p.id JOIN place_kinds k ON k.id = l.kind_id ORDER BY p.name"
        )).all()
        assert places == [("Louvre", "https://louvre.fr", "Museum"), ("New Morning", "", "Concert venue")]
        visits = connection.execute(text(
            "SELECT v.owner_id, p.name, t.name, v.rating, v.remark FROM visits v JOIN places p ON p.id = v.place_id JOIN visit_types t ON t.id = v.type_id ORDER BY v.id"
        )).all()
        assert visits == [(1, "Louvre", "Museum visit", 9, "mine"), (1, "Louvre", "Museum visit", 7, "mine")]
        assert connection.execute(text("SELECT visit_id, person_id FROM visit_companions")).all() == [(1, 1)]
        # the club's remark is the concert's now
        assert connection.execute(text("SELECT remark FROM concert_visits")).scalar() == "Great\nAbout the place: Location approximate."
        assert connection.execute(text("SELECT count(*) FROM countries")).scalar() == 1
    tables_now = tables(url)
    assert not {"museum_sites", "museum_visits", "museum_companions"} & tables_now
    for table in ("countries", "regions", "cities", "places"):
        assert "owner_id" not in {column["name"] for column in inspect(engine).get_columns(table)}, table
    engine.dispose()
    assert run(url, "drift").stdout.strip() == "0 differences between the database and the models"


def test_podcasts_become_shared_and_what_was_heard_each_accounts(url: str) -> None:
    """ 0024 and 0025: podcasts and their episodes are everyone's; each account's rating, review and hearing of them are its own. """
    alembic(url, "upgrade", "0023")
    engine = create_engine(url)
    with engine.begin() as connection:
        for user in (1, 2):
            connection.execute(text("INSERT INTO users (id, email, name, picture, created_at, role) VALUES (:id, :email, '', '', '2026-01-01', 'user')"), {"id": user, "email": f"{user}@example.com"})
        connection.execute(text("INSERT INTO devices (id, owner_id, name, description, image_source, image_license, image_author) VALUES (1, 1, 'Samsung S25', '', '', '', '')"))
        connection.execute(text("INSERT INTO images (id, owner_id, filename, content_type, sha256, data) VALUES (1, 2, 'podcast-1.jpg', 'image/jpeg', '0', X'FFD8')"))
        # both accounts have the podcast, the second with the cover; both heard its trailer, the first also episode 1
        connection.execute(text("INSERT INTO podcasts (id, owner_id, name, url, rss_feed, rating, review, image_id) VALUES (1, 1, 'History', '', 'https://f', 7, 'So-so', NULL)"))
        connection.execute(text("INSERT INTO podcasts (id, owner_id, name, url, rss_feed, rating, review, image_id) VALUES (2, 2, 'History', '', 'https://f', 9, 'Great', 1)"))
        episode = (
            "INSERT INTO podcast_episodes (id, owner_id, podcast_id, name, description, episode_type, explicit, enclosure_url, image_url, author, guid,"
            " review, listened_at, device_id, date_ymd, date_my, date_timezone) VALUES (:id, :owner, :podcast, :name, '', '', '', '', '', '', :guid, :review, :where, :device, '2026-03-22', '', '')"
        )
        for row in (
            {"id": 1, "owner": 1, "podcast": 1, "name": "Trailer", "guid": "g0", "review": "", "where": "Night Walks", "device": 1},
            {"id": 2, "owner": 1, "podcast": 1, "name": "1. Greatness", "guid": "g1", "review": "Good", "where": "", "device": None},
            {"id": 3, "owner": 2, "podcast": 2, "name": "Trailer", "guid": "g0", "review": "Short", "where": "Car", "device": None},
        ):
            connection.execute(text(episode), row)
    engine.dispose()
    said = run(url, "upgrade").stdout.strip().splitlines()
    assert said == [
        "0024: podcasts ('History',) kept once (row 1; row 2 merged into it)",
        "0024: podcast_episodes (1, 'g0') kept once (row 1; row 3 merged into it)",
        f"migrated from 0023 to {SCHEMA_REVISION}; user 1 made the first admin",
    ]
    engine = create_engine(url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id, name, rss_feed, image_id FROM podcasts")).all() == [(1, "History", "https://f", 1)]
        assert connection.execute(text("SELECT id, podcast_id, name, guid FROM podcast_episodes ORDER BY id")).all() == [(1, 1, "Trailer", "g0"), (2, 1, "1. Greatness", "g1")]
        assert connection.execute(text("SELECT owner_id, podcast_id, rating, review FROM podcasts_heard ORDER BY owner_id")).all() == [(1, 1, 7, "So-so"), (2, 1, 9, "Great")]
        assert connection.execute(text("SELECT owner_id, episode_id, review, listened_at, device_id, date_ymd FROM episodes_heard ORDER BY owner_id, episode_id")).all() == [
            (1, 1, "", "Night Walks", 1, "2026-03-22"), (1, 2, "Good", "", None, "2026-03-22"), (2, 1, "Short", "Car", None, "2026-03-22"),
        ]
    for table in ("podcasts", "podcast_episodes"):
        assert "owner_id" not in {column["name"] for column in inspect(engine).get_columns(table)}, table
    engine.dispose()
    assert run(url, "drift").stdout.strip() == "0 differences between the database and the models"


def test_audio_books_become_shared_each_in_versions_and_what_was_heard_each_accounts(url: str) -> None:
    """ 0026 and 0027: audio books are everyone's, each in versions (Audible, MP3); each account's rating, review and listening are its own. """
    alembic(url, "upgrade", "0025")
    engine = create_engine(url)
    with engine.begin() as connection:
        for user in (1, 2):
            connection.execute(text("INSERT INTO users (id, email, name, picture, created_at, role) VALUES (:id, :email, '', '', '2026-01-01', 'user')"), {"id": user, "email": f"{user}@example.com"})
        connection.execute(text("INSERT INTO devices (id, owner_id, name, description, image_source, image_license, image_author) VALUES (1, 1, 'Samsung S7', '', '', '', '')"))
        connection.execute(text("INSERT INTO images (id, owner_id, filename, content_type, sha256, data) VALUES (1, 1, 'audible-B1.jpg', 'image/jpeg', '0', X'FFD8')"))
        book = (
            "INSERT INTO audio_books (id, owner_id, source, source_id, name, subtitle, authors, narrators, series, series_sequence, genres, minutes,"
            " finished, percent_heard, added_utcz, purchased_utcz, cover_url, rating, review, progress, listened_at, device_id, date_ymd, date_my,"
            " date_timezone, image_id) VALUES (:id, :owner, :source, :asin, :name, '', 'Sam Harris', :narrators, '', '', :genres, :minutes, :finished,"
            " :percent, :added, NULL, '', :rating, :review, '', :where, :device, :date, '', '', :image)"
        )
        for row in (
            # the first account has Letter from Audible, and heard it as MP3 files too; and Free Will from Audible
            {"id": 1, "owner": 1, "source": "audible", "asin": "B1", "name": "Letter", "narrators": "Jordan Bridges", "genres": '["Religion"]', "minutes": 115,
             "finished": True, "percent": 100.0, "added": "2023-03-04", "rating": None, "review": "", "where": "", "device": None, "date": None, "image": 1},
            {"id": 2, "owner": 1, "source": "", "asin": None, "name": "Letter", "narrators": "", "genres": "[]", "minutes": None,
             "finished": True, "percent": None, "added": None, "rating": 9, "review": "Sharp", "where": "Night Walks", "device": 1, "date": "2016-05-01", "image": None},
            {"id": 3, "owner": 1, "source": "audible", "asin": "B2", "name": "Free Will", "narrators": "Sam Harris", "genres": "[]", "minutes": 60,
             "finished": False, "percent": 12.5, "added": "2021-01-01", "rating": None, "review": "", "where": "", "device": None, "date": None, "image": None},
            # the second account has Free Will from Audible too
            {"id": 4, "owner": 2, "source": "audible", "asin": "B2", "name": "Free Will", "narrators": "Sam Harris", "genres": "[]", "minutes": 60,
             "finished": True, "percent": 100.0, "added": "2022-01-01", "rating": 6, "review": "Short", "where": "", "device": None, "date": None, "image": None},
        ):
            connection.execute(text(book), row)
    engine.dispose()
    said = run(url, "upgrade").stdout.strip().splitlines()
    assert said == [
        "0026: audio_books row 4 is the Audible book B2 of row 3: its version",
        "0026: audio_books ('Letter', '', 'Sam Harris') kept once (row 1; row 2 merged into it)",
        "0026: audio_books ('Free Will', '', 'Sam Harris') kept once (row 3; row 4 merged into it)",
        f"migrated from 0025 to {SCHEMA_REVISION}; user 1 made the first admin",
    ]
    engine = create_engine(url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id, name, subtitle, authors FROM audio_books ORDER BY id")).all() == [
            (1, "Letter", "", "Sam Harris"), (3, "Free Will", "", "Sam Harris")]
        # Letter in two versions, Audible and MP3; Free Will's Audible version once, by its ASIN; the cover Audible's (0028), the MP3 files' none
        assert connection.execute(text("SELECT id, book_id, kind, asin, narrators, minutes, image_id FROM audio_book_versions ORDER BY id")).all() == [
            (1, 1, "audible", "B1", "Jordan Bridges", 115, 1), (2, 1, "mp3", None, "", None, None), (3, 3, "audible", "B2", "Sam Harris", 60, None)]
        # each account's rating and review of a book once: of Letter, the MP3 row's, as the Audible one had none
        assert connection.execute(text("SELECT owner_id, book_id, rating, review FROM audio_books_heard ORDER BY owner_id, book_id")).all() == [
            (1, 1, 9, "Sharp"), (1, 3, None, ""), (2, 3, 6, "Short")]
        # and a listen of each version it heard, as it heard it
        listens = text("SELECT owner_id, version_id, finished, percent_heard, listened_at, device_id, date_ymd FROM audio_book_listens ORDER BY owner_id, version_id")
        assert [tuple(row) for row in connection.execute(listens).all()] == [
            (1, 1, True, 100.0, "", None, None), (1, 2, True, None, "Night Walks", 1, datetime.date(2016, 5, 1) if url.startswith("postgresql") else "2016-05-01"),
            (1, 3, False, 12.5, "", None, None), (2, 3, True, 100.0, "", None, None)]
    assert not {"owner_id", "image_id"} & {column["name"] for column in inspect(engine).get_columns("audio_books")}
    engine.dispose()
    assert run(url, "drift").stdout.strip() == "0 differences between the database and the models"


def test_the_films_of_the_library_become_shared_films(url: str) -> None:
    """ 0031: a film of library_works becomes a shared film, once by its IMDb id; one no library entry has goes from library_works. """
    alembic(url, "upgrade", "0030")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO locales (code, name, script, position) VALUES ('en', 'English', 'Latin', 0)"))
        connection.execute(text("INSERT INTO users (id, email, name, picture, created_at, role) VALUES (1, '1@example.com', '', '', '2026-01-01', 'user')"))
        work = (
            "INSERT INTO library_works (id, owner_id, kind, title, creator, year, isbn, imdb_id, tmdb_id, rotten_tomatoes_id, goodreads_id, simania_id)"
            " VALUES (:id, 1, :kind, :title, :creator, :year, '', :imdb, :tmdb, :rt, '', '')"
        )
        for row in (
            # Dune is in no library; Solaris is in the account's, so it stays there too; a second Dune by the same IMDb id is one film
            {"id": 1, "kind": "film", "title": "Dune", "creator": "Denis Villeneuve", "year": 2021, "imdb": "tt1160419", "tmdb": 438631, "rt": "m/dune_2021"},
            {"id": 2, "kind": "film", "title": "Solaris", "creator": "Andrei Tarkovsky", "year": 1972, "imdb": "", "tmdb": None, "rt": ""},
            {"id": 3, "kind": "film", "title": "Dune: Part One", "creator": "Denis Villeneuve", "year": 2021, "imdb": "tt1160419", "tmdb": None, "rt": ""},
            {"id": 4, "kind": "book", "title": "Emma", "creator": "Jane Austen", "year": 1815, "imdb": "", "tmdb": None, "rt": ""},
        ):
            connection.execute(text(work), row)
        connection.execute(text("INSERT INTO library_entries (owner_id, work_id, notes, updated_at) VALUES (1, 2, '', '2026-01-01')"))
    engine.dispose()
    run(url, "upgrade")
    engine = create_engine(url)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT name, year, directors, imdb_id, tmdb_id, rotten_tomatoes_id FROM films ORDER BY id")).all() == [
            ("Dune", 2021, "Denis Villeneuve", "tt1160419", 438631, "m/dune_2021"), ("Solaris", 1972, "Andrei Tarkovsky", None, None, "")]
        assert connection.execute(text("SELECT id, kind FROM library_works ORDER BY id")).all() == [(2, "film"), (4, "book")]
    engine.dispose()
    assert run(url, "drift").stdout.strip() == "0 differences between the database and the models"
