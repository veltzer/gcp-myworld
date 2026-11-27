"""
Checks of the library: the books.
"""

from typing import TYPE_CHECKING

from sqlalchemy import select

from myworld import languages, notes
from myworld.checks.core import (
    Problem,
    Result,
    check,
    entries_of,
    problem,
    twice,
)
from myworld.models import (
    DEFAULT_LOCALE,
    KINDS,
    Read,
    UserWork,
    library_entry_authors,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

# what having done a library kind is called: a book read
DONE_VERBS = {"book": "read"}


def _library_checks(kind: str) -> None:
    """ The checks every library kind has: a cover, a rating once done, no entry twice. """
    name, plural, creator = KINDS[kind]
    noun, verb = plural.lower(), DONE_VERBS[kind]
    one = name.lower()

    def covers(session: Session) -> Result:
        entries = entries_of(session, kind)
        return Result(checked=len(entries), problems=[problem(e, "has no cover") for e in entries if not e.cover_ids])

    def ratings(session: Session) -> Result:
        done = [e for e in entries_of(session, kind) if e.status == "done"]
        return Result(checked=len(done), problems=[problem(e, f"is {verb} but has no rating") for e in done if e.rating is None])

    def duplicates(session: Session) -> Result:
        entries = entries_of(session, kind)
        def key(entry: UserWork) -> tuple[int, str, str]:
            return entry.owner_id, entry.work.title.strip().lower(), entry.work.creator.strip().lower()
        return Result(checked=len(entries), problems=twice(entries, key, f"title and {creator.lower()}", one))

    covers.__doc__ = f"Every {one} in a library, of every account, has at least one cover image (it may have several)."
    ratings.__doc__ = f"Every {one} an account has {verb} (Done), of every account, has a rating; one not {verb} yet need not."
    duplicates.__doc__ = f"No account has two {noun} of the same title and {creator.lower()} (ignoring case and spaces at the ends), as two works."
    check(f"{kind}-covers", f"Every {one} has at least one cover", noun, kind)(covers)
    check(f"{kind}-ratings", f"Every {one} {verb} is rated", f"{noun} {verb}", kind)(ratings)
    check(f"{kind}-duplicates", f"No {one} is listed twice", noun, kind)(duplicates)


for _kind in KINDS:
    _library_checks(_kind)


@check("book-links", "Every book links to its page", "books", "book")
def check_book_links(session: Session) -> Result:
    """ Every book in a library, of every account, has a Goodreads or a Simania id, so its card links to its page. """
    books = entries_of(session, "book")
    problems = [
        problem(b, "has neither a Goodreads nor a Simania id")
        for b in books
        if not b.work.goodreads_id.strip() and not b.work.simania_id.strip()
    ]
    return Result(checked=len(books), problems=problems)


@check("book-authors", "Every book has an author", "books", "book")
def check_book_authors(session: Session) -> Result:
    """ Every book in a library, of every account, has an author: one of the account's people (a Book Author), linked to it. """
    books = entries_of(session, "book")
    written = set(session.execute(select(library_entry_authors.c.owner_id, library_entry_authors.c.work_id)))
    return Result(checked=len(books), problems=[problem(b, "has no author") for b in books if (b.owner_id, b.work_id) not in written])


@check("book-years", "Every book has the year it came out", "books", "book")
def check_book_years(session: Session) -> Result:
    """ Every book in a library, of every account, has the year it came out. """
    books = entries_of(session, "book")
    return Result(checked=len(books), problems=[problem(b, "has no year it came out") for b in books if b.work.year is None])


@check("book-original-languages", "Every book has the language it was written in", "books", "book")
def check_book_original_languages(session: Session) -> Result:
    """ Every book in a library, of every account, says the language it was first written in. """
    books = entries_of(session, "book")
    return Result(checked=len(books), problems=[problem(b, "has no original language") for b in books if not b.work.original_locale])


@check("book-original-titles", "Every book has a title in the language it was written in", "books with an original language", "book")
def check_book_original_titles(session: Session) -> Result:
    """
    Every book in a library, of every account, that says the language it was
    first written in has a title in that language: the title it was given by
    its author, whatever language it was read in.
    """
    books = [(b, b.work.original_locale) for b in entries_of(session, "book") if b.work.original_locale]
    known = languages.known(session)
    problems = [
        problem(b, f"was written in {known[original].name} but has no title in it")
        for b, original in books
        if original not in {b.work.title_locale, *(title.locale for title in b.work.titles)}
    ]
    return Result(checked=len(books), problems=problems)


@check("book-reads", "Every book has a reading", "books", "book")
def check_book_reads(session: Session) -> Result:
    """ Every book in a library, of every account, has at least one reading: where its status, rating and review are, with its day and its language. """
    books = entries_of(session, "book")
    return Result(checked=len(books), problems=[problem(b, "has no reading") for b in books if not b.reads])


def _readings_finished(session: Session) -> list[tuple[UserWork, Read]]:
    """ The readings of books that were finished (Done), each with its book. """
    return [(b, read) for b in entries_of(session, "book") for read in b.reads if read.status == "done"]


@check("book-languages", "Every finished reading of a book says the language it was read in", "readings", "book")
def check_book_languages(session: Session) -> Result:
    """ Every finished (Done) reading of a book, of every account, says the language it was read in. """
    reads = _readings_finished(session)
    return Result(checked=len(reads), problems=[problem(b, "has a reading that does not say the language it was read in") for b, read in reads if not read.locale])


@check("book-read-dates", "Every finished reading of a book has its date", "readings", "book")
def check_book_read_dates(session: Session) -> Result:
    """ Every finished (Done) reading of a book, of every account, has the day it was finished. """
    reads = _readings_finished(session)
    return Result(checked=len(reads), problems=[problem(b, "has a reading with no date") for b, read in reads if read.read_on is None])


@check("book-titles", "Every book has a title", "books", "book")
def check_book_titles(session: Session) -> Result:
    """ Every book in a library, of every account, has at least one title: its main title is not empty. """
    books = entries_of(session, "book")
    return Result(checked=len(books), problems=[problem(b, "has no title") for b in books if not b.work.title.strip()])


@check("book-english-titles", "Every book with a Hebrew title has an English one", "books with a Hebrew title", "book")
def check_book_english_titles(session: Session) -> Result:
    """
    Every book in a library, of every account, that has a title in Hebrew
    (its main title or one in another language) has a title in English as
    well: the published one, or a translation of the Hebrew where the book
    never came out in English.
    """
    hebrew = []
    for book in entries_of(session, "book"):
        locales = {book.work.title_locale, *(t.locale for t in book.work.titles)}
        if "he" in locales:
            hebrew.append((book, DEFAULT_LOCALE in locales))
    return Result(checked=len(hebrew), problems=[problem(b, "has a Hebrew title but no English one") for b, english in hebrew if not english])


@check("book-title-languages", "Every title is in the language it says", "titles", "book")
def check_book_title_languages(session: Session) -> Result:
    """
    Every title of a book in a library, of every account, the main one and
    those in other languages, is written in the script of the language it
    says: a title in Hebrew letters is not English. scripts/fix_languages.py
    sets the language its letters say.
    """
    locales = languages.known(session)
    problems: list[Problem] = []
    checked = 0
    for book in entries_of(session, "book"):
        work = book.work
        for locale, title in [(work.title_locale, work.title), *((t.locale, t.title) for t in work.titles)]:
            checked += 1
            if not languages.fits(locales[locale], title):
                problems.append(problem(book, f"the title {title!r} says {locales[locale].name} but is written in {languages.script_of(title)} letters"))
    return Result(checked=checked, problems=problems)


@check("book-notes", "No book note repeats the book", "books", "book")
def check_book_notes(session: Session) -> Result:
    """
    No note of a book, of any account, says what the book says elsewhere:
    the language it was written in, or a name it once had that is its title
    told a little differently (scripts/tidy_book_notes.py takes these out).
    """
    books = entries_of(session, "book")
    codes = {locale.name.lower(): code for code, locale in languages.known(session).items()}
    problems = [problem(entry, "has a note that repeats what the book says elsewhere") for entry in books if notes.without_said_twice(entry, codes) != entry.notes.strip()]
    return Result(checked=len(books), problems=problems)


@check("book-translations", "Every book was read in the language it was written in", "books read", "book")
def check_book_translations(session: Session) -> Result:
    """
    Every book with a finished reading that says its language, of every
    account, was read at least once in the language it was first written
    in. A book read only in translation is no mistake: this lists them, and
    is turned off by whoever does not want the list.
    """
    names_of = {code: locale.name for code, locale in languages.known(session).items()}
    books = []
    problems = []
    for entry in entries_of(session, "book"):
        read_in = list(dict.fromkeys(read.locale for read in entry.reads if read.status == "done" and read.locale))
        original = entry.work.original_locale
        if not read_in or not original:
            continue
        books.append(entry)
        if original not in read_in:
            problems.append(problem(
                entry, f"was read only in translation: written in {names_of.get(original, original)}, read in {', '.join(names_of.get(code, code) for code in read_in)}",
            ))
    return Result(checked=len(books), problems=problems)
