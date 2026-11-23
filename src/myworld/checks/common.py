"""
Checks several pages have, made once for each: a credit that says its source and its license, a pin near its city, a website that is a well-formed URL.
"""

import dataclasses
import math
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from myworld.checks.core import (
    CHECKS,
    DATASETS,
    Result,
    check,
    problem,
    rows,
)
from myworld.models import (
    City,
    CityPhoto,
    Concert,
    Country,
    Device,
    Group,
    Organization,
    Person,
    PersonPhoto,
    PersonType,
    Place,
    is_shared,
)

# what has a picture with a credit, by the page it is on: (model, what the picture is called, the link to a row)
_CREDITED: dict[str, tuple[Any, str]] = {
    "concerts": (Concert, "photo"),
    "groups": (Group, "photo"),
    "places": (Place, "photo"),
    "cities": (City, "photo"),
    "countries": (Country, "flag"),
    "devices": (Device, "photo"),
    "person-types": (PersonType, "photo"),
}


def credit_gaps(source: str, license_: str, author: str) -> list[str]:
    """
    What the credit of a picture taken from elsewhere lacks: a picture with
    any of it says where it is from and its license. Who made it is said
    when it is known, and not asked for: many a picture names no author.
    """
    needed = {"source": source.strip(), "license": license_.strip()}
    return [what for what, value in needed.items() if not value] if any((*needed.values(), author.strip())) else []


def _credit_checks(dataset: str, model: Any, what: str) -> None:
    page = DATASETS[dataset].lower()

    @check(f"{dataset}-credits", f"Every credited {what} of {page} says its source and license", f"{what}s with a credit", dataset)
    def run(session: Session) -> Result:
        owner = () if is_shared(model) else (model.owner_id,)
        rows = session.scalars(select(model).where(model.image_id.is_not(None)).order_by(*owner, model.name, model.id)).all()
        pictures = [(row, row.image_source, row.image_license, row.image_author) for row in rows]
        if model is City:
            # a city's further photos, each with its own credit
            cities = {city.id: city for city in session.scalars(select(City))}
            pictures += [(cities[photo.city_id], photo.image_source, photo.image_license, photo.image_author) for photo in session.scalars(select(CityPhoto).order_by(CityPhoto.id))]
        credited = [(row, credit_gaps(source, license_, author)) for row, source, license_, author in pictures if source.strip() or license_.strip() or author.strip()]
        problems = [
            problem(row, f"has a {what} credited with no {' and no '.join(gaps)}")
            for row, gaps in credited
            if gaps
        ]
        return Result(checked=len(credited), problems=problems)

    run.__doc__ = (
        f"Every {what} of {page}, of every account, that has a credit (it was taken from elsewhere, as scripts/fetch_pictures.py does from Wikipedia)"
        " says the page it comes from and its license; its author only when one is known."
    )
    CHECKS[f"{dataset}-credits"] = dataclasses.replace(CHECKS[f"{dataset}-credits"], description=" ".join(run.__doc__.split()))


for _dataset, (_model, _what) in _CREDITED.items():
    _credit_checks(_dataset, _model, _what)


@check("people-credits", "Every credited photo of people says its source and license", "photos with a credit", "people")
def check_people_credits(session: Session) -> Result:
    """
    Every photo of a person, of every account, that has a credit (it was
    taken from elsewhere, as scripts/fetch_pictures.py does from Wikipedia)
    says the page it comes from and its license; its author only when one is known.
    """
    people = {person.id: person for person in rows(session, Person)}
    photos = [photo for photo in session.scalars(select(PersonPhoto).order_by(PersonPhoto.person_id, PersonPhoto.position)) if photo.image_source.strip() or photo.image_license.strip() or photo.image_author.strip()]
    problems = []
    for photo in photos:
        gaps = credit_gaps(photo.image_source, photo.image_license, photo.image_author)
        if gaps:
            problems.append(problem(people[photo.person_id], f"has a photo credited with no {' and no '.join(gaps)}"))
    return Result(checked=len(photos), problems=problems)


# how far from its city's pin something may be and still be in it (a city is wide, and its pin is its middle)
NEAR_KM = 50


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """ The distance between two (latitude, longitude) points on the globe, in kilometers. """
    lat1, lon1, lat2, lon2 = (math.radians(value) for value in (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def _near_city_check(dataset: str, model: Any, noun: str) -> None:
    page = DATASETS[dataset].lower()

    @check(f"{noun}-near-city", f"Every {noun} is where its city is", f"{page} on the map in a city on the map", dataset)
    def run(session: Session) -> Result:
        placed = [
            row for row in rows(session, model)
            if row.latitude is not None and row.longitude is not None and row.city is not None and row.city.latitude is not None and row.city.longitude is not None
        ]
        problems = []
        for row in placed:
            far = km((row.latitude, row.longitude), (row.city.latitude, row.city.longitude))
            if far > NEAR_KM:
                problems.append(problem(row, f"is {far:.0f} km from {row.city.name}, the city it is in"))
        return Result(checked=len(placed), problems=problems)

    CHECKS[f"{noun}-near-city"] = dataclasses.replace(CHECKS[f"{noun}-near-city"], description=(
        f"Every one of the {page}, of every account, that is on the map and in a city that is on the map is within {NEAR_KM} km of its city:"
        " farther, its pin or its city is wrong."
    ))


_near_city_check("places", Place, "place")


_near_city_check("organizations", Organization, "organization")


WEBSITE = re.compile(r"https?://[^\s/.]+(\.[^\s/.]+)+(/\S*)?")


def _website_check(dataset: str, model: Any, noun: str, column: str) -> None:
    page = DATASETS[dataset].lower()

    @check(f"{noun}-websites", f"Every website of {page} is a well-formed URL", "websites", dataset)
    def run(session: Session) -> Result:
        linked = [row for row in rows(session, model) if getattr(row, column).strip()]
        problems = [
            problem(row, f"has a website that is no web address: {getattr(row, column)}")
            for row in linked
            if not WEBSITE.fullmatch(getattr(row, column).strip())
        ]
        return Result(checked=len(linked), problems=problems)

    CHECKS[f"{noun}-websites"] = dataclasses.replace(CHECKS[f"{noun}-websites"], description=(
        f"Every website of the {page}, of every account, is a web address: http:// or https://, a host with a dot in it, and no spaces."
    ))


_website_check("places", Place, "place", "website")


_website_check("groups", Group, "group", "website")


_website_check("organizations", Organization, "organization", "website")
