#!/usr/bin/env python
"""
What scripts/migrate.sh does to the database DATABASE_URL names (or the
local sqlite file), one step at a time:

  run.py state    where the database is: "empty", "legacy" (it has tables
                  from before the migrations kept count) or its revision
  run.py upgrade  apply the migrations it lacks, make the oldest account an
                  admin when no account is one, and say what was done
  run.py baseline mark a database the legacy script has brought up to date
                  as being at the first migration, then upgrade
  run.py drift    how the database differs from what the models declare
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "src"))

# pylint: disable=wrong-import-position
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from myworld.models import ROLE_ADMIN, Base, User, database_url

BASELINE = "0001"
STEPS = {
    "state": "where the database is: empty, legacy, or its revision",
    "upgrade": "apply the migrations the database lacks",
    "baseline": "mark a database the legacy script brought up to date, then upgrade",
    "drift": "how the database differs from what the models declare",
}


def config() -> Config:
    return Config(str(HERE / "alembic.ini"))


def head() -> str:
    revision = ScriptDirectory.from_config(config()).get_current_head()
    assert revision is not None
    return revision


def state() -> str:
    engine = create_engine(database_url())
    try:
        tables = set(inspect(engine).get_table_names())
        if not tables:
            return "empty"
        if "alembic_version" not in tables:
            return "legacy"
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision() or "empty"
    finally:
        engine.dispose()


def upgrade() -> None:
    before = state()
    if before == "legacy":
        sys.exit("run.py upgrade: this database is from before the migrations kept count: scripts/migrate.sh brings it up to date first")
    command.upgrade(config(), "head")
    after = state()
    made = first_admin()
    said = f"nothing to migrate: the database is at {after}" if before == after else f"migrated from {before} to {after}"
    print(said + (f"; user {made} made the first admin" if made is not None else ""))


def first_admin() -> int | None:
    """ When there are accounts and none is an admin, the oldest becomes one: there is always someone to delegate from. """
    engine = create_engine(database_url())
    try:
        with Session(engine) as session:
            if session.scalar(select(User.id).where(User.role == ROLE_ADMIN).limit(1)) is not None:
                return None
            oldest = session.scalars(select(User).order_by(User.id).limit(1)).first()
            if oldest is None:
                return None
            oldest.role = ROLE_ADMIN
            session.commit()
            return oldest.id
    finally:
        engine.dispose()


def baseline() -> None:
    if state() != "legacy":
        sys.exit(f"run.py baseline: only a database from before the migrations kept count is marked; this one is {state()}")
    command.stamp(config(), BASELINE)
    print(f"marked as being at {BASELINE}")
    upgrade()


def drift() -> None:
    engine = create_engine(database_url())
    with engine.connect() as connection:
        found = compare_metadata(MigrationContext.configure(connection, opts={"compare_type": True}), Base.metadata)
    engine.dispose()
    for difference in found:
        print(difference)
    print(f"{len(found)} difference{'' if len(found) == 1 else 's'} between the database and the models")


def main() -> None:
    step = sys.argv[1] if len(sys.argv) == 2 else ""
    if step not in STEPS:
        print("run.py: say which step:", file=sys.stderr)
        for name, what in STEPS.items():
            print(f"  {name:9} {what}", file=sys.stderr)
        sys.exit(2)
    if step == "state":
        print(state())
    else:
        {"upgrade": upgrade, "baseline": baseline, "drift": drift}[step]()


if __name__ == "__main__":
    main()
