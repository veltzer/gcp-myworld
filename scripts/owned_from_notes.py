#!/usr/bin/env python
"""
Derive the languages a book is owned in from its notes.

The import once wrote what it knew of ownership into a book's notes, as a
sentence of its own: "Owned in Hebrew", "Owned in English and Hebrew". A
book now has the languages it is owned in as a list (library_ownings), so
that sentence is taken out of the notes and its languages are added to the
list. Only a sentence that is exactly that, naming languages of the locales
table, is touched; the rest of the notes stay as they are. It can run again:
a book whose notes no longer say it is left alone.

    scripts/owned_from_notes.py --dry-run
    scripts/with_cloud_db.sh scripts/owned_from_notes.py
"""

import argparse
import os
import re
import sys
from pathlib import Path

# the myworld package is in src/, not installed (see scripts/check.py)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import select
from sqlalchemy.orm import Session

from myworld import languages
from myworld.models import UserWork, make_engine

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)

OWNED = re.compile(r"Owned in (.+)", re.IGNORECASE)


def split_notes(notes: str, codes: dict[str, str]) -> tuple[list[str], str]:
    """
    The languages (locale codes) the notes say the book is owned in, and the
    notes without the sentences that said so. codes is locale name
    (lowercase) -> code; a sentence naming anything else stays.
    """
    owned: list[str] = []
    kept = []
    for sentence in notes.split(". "):
        found = OWNED.fullmatch(sentence.strip().rstrip("."))
        names = [name.strip().lower() for name in re.split(r",| and ", found.group(1))] if found else []
        if names and all(name in codes for name in names):
            owned += [codes[name] for name in names]
        else:
            kept.append(sentence)
    return list(dict.fromkeys(owned)), ". ".join(kept).strip()


def derive(session: Session) -> int:
    """ Move what the notes of every book say of ownership into its list; the number of books changed. """
    codes = {locale.name.lower(): code for code, locale in languages.known(session).items()}
    moved = 0
    for entry in session.scalars(select(UserWork)).all():
        owned, notes = split_notes(entry.notes, codes)
        if owned:
            print(f"{entry.work.title}: owned in {', '.join(owned)}; notes {entry.notes!r} -> {notes!r}")
            entry.owned = [*entry.owned, *owned]
            entry.notes = notes
            moved += 1
    return moved


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").strip().splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="say what would change, change nothing")
    args = parser.parse_args()
    with Session(make_engine()) as session:
        moved = derive(session)
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
    print(f"{moved} books{' would be' if args.dry_run else ''} changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
