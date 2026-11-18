"""
Checks of the organizations, and of their logos.
"""

import re
import xml.etree.ElementTree as ET

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
from myworld.models import (
    Image,
    Organization,
    organization_relation_types,
)

SVG_NS = "http://www.w3.org/2000/svg"


XLINK_NS = "http://www.w3.org/1999/xlink"


LOGO_SIZE = "1000"


# elements that run code, pull in other content, or embed a bitmap
FORBIDDEN_ELEMENTS = ("script", "foreignObject", "image", "iframe", "object", "embed")


# @import, or url() of anything but a #fragment of the same file
OUTSIDE_STYLE = re.compile(r"@import|url\(\s*['\"]?(?!#)")


NUMBER = re.compile(r"[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?")


def _local(tag: str) -> str:
    """ An element or attribute name without its {namespace}. """
    return tag.rsplit("}", 1)[-1]


def logo_problems(data: bytes) -> list[str]:
    """
    What is wrong with one SVG logo, by the convention in doc/logos.md: a
    1000x1000 canvas, a square viewBox, nothing active or external. The
    6% margin and the centering are not checked: they need the drawn
    bounding box, so a renderer.
    """
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        return [f"not well-formed XML: {e}"]
    if root.tag != f"{{{SVG_NS}}}svg":
        return [f"the root element is {root.tag}, not an SVG <svg>"]
    problems = []
    width, height = root.get("width"), root.get("height")
    if (width, height) != (LOGO_SIZE, LOGO_SIZE):
        problems.append(f'width/height are {width!r}/{height!r}, not "{LOGO_SIZE}"/"{LOGO_SIZE}"')
    view_box = root.get("viewBox")
    if view_box is None:
        problems.append("no viewBox")
    else:
        numbers = [float(n.group(0)) for n in NUMBER.finditer(view_box)]
        if len(numbers) != 4:
            problems.append(f"viewBox {view_box!r} is not four numbers")
        elif numbers[2] <= 0 or numbers[2] != numbers[3]:
            problems.append(f"viewBox {view_box!r} is not a square")
    for element in root.iter():
        name = _local(element.tag) if isinstance(element.tag, str) else ""
        if name in FORBIDDEN_ELEMENTS:
            problems.append(f"has a <{name}> element")
        if name == "style" and element.text and OUTSIDE_STYLE.search(element.text):
            problems.append("<style> refers to something outside the file")
        for attribute, value in element.attrib.items():
            local = _local(attribute)
            if local.lower().startswith("on"):
                problems.append(f"<{name}> has an event handler, {local}")
            elif local == "href" and not value.startswith("#"):
                problems.append(f"<{name}> links to {value[:80]!r}")
            elif OUTSIDE_STYLE.search(value):
                problems.append(f"<{name}> {local} refers to something outside the file")
    # the same problem in many elements is said once
    return list(dict.fromkeys(problems))


@check("logos", "Organization logos", "logos", "organizations")
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


@check("organization-logos", "Every organization has a logo", "organizations", "organizations")
def check_organization_logos(session: Session) -> Result:
    """ Every organization, of every account, has a logo. """
    organizations = rows(session, Organization)
    return Result(checked=len(organizations), problems=[problem(o, "has no logo") for o in organizations if o.image_id is None])


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
