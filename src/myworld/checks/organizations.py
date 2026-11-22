"""
Checks of the organizations, and of their logos.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from myworld.checks.core import (
    Problem,
    Result,
    check,
    problem,
    rows,
    squashed,
    twice,
)
from myworld.logos import SVG_TYPE, logo_problems
from myworld.models import (
    Image,
    Organization,
    organization_relation_types,
)


@check("logos", "Every logo follows the logo convention", "logos", "organizations")
def check_logos(session: Session) -> Result:
    """
    Every SVG image in the database follows the logo convention
    (doc/logos.md): a 1000x1000 canvas with a square viewBox, valid XML,
    and no scripts, event handlers, embedded images or links outside the
    file. The margin and centering are not checked.
    """
    users_of: dict[int | None, list[tuple[str, int]]] = {}
    for image_id, name, organization_id in session.execute(select(Organization.image_id, Organization.name, Organization.id).order_by(Organization.name)):
        users_of.setdefault(image_id, []).append((name, organization_id))
    images = session.execute(
        select(Image.id, Image.owner_id, Image.filename, Image.data).where(Image.content_type == "image/svg+xml").order_by(Image.id),
    ).all()
    problems = []
    for image_id, owner_id, filename, data in images:
        users = users_of.get(image_id, [])
        names = ", ".join(name for name, _ in users) or "no organization"
        subject = f"{filename} (image {image_id}, account {owner_id}: {names})"
        # an image no organization uses has no place in the app to go to
        link = f"organizations/{users[0][1]}" if users else ""
        problems.extend(Problem(subject, message, link, owner_id) for message in logo_problems(data))
    return Result(checked=len(images), problems=problems)


@check("organization-logos", "Every organization has an SVG logo", "organizations", "organizations")
def check_organization_logos(session: Session) -> Result:
    """ Every organization, of every account, has a logo, and it is an SVG image (a logo is never a bitmap: doc/logos.md). """
    organizations = rows(session, Organization)
    logo_ids = [o.image_id for o in organizations if o.image_id is not None]
    types = {image_id: content_type for image_id, content_type in session.execute(select(Image.id, Image.content_type).where(Image.id.in_(logo_ids)))}
    problems = []
    for o in organizations:
        if o.image_id is None:
            problems.append(problem(o, "has no logo"))
        elif types.get(o.image_id) != SVG_TYPE:
            problems.append(problem(o, f"has a logo that is not an SVG ({types.get(o.image_id)})"))
    return Result(checked=len(organizations), problems=problems)


@check("organization-has-website", "Every organization has a website", "organizations", "organizations")
def check_organization_has_website(session: Session) -> Result:
    """
    Every organization, of every account, has a website. One that is gone
    still gets one: a snapshot of it on the Wayback Machine (web.archive.org)
    is better than none.
    """
    organizations = rows(session, Organization)
    return Result(checked=len(organizations), problems=[problem(o, "has no website") for o in organizations if not o.website.strip()])


@check("organization-relations", "Every organization is related to you", "organizations", "organizations")
def check_organization_relations(session: Session) -> Result:
    """ Every organization, of every account, has at least one relation type (taught there, consulted, ...). """
    related = set(session.scalars(select(organization_relation_types.c.organization_id)))
    organizations = rows(session, Organization)
    return Result(checked=len(organizations), problems=[problem(o, "has no relation type") for o in organizations if o.id not in related])


@check("organization-addresses", "Every organization has an address", "organizations", "organizations")
def check_organization_addresses(session: Session) -> Result:
    """ Every organization, of every account, has a street address (the office you knew, not only the city). """
    organizations = rows(session, Organization)
    return Result(checked=len(organizations), problems=[problem(o, "has no address") for o in organizations if not o.street.strip()])


@check("organization-locations", "Every organization is on the map", "organizations", "organizations")
def check_organization_locations(session: Session) -> Result:
    """ Every organization, of every account, has a latitude and a longitude (scripts/geocode.py finds them from the address). """
    organizations = rows(session, Organization)
    return Result(checked=len(organizations), problems=[problem(o, "has no latitude and longitude") for o in organizations if o.latitude is None or o.longitude is None])


@check("organization-cities", "Every organization is in a city", "organizations", "organizations")
def check_organization_cities(session: Session) -> Result:
    """ Every organization, of every account, says which city it is in (the Cities page). """
    organizations = rows(session, Organization)
    return Result(checked=len(organizations), problems=[problem(o, "has no city") for o in organizations if o.city_id is None])


@check("organization-duplicates", "No organization is listed twice", "organizations", "organizations")
def check_organization_duplicates(session: Session) -> Result:
    """ No account has two organizations of the same name (ignoring case and spaces). """
    organizations = rows(session, Organization)
    return Result(checked=len(organizations), problems=twice(organizations, lambda o: (o.owner_id, squashed(o.name)), "name"))
