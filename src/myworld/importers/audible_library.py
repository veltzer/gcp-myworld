"""
The books of the user's Audible library, as their listens of the books'
Audible versions. Audio books are shared: a book My World does not have
yet is added (with its cover, and its Audible version), and so is the
Audible version of a book it has; one there already is given what Audible
says of it now (its rating there, ...), and the user's listen what the
library says of their listening (finished, how much was heard). What
anyone wrote (a rating, a review, a title) stays. It only ever adds: a
book gone from the library since stays.
"""

from typing import TYPE_CHECKING, Any

from myworld import audible
from myworld.importers.core import Importer, ImporterError, Report, register

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from myworld.models import User

# what store_library counts -> what the run's report calls it
COUNTS = {
    "audio books added": "audio books added",
    "audio books refreshed": "audio books given Audible's details",
    "images": "covers added",
}


def unavailable(session: Session, owner: User) -> str:
    return "" if audible.connection(session, owner) is not None else "Connect Audible first"


def run(session: Session, owner: User, params: dict[str, Any], report: Report) -> None:
    del params
    try:
        items = audible.library(audible.client_for(session, owner))
        report.say(f"The library has {len(items)} books")
        audible.check_items(items, "the library")
        counts = audible.store_library(session, owner, items, lambda _asin, url: audible.fetch_cover(url), report.say)
    except audible.AudibleError as e:
        raise ImporterError(str(e)) from e
    for key, what in COUNTS.items():
        if counts[key]:
            report.count(what, counts[key])


IMPORTER = register(Importer(
    name="audible-library",
    title="Audible library",
    description=(
        "The books of your Audible library, as your listens of their Audible versions. A book My World does not have yet is "
        "added to the shared Audio books, with its cover; the ones there get Audible's details as they are now (the rating "
        "there), your listens what the library says (finished, how much you heard), and everyone's ratings, reviews and edits "
        "stay. Safe to run again: it only ever adds."
    ),
    dataset="audio-book-listens",
    params=(),
    run=run,
    unavailable=unavailable,
))
