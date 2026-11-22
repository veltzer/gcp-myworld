"""
The audio books' ids in catalogs, into the shared data (an admin's
importer): each audio book missing its Open Library work, its Goodreads
book or its Wikidata item is looked up in Open Library's search by its
title and its first author, and given what it lacks from the first result
that is the same book (the same title, its subtitle left out, and one of
its authors). Open Library's search says, of a work, the Goodreads books
and the Wikidata item its editions are linked to.

It only fills what is empty: an id typed in by hand, or found before, is
kept, so a run again looks up only the books still missing one. A book
Open Library does not find, or finds only as another book, is said in the
log and left as it is.
"""

import re
import time
import unicodedata
from typing import Any

import requests
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from myworld.importers.core import Importer, Report, register
from myworld.models import AudioBook, User

SEARCH_URL = "https://openlibrary.org/search.json"
SEARCH_FIELDS = "key,title,author_name,id_goodreads,id_wikidata"
HTTP_TIMEOUT = 30
# seconds between two requests: Open Library is a free service
PAUSE = 1.0
IDS = ("openlibrary_id", "goodreads_id", "wikidata_id")
# what a run's report calls each id it added
COUNTED = {"openlibrary_id": "Open Library ids added", "goodreads_id": "Goodreads ids added", "wikidata_id": "Wikidata ids added"}


class OpenLibraryError(Exception):
    """ Open Library could not be asked. """


def _missing(session: Session) -> list[AudioBook]:
    return list(session.scalars(select(AudioBook).where(or_(*(getattr(AudioBook, key) == "" for key in IDS))).order_by(AudioBook.name)))


def unavailable(session: Session, _owner: User) -> str:
    return "" if _missing(session) else "Every audio book has its Open Library, Goodreads and Wikidata ids"


def search(title: str, author: str) -> list[dict[str, Any]]:
    """ Open Library's search for title by author: its works, the best match first. """
    params = {"title": title, "fields": SEARCH_FIELDS, "limit": "10"}
    if author:
        params["author"] = author
    try:
        response = requests.get(SEARCH_URL, params=params, timeout=HTTP_TIMEOUT, headers={"User-Agent": "My World audio book ids"})
        if not response.ok:
            raise OpenLibraryError(f"Open Library answered {response.status_code}: {response.reason}")
        return list(response.json().get("docs", []))
    except (requests.RequestException, ValueError) as e:
        raise OpenLibraryError(f"Open Library could not be asked: {e}") from e


def _key(text: str) -> str:
    """ What two titles or names are compared by: letters and digits only, lowercase, without accents. """
    text = unicodedata.normalize("NFKD", text)
    return re.sub(r"[^a-z0-9]+", "", "".join(c for c in text if not unicodedata.combining(c)).lower())


def _title(book: AudioBook) -> str:
    """ The title Open Library knows a book by: without a subtitle the title itself says after a colon. """
    return book.name.split(":")[0].strip()


def same_book(book: AudioBook, doc: dict[str, Any]) -> bool:
    """ Whether doc (a work of Open Library's search) is book: the same title, and one of its authors' surnames among the work's authors. """
    if _key(str(doc.get("title", "")).split(":")[0]) != _key(_title(book)):
        return False
    surnames = {_key(name.split()[-1]) for name in book.authors.split(",") if name.strip() and " - " not in name}
    names = [_key(name) for name in doc.get("author_name", [])]
    return not surnames or any(surname and surname in name for surname in surnames for name in names)


def ids_of(doc: dict[str, Any]) -> dict[str, str]:
    """ The ids a work of the search says: its own key, the first Goodreads book and Wikidata item of its editions. """
    goodreads = [str(g) for g in doc.get("id_goodreads", []) if str(g).isdigit()]
    wikidata = [str(w) for w in doc.get("id_wikidata", []) if re.fullmatch(r"Q\d+", str(w))]
    return {
        "openlibrary_id": str(doc.get("key", "")).removeprefix("/works/"),
        "goodreads_id": goodreads[0] if goodreads else "",
        "wikidata_id": wikidata[0] if wikidata else "",
    }


def fill(book: AudioBook, found: dict[str, str]) -> list[str]:
    """ book given the ids of found it has none of; the ids given. """
    given = [key for key in IDS if not getattr(book, key) and found.get(key)]
    for key in given:
        setattr(book, key, found[key])
    return given


def run(session: Session, owner: User, params: dict[str, Any], report: Report) -> None:
    del owner, params
    for index, book in enumerate(_missing(session)):
        if index:
            time.sleep(PAUSE)
        author = book.authors.split(",")[0].strip()
        try:
            docs = search(_title(book), author)
        except OpenLibraryError as e:
            report.say(f"{book.name}: {e}")
            report.count("audio books not looked up")
            continue
        doc = next((d for d in docs if same_book(book, d)), None)
        if doc is None:
            report.say(f"{book.name}: Open Library does not have it")
            report.count("audio books not found")
            continue
        given = fill(book, ids_of(doc))
        report.say(f"{book.name}: {', '.join(given) if given else 'nothing new'}")
        for key in given:
            report.count(COUNTED[key])
    session.flush()


IMPORTER = register(Importer(
    name="audio-book-ids",
    title="Audio book ids",
    description=(
        "Looks up the audio books missing an id in Open Library's search, by title and author, and gives each what it lacks: "
        "its Open Library work, a Goodreads book of it and its Wikidata item. Only fills what is empty: safe to run again."
    ),
    dataset="audio-books",
    shared=True,
    params=(),
    run=run,
    unavailable=unavailable,
))
