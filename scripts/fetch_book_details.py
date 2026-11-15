#!/usr/bin/env python

"""
Fill in every book's year it came out, its ISBN and its Open Library work,
where the book has none of them yet (a work is shared by every account that
has it, so nothing it has is ever replaced).

  scripts/fetch_book_details.py            fill them in
  scripts/fetch_book_details.py --dry-run  only print what it would take

The year is the one Goodreads says the book was first published in (its page
of the edition the book points to), else Open Library's first publication,
else the year Simania's edition came out. The ISBN is that of the edition
Goodreads or Simania points to. The Open Library work is the one that has
that Goodreads edition, else that ISBN, else the first of a search for the
title and the author whose title is the book's.

The database is DATABASE_URL (default: the local sqlite file); for Cloud SQL
run it through the proxy: scripts/with_cloud_db.sh scripts/fetch_book_details.py.
"""

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# the myworld package is in src/, not installed (see scripts/check.py)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from myworld.models import Work, make_engine

USER_AGENT = "myworld-books/1.0 (+https://github.com/veltzer/gcp-myworld)"
# seconds between two requests to one site: these are free services
PAUSE = 1.0
# "First published February 17, 1884", "First published 1937", "First published 380 BC"
FIRST_PUBLISHED = re.compile(r"First published (?:[A-Z][a-z]+ (?:\d{1,2}, )?)?(\d{1,4})( BC)?")
# this edition's own date, milliseconds from 1970 (the first in the page is the edition's)
PUBLICATION_TIME = re.compile(r'"publicationTime":(-?\d+)')
GOODREADS_ISBN = (re.compile(r'"isbn13":"(\d{13})"'), re.compile(r'"isbn":"(\d{9}[\dX])"'))
SIMANIA_YEAR = re.compile(r'\\?"datePublished\\?":\s*\\?"(\d{4})')
SIMANIA_ISBN = re.compile(r'\\?"isbn\\?":\s*\\?"([\dX-]{10,17})\\?"')
OPENLIBRARY_FIELDS = "key,title,first_publish_year,edition_count"
last_request: dict[str, float] = {}


def get(url: str) -> str | None:
    """ The page at url, waiting PAUSE since the last request to its site; None when it is not there. """
    site = urllib.parse.urlsplit(url).netloc
    wait = last_request.get(site, 0) + PAUSE - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=30) as response:
                body: str = response.read().decode("utf-8", errors="replace")
                return body
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if attempt == 2 or e.code not in (429, 500, 502, 503, 504):
                raise
            time.sleep(5 * (attempt + 1))
        finally:
            last_request[site] = time.monotonic()
    return None


def goodreads(goodreads_id: str) -> dict[str, Any]:
    """ The year first published and the ISBN, from the Goodreads page of an edition. """
    page = get(f"https://www.goodreads.com/book/show/{urllib.parse.quote(goodreads_id)}")
    if page is None:
        return {}
    found: dict[str, Any] = {}
    first = FIRST_PUBLISHED.search(html.unescape(page))
    if first:
        found["year"] = -int(first.group(1)) if first.group(2) else int(first.group(1))
    else:
        published = PUBLICATION_TIME.search(page)
        if published:
            found["year"] = time.gmtime(int(published.group(1)) / 1000).tm_year
    for pattern in GOODREADS_ISBN:
        isbn = pattern.search(page)
        if isbn:
            found["isbn"] = isbn.group(1)
            break
    return found


def simania(simania_id: str) -> dict[str, Any]:
    """ The year its edition came out and its ISBN, from the Simania page of a book. """
    page = get(f"https://simania.co.il/bookdetails.php?item_id={urllib.parse.quote(simania_id)}")
    if page is None:
        return {}
    found: dict[str, Any] = {}
    year = SIMANIA_YEAR.search(page)
    if year:
        found["year"] = int(year.group(1))
    isbn = SIMANIA_ISBN.search(page)
    if isbn and isbn.group(1).replace("-", "").strip("0"):
        found["isbn"] = isbn.group(1).replace("-", "")
    return found


def openlibrary_search(**query: str) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({**query, "fields": OPENLIBRARY_FIELDS, "limit": 5})
    page = get(f"https://openlibrary.org/search.json?{params}")
    docs: list[dict[str, Any]] = json.loads(page)["docs"] if page else []
    return docs


def plain(title: str) -> str:
    """ A title to compare: its main part (before a colon), letters and digits only, any case. """
    return re.sub(r"\W+", " ", title.split(":")[0]).casefold().strip()


def openlibrary(work: Work, isbn: str) -> dict[str, Any] | None:
    """ The Open Library work of a book: by its Goodreads edition, else its ISBN, else its title and author. """
    wanted = plain(work.title)
    docs = openlibrary_search(q=f"id_goodreads:{work.goodreads_id}") if work.goodreads_id else []
    if not docs and isbn:
        docs = openlibrary_search(q=f"isbn:{isbn}")
    # One Goodreads edition can be listed under several works: a story of a collection, a translation
    # made a work of its own, a reprint someone entered again. The book is the work with most editions,
    # named in the original language as often as not ("Žert"), one of its own title counting twice; a
    # search by title and author adds those of its title when none of the works found has it.
    def matches(doc: dict[str, Any]) -> bool:
        return plain(doc.get("title", "")) == wanted

    if not any(matches(d) for d in docs) and work.creator:
        docs += [d for d in openlibrary_search(title=work.title, author=work.creator.split(",")[0]) if matches(d)]
    if not docs:
        return None
    return max(docs, key=lambda d: d.get("edition_count", 0) * (2 if matches(d) else 1))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1] if __doc__ else None)
    parser.add_argument("--dry-run", action="store_true", help="only print what it would take")
    args = parser.parse_args()
    engine = make_engine()
    print(engine.url.render_as_string(hide_password=True))
    counts = {"years": 0, "isbns": 0, "open library works": 0, "books with no year found": 0}
    with Session(engine) as session:
        works = session.scalars(select(Work).where(
            Work.kind == "book", or_(Work.year.is_(None), Work.isbn == "", Work.openlibrary_id == ""),
        ).order_by(Work.id)).all()
        for work in works:
            found = goodreads(work.goodreads_id) if work.goodreads_id else {}
            edition = simania(work.simania_id) if work.simania_id and not ("year" in found and "isbn" in found) else {}
            isbn = work.isbn or found.get("isbn") or edition.get("isbn", "")
            library = openlibrary(work, isbn) if not work.openlibrary_id or (work.year is None and "year" not in found) else None
            year = found.get("year") or (library or {}).get("first_publish_year") or edition.get("year")
            source = "Goodreads" if found.get("year") else "Open Library" if (library or {}).get("first_publish_year") else "Simania" if year else ""
            took = []
            if work.year is None and year is not None:
                work.year = year
                counts["years"] += 1
                took.append(f"year {year} ({source})")
            elif work.year is None:
                counts["books with no year found"] += 1
            if not work.isbn and isbn:
                work.isbn = isbn
                counts["isbns"] += 1
                took.append(f"ISBN {isbn}")
            if not work.openlibrary_id and library:
                work.openlibrary_id = library["key"].removeprefix("/works/")
                counts["open library works"] += 1
                took.append(f"Open Library {work.openlibrary_id} ({library.get('title', '')})")
            print(f"{'ok  ' if took else 'MISS'}  book {work.id}, {work.title}: {', '.join(took) or 'nothing found'}", flush=True)
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
    print(", ".join(f"{count} {what}" for what, count in counts.items()) + (" (dry run: rolled back)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
