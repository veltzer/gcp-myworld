"""
Checks of the cities.
"""

from sqlalchemy.orm import Session

from myworld.checks.core import (
    Result,
    check,
    ids,
    problem,
    rows,
    same,
)
from myworld.cities import city_key
from myworld.models import (
    City,
    Organization,
    Place,
)


@check("city-used", "Every city has something in it", "cities", "cities")
def check_city_used(session: Session) -> Result:
    """ Every city has a place (a museum, a concert venue, ...), an organization or an organization's headquarters in it. """
    cities, used = rows(session, City), ids(session, Place.city_id, Organization.city_id, Organization.headquarters_id)
    return Result(checked=len(cities), problems=[problem(city, "nothing is in it") for city in cities if city.id not in used])


@check("city-countries", "Every city has a country", "cities", "cities")
def check_city_countries(session: Session) -> Result:
    """ Every city says which country it is in. """
    cities = rows(session, City)
    return Result(checked=len(cities), problems=[problem(city, "has no country") for city in cities if city.country_id is None])


@check("city-locations", "Every city is on the map", "cities", "cities")
def check_city_locations(session: Session) -> Result:
    """ Every city has a latitude and a longitude (scripts/geocode.py finds them). """
    cities = rows(session, City)
    return Result(checked=len(cities), problems=[problem(city, "has no latitude and longitude") for city in cities if city.latitude is None or city.longitude is None])


@check("city-photos", "Every city has a photo", "cities", "cities")
def check_city_photos(session: Session) -> Result:
    """ Every city has a photo (scripts/fetch_pictures.py takes Wikipedia's). """
    cities = rows(session, City)
    return Result(checked=len(cities), problems=[problem(city, "has no photo") for city in cities if city.image_id is None])


@check("city-duplicates", "No city is listed twice", "cities", "cities")
def check_city_duplicates(session: Session) -> Result:
    """ No city is there twice: the same name and country, however spaced, hyphenated or capitalized ("Tel-Aviv", "Tel Aviv"). """
    cities = rows(session, City)
    alike = same(cities, lambda city: city_key(city.name, city.country.name if city.country else ""))
    problems = [problem(city, f"is the same city as {len(group) - 1} other{'s' if len(group) > 2 else ''}") for group in alike for city in group]
    return Result(checked=len(cities), problems=problems)


@check("city-regions", "The cities of a country all have a region, or none has", "cities", "cities")
def check_city_regions(session: Session) -> Result:
    """
    The cities of a country either all say their region (a state, a
    district) or none does: where some do, those that do not are the gap.
    """
    cities = [city for city in rows(session, City) if city.country_id is not None]
    with_region = {city.country_id for city in cities if city.region.strip()}
    problems = [
        problem(city, "has no region, where other cities of its country have one")
        for city in cities
        if not city.region.strip() and city.country_id in with_region
    ]
    return Result(checked=len(cities), problems=problems)
