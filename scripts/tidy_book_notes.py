#!/usr/bin/env python
"""
Take out of the notes of books what the book says elsewhere.

The import once wrote into a book's notes what it had no field for. Some of
it has a field now, and is said twice; this takes those sentences out:

- "Read in English (date unknown); Hebrew (2006-08-19, rated 8, very good)":
  the readings. Each one the book does not have yet becomes a reading of it
  (its language, its day, its rating and review), in the order the notes
  list them, and the sentence goes.
- "was named: Macbeth", when that is one of the book's titles, or one of
  them told a little differently: a part of it ("The Blind Watchmaker" of
  "The Blind Watchmaker: Why the Evidence..."), or it but for its spelling,
  its punctuation, a leading "The" or an "&" for an "and" ("Ulysees").
- "Written in French", when French is the language the book was first
  written in, or one it has a title, a reading or a copy in.

Only a sentence that is exactly one of these is touched: the rest of the
notes (the publisher, a name it once had that is not its title, the user's
own words) stay as they are. A book whose status, rating,
review, day or language would come out different is left alone and said.
It can run again: what is gone is not looked for.

    scripts/tidy_book_notes.py --dry-run
    scripts/with_cloud_db.sh scripts/tidy_book_notes.py
"""

import argparse
import datetime
import difflib
import os
import re
import sys
import unicodedata
from pathlib import Path

# the myworld package is in src/, not installed (see scripts/check.py)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)

from sqlalchemy import select
from sqlalchemy.orm import Session

from myworld import languages
from myworld.models import Read, UserWork, make_engine

READING = re.compile(r"(\w+) \((date unknown|\d{4}-\d{2}-\d{2})(?:, rated (\d+))?(?:, (.+))?\)")


def readings_said(sentence: str, codes: dict[str, str]) -> list[Read] | None:
    """
    The readings a sentence of the notes lists ("Read in Hebrew (date
    unknown); English (2004-08-13)"), each a Done reading; None when the
    sentence is not exactly such a list. codes is locale name (lowercase) -> code.
    """
    if not sentence.startswith("Read in "):
        return None
    reads = []
    for item in sentence.removeprefix("Read in ").rstrip(".").split("; "):
        found = READING.fullmatch(item)
        if not found or found.group(1).lower() not in codes:
            return None
        language, day, rating, review = found.groups()
        reads.append(Read(
            read_on=None if day == "date unknown" else datetime.date.fromisoformat(day),
            locale=codes[language.lower()], status="done", rating=int(rating) if rating else None, review=review or "",
        ))
    return reads


WRITTEN = re.compile(r"Written in (\w+)(?:\. |\.?$)")
# the name the book once had: the last thing its notes say, after a sentence or a clause
NAMED = re.compile(r"(?:^|; |\. )was named: (.+)$")
# how alike a name and a title are for one to be the other misspelt ("Silmarilion")
ALIKE = 0.85


def _plain(text: str) -> str:
    """ A title as it is compared: its letters and digits, lowercase and unaccented, "&" an "and", no leading article. """
    text = unicodedata.normalize("NFKD", text.casefold().replace("&", " and "))
    words = re.findall(r"\w+", "".join(char for char in text if not unicodedata.combining(char)).replace("'", "").replace("’", ""))
    return " ".join(words[1:] if words and words[0] in ("the", "a", "an") else words)


def same_title(name: str, titles: list[str]) -> bool:
    """
    Whether name is one of titles told a little differently: a part of it
    (words in a row, of two or more words or a whole part before or after
    its colon), or it or such a part but for the spelling.
    """
    said = _plain(name)
    if not said:
        return False
    for title in titles:
        whole = _plain(title)
        parts = [whole, *(_plain(part) for part in re.split(r":| or, |, or | - ", title))]
        if said in parts or (" " in said and f" {said} " in f" {whole} "):
            return True
        if any(difflib.SequenceMatcher(None, said, part).ratio() >= ALIKE for part in parts if part):
            return True
    return False


