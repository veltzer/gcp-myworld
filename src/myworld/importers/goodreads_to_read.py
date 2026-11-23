"""
The books on the user's Goodreads to-read shelf, as books they want to read:
each one their library does not have yet is added as a book, wanted (a
reading of the status Want to), with its author, year, ISBN, Goodreads id
and cover, and a note of when it went on the shelf (and its series, which
Goodreads writes into the title: "Dune (Dune, #1)" is the book Dune, of
the series Dune, #1).

A book is found in the library by its Goodreads id, its ISBN, or its title
(with or without that series) and author; one there is left as it is, but
for its Goodreads id and ISBN, given when it has none. Its author is the
user's person of that name, or a new person, a Book Author; a name two of
the user's people have is left as the book's author text only. It only
ever adds: a book taken off the shelf since stays.
"""

import hashlib
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from myworld import goodreads, languages
from myworld import names as naming
from myworld.importers.core import Importer, ImporterError, Report, register
from myworld.models import DEFAULT_LOCALE, Image, Person, PersonType, Read, User, UserWork, Work
from myworld.pictures import IMAGE_EXTENSIONS

SHELF = "to-read"
# "Dune (Dune, #1)": the series Goodreads adds to a title
SERIES = re.compile(r"^(?P<title>.+?)\s*\((?P<series>[^()]+?,?\s*#[\d.]+(?:-[\d.]+)?)\)$")
BOOK_AUTHOR = "Book Author"


def unavailable(session: Session, owner: User) -> str:
    return "" if goodreads.connection(session, owner) is not None else "Connect Goodreads first"


def split_series(title: str) -> tuple[str, str]:
    """ A Goodreads title as the book's title and its series ("Dune", "Dune, #1"); the series is "" when it says none. """
    found = SERIES.match(title)
    return (found.group("title"), found.group("series")) if found else (title, "")


def _key(text: str) -> str:
    return " ".join(text.casefold().split())


class _Library:
    """ owner's books, found by Goodreads id, ISBN, title and author, and as the library keeps them (title, author, year). """

    def __init__(self, session: Session, owner: User) -> None:
        self.session, self.owner = session, owner
        self.works = list(session.scalars(select(Work).where(Work.owner_id == owner.id, Work.kind == "book")))
        self.entries = set(session.scalars(select(UserWork.work_id).where(UserWork.owner_id == owner.id)))

    def find(self, book: goodreads.Book, title: str) -> Work | None:
        titles = {_key(book.title), _key(title)}
        for work in self.works:
            if (book.goodreads_id and work.goodreads_id == book.goodreads_id) or (book.isbn and work.isbn == book.isbn):
                return work
        for work in self.works:
            if _key(work.title) in titles and _key(book.author) in _key(work.creator):
                return work
        return None

    def same(self, title: str, author: str, year: int | None) -> Work | None:
        """ The work the library's identity (title, author, year) says is this one. """
        return next((w for w in self.works if (w.title, w.creator, w.year) == (title, author, year)), None)


class _Authors:
    """ owner's people by name: the one of a name, a new one (a Book Author) when none, nobody when two share it. """

    def __init__(self, session: Session, owner: User) -> None:
        self.session, self.owner = session, owner
        self.by_name: dict[str, list[Person]] = {}
        for person in session.scalars(select(Person).where(Person.owner_id == owner.id)):
            self.by_name.setdefault(naming.key(person.name), []).append(person)
        self.book_author = session.scalars(select(PersonType).where(PersonType.owner_id == owner.id, PersonType.name == BOOK_AUTHOR)).first()
        self.added = 0

    def of(self, name: str) -> Person | None:
        if not name:
            return None
        found = self.by_name.get(naming.key(name), [])
        if len(found) > 1:
            return None
        if not found:
            honorific, first, middle, surname = naming.split_name(name) or ("", name, "", "")
            found = [Person(owner_id=self.owner.id, honorific=honorific, first_name=first, middle_name=middle, surname=surname, description="")]
            self.session.add(found[0])
            self.by_name[naming.key(name)] = found
            self.added += 1
        person = found[0]
        if self.book_author is not None and self.book_author not in person.types:
            person.types.append(self.book_author)
        return person


def _cover(session: Session, owner: User, book: goodreads.Book) -> Image | None:
    if not book.image_url:
        return None
    fetched = goodreads.fetch_cover(book.image_url)
    if fetched is None:
        return None
    data, content_type = fetched
    image = Image(
        owner_id=owner.id, filename=f"book-goodreads-{book.goodreads_id}{IMAGE_EXTENSIONS[content_type]}",
        content_type=content_type, sha256=hashlib.sha256(data).hexdigest(), data=data,
    )
    session.add(image)
    return image


def _notes(book: goodreads.Book, series: str) -> str:
    lines = [f"Series: {series}"] if series else []
    if book.added is not None:
        lines.append(f"On my Goodreads to-read shelf since {book.added.isoformat()}")
    return "\n".join(lines)


def store_wanted(session: Session, owner: User, books: list[goodreads.Book], report: Report) -> None:
    """ Add the books owner's library does not have as wanted; give the ones it has their Goodreads id and ISBN when they have none. """
    library, authors = _Library(session, owner), _Authors(session, owner)
    locales = languages.known(session)
    for book in books:
        title, series = split_series(book.title)
        work = library.find(book, title) or library.same(title, book.author, book.year)
        if work is not None and work.id in library.entries:
            given = [name for name, value in (("goodreads_id", book.goodreads_id), ("isbn", book.isbn)) if value and not getattr(work, name)]
            for name in given:
                setattr(work, name, getattr(book, name))
            if given:
                report.count("books there given their Goodreads id or ISBN")
            report.count("books in your library already")
            continue
        if work is None:
            work = Work(
                owner_id=owner.id, kind="book", title=title[:500], creator=book.author[:500], year=book.year, isbn=book.isbn,
                goodreads_id=book.goodreads_id, title_locale=languages.locale_of(locales, title) or DEFAULT_LOCALE,
            )
            session.add(work)
            library.works.append(work)
            session.flush()
        entry = UserWork(owner_id=owner.id, work_id=work.id, work=work, notes=_notes(book, series))
        session.add(entry)
        author = authors.of(book.author)
        if author is not None:
            entry.authors = [author]
        entry.reads.append(Read(status="wishlist", review=""))
        cover = _cover(session, owner, book)
        if cover is not None:
            session.flush()
            entry.image_id = cover.id
            report.count("covers added")
        library.entries.add(work.id)
        report.count("books added, wanted")
        report.say(f"+ {title}{f' ({book.author})' if book.author else ''}")
        session.flush()
    if authors.added:
        report.count("authors added to People", authors.added)


def run(session: Session, owner: User, params: dict[str, Any], report: Report) -> None:
    del params
    try:
        user, key = goodreads.kept_feed(session, owner)
        books = goodreads.shelf_books(user, key, SHELF)
    except goodreads.GoodreadsError as e:
        raise ImporterError(str(e)) from e
    report.say(f"The to-read shelf has {len(books)} books")
    store_wanted(session, owner, books, report)


IMPORTER = register(Importer(
    name="goodreads-to-read",
    title="Goodreads: books to read",
    description=(
        "The books on your Goodreads to-read shelf, as books you want to read: each one your library does not have yet is "
        "added, with its author, year, ISBN, Goodreads id and cover, and a note of when it went on the shelf. A book you "
        "have is left as it is (it only gets its Goodreads id and ISBN, when it has none). Safe to run again: it only ever adds."
    ),
    dataset="book",
    params=(),
    run=run,
    unavailable=unavailable,
))
