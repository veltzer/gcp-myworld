"""
Checks of the audio books.
"""

from sqlalchemy.orm import Session

from myworld.checks.core import (
    Result,
    check,
    problem,
    rows,
    twice,
)
from myworld.models import AudioBook


@check("audio-book-authors", "Every audio book has an author", "audio books", "audio-books")
def check_audio_book_authors(session: Session) -> Result:
    """ Every audio book, of every account, says who wrote it. """
    books = rows(session, AudioBook)
    return Result(checked=len(books), problems=[problem(b, "has no author") for b in books if not b.authors.strip()])


@check("audio-book-covers", "Every audio book has a cover", "audio books", "audio-books")
def check_audio_book_covers(session: Session) -> Result:
    """ Every audio book, of every account, has a cover image. """
    books = rows(session, AudioBook)
    return Result(checked=len(books), problems=[problem(b, "has no cover") for b in books if b.image_id is None])


@check("audio-book-reviews", "Every finished audio book is rated and reviewed", "finished audio books", "audio-books")
def check_audio_book_reviews(session: Session) -> Result:
    """ Every finished audio book, of every account, has the user's own rating and review; one not finished need not. """
    finished = [b for b in rows(session, AudioBook) if b.finished]
    problems = []
    for book in finished:
        missing = [what for what, absent in (("rating", book.rating is None), ("review", not book.review.strip())) if absent]
        if missing:
            problems.append(problem(book, f"is finished but has no {' and no '.join(missing)}"))
    return Result(checked=len(finished), problems=problems)


@check("audio-book-duplicates", "No audio book is listed twice", "audio books", "audio-books")
def check_audio_book_duplicates(session: Session) -> Result:
    """ No account has two audio books of the same title and subtitle (ignoring case and spaces at the ends). """
    books = rows(session, AudioBook)
    return Result(checked=len(books), problems=twice(books, lambda b: (b.owner_id, b.name.strip().lower(), b.subtitle.strip().lower()), "title", "audio book"))
