"""
Checks of the countries.
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
from myworld.cities import country_name
from myworld.models import (
    City,
    Country,
    Organization,
    Place,
)


@check("country-used", "Every country has a city", "countries", "countries")
def check_country_used(session: Session) -> Result:
    """ Every country added by hand has at least one city in it (the Locale importer brings every country of the world, with cities or not). """
    countries, used = [c for c in rows(session, Country) if not c.code], ids(session, City.country_id)
    return Result(checked=len(countries), problems=[problem(c, "has no city") for c in countries if c.id not in used])


@check("country-locations", "Every country is on the map", "countries", "countries")
def check_country_locations(session: Session) -> Result:
    """ Every country has a latitude and a longitude (scripts/geocode.py finds them). """
    countries = rows(session, Country)
    return Result(checked=len(countries), problems=[problem(c, "has no latitude and longitude") for c in countries if c.latitude is None or c.longitude is None])


@check("country-flags", "Every country has its flag", "countries", "countries")
def check_country_flags(session: Session) -> Result:
    """ Every country a city something is in is in has its flag (scripts/fetch_pictures.py takes Wikipedia's): of the world's countries, the ones in use. """
    in_use = ids(session, Place.city_id, Organization.city_id, Organization.headquarters_id)
    used = {city.country_id for city in rows(session, City) if city.id in in_use}
    countries = [c for c in rows(session, Country) if c.id in used]
    return Result(checked=len(countries), problems=[problem(c, "has no flag") for c in countries if c.image_id is None])


@check("country-duplicates", "No country is listed twice", "countries", "countries")
def check_country_duplicates(session: Session) -> Result:
    """ No country is there twice, however it is written ("USA", "United States of America"). """
    countries = rows(session, Country)
    alike = same(countries, lambda country: country_name(country.name).casefold())
    return Result(checked=len(countries), problems=[problem(country, "is the same country as another") for group in alike for country in group])


@check("country-codes", "Every country has its ISO code", "countries", "countries")
def check_country_codes(session: Session) -> Result:
    """ Every country has its ISO 3166 code (IL, US): the Locale importer gives every country of the world its own, and knows it again by it. """
    countries = rows(session, Country)
    return Result(checked=len(countries), problems=[problem(c, "has no ISO code") for c in countries if not c.code])
