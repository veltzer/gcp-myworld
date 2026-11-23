"""
The user's Goodreads shelves, for the importer that reads them. Goodreads
has had no API since 2020, and since 2026-11 it has neither its shelves'
RSS feeds nor a shelf page for anyone signed out (public profiles too: a
shelf sends them to its sign-in). What it still gives is the library
export: the CSV it makes of every book on every shelf (My Books, Import and
export, Export Library), which the user uploads with a run (parse_export).

A book of a shelf is a Book: its Goodreads id, title, author, ISBN, year,
cover (Open Library's, by ISBN: the export has none) and the day it was put
on the shelf.
"""

import csv
import dataclasses
import datetime as dt
import io
import re
from typing import Any

from myworld import podcasts

# a book's cover by its ISBN, for the export, which has no cover (404 when Open Library has none)
OPEN_LIBRARY_COVER = "https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false"


class GoodreadsError(Exception):
    """ Goodreads did not answer usefully, or what it gave is not what it should be. """


@dataclasses.dataclass(frozen=True)
class Book:
    goodreads_id: str
    title: str
    author: str
    isbn: str
    year: int | None
    image_url: str
    added: dt.date | None


def book_json(book: Book) -> dict[str, Any]:
    """ A book as a run's parameters keep it (JSON). """
    return {**dataclasses.asdict(book), "added": book.added.isoformat() if book.added else None}


def book_from_json(value: dict[str, Any]) -> Book:
    added = value.get("added")
    year = value.get("year")
    return Book(
        goodreads_id=str(value["goodreads_id"]), title=str(value["title"]), author=str(value.get("author") or ""),
        isbn=str(value.get("isbn") or ""), year=int(year) if year is not None else None, image_url=str(value.get("image_url") or ""),
        added=dt.date.fromisoformat(added) if added else None,
    )


def _clean(value: str) -> str:
    return " ".join(value.split())


def _year(value: str) -> int | None:
    """ The year of "1965" (or of any text with one); None for none. """
    found = re.findall(r"\b(\d{4})\b", value)
    return int(found[-1]) if found else None


def _day(value: str, fmt: str) -> dt.date:
    """ A day as written (no time, so no zone: read as UTC's); ValueError when it is not one. """
    return dt.datetime.strptime(value, fmt).replace(tzinfo=dt.UTC).date()


def _isbn(value: str) -> str:
    """ An ISBN as the export writes it, ="0441172717", or bare; "" for none. """
    return re.sub(r"[^0-9Xx]", "", value)[:20]


# ─── the library export ─────────────────────────────────────────────────────

# the export's columns this reads; a file without them is not an export
EXPORT_COLUMNS = ("Book Id", "Title", "Author", "Exclusive Shelf", "Date Added")


def parse_export(data: str, shelf: str) -> list[Book]:
    """
    The books of one shelf of a Goodreads library export (CSV), in the file's
    order; GoodreadsError when it is not one. The export has no covers: a
    book with an ISBN gets Open Library's.
    """
    reader = csv.DictReader(io.StringIO(data.removeprefix("﻿")))
    missing = [column for column in EXPORT_COLUMNS if column not in (reader.fieldnames or [])]
    if missing:
        raise GoodreadsError(
            "that is not a Goodreads library export (no " + ", ".join(missing) + " column): on goodreads.com open My Books, "
            "Import and export, Export Library, and upload the file it makes",
        )
    books = []
    for row in reader:
        shelves = [_clean(row.get("Exclusive Shelf") or "")] + [_clean(s) for s in (row.get("Bookshelves") or "").split(",")]
        if shelf not in shelves:
            continue
        isbn = _isbn(row.get("ISBN13") or "") or _isbn(row.get("ISBN") or "")
        added = _clean(row.get("Date Added") or "")
        try:
            day = _day(added, "%Y/%m/%d") if added else None
        except ValueError:
            day = None
        books.append(Book(
            goodreads_id=_clean(row.get("Book Id") or ""),
            title=_clean(row.get("Title") or ""),
            author=_clean(row.get("Author") or ""),
            isbn=isbn,
            year=_year(row.get("Original Publication Year") or "") or _year(row.get("Year Published") or ""),
            image_url=OPEN_LIBRARY_COVER.format(isbn=isbn) if isbn else "",
            added=day,
        ))
    return [book for book in books if book.goodreads_id and book.title]


def fetch_cover(url: str) -> tuple[bytes, str] | None:
    """ A book's cover and its type; None when there is none to be had (as a podcast's: podcasts.fetch_cover). """
    return podcasts.fetch_cover(url)
