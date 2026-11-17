#!/usr/bin/env python

"""
Move the review that leads a book's notes into its own field
(library_entries.review). The import wrote what the user thought of a book
("very good") as the first sentences of its notes, before the facts it has
no field for ("Owned in English", "Written in German", "was named: ...");
the sentences before the first such fact are the review, and the facts stay
the notes. Notes with no such fact are left as they are (they are the
user's own words, and may be anything), and so is an entry that has a
review already. Nothing is deleted. Safe to run any time; a second run
changes nothing.

  scripts/split_reviews.py            move them
  scripts/split_reviews.py --dry-run  only print what would move

The database is DATABASE_URL (default: the local sqlite file); for Cloud SQL
run it through the proxy: scripts/with_cloud_db.sh scripts/split_reviews.py.
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

from myworld.models import UserWork, make_engine

# how the sentences the import writes into a book's notes start (scripts/import_world.py, _book_notes)
FACTS = ("Read in ", "Owned in ", "Written in ", "Publisher: ", "was named: ")


def split_notes(notes: str) -> tuple[str, str]:
    """ notes as (review, the rest): the sentences before the first fact, and from it on; no review when there is no fact. """
    parts = notes.split(". ")
    first = next((index for index, part in enumerate(parts) if part.startswith(FACTS)), None)
    if first is None:
        return "", notes
    return ". ".join(parts[:first]), ". ".join(parts[first:])


def split(session: Session) -> int:
    """ Move the reviews in the session (not committed), printing each; how many moved. """
    moved = 0
    for entry in session.scalars(select(UserWork).order_by(UserWork.user_id, UserWork.work_id)):
        review, notes = split_notes(entry.notes)
        if review and not entry.review:
            moved += 1
            print(f"{entry.work.kind} {entry.work_id} ({entry.work.title}): review {review!r}, notes {notes!r}")
            entry.review, entry.notes = review, notes
    return moved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="only print what would move")
    args = parser.parse_args()
    with Session(make_engine()) as session:
        moved = split(session)
        if not args.dry_run:
            session.commit()
    print(f"{moved} reviews {'would move' if args.dry_run else 'moved'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
