"""
Checks of the films and the series (shared: a series is a film of another
kind), and of those each account watched or means to see.
"""


from typing import TYPE_CHECKING

from sqlalchemy import select

from myworld.checks.core import (
    Result,
    check,
    dated,
    problem,
)
from myworld.models import Film, FilmWatch

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session


def _films(session: Session, kind: str) -> list[Film]:
    return list(session.scalars(select(Film).where(Film.kind == kind).order_by(Film.name, Film.id)))


def _watched(session: Session, kind: str) -> list[FilmWatch]:
    """ Every account's watches of the films of kind (not those still to see). """
    found = session.scalars(
        select(FilmWatch).join(Film).where(FilmWatch.status == "done", Film.kind == kind).order_by(FilmWatch.owner_id, Film.name, FilmWatch.id),
    )
    return list(found)


def _missing(row: FilmWatch) -> list[str]:
    return [what for what, absent in (("rating", row.rating is None), ("review", not row.review.strip())) if absent]


def _register(kind: str, page: str, watches: str, plural: str) -> None:
    """ The checks of the films of kind (on page) and of the watches of them (on watches). """
    started = "came out" if kind == "film" else "started"

    def film_check(name: str, title: str, description: str, fails: Callable[[Film], str]) -> None:
        def run(session: Session) -> Result:
            films = _films(session, kind)
            return Result(checked=len(films), problems=[problem(f, fails(f)) for f in films if fails(f)])
        run.__doc__ = description
        check(f"{kind}-{name}", title, plural, page)(run)

    film_check("posters", f"Every {kind} has a poster", f"Every {kind} has its poster.", lambda f: "" if f.image_id is not None else "has no poster")
    film_check(
        "imdb-ids", f"Every {kind} has its IMDb id", f"Every {kind} has its IMDb id: the importers find it again by it, and its card links its page there.",
        lambda f: "" if f.imdb_id else "has no IMDb id",
    )
    film_check(
        "years", f"Every {kind} says the year it {started}", f"Every {kind} has the year it {started}, which tells apart two of one title.",
        lambda f: "" if f.year is not None else "has no year",
    )

    def dates(session: Session) -> Result:
        watched = _watched(session, kind)
        return Result(checked=len(watched), problems=[problem(w, "has no date") for w in watched if not dated(w)])
    dates.__doc__ = f"Every {kind} watched, of every account, has the date it was watched."
    check(f"{kind}-watch-dates", f"Every {kind} watched says when", f"{plural} watched", watches)(dates)

    def reviews(session: Session) -> Result:
        watched = _watched(session, kind)
        return Result(checked=len(watched), problems=[problem(w, f"has no {' and no '.join(_missing(w))}") for w in watched if _missing(w)])
    reviews.__doc__ = f"Every {kind} watched, of every account, has the user's own rating and review."
    check(f"{kind}-watch-reviews", f"Every {kind} watched is rated and reviewed", f"{plural} watched", watches)(reviews)


_register("film", "films", "film-watches", "films")
_register("series", "series", "series-watches", "series")
