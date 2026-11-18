"""
Checks of the concerts.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from myworld.checks.core import (
    Result,
    check,
    dated,
    problem,
    rows,
    twice,
)
from myworld.models import (
    Concert,
    concert_companions,
    concert_groups,
    concert_performers,
)


@check("concert-dates", "Every concert has a date", "concerts", "concerts")
def check_concert_dates(session: Session) -> Result:
    """ Every concert, of every account, has a date (a day, a month, a year or a full time). """
    concerts = rows(session, Concert)
    return Result(checked=len(concerts), problems=[problem(c, "has no date") for c in concerts if not dated(c)])


@check("concert-places", "Every concert says where it was", "concerts", "concerts")
def check_concert_places(session: Session) -> Result:
    """ Every concert, of every account, points to the place it was at (the Places page); one seen on TV need not. """
    concerts = rows(session, Concert)
    problems = [problem(concert, "has no place") for concert in concerts if concert.place_id is None and not concert.broadcast]
    return Result(checked=len(concerts), problems=problems)


@check("concert-performers", "Every concert has a performer", "concerts", "concerts")
def check_concert_performers(session: Session) -> Result:
    """ Every concert, of every account, has at least one performer: a person or a group. """
    performed = set(session.scalars(select(concert_performers.c.concert_id))) | set(session.scalars(select(concert_groups.c.concert_id)))
    concerts = rows(session, Concert)
    return Result(checked=len(concerts), problems=[problem(c, "has no performer") for c in concerts if c.id not in performed])


@check("concert-photos", "Every concert has a photo", "concerts", "concerts")
def check_concert_photos(session: Session) -> Result:
    """ Every concert, of every account, has a photo. """
    concerts = rows(session, Concert)
    return Result(checked=len(concerts), problems=[problem(c, "has no photo") for c in concerts if c.image_id is None])


@check("concert-duplicates", "No concert is listed twice", "concerts", "concerts")
def check_concert_duplicates(session: Session) -> Result:
    """ No account has two concerts of the same name on the same date (ignoring case and spaces at the ends). """
    concerts = rows(session, Concert)
    def key(concert: Concert) -> tuple[int, str, str]:
        return concert.owner_id, concert.name.strip().lower(), str(concert.date_utcz or concert.date_ymd or concert.date_my or concert.date_y or "")
    return Result(checked=len(concerts), problems=twice(concerts, key, "name and date", "concert"))


@check("concert-company", "Every concert says who you were with", "concerts", "concerts")
def check_concert_company(session: Session) -> Result:
    """
    Every concert, of every account, either has the people you went with or
    is marked "I went alone", so an empty With is never a gap nobody filled
    in; and none is both.
    """
    with_people = set(session.scalars(select(concert_companions.c.concert_id)))
    concerts = rows(session, Concert)
    problems = []
    for concert in concerts:
        if concert.alone and concert.id in with_people:
            problems.append(problem(concert, "is marked alone but has people in With"))
        elif not concert.alone and concert.id not in with_people:
            problems.append(problem(concert, "has no one in With and is not marked alone"))
    return Result(checked=len(concerts), problems=problems)


@check("concert-reviews", "Every concert has a review", "concerts", "concerts")
def check_concert_reviews(session: Session) -> Result:
    """ Every concert, of every account, has a review: what you thought of it. """
    concerts = rows(session, Concert)
    return Result(checked=len(concerts), problems=[problem(concert, "has no review") for concert in concerts if not concert.review.strip()])
