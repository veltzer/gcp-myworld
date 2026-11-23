#!/usr/bin/env python

"""
Set the language of every title and name whose letters are not that
language's (src/myworld/languages.py): a book's title in Hebrew letters
that says English becomes Hebrew, and so do a work's other titles and a
person's names in other languages. The text itself is never changed, and
nothing is deleted: a row that cannot take the language of its letters
(the work or the person already has one in that language, or a person's
name in Latin letters, which is their English name) is listed and left for the
book-title-languages and people-name-languages checks. Safe to run any time;
a second run changes nothing.

  scripts/fix_languages.py            change them
  scripts/fix_languages.py --dry-run  only print what would change

The database is DATABASE_URL (default: the local sqlite file); for Cloud SQL
run it through the proxy: scripts/with_cloud_db.sh scripts/fix_languages.py.
"""

import argparse
import os
import sys
from pathlib import Path

# the myworld package is in src/, not installed (see scripts/check.py)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import select
from sqlalchemy.orm import Session

from myworld import languages
from myworld.models import DEFAULT_LOCALE, PersonName, Work, WorkTitle, make_engine

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)


def fix(session: Session) -> tuple[int, int]:
    """ Set the languages in the session (not committed), printing each; how many changed and how many were left. """
    changed = left = 0
    locales = languages.known(session)
    for work in session.scalars(select(Work).order_by(Work.id)):
        if not languages.fits(locales[work.title_locale], work.title):
            locale = languages.locale_of(locales, work.title)
            if locale and all(t.locale != locale for t in work.titles):
                changed += 1
                print(f"{work.kind} {work.id}: {work.title!r}: {work.title_locale} -> {locale}")
                work.title_locale = locale
            else:
                left += 1
                print(f"{work.kind} {work.id}: {work.title!r} is not {work.title_locale}: left (the work has another title in {locale or 'no language known here'})")
    for title in session.scalars(select(WorkTitle).order_by(WorkTitle.id)):
        if not languages.fits(locales[title.locale], title.title):
            locale = languages.locale_of(locales, title.title)
            work = title.work
            have = {work.title_locale, *(t.locale for t in work.titles)}
            if locale and locale not in have:
                changed += 1
                print(f"{work.kind} {work.id}, other title {title.title!r}: {title.locale} -> {locale}")
                title.locale = locale
            else:
                left += 1
                print(f"{work.kind} {work.id}, other title {title.title!r} is not {title.locale}: left (the work has a title in {locale or 'no language known here'})")
    for name in session.scalars(select(PersonName).order_by(PersonName.id)):
        if not languages.fits(locales[name.locale], name.name):
            locale = languages.locale_of(locales, name.name)
            taken = {n.locale for n in name.person.names}
            if locale and locale != DEFAULT_LOCALE and locale not in taken:
                changed += 1
                print(f"person {name.person_id}, name {name.name!r}: {name.locale} -> {locale}")
                name.locale = locale
            else:
                left += 1
                print(f"person {name.person_id}, name {name.name!r} is not {name.locale}: left")
    return changed, left


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="only print what would change")
    args = parser.parse_args()
    with Session(make_engine()) as session:
        changed, left = fix(session)
        if not args.dry_run:
            session.commit()
    print(f"{changed} languages {'would change' if args.dry_run else 'changed'}, {left} left to fix by hand")
    return 0


if __name__ == "__main__":
    sys.exit(main())
