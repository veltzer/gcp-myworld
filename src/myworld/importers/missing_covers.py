"""
The covers the shared data is missing (an admin's importer): an Audible
version of an audio book with no cover gets Audible's, from the address
Audible gave for it (cover_url), and a film or series with no poster gets
The Movie Database's, found by its IMDb id (with TMDB_API_KEY set; without
it the films are left for a later run).

It only fills what is empty: a cover there, uploaded by hand or brought
before, stays, so a run again asks only about those still missing one.
One its source has no cover for is said in the log and left as it is.
"""

import hashlib
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from myworld import audible, movies
from myworld.importers.core import Importer, Report, register
from myworld.models import AudioBook, AudioBookVersion, Film, Image, User

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _versions(session: Session) -> list[AudioBookVersion]:
    """ The Audible versions with no cover. """
    query = select(AudioBookVersion).join(AudioBook).where(AudioBookVersion.kind == "audible", AudioBookVersion.image_id.is_(None))
    return list(session.scalars(query.order_by(AudioBook.name, AudioBookVersion.id)))


def _films(session: Session) -> list[Film]:
    """ The films and series with no poster that have an IMDb id to find one by. """
    return list(session.scalars(select(Film).where(Film.image_id.is_(None), Film.imdb_id.is_not(None)).order_by(Film.name, Film.id)))


def unavailable(session: Session, _owner: User) -> str:
    if _versions(session) or (movies.configured() and _films(session)):
        return ""
    return "Every Audible version has its cover, and every film and series its poster" if movies.configured() else (
        "Every Audible version has its cover (the films' posters need TMDB_API_KEY)"
    )


def _image(owner: User, filename: str, data: bytes) -> Image:
    return Image(owner_id=owner.id, filename=filename, content_type="image/jpeg", sha256=hashlib.sha256(data).hexdigest(), data=data)


def run(session: Session, owner: User, params: dict[str, Any], report: Report) -> None:
    del params
    for version in _versions(session):
        name = f"{version.book.name} (Audible {version.asin})"
        data = audible.fetch_cover(version.cover_url) if version.cover_url else None
        if data is None:
            report.say(f"{name}: {'Audible gave no cover' if version.cover_url else 'no cover address from Audible'}")
            report.count("audio book covers not found")
            continue
        version.image = _image(owner, f"audible-{version.asin}.jpg", data)
        report.say(f"{name}: cover added")
        report.count("audio book covers added")
    if not movies.configured():
        if _films(session):
            report.say("the films' and series' posters need TMDB_API_KEY: left for a run that has it")
        session.flush()
        return
    for film in _films(session):
        name = f"{film.name} ({film.imdb_id})"
        try:
            facts = movies.tmdb_find(film.imdb_id or "")
            data = movies.poster_bytes(facts["poster_url"]) if facts and facts["poster_url"] else None
        except (movies.MovieLookupError, OSError, ValueError, KeyError) as e:
            report.say(f"{name}: TMDB: {e}")
            report.count("posters not looked up")
            continue
        if data is None:
            report.say(f"{name}: TMDB has no poster")
            report.count("posters not found")
            continue
        film.image = _image(owner, f"tmdb-{film.imdb_id}.jpg", data)
        if film.tmdb_id is None and facts:
            film.tmdb_id = facts["tmdb_id"]
        report.say(f"{name}: poster added")
        report.count("posters added")
    session.flush()


IMPORTER = register(Importer(
    name="missing-covers",
    title="Missing covers",
    description=(
        "Gives the shared data the covers it is missing: an Audible version of an audio book Audible's cover, a film or series "
        "The Movie Database's poster. Only fills what has none: safe to run again."
    ),
    dataset="audio-book-versions",
    shared=True,
    params=(),
    run=run,
    unavailable=unavailable,
))
