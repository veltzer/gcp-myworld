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
import datetime
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from myworld.models import (
    KINDS,
    YOUTUBE_ID_LENGTH,
    AudioCourse,
    Concert,
    Device,
    Image,
    Museum,
    Organization,
    OrganizationType,
    Person,
    PersonType,
    RelationType,
    UserWork,
    Work,
    YouTubeVideo,
    audio_course_lecturers,
    concert_performers,
    library_entry_authors,
    museum_companions,
    organization_relation_types,
    person_type_links,
)


@dataclasses.dataclass(frozen=True)
class Problem:
    """
    One thing wrong: what it is about (a row a person can find), what is
    wrong with it, and where the row is in the app, when it has a place
    there: "<view>/<id>" ("organizations/121"), opened as /library#<link>
    by the account that owns it.
    """
    subject: str
    message: str
    link: str = ""
    # the account the row belongs to: the app opens only the viewer's own rows
    owner: int | None = None


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
    # the data it is about, a key of DATASETS
    dataset: str
    run: Callable[[Session], Result]


# What the checks are about: the app's page of that data (its #hash) -> its
# name. The Checks page groups them in this order, and each page runs its own.
# Every page of data has checks (tests/checks_test.py makes sure of it).
DATASETS: dict[str, str] = {
    **{kind: plural for kind, (_, plural, _) in KINDS.items()},
    "concerts": "Concerts",
    "museums": "Museums",
    "audio-courses": "Audio courses",
    "youtube": "YouTube",
    "people": "People",
    "organizations": "Organizations",
    "organization-types": "Org types",
    "person-types": "Person types",
    "relation-types": "Relation types",
    "devices": "Devices",
}

CHECKS: dict[str, Check] = {}


def check(name: str, title: str, noun: str, dataset: str) -> Callable[[Callable[[Session], Result]], Callable[[Session], Result]]:
    """ Register a check of a dataset; its docstring is the description shown with it. """
    if dataset not in DATASETS:
        raise ValueError(f"check {name!r}: no dataset called {dataset!r}")
    def register(function: Callable[[Session], Result]) -> Callable[[Session], Result]:
        if name in CHECKS:
            raise ValueError(f"check {name!r} is registered twice")
        description = " ".join((function.__doc__ or "").split())
        CHECKS[name] = Check(name=name, title=title, description=description, noun=noun, dataset=dataset, run=function)
        return function
    return register


# the most problems a check sends to the page: enough to work through, not
# thousands of rows (problem_count still says how many there are)
PROBLEMS_SHOWN = 500


