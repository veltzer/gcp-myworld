"""
The migrations (scripts/migrations/, run by scripts/migrate.sh): they make
the tables the models declare, the app marks a database it made as being at
the newest of them, and one the migrations keep is changed by them alone.
"""

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
        user, work = User(email="a@example.com", role=ROLE_ADMIN), Work(kind="book", title="Dune", creator="Frank Herbert")
        session.add_all([user, work])
        session.flush()
        session.add(UserWork(user_id=user.id, work_id=work.id, notes="kept"))
        session.commit()
    with engine.begin() as connection:
        connection.execute(text("UPDATE library_entries SET not_owned = 1"))
    engine.dispose()
    assert run(url, "upgrade").stdout.strip() == f"migrated from 0001 to {SCHEMA_REVISION}"
    engine = create_engine(url)
    assert "not_owned" not in {column["name"] for column in inspect(engine).get_columns("library_entries")}
    # the row is as it was
    with engine.connect() as connection:
        assert connection.execute(text("SELECT user_id, work_id, notes FROM library_entries")).all() == [(1, 1, "kept")]
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
    # 0004, after it: the text goes
    assert run(url, "upgrade").stdout.strip() == f"migrated from 0003 to {SCHEMA_REVISION}"
    engine = create_engine(url)
    assert "region" not in {column["name"] for column in inspect(engine).get_columns("cities")}
    with Session(engine) as session:
        assert [(city.name, city.region) for city in session.scalars(select(City).order_by(City.id))] == [
            ("Austin", "Texas"), ("Dallas", "Texas"), ("Portland", "Oregon"), ("Tel Aviv", ""), ("Houston", "Texas"), ("Atlantis", "The Deep"), ("Haifa", ""),
        ]
    engine.dispose()
    assert run(url, "drift").stdout.strip() == "0 differences between the database and the models"
