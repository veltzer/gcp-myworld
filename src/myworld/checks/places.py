"""
Checks of the places.
"""


from typing import TYPE_CHECKING

from myworld.checks.core import (
    Result,
    check,
    ids,
    problem,
    rows,
    squashed,
    twice,
)
from myworld.models import (
    Concert,
    Place,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@check("place-used", "Every place has something that happened there", "places", "places")
def check_place_used(session: Session) -> Result:
    """ Every place has at least one concert that was there. """
    places, used = rows(session, Place), ids(session, Concert.place_id)
    return Result(checked=len(places), problems=[problem(place, "nothing happened there") for place in places if place.id not in used])


@check("place-cities", "Every place is in a city", "places", "places")
def check_place_cities(session: Session) -> Result:
    """ Every place says which city it is in (the Cities page). """
    places = rows(session, Place)
    return Result(checked=len(places), problems=[problem(place, "has no city") for place in places if place.city_id is None])


@check("place-locations", "Every place is on the map", "places", "places")
def check_place_locations(session: Session) -> Result:
    """ Every place has a latitude and a longitude, so the Map layout shows it. """
    places = rows(session, Place)
    problems = [problem(place, "has no latitude and longitude") for place in places if place.latitude is None or place.longitude is None]
    return Result(checked=len(places), problems=problems)


@check("place-duplicates", "No place is listed twice", "places", "places")
def check_place_duplicates(session: Session) -> Result:
    """ No two places have the same name in the same city (ignoring case and spaces). """
    places = rows(session, Place)
    return Result(checked=len(places), problems=twice(places, lambda p: (squashed(p.name), p.city_id or 0), "name and city", "place"))


@check("place-addresses", "Every place has an address", "places", "places")
def check_place_addresses(session: Session) -> Result:
    """ Every place has a street or a neighbourhood: more than the city it is in. """
    places = rows(session, Place)
    problems = [problem(place, "has no street and no neighbourhood") for place in places if not place.street.strip() and not place.neighbourhood.strip()]
    return Result(checked=len(places), problems=problems)


@check("place-photos", "Every place has a photo", "places", "places")
def check_place_photos(session: Session) -> Result:
    """ Every place has a photo (scripts/fetch_pictures.py --only places takes Wikipedia's). """
    places = rows(session, Place)
    return Result(checked=len(places), problems=[problem(place, "has no photo") for place in places if place.image_id is None])
