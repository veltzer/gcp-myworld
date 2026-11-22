"""
Checks of the audio books and their versions (shared), and of the audio
books and versions each account heard.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from myworld.checks.core import (
    Result,
    check,
    problem,
    rows,
    twice,
)
from myworld.models import AudioBook, AudioBookHeard, AudioBookListen, AudioBookVersion


@check("audio-book-authors", "Every audio book has an author", "audio books", "audio-books")
def check_audio_book_authors(session: Session) -> Result:
    """ Every audio book says who wrote it. """
    books = rows(session, AudioBook)
    return Result(checked=len(books), problems=[problem(b, "has no author") for b in books if not b.authors.strip()])


@check("audio-book-covers", "Every audio book has a cover", "audio books", "audio-books")
def check_audio_book_covers(session: Session) -> Result:
    """ Every audio book has a cover image. """
    books = rows(session, AudioBook)
    return Result(checked=len(books), problems=[problem(b, "has no cover") for b in books if b.image_id is None])


@check("audio-book-duplicates", "No audio book is listed twice", "audio books", "audio-books")
def check_audio_book_duplicates(session: Session) -> Result:
    """ No two audio books have the same title and subtitle (ignoring case and spaces at the ends): one book's versions belong together. """
    books = rows(session, AudioBook)
    return Result(checked=len(books), problems=twice(books, lambda b: (b.name.strip().lower(), b.subtitle.strip().lower()), "title", "audio book"))


@check("audio-book-version-asins", "Every Audible version has its ASIN", "Audible versions", "audio-book-versions")
def check_audio_book_version_asins(session: Session) -> Result:
    """ Every Audible version has its ASIN: the Audible library importer finds it again by it, and links its page. """
    found = session.scalars(select(AudioBookVersion).join(AudioBook).where(AudioBookVersion.kind == "audible").order_by(AudioBook.name, AudioBookVersion.id))
    audible = list(found)
    return Result(checked=len(audible), problems=[problem(v, "has no ASIN") for v in audible if not v.asin])


def _finished_heard(session: Session) -> list[AudioBookHeard]:
    """ Every account's books in Your audio books that it finished a version of. """
    finished = {(owner, book) for owner, book in session.execute(
        select(AudioBookListen.owner_id, AudioBookVersion.book_id).join(AudioBookVersion).where(AudioBookListen.finished),
    )}
    found = session.scalars(select(AudioBookHeard).join(AudioBook).order_by(AudioBookHeard.owner_id, AudioBook.name, AudioBookHeard.id))
    return [row for row in found if (row.owner_id, row.book_id) in finished]


@check("audio-book-reviews", "Every finished audio book is rated and reviewed", "finished audio books", "audio-books-heard")
def check_audio_book_reviews(session: Session) -> Result:
    """ Every book in Your audio books, of every account, that a version of was finished has the user's own rating and review. """
    finished = _finished_heard(session)
    problems = []
    for row in finished:
        missing = [what for what, absent in (("rating", row.rating is None), ("review", not row.review.strip())) if absent]
        if missing:
            problems.append(problem(row, f"is finished but has no {' and no '.join(missing)}"))
    return Result(checked=len(finished), problems=problems)


@check("audio-book-listen-progress", "Every audio book not finished says how far it got", "audio book listens not finished", "audio-book-listens")
def check_audio_book_listen_progress(session: Session) -> Result:
    """ Every listen, of every account, that is not finished says how far it got: how much of it was heard (Audible says), or in words ("did part03"). """
    found = session.scalars(
        select(AudioBookListen).join(AudioBookVersion).join(AudioBook).where(~AudioBookListen.finished)
        .order_by(AudioBookListen.owner_id, AudioBook.name, AudioBookListen.id),
    )
    going = list(found)
    return Result(checked=len(going), problems=[
        problem(listen, "says neither how much was heard nor how far it got") for listen in going if listen.percent_heard is None and not listen.progress.strip()
    ])
