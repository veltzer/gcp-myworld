#!/usr/bin/env python

"""
Make people's names follow the rules (src/myworld/names.py): the first name
and the surname one word each, a surname of two words hyphenated
("Di-Meola"), whatever comes between in the middle name. Only what is plain
is changed; a band or a description kept whole in the first name is left
for the people-names check to list. No name is lost: every word stays, in
the same order. Safe to run any time; a second run changes nothing.

  scripts/tidy_names.py            change them
  scripts/tidy_names.py --dry-run  only print what would change

The database is DATABASE_URL (default: the local sqlite file); for Cloud SQL
run it through the proxy: scripts/with_cloud_db.sh scripts/tidy_names.py.
Run scripts/migrate.sh first: it adds people.middle_name.
"""

import argparse
import os
import sys
from pathlib import Path

# the myworld package is in src/, not installed (see scripts/check.py)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)

from sqlalchemy import select
from sqlalchemy.orm import Session

from myworld import names
from myworld.models import Person, make_engine


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="only print what would change")
    args = parser.parse_args()
    with Session(make_engine()) as session:
        changed = 0
        for person in session.scalars(select(Person).order_by(Person.id)):
            before = (person.first_name, person.middle_name, person.surname)
            after = names.tidy(*before)
            if after != before:
                changed += 1
                print(f"{person.id}: {' / '.join(before)} -> {' / '.join(after)}")
                person.first_name, person.middle_name, person.surname = after
        if not args.dry_run:
            session.commit()
        print(f"{changed} names {'would change' if args.dry_run else 'changed'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
