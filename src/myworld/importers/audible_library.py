"""
The books of the user's Audible library, as audio books from Audible: each
one they do not have yet is added, with its cover; one they have is given
what Audible says of it now (finished, how much was heard, its rating
there, ...) and keeps everything they wrote of it (rating, review, title,
...). It only ever adds: a book gone from the library since stays.
"""

from typing import Any

from sqlalchemy.orm import Session

from myworld import audible
from myworld.importers.core import Importer, ImporterError, Report, register
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
        counts = audible.store_library(session, owner, items, lambda _asin, url: audible.fetch_cover(url))
    except audible.AudibleError as e:
        raise ImporterError(str(e)) from e
    for key, what in COUNTS.items():
        if counts[key]:
            report.count(what, counts[key])


IMPORTER = register(Importer(
    name="audible-library",
    title="Audible library",
    description=(
        "The books of your Audible library, as audio books. Only the ones you do not have are added, with their covers; "
        "the ones you have get Audible's details as they are now (finished, how much you heard, the rating there) and keep "
        "your rating, review and edits. Safe to run again: it only ever adds."
    ),
    dataset="audio-books",
    params=(),
    run=run,
    unavailable=unavailable,
))
