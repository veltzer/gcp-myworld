"""
Checks of the museums and of the visits to them.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from myworld.checks.core import (
    Result,
    check,
    problem,
    rows,
    squashed,
    twice,
)
from myworld.models import (
    Museum,
    MuseumVisit,
    museum_companions,
)


def _visits(session: Session) -> list[MuseumVisit]:
    """ Every visit of every museum, by its museum and then as added. """
    return [visit for museum in rows(session, Museum) for visit in museum.visits]


@check("museum-visits", "Every museum has a visit", "museums", "museums")
def check_museum_visits(session: Session) -> Result:
    """ Every museum, of every account, has at least one visit: when you went, what you thought of it and who you went with. """
    museums = rows(session, Museum)
    return Result(checked=len(museums), problems=[problem(museum, "has no visit") for museum in museums if not museum.visits])


@check("museum-dates", "Every museum visit has a date", "museum visits", "museums")
def check_museum_dates(session: Session) -> Result:
    """ Every museum visit, of every account, has a date: a day, a month, a year or a full time, whichever is known. """
    visits = _visits(session)
    problems = [
        problem(visit, "has no date")
        for visit in visits
        if visit.date_utcz is None and visit.date_ymd is None and not visit.date_my and visit.date_y is None
    ]
    return Result(checked=len(visits), problems=problems)


@check("museum-addresses", "Every museum has an address", "museums", "museums")
def check_museum_addresses(session: Session) -> Result:
    """ Every museum, of every account, has its street address. """
    museums = rows(session, Museum)
    return Result(checked=len(museums), problems=[problem(museum, "has no address") for museum in museums if not museum.street.strip()])


@check("museum-locations", "Every museum is on the map", "museums", "museums")
def check_museum_locations(session: Session) -> Result:
    """ Every museum, of every account, has a latitude and a longitude (scripts/geocode.py finds them from the address). """
    museums = rows(session, Museum)
    problems = [problem(museum, "has no latitude and longitude") for museum in museums if museum.latitude is None or museum.longitude is None]
    return Result(checked=len(museums), problems=problems)


@check("museum-company", "Every museum visit says who you were with", "museum visits", "museums")
def check_museum_company(session: Session) -> Result:
    """
    Every museum visit, of every account, either has the people you went
    with or is marked "I went alone", so an empty With is never a gap
    nobody filled in; and none is both.
    """
    with_people = set(session.scalars(select(museum_companions.c.museum_id)))
    visits = _visits(session)
    problems = []
    for visit in visits:
        if visit.alone and visit.id in with_people:
            problems.append(problem(visit, "is marked alone but has people in With"))
        elif not visit.alone and visit.id not in with_people:
            problems.append(problem(visit, "has no one in With and is not marked alone"))
    return Result(checked=len(visits), problems=problems)


@check("museum-photos", "Every museum has a photo", "museums", "museums")
def check_museum_photos(session: Session) -> Result:
    """ Every museum, of every account, has a photo. """
    museums = rows(session, Museum)
    return Result(checked=len(museums), problems=[problem(museum, "has no photo") for museum in museums if museum.image_id is None])


@check("museum-cities", "Every museum is in a city", "museums", "museums")
def check_museum_cities(session: Session) -> Result:
    """ Every museum, of every account, says which city it is in (the Cities page). """
    museums = rows(session, Museum)
    return Result(checked=len(museums), problems=[problem(museum, "has no city") for museum in museums if museum.city_id is None])


@check("museum-ratings", "Every museum visit is rated and reviewed", "museum visits", "museums")
def check_museum_ratings(session: Session) -> Result:
    """ Every museum visit, of every account, has a rating and a review. """
    visits = _visits(session)
    problems = []
    for visit in visits:
        missing = [what for what, absent in (("rating", visit.rating is None), ("review", not visit.review.strip())) if absent]
        if missing:
            problems.append(problem(visit, f"has no {' and no '.join(missing)}"))
    return Result(checked=len(visits), problems=problems)


@check("museum-duplicates", "No museum is listed twice", "museums", "museums")
def check_museum_duplicates(session: Session) -> Result:
    """ No account has two museums of the same name in the same city (ignoring case and spaces): a second visit is a visit of the first. """
    museums = rows(session, Museum)
    return Result(checked=len(museums), problems=twice(museums, lambda m: (m.owner_id, squashed(m.name), m.city_id or 0), "name and city"))
