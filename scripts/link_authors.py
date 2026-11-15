#!/usr/bin/env python

"""
Link every book that has no author linked to its authors, the user's own
people, from its creator text: "Garry Kasparov", "Kernighan, Ritchie" and
"Brian Kernighan and Dennis Ritchie" name one or more people. Each name is
the user's person of that name (matched however it is spaced or
hyphenated), else a new person; every author linked becomes a Book Author.
A book whose creator is empty, or names more than one person of the user's,
is listed and left alone. Only books with no author are touched; safe to
run again.

  scripts/link_authors.py            link them
  scripts/link_authors.py --dry-run  only print what it would do

The database is DATABASE_URL (default: the local sqlite file); for Cloud SQL
run it through the proxy: scripts/with_cloud_db.sh scripts/link_authors.py.
"""

import argparse
import os
import re
import sys
from pathlib import Path

# the myworld package is in src/, not installed (see scripts/check.py)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from myworld import names as naming
from myworld.models import Person, PersonType, UserWork, Work, make_engine

# what separates the authors in a creator text
SEPARATOR = re.compile(r"\s*(?:,|;|&|\band\b|\bwith\b)\s*", re.IGNORECASE)
BOOK_AUTHOR = ("Book Author", "Someone who wrote a book I read or own")


def author_names(creator: str) -> list[str]:
    """ The names in a creator text, in order, each once. """
    return list(dict.fromkeys(name for name in SEPARATOR.split(creator.strip()) if name))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="only print what it would do")
    args = parser.parse_args()
    engine = make_engine()
    print(engine.url.render_as_string(hide_password=True))
    linked = added = skipped = 0
    with Session(engine) as session:
        entries = session.scalars(
            select(UserWork).join(Work).where(Work.kind == "book", ~UserWork.authors.any())
            .order_by(UserWork.user_id, Work.title).options(selectinload(UserWork.work))
        ).all()
        people: dict[int, dict[str, list[Person]]] = {}
        book_authors: dict[int, PersonType] = {}
        for entry in entries:
            owner = entry.user_id
            if owner not in people:
                people[owner] = {}
                for person in session.scalars(select(Person).where(Person.owner_id == owner).options(selectinload(Person.types))):
                    people[owner].setdefault(naming.key(person.name), []).append(person)
                kind = session.scalars(select(PersonType).where(PersonType.owner_id == owner, PersonType.name == BOOK_AUTHOR[0])).first()
                if kind is None:
                    kind = PersonType(owner_id=owner, name=BOOK_AUTHOR[0], description=BOOK_AUTHOR[1])
                    session.add(kind)
                book_authors[owner] = kind
            what = f"account {owner}, {entry.work.title!r}"
            names = author_names(entry.work.creator)
            if not names:
                skipped += 1
                print(f"SKIP  {what}: no creator")
                continue
            twice = [name for name in names if len(people[owner].get(naming.key(name), [])) > 1]
            if twice:
                skipped += 1
                print(f"SKIP  {what}: several people are called {', '.join(twice)}")
                continue
            authors = []
            for name in names:
                found = people[owner].get(naming.key(name))
                if found:
                    authors.append(found[0])
                    continue
                honorific, first_name, middle_name, surname = naming.split_name(name) or ("", name, "", "")
                person = Person(owner_id=owner, honorific=honorific, first_name=first_name, middle_name=middle_name, surname=surname, description="", types=[])
                session.add(person)
                people[owner][naming.key(name)] = [person]
                authors.append(person)
                added += 1
            for person in authors:
                if book_authors[owner] not in person.types:
                    person.types.append(book_authors[owner])
            entry.authors = authors
            linked += 1
            print(f"ok    {what}: {' + '.join(names)}")
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
    print(f"{'would link' if args.dry_run else 'linked'} {linked} books ({added} new people), skipped {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
