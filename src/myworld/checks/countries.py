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
)


@check("country-used", "Every country has a city", "countries", "countries")
def check_country_used(session: Session) -> Result:
    """ Every country, of every account, has at least one city in it. """
    countries, used = rows(session, Country), ids(session, City.country_id)
    return Result(checked=len(countries), problems=[problem(c, "has no city") for c in countries if c.id not in used])


@check("country-locations", "Every country is on the map", "countries", "countries")
def check_country_locations(session: Session) -> Result:
    """ Every country, of every account, has a latitude and a longitude (scripts/geocode.py finds them). """
    countries = rows(session, Country)
    return Result(checked=len(countries), problems=[problem(c, "has no latitude and longitude") for c in countries if c.latitude is None or c.longitude is None])


@check("country-flags", "Every country has its flag", "countries", "countries")
def check_country_flags(session: Session) -> Result:
    """ Every country, of every account, has its flag (scripts/fetch_pictures.py takes Wikipedia's). """
    countries = rows(session, Country)
    return Result(checked=len(countries), problems=[problem(c, "has no flag") for c in countries if c.image_id is None])


@check("country-duplicates", "No country is listed twice", "countries", "countries")
def check_country_duplicates(session: Session) -> Result:
    """ No account has one country twice, however it is written ("USA", "United States of America"). """
    countries = rows(session, Country)
    alike = same(countries, lambda country: (country.owner_id, country_name(country.name).casefold()))
    return Result(checked=len(countries), problems=[problem(country, "is the same country as another of the account") for group in alike for country in group])
