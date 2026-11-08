"""
Checks over the whole database, of every account: rules the data should
follow that the app does not enforce when it is written (an SVG logo
inserted with SQL, say). An admin runs them from the Checks page
(GET /api/checks), and scripts/check.py runs the same ones from the
command line, so both always agree.

A check is a function from a database session to a Result, registered
with @check: one more is one function here, and both the page and the
script pick it up. A check only reads; it never changes anything.
"""

import dataclasses
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from myworld.models import (
    Image,
    Organization,
    Person,
    organization_relation_types,
    person_person_types,
)


@dataclasses.dataclass(frozen=True)
class Problem:
    """ One thing wrong: what it is about (a row a person can find) and what is wrong with it. """
    subject: str
    message: str


@dataclasses.dataclass(frozen=True)
class Result:
    checked: int
    problems: list[Problem]

    @property
    def ok(self) -> bool:
        return not self.problems


@dataclasses.dataclass(frozen=True)
class Check:
    name: str
    title: str
    description: str
    # what is counted in Result.checked: "logos", "organizations", ...
    noun: str
    run: Callable[[Session], Result]


CHECKS: dict[str, Check] = {}


def check(name: str, title: str, noun: str) -> Callable[[Callable[[Session], Result]], Callable[[Session], Result]]:
    """ Register a check; its docstring is the description shown with it. """
    def register(function: Callable[[Session], Result]) -> Callable[[Session], Result]:
        if name in CHECKS:
            raise ValueError(f"check {name!r} is registered twice")
        description = " ".join((function.__doc__ or "").split())
        CHECKS[name] = Check(name=name, title=title, description=description, noun=noun, run=function)
        return function
    return register


def result_json(chosen: Check, result: Result) -> dict[str, Any]:
    return {
        "name": chosen.name,
        "title": chosen.title,
        "noun": chosen.noun,
        "checked": result.checked,
        "ok": result.ok,
        "problems": [dataclasses.asdict(p) for p in result.problems],
    }


# ─── organization logos ─────────────────────────────────────────────────────

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


@check("logos", "Organization logos", "logos")
def check_logos(session: Session) -> Result:
    """
    Every SVG image in the database follows the logo convention
    (doc/logos.md): a 1000x1000 canvas with a square viewBox, valid XML,
    and no scripts, event handlers, embedded images or links outside the
    file. The margin and centering are not checked.
    """
    users_of: dict[int | None, list[str]] = {}
    for image_id, name in session.execute(select(Organization.image_id, Organization.name)):
        users_of.setdefault(image_id, []).append(name)
    images = session.execute(
        select(Image.id, Image.owner_id, Image.filename, Image.data).where(Image.content_type == "image/svg+xml").order_by(Image.id),
    ).all()
    problems = []
    for image_id, owner_id, filename, data in images:
        names = ", ".join(sorted(users_of.get(image_id, []))) or "no organization"
        subject = f"{filename} (image {image_id}, account {owner_id}: {names})"
        problems.extend(Problem(subject, message) for message in logo_problems(data))
    return Result(checked=len(images), problems=problems)


@check("organization-logos", "Every organization has a logo", "organizations")
def check_organization_logos(session: Session) -> Result:
    """ Every organization, of every account, has a logo. """
    organizations = session.execute(select(Organization.id, Organization.owner_id, Organization.name, Organization.image_id).order_by(Organization.name)).all()
    problems = [
        Problem(f"{name} (organization {organization_id}, account {owner_id})", "has no logo")
        for organization_id, owner_id, name, image_id in organizations
        if image_id is None
    ]
    return Result(checked=len(organizations), problems=problems)


@check("organization-relations", "Every organization is related to you", "organizations")
def check_organization_relations(session: Session) -> Result:
    """ Every organization, of every account, has at least one relation type (taught there, consulted, ...). """
    related = set(session.scalars(select(organization_relation_types.c.organization_id)))
    organizations = session.execute(select(Organization.id, Organization.owner_id, Organization.name).order_by(Organization.name)).all()
    problems = [
        Problem(f"{name} (organization {organization_id}, account {owner_id})", "has no relation type")
        for organization_id, owner_id, name in organizations
        if organization_id not in related
    ]
    return Result(checked=len(organizations), problems=problems)


# ─── people ─────────────────────────────────────────────────────────────────

@check("person-types", "Every person has a type", "people")
def check_person_types(session: Session) -> Result:
    """ Every person, of every account, is categorized as at least one person type (family, co-worker, ...). """
    typed = set(session.scalars(select(person_person_types.c.person_id)))
    people = session.scalars(select(Person).order_by(Person.owner_id, Person.first_name, Person.surname, Person.id)).all()
    problems = [
        Problem(f"{person.name} (person {person.id}, account {person.owner_id})", "has no type")
        for person in people
        if person.id not in typed
    ]
    return Result(checked=len(people), problems=problems)
