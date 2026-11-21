"""
Checks of the museums (shared places of the kind Museum) and of the users'
visits to them (visits of the type Museum visit).
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
    MUSEUM_KIND,
    MUSEUM_VISIT,
    Place,
    Visit,
    VisitType,
    visit_companions,
)


def _museums(session: Session) -> list[Place]:
    """ Every museum: the places of the kind Museum, by name and then as added. """
    return [place for place in rows(session, Place) if any(kind.name == MUSEUM_KIND for kind in place.kinds)]


def _visits(session: Session) -> list[Visit]:
    """ Every museum visit, of every account: by account, then as added. """
    query = select(Visit).join(VisitType).where(VisitType.name == MUSEUM_VISIT).order_by(Visit.owner_id, Visit.id)
    return list(session.scalars(query))


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


@check("museum-visit-places", "Every museum visit is to a museum", "museum visits", "museums")
def check_museum_visit_places(session: Session) -> Result:
    """ Every museum visit, of every account, is to a place of the kind Museum: not to none (an admin deleted it), nor to a place that is no museum. """
    visits = _visits(session)
    problems = []
    for visit in visits:
        if visit.place is None:
            problems.append(problem(visit, "is to no place"))
        elif not any(kind.name == MUSEUM_KIND for kind in visit.place.kinds):
            problems.append(problem(visit, f"is to {visit.place.name}, which is not of the kind {MUSEUM_KIND}"))
    return Result(checked=len(visits), problems=problems)


@check("museum-addresses", "Every museum has an address", "museums", "museums")
def check_museum_addresses(session: Session) -> Result:
    """ Every museum has its street address. """
    museums = _museums(session)
    return Result(checked=len(museums), problems=[problem(museum, "has no address") for museum in museums if not museum.street.strip()])


@check("museum-locations", "Every museum is on the map", "museums", "museums")
def check_museum_locations(session: Session) -> Result:
    """ Every museum has a latitude and a longitude (scripts/geocode.py finds them from the address). """
    museums = _museums(session)
    problems = [problem(museum, "has no latitude and longitude") for museum in museums if museum.latitude is None or museum.longitude is None]
    return Result(checked=len(museums), problems=problems)


@check("museum-company", "Every museum visit says who you were with", "museum visits", "museums")
def check_museum_company(session: Session) -> Result:
    """
    Every museum visit, of every account, either has the people you went
    with or is marked "I went alone", so an empty With is never a gap
    nobody filled in; and none is both.
    """
    with_people = set(session.scalars(select(visit_companions.c.visit_id)))
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
    """ Every museum has a photo. """
    museums = _museums(session)
    return Result(checked=len(museums), problems=[problem(museum, "has no photo") for museum in museums if museum.image_id is None])


@check("museum-cities", "Every museum is in a city", "museums", "museums")
def check_museum_cities(session: Session) -> Result:
    """ Every museum says which city it is in (the Cities page). """
    museums = _museums(session)
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
    """ No two museums have the same name in the same city (ignoring case and spaces). """
    museums = _museums(session)
    return Result(checked=len(museums), problems=twice(museums, lambda m: (squashed(m.name), m.city_id or 0), "name and city"))