def result_json(chosen: Check, result: Result) -> dict[str, Any]:
    return {
        "name": chosen.name,
        "title": chosen.title,
        "noun": chosen.noun,
        "dataset": chosen.dataset,
        "checked": result.checked,
        "ok": result.ok,
        "problem_count": len(result.problems),
        "problems": [dataclasses.asdict(p) for p in result.problems[:PROBLEMS_SHOWN]],
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
    organizations = session.execute(select(Organization.id, Organization.owner_id, Organization.name, Organization.image_id).order_by(Organization.name)).all()
    problems = [
        Problem(f"{name} (organization {organization_id}, account {owner_id})", "has no logo", f"organizations/{organization_id}", owner_id)
        for organization_id, owner_id, name, image_id in organizations
        if image_id is None
    ]
    return Result(checked=len(organizations), problems=problems)


@check("organization-relations", "Every organization is related to you", "organizations", "organizations")
def check_organization_relations(session: Session) -> Result:
    """ Every organization, of every account, has at least one relation type (taught there, consulted, ...). """
    related = set(session.scalars(select(organization_relation_types.c.organization_id)))
    organizations = session.execute(select(Organization.id, Organization.owner_id, Organization.name).order_by(Organization.name)).all()
    problems = [
        Problem(f"{name} (organization {organization_id}, account {owner_id})", "has no relation type", f"organizations/{organization_id}", owner_id)
        for organization_id, owner_id, name in organizations
        if organization_id not in related
    ]
    return Result(checked=len(organizations), problems=problems)


@check("organization-addresses", "Every organization has an address", "organizations", "organizations")
def check_organization_addresses(session: Session) -> Result:
    """ Every organization, of every account, has an address (the office you knew, not only the city). """
    organizations = session.execute(select(Organization.id, Organization.owner_id, Organization.name, Organization.address).order_by(Organization.name)).all()
    problems = [
        Problem(f"{name} (organization {organization_id}, account {owner_id})", "has no address", f"organizations/{organization_id}", owner_id)
        for organization_id, owner_id, name, address in organizations
        if not address.strip()
    ]
    return Result(checked=len(organizations), problems=problems)


@check("organization-locations", "Every organization is on the map", "organizations", "organizations")
def check_organization_locations(session: Session) -> Result:
    """ Every organization, of every account, has a latitude and a longitude (scripts/geocode.py finds them from the address). """
    organizations = session.execute(
        select(Organization.id, Organization.owner_id, Organization.name, Organization.latitude, Organization.longitude).order_by(Organization.name),
    ).all()
    problems = [
        Problem(f"{name} (organization {organization_id}, account {owner_id})", "has no latitude and longitude", f"organizations/{organization_id}", owner_id)
        for organization_id, owner_id, name, latitude, longitude in organizations
        if latitude is None or longitude is None
    ]
    return Result(checked=len(organizations), problems=problems)


# ─── people ─────────────────────────────────────────────────────────────────

@check("people-types", "Every person has a type", "people", "people")
def check_person_types(session: Session) -> Result:
    """ Every person, of every account, is categorized as at least one person type (family, co-worker, ...). """
    typed = set(session.scalars(select(person_type_links.c.person_id)))
    people = session.scalars(select(Person).order_by(Person.owner_id, Person.first_name, Person.surname, Person.id)).all()
    problems = [
        Problem(f"{person.name} (person {person.id}, account {person.owner_id})", "has no type", f"people/{person.id}", person.owner_id)
        for person in people
        if person.id not in typed
    ]
    return Result(checked=len(people), problems=problems)


# ─── museums ────────────────────────────────────────────────────────────────

@check("museum-dates", "Every museum visit has a date", "museum visits", "museums")
def check_museum_dates(session: Session) -> Result:
    """ Every museum visit, of every account, has a date: a day, a month, a year or a full time, whichever is known. """
    visits = session.scalars(select(Museum).order_by(Museum.owner_id, Museum.name, Museum.id)).all()
    problems = [
        Problem(f"{visit.name} (museum visit {visit.id}, account {visit.owner_id})", "has no date", f"museums/{visit.id}", visit.owner_id)
        for visit in visits
        if visit.date_utcz is None and visit.date_ymd is None and not visit.date_my and visit.date_y is None
    ]
    return Result(checked=len(visits), problems=problems)


@check("museum-addresses", "Every museum visit has an address", "museum visits", "museums")
def check_museum_addresses(session: Session) -> Result:
    """ Every museum visit, of every account, has the museum's street address. """
    visits = session.scalars(select(Museum).order_by(Museum.owner_id, Museum.name, Museum.id)).all()
    problems = [
        Problem(f"{visit.name} (museum visit {visit.id}, account {visit.owner_id})", "has no address", f"museums/{visit.id}", visit.owner_id)
        for visit in visits
        if not visit.address.strip()
    ]
    return Result(checked=len(visits), problems=problems)


@check("museum-locations", "Every museum visit is on the map", "museum visits", "museums")
def check_museum_locations(session: Session) -> Result:
    """ Every museum visit, of every account, has a latitude and a longitude (scripts/geocode.py finds them from the address). """
    visits = session.scalars(select(Museum).order_by(Museum.owner_id, Museum.name, Museum.id)).all()
    problems = [
        Problem(f"{visit.name} (museum visit {visit.id}, account {visit.owner_id})", "has no latitude and longitude", f"museums/{visit.id}", visit.owner_id)
        for visit in visits
        if visit.latitude is None or visit.longitude is None
    ]
    return Result(checked=len(visits), problems=problems)


@check("museum-company", "Every museum visit says who you were with", "museum visits", "museums")
def check_museum_company(session: Session) -> Result:
    """
    Every museum visit, of every account, either has the people you went
    with or is marked "I went alone", so an empty With is never a gap
    nobody filled in; and none is both.
    """
    with_people = set(session.scalars(select(museum_companions.c.museum_id)))
    visits = session.scalars(select(Museum).order_by(Museum.owner_id, Museum.name, Museum.id)).all()
    problems = []
    for visit in visits:
        subject = f"{visit.name} (museum visit {visit.id}, account {visit.owner_id})"
        if visit.alone and visit.id in with_people:
            problems.append(Problem(subject, "is marked alone but has people in With", f"museums/{visit.id}", visit.owner_id))
        elif not visit.alone and visit.id not in with_people:
            problems.append(Problem(subject, "has no one in With and is not marked alone", f"museums/{visit.id}", visit.owner_id))
    return Result(checked=len(visits), problems=problems)


# ─── audio courses ──────────────────────────────────────────────────────────

# in progress for longer than this, a course is reported as stalled
STALLED_AFTER = datetime.timedelta(days=365)


def _courses(session: Session) -> list[AudioCourse]:
    return list(session.scalars(select(AudioCourse).order_by(AudioCourse.owner_id, AudioCourse.name, AudioCourse.id)))


def _course_problem(course: AudioCourse, message: str) -> Problem:
    return Problem(f"{course.name} (audio course {course.id}, account {course.owner_id})", message, f"audio-courses/{course.id}", course.owner_id)


def _finished(course: AudioCourse | YouTubeVideo | Concert) -> bool:
    """ Whether it has a date, at any precision: the day it was finished. """
    return course.date_utcz is not None or course.date_ymd is not None or bool(course.date_my) or course.date_y is not None


@check("audio-course-lecturers", "Every audio course has a lecturer", "audio courses", "audio-courses")
def check_audio_course_lecturers(session: Session) -> Result:
    """ Every audio course, of every account, has at least one lecturer (a person). """
    taught = set(session.scalars(select(audio_course_lecturers.c.audio_course_id)))
    courses = _courses(session)
    return Result(checked=len(courses), problems=[_course_problem(c, "has no lecturer") for c in courses if c.id not in taught])


@check("audio-course-devices", "Every audio course has a device", "audio courses", "audio-courses")
def check_audio_course_devices(session: Session) -> Result:
    """ Every audio course, of every account, says what it was played on (one of the account's devices). """
    courses = _courses(session)
    return Result(checked=len(courses), problems=[_course_problem(c, "has no device") for c in courses if c.device_id is None])


@check("audio-course-status", "Every audio course is finished or in progress", "audio courses", "audio-courses")
def check_audio_course_status(session: Session) -> Result:
    """
    Every audio course, of every account, is either finished (it has a date)
    or in progress (it has a start), never neither.
    """
    courses = _courses(session)
    problems = [
        _course_problem(c, "has neither a finished date nor a start: is it finished or in progress?")
        for c in courses
        if not _finished(c) and c.started_utcz is None
    ]
    return Result(checked=len(courses), problems=problems)


@check("audio-course-reviews", "Every finished audio course is rated and reviewed", "finished audio courses", "audio-courses")
def check_audio_course_reviews(session: Session) -> Result:
    """ Every finished audio course, of every account, has a rating and a review; one still in progress need not. """
    finished = [c for c in _courses(session) if _finished(c)]
    problems = []
    for course in finished:
        missing = [what for what, absent in (("rating", course.rating is None), ("review", not course.review.strip())) if absent]
        if missing:
            problems.append(_course_problem(course, f"is finished but has no {' and no '.join(missing)}"))
    return Result(checked=len(finished), problems=problems)


@check("audio-course-covers", "Every audio course has a cover", "audio courses", "audio-courses")
def check_audio_course_covers(session: Session) -> Result:
    """ Every audio course, of every account, has a cover image. """
    courses = _courses(session)
    return Result(checked=len(courses), problems=[_course_problem(c, "has no cover") for c in courses if c.image_id is None])


@check("audio-course-links", "Every audio course links to its page", "audio courses", "audio-courses")
def check_audio_course_links(session: Session) -> Result:
    """
    Every audio course, of every account, has a Great Courses slug, an
    Audible ASIN or a link (any page about it, for one no longer sold), so
    its card links to its page.
    """
    courses = _courses(session)
    problems = [
        _course_problem(c, "has no Great Courses slug, Audible ASIN or link")
        for c in courses
        if not c.great_courses_slug.strip() and not c.audible_asin.strip() and not c.link.strip()
    ]
    return Result(checked=len(courses), problems=problems)


@check("audio-course-stalled", "No audio course is stuck in progress", "audio courses in progress", "audio-courses")
def check_audio_course_stalled(session: Session) -> Result:
    """
    No audio course, of any account, has been in progress (started, not
    finished) for more than a year: finish it, or say how far it got and
    give up on it.
    """
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    running = [c for c in _courses(session) if not _finished(c) and c.started_utcz is not None]
    problems = []
    for course in running:
        assert course.started_utcz is not None
        waited = now - course.started_utcz
        if waited > STALLED_AFTER:
            progress = f", at {course.progress}" if course.progress else ""
            problems.append(_course_problem(course, f"in progress since {course.started_utcz.date().isoformat()} ({waited.days} days{progress})"))
    return Result(checked=len(running), problems=problems)


@check("audio-course-duplicates", "No audio course is listed twice", "audio courses", "audio-courses")
def check_audio_course_duplicates(session: Session) -> Result:
    """ No account has two audio courses of the same name (ignoring case and spaces at the ends). """
    courses = _courses(session)
    seen: dict[tuple[int, str], list[AudioCourse]] = {}
    for course in courses:
        seen.setdefault((course.owner_id, course.name.strip().lower()), []).append(course)
    problems = [
        _course_problem(course, f"has the same name as {len(same) - 1} other audio course{'s' if len(same) > 2 else ''} of the account")
        for same in seen.values()
        if len(same) > 1
        for course in same
    ]
    return Result(checked=len(courses), problems=problems)


def _entries(session: Session, kind: str) -> list[UserWork]:
    """ Every account's library entries of a kind, with their works. """
    query = select(UserWork).join(Work).where(Work.kind == kind).order_by(UserWork.user_id, Work.title, Work.id)
    return list(session.scalars(query))


def _entry_problem(entry: UserWork, message: str) -> Problem:
    kind = entry.work.kind
    return Problem(f"{entry.work.title} ({KINDS[kind][0].lower()} {entry.work_id}, account {entry.user_id})", message, f"{kind}/{entry.work_id}", entry.user_id)


# what having done a library kind is called: a book read
DONE_VERBS = {"book": "read"}


def _library_checks(kind: str) -> None:
    """ The checks every library kind has: a cover, a rating once done, no entry twice. """
    name, plural, creator = KINDS[kind]
    noun, verb = plural.lower(), DONE_VERBS[kind]
    one = name.lower()

    def covers(session: Session) -> Result:
        entries = _entries(session, kind)
        return Result(checked=len(entries), problems=[_entry_problem(e, "has no cover") for e in entries if e.image_id is None])

    def ratings(session: Session) -> Result:
        done = [e for e in _entries(session, kind) if e.status == "done"]
        return Result(checked=len(done), problems=[_entry_problem(e, f"is {verb} but has no rating") for e in done if e.rating is None])

    def duplicates(session: Session) -> Result:
        entries = _entries(session, kind)
        seen: dict[tuple[int, str, str], list[UserWork]] = {}
        for entry in entries:
            seen.setdefault((entry.user_id, entry.work.title.strip().lower(), entry.work.creator.strip().lower()), []).append(entry)
        problems = [
            _entry_problem(entry, f"has the same title and {creator.lower()} as {len(same) - 1} other {one if len(same) == 2 else noun} of the account")
            for same in seen.values()
            if len(same) > 1
            for entry in same
        ]
        return Result(checked=len(entries), problems=problems)

    covers.__doc__ = f"Every {one} in a library, of every account, has a cover image."
    ratings.__doc__ = f"Every {one} an account has {verb} (Done), of every account, has a rating; one not {verb} yet need not."
    duplicates.__doc__ = f"No account has two {noun} of the same title and {creator.lower()} (ignoring case and spaces at the ends), as two works."
    check(f"{kind}-covers", f"Every {one} has a cover", noun, kind)(covers)
    check(f"{kind}-ratings", f"Every {one} {verb} is rated", f"{noun} {verb}", kind)(ratings)
    check(f"{kind}-duplicates", f"No {one} is listed twice", noun, kind)(duplicates)


for _kind in KINDS:
    _library_checks(_kind)


@check("book-links", "Every book links to its page", "books", "book")
def check_book_links(session: Session) -> Result:
    """ Every book in a library, of every account, has a Goodreads or a Simania id, so its card links to its page. """
    books = _entries(session, "book")
    problems = [
        _entry_problem(b, "has neither a Goodreads nor a Simania id")
        for b in books
        if not b.work.goodreads_id.strip() and not b.work.simania_id.strip()
    ]
    return Result(checked=len(books), problems=problems)


@check("book-authors", "Every book has an author", "books", "book")
def check_book_authors(session: Session) -> Result:
    """ Every book in a library, of every account, has an author: one of the account's people (a Book Author), linked to it. """
    books = _entries(session, "book")
    written = set(session.execute(select(library_entry_authors.c.user_id, library_entry_authors.c.work_id)).tuples())
    return Result(checked=len(books), problems=[_entry_problem(b, "has no author") for b in books if (b.user_id, b.work_id) not in written])


# ─── concerts ───────────────────────────────────────────────────────────────

def _concerts(session: Session) -> list[Concert]:
    return list(session.scalars(select(Concert).order_by(Concert.owner_id, Concert.name, Concert.id)))


def _concert_problem(concert: Concert, message: str) -> Problem:
    return Problem(f"{concert.name} (concert {concert.id}, account {concert.owner_id})", message, f"concerts/{concert.id}", concert.owner_id)


@check("concert-dates", "Every concert has a date", "concerts", "concerts")
def check_concert_dates(session: Session) -> Result:
    """ Every concert, of every account, has a date (a day, a month, a year or a full time). """
    concerts = _concerts(session)
    return Result(checked=len(concerts), problems=[_concert_problem(c, "has no date") for c in concerts if not _finished(c)])


@check("concert-places", "Every concert says where it was", "concerts", "concerts")
def check_concert_places(session: Session) -> Result:
    """ Every concert, of every account, has a venue and a city; one seen on TV need not. """
    concerts = _concerts(session)
    problems = []
    for concert in concerts:
        missing = [what for what, absent in (("venue", not concert.venue.strip()), ("city", not concert.city.strip())) if absent]
        if missing and not concert.broadcast:
            problems.append(_concert_problem(concert, f"has no {' and no '.join(missing)}"))
    return Result(checked=len(concerts), problems=problems)


@check("concert-performers", "Every concert has a performer", "concerts", "concerts")
def check_concert_performers(session: Session) -> Result:
    """ Every concert, of every account, has at least one performer (a person). """
    performed = set(session.scalars(select(concert_performers.c.concert_id)))
    concerts = _concerts(session)
    return Result(checked=len(concerts), problems=[_concert_problem(c, "has no performer") for c in concerts if c.id not in performed])


@check("concert-photos", "Every concert has a photo", "concerts", "concerts")
def check_concert_photos(session: Session) -> Result:
    """ Every concert, of every account, has a photo. """
    concerts = _concerts(session)
    return Result(checked=len(concerts), problems=[_concert_problem(c, "has no photo") for c in concerts if c.image_id is None])


@check("concert-duplicates", "No concert is listed twice", "concerts", "concerts")
def check_concert_duplicates(session: Session) -> Result:
    """ No account has two concerts of the same name on the same date (ignoring case and spaces at the ends). """
    concerts = _concerts(session)
    seen: dict[tuple[int, str, str], list[Concert]] = {}
    for concert in concerts:
        when = str(concert.date_utcz or concert.date_ymd or concert.date_my or concert.date_y or "")
        seen.setdefault((concert.owner_id, concert.name.strip().lower(), when), []).append(concert)
    problems = [
        _concert_problem(concert, f"has the same name and date as {len(same) - 1} other concert{'s' if len(same) > 2 else ''} of the account")
        for same in seen.values()
        if len(same) > 1
        for concert in same
    ]
    return Result(checked=len(concerts), problems=problems)


# ─── the user's enumerations: org, person and relation types, devices ───────

type _Enumeration = type[OrganizationType | PersonType | RelationType | Device]


def _enumeration_checks(dataset: str, model: _Enumeration, used: Callable[[Session], set[int]]) -> None:
    """ The checks every enumeration has: each value used, described, and not there twice. """
    one = DATASETS[dataset].lower().removesuffix("s").replace("org ", "organization ")
    noun = f"{one}s"

    def rows(session: Session) -> list[Any]:
        return list(session.scalars(select(model).order_by(model.owner_id, model.name, model.id)))

    def problem(row: Any, message: str) -> Problem:
        return Problem(f"{row.name} ({one} {row.id}, account {row.owner_id})", message, f"{dataset}/{row.id}", row.owner_id)

    def check_used(session: Session) -> Result:
        all_rows, in_use = rows(session), used(session)
        return Result(checked=len(all_rows), problems=[problem(r, "is used by nothing") for r in all_rows if r.id not in in_use])

    def check_described(session: Session) -> Result:
        all_rows = rows(session)
        return Result(checked=len(all_rows), problems=[problem(r, "has no description") for r in all_rows if not r.description.strip()])

    def check_twice(session: Session) -> Result:
        all_rows = rows(session)
        seen: dict[tuple[int, str], list[Any]] = {}
        for row in all_rows:
            seen.setdefault((row.owner_id, row.name.strip().lower()), []).append(row)
        problems = [
            problem(row, f"has the same name as {len(same) - 1} other {one if len(same) == 2 else noun} of the account")
            for same in seen.values()
            if len(same) > 1
            for row in same
        ]
        return Result(checked=len(all_rows), problems=problems)

    check_used.__doc__ = f"Every {one}, of every account, is used by at least one row; one used by nothing can go."
    check_described.__doc__ = f"Every {one}, of every account, has a description, so its tooltip and page say what it means."
    check_twice.__doc__ = f"No account has two {noun} of the same name (ignoring case and spaces at the ends)."
    prefix = dataset.removesuffix("s")
    check(f"{prefix}-used", f"Every {one} is used", noun, dataset)(check_used)
    check(f"{prefix}-descriptions", f"Every {one} has a description", noun, dataset)(check_described)
    check(f"{prefix}-duplicates", f"No {one} is listed twice", noun, dataset)(check_twice)


def _ids(session: Session, *columns: Any) -> set[int]:
    """ The non-null values of the given id columns, together. """
    found: set[int] = set()
    for column in columns:
        found |= {value for value in session.scalars(select(column)) if value is not None}
    return found


_enumeration_checks("organization-types", OrganizationType, lambda session: _ids(session, Organization.type_id))
_enumeration_checks("person-types", PersonType, lambda session: _ids(session, person_type_links.c.person_type_id))
_enumeration_checks("relation-types", RelationType, lambda session: _ids(session, organization_relation_types.c.relation_type_id))
_enumeration_checks("devices", Device, lambda session: _ids(session, AudioCourse.device_id, YouTubeVideo.device_id))


def _videos(session: Session) -> list[YouTubeVideo]:
    return list(session.scalars(select(YouTubeVideo).order_by(YouTubeVideo.owner_id, YouTubeVideo.name, YouTubeVideo.id)))


def _video_problem(video: YouTubeVideo, message: str) -> Problem:
    return Problem(f"{video.name} (YouTube video {video.id}, account {video.owner_id})", message, f"youtube/{video.id}", video.owner_id)


YOUTUBE_ID = re.compile(rf"[A-Za-z0-9_-]{{{YOUTUBE_ID_LENGTH}}}")


@check("youtube-ids", "Every YouTube video has a well-formed id", "YouTube videos", "youtube")
def check_youtube_ids(session: Session) -> Result:
    """
    Every YouTube video, of every account, has an id YouTube could have
    given: 11 letters, digits, - and _. One that is not links to no video.
    """
    videos = _videos(session)
    problems = [
        _video_problem(v, f"has the id {v.youtube_id!r}, not {YOUTUBE_ID_LENGTH} letters, digits, - and _")
        for v in videos
        if not YOUTUBE_ID.fullmatch(v.youtube_id)
    ]
    return Result(checked=len(videos), problems=problems)


@check("youtube-dates", "Every YouTube video has a date", "YouTube videos", "youtube")
def check_youtube_dates(session: Session) -> Result:
    """ Every YouTube video, of every account, has the date it was watched (a day, a month, a year or a full time). """
    videos = _videos(session)
    return Result(checked=len(videos), problems=[_video_problem(v, "has no date") for v in videos if not _finished(v)])


@check("youtube-reviews", "Every YouTube video is rated and reviewed", "YouTube videos", "youtube")
def check_youtube_reviews(session: Session) -> Result:
    """ Every YouTube video, of every account, has a rating and a review. """
    videos = _videos(session)
    problems = []
    for video in videos:
        missing = [what for what, absent in (("rating", video.rating is None), ("review", not video.review.strip())) if absent]
        if missing:
            problems.append(_video_problem(video, f"has no {' and no '.join(missing)}"))
    return Result(checked=len(videos), problems=problems)


@check("youtube-devices", "Every YouTube video has a device", "YouTube videos", "youtube")
def check_youtube_devices(session: Session) -> Result:
    """ Every YouTube video, of every account, has the device it was watched on. """
    videos = _videos(session)
    return Result(checked=len(videos), problems=[_video_problem(v, "has no device") for v in videos if v.device_id is None])
