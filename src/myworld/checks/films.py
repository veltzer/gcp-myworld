"""
Checks of the films (shared), and of the films each account watched or
means to see.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from myworld.checks.core import (
    Result,
    check,
    dated,
    problem,
    rows,
)
from myworld.models import Film, FilmWatch


@check("film-posters", "Every film has a poster", "films", "films")
def check_film_posters(session: Session) -> Result:
    """ Every film has its poster. """
    films = rows(session, Film)
    return Result(checked=len(films), problems=[problem(f, "has no poster") for f in films if f.image_id is None])


@check("film-imdb-ids", "Every film has its IMDb id", "films", "films")
def check_film_imdb_ids(session: Session) -> Result:
    """ Every film has its IMDb id: the importers find it again by it, and its card links its page there. """
    films = rows(session, Film)
    return Result(checked=len(films), problems=[problem(f, "has no IMDb id") for f in films if not f.imdb_id])


@check("film-years", "Every film says the year it came out", "films", "films")
def check_film_years(session: Session) -> Result:
    """ Every film has the year it came out, which tells apart two films of one title. """
    films = rows(session, Film)
    return Result(checked=len(films), problems=[problem(f, "has no year") for f in films if f.year is None])


def _watched(session: Session) -> list[FilmWatch]:
    """ Every account's films watched (not those still to see). """
    found = session.scalars(select(FilmWatch).join(Film).where(FilmWatch.status == "done").order_by(FilmWatch.owner_id, Film.name, FilmWatch.id))
    return list(found)


@check("film-watch-dates", "Every film watched says when", "films watched", "film-watches")
def check_film_watch_dates(session: Session) -> Result:
    """ Every film watched, of every account, has the date it was watched. """
    watched = _watched(session)
    return Result(checked=len(watched), problems=[problem(w, "has no date") for w in watched if not dated(w)])


@check("film-watch-reviews", "Every film watched is rated and reviewed", "films watched", "film-watches")
def check_film_watch_reviews(session: Session) -> Result:
    """ Every film watched, of every account, has the user's own rating and review. """
    watched = _watched(session)
    problems = []
    for row in watched:
        missing = [what for what, absent in (("rating", row.rating is None), ("review", not row.review.strip())) if absent]
        if missing:
            problems.append(problem(row, f"has no {' and no '.join(missing)}"))
    return Result(checked=len(watched), problems=problems)