def without_said_twice(entry: UserWork, codes: dict[str, str]) -> str:
    """ The entry's notes without the language it was written in and the name it once had, where the book says them elsewhere. """
    notes = entry.notes
    work = entry.work
    written = WRITTEN.match(notes)
    if written:
        known = {work.original_locale, work.title_locale, *(t.locale for t in work.titles), *(read.locale for read in entry.reads), *entry.owned}
        if codes.get(written.group(1).lower()) in known - {None}:
            notes = notes[written.end():]
    named = NAMED.search(notes)
    if named and same_title(named.group(1).rstrip("."), [work.title, *(t.title for t in work.titles)]):
        notes = notes[:named.start()]
    return notes.strip()


def _goes_by(entry: UserWork) -> tuple[object, ...]:
    return (entry.status, entry.rating, entry.review, entry.locale, entry.finished_on, entry.started_on)


def tidy_entry(entry: UserWork, codes: dict[str, str]) -> tuple[int, str] | None:
    """
    The entry without what its notes say twice: how many readings it gained
    and its notes before; None when nothing changed.
    """
    before = entry.notes
    titles = {title.strip().casefold() for title in (entry.work.title, *(t.title for t in entry.work.titles))}
    kept = []
    said: list[Read] = []
    for sentence in before.split(". "):
        reads = readings_said(sentence.strip(), codes)
        if reads is not None:
            said += reads
        elif not (sentence.startswith("was named: ") and sentence.removeprefix("was named: ").rstrip(".").strip().casefold() in titles):
            kept.append(sentence)
    entry.notes = ". ".join(kept).strip()
    notes = without_said_twice(entry, codes)
    entry.notes = before
    if notes == before:
        return None
    # the readings in the order the notes list them: one the entry has already (same day and
    # language) is that one, with what it says; the others are new; then those the notes do not list
    have = list(entry.reads)
    ordered: list[Read] = []
    gained = 0
    for read in said:
        match = next((old for old in have if (old.read_on, old.locale) == (read.read_on, read.locale)), None)
        if match is not None:
            have.remove(match)
            read = Read(read_on=match.read_on, locale=match.locale, status=match.status, rating=match.rating, review=match.review, started_on=match.started_on)
        else:
            gained += 1
        ordered.append(read)
    if gained:
        went_by = _goes_by(entry)
        entry.reads = [*ordered, *(Read(read_on=old.read_on, locale=old.locale, status=old.status, rating=old.rating, review=old.review, started_on=old.started_on) for old in have)]
        if _goes_by(entry) != went_by:
            raise ValueError(f"{entry.work.title}: would go by {_goes_by(entry)} where it goes by {went_by}")
    entry.notes = notes
    return gained, before


def tidy(session: Session) -> tuple[int, int, int]:
    """ Tidy the notes of every book in the session (not committed), printing each: books changed, readings gained, books left. """
    codes = {locale.name.lower(): code for code, locale in languages.known(session).items()}
    changed = gained = left = 0
    for entry in session.scalars(select(UserWork)).all():
        try:
            with session.begin_nested():
                found = tidy_entry(entry, codes)
                session.flush()
        except ValueError as e:
            print(f"left alone: {e}")
            session.refresh(entry)
            left += 1
            continue
        if found is not None:
            print(f"{entry.work.title}: {found[0]} readings added; notes {found[1]!r} -> {entry.notes!r}")
            changed += 1
            gained += found[0]
    return changed, gained, left


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").strip().splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="say what would change, change nothing")
    args = parser.parse_args()
    with Session(make_engine()) as session:
        changed, gained, left = tidy(session)
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
    print(f"{changed} books {'would change' if args.dry_run else 'changed'}, {gained} readings added, {left} left alone")
    return 0


if __name__ == "__main__":
    sys.exit(main())
