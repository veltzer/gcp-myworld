#!/usr/bin/env python

"""
Load concerts, museum visits, people and organizations, with their images, into
the database for one user.

The source is a directory laid out the way veltzer.github.io keeps them:
data/yaml/{concerts,museums,people,organizations}.yaml, the photos in
static/images/ (concert-*.jpg named by each concert's image field,
museum-<internal_id>.jpg for the first visit of each museum, which every
later visit of the same museum shares) and the organization logos in
data/logos/.

The organizations are those of organizations.yaml plus every one a person
names (the company field of people.yaml) that is not among them; each person
is linked to the organizations they name.

Audio courses come from data/yaml/audio_courses.yaml, their covers from
static/images/audiocourse-{gc-<great_courses_id>,audible-<asin>,internal-<n>}.jpg;
each lecturer is a person (one of the same name, or a new one), typed Lecturer,
and each device one of the account's devices (made when first named).

YouTube videos come from data/yaml/video_youtube.yaml (the reviewed ones)
and static/data/youtube.json.gz (the watch history: what YouTube says about
each video, no date or review); a video in both is one row. Their
thumbnails are YouTube's own, so there is no image to import. Their devices
are the same list as the audio courses'.

Everything the user had in these tables is replaced, in one transaction, so
the script is safe to run again. Unknown fields in the YAML stop the import
rather than being dropped, so nothing is lost on the way in.

The user must have signed in at least once; pass the email they signed in
with (and --subject when that email has several accounts, e.g. Google and
GitHub).

  scripts/import_world.py --email me@example.com [--source ../veltzer.github.io]

With --audio-courses only the audio courses are imported, added to what the
account already has and touching nothing else; it stops if the account has
audio courses already, rather than replace what was edited since. --youtube
does the same for the YouTube videos. --youtube-history adds the watch
history to the videos there are: the ones not there yet as new rows, and
YouTube's details (channel, category, ...) on those already there; it can
run again.

The database is DATABASE_URL (default: the local sqlite file); for Cloud SQL
see doc/deploy.md.
"""

import argparse
import datetime
import gzip
import hashlib
import json
import mimetypes
import re
import sys
from pathlib import Path
from typing import Any

# the myworld package is in src/, not installed: find it from any directory, no PYTHONPATH needed
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import yaml
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session, selectinload

from myworld.models import (
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
    User,
    YouTubeVideo,
    audio_course_lecturers,
    concert_companions,
    concert_performers,
    make_engine,
    museum_companions,
    organization_relation_types,
    person_organizations,
    person_type_links,
)

DATE_FIELDS = {"date_utcz", "date_ymd", "date_my", "date_y", "date_timezone"}
# company: the name, or a list of names, of the organizations the person is at
PERSON_FIELDS = {"name", "company", "description"}
CONCERT_FIELDS = DATE_FIELDS | {
    "name", "performers", "event", "genre", "venue", "city", "country", "with", "tickets",
    "broadcast", "review", "remark", "image", "image_source", "image_license", "image_author",
}
# organization fields that have a column of their own (functions: the relation
# types); logo names the logo file
ORGANIZATION_COLUMNS = {"name", "type", "functions", "status", "website", "location", "address", "what_happened", "remark"}
# kept as they are in organizations.details
ORGANIZATION_DETAILS = {
    "id", "slug", "logo_kind", "logo_source", "logo_license", "logo_note", "old_url", "location_geo",
    "israel_office", "israel_office_geo", "former_website", "former_location", "former_location_geo",
    "address_source", "geo", "sources", "from_date",
}
# the organization types every import starts the user with; more are added on
# the Org types page, or by a type the YAML names
ORGANIZATION_TYPES = {
    "Company": "A business",
    "University": "Grants degrees and does research",
    "College": "A school past high school that is not a university",
    "Government": "A ministry, office or agency of the state",
    "Public body": "Owned or chartered by the public, not a ministry",
    "Military": "An army unit or school",
    "Non-profit": "A charity or other organization not run for profit",
}
DEFAULT_ORGANIZATION_TYPE = "Company"
# the person types every import starts the user with
PERSON_TYPES = {
    "Family": "A relative",
    "Girlfriend": "A girlfriend, now or before",
    "Performer": "Someone seen on stage",
    "Co-Worker": "Someone worked with",
    "Lecturer": "Someone who taught a course I took",
}
# the relation types (how an organization is related to the user) every import
# starts the user with, by the word organizations.yaml uses in its functions
# field: (name, description). scripts/migrate.sh names them the same way.
RELATION_TYPES = {
    "teaching": ("Teaching", "I taught there"),
    "training-provider": ("Training provider", "Hired me to teach"),
    "consulting": ("Consulting", "I consulted for them"),
    "certification": ("Certification", "Certified me"),
    "publisher": ("Publisher", "I consumed media they published"),
    "education": ("Education", "I studied there"),
}
# what _person_type reads a person's type from
FAMILY_NAME = "Veltzer"
FAMILY_DESCRIPTION = re.compile(r"my (brother|sister|mother|father|son|daughter|wife|husband|cousin|uncle|aunt)\b", re.IGNORECASE)
GIRLFRIEND_DESCRIPTION = re.compile(r"(ex-)?girlfriend\b", re.IGNORECASE)
TWO_WORD_NAME = re.compile(r"([A-Z][^ ]*) ([A-Z][^ ]*)")
CO_WORKER_DESCRIPTION = re.compile(r"\bMAFAT\b|\bwork(ed)? with\b")
# organizations.yaml has no type field (yet): these are the ones that are not a
# company; a type field in the YAML (a type name) wins over this list
ORGANIZATION_TYPE_BY_NAME = {
    "Hebrew University of Jerusalem": "University",
    "Open University of Israel": "University",
    "Tel Aviv University": "University",
    "Rimon School of Music": "College",
    "Israeli Defence Ministry": "Government",
    "Prime ministers office": "Government",
    "Bank of Israel": "Government",
    "Bituach Leumi": "Government",
    "Mifal Hapayis": "Public body",
    "BBC Radio": "Public body",
    "Basmach": "Military",
    "MercyCorps": "Non-profit",
}
ORGANIZATION_FIELDS = ORGANIZATION_COLUMNS | ORGANIZATION_DETAILS | {"logo"}
# internal_id only names the image file; it is not stored
AUDIO_COURSE_FIELDS = DATE_FIELDS | {
    "name", "lecturers", "rating", "review", "device", "location", "date_started_utcz", "date_ended_utcz", "progress",
    "great_courses_id", "great_courses_slug", "audible_asin", "internal_id",
}
YOUTUBE_FIELDS = DATE_FIELDS | {"id", "name", "rating", "review", "device", "location"}
# the watch history: yt-dlp's names; status "missing" (with video_id) is a video YouTube no longer has
YOUTUBE_HISTORY_FIELDS = {"title", "webpage_url", "channel", "categories", "duration", "upload_date", "view_count", "status", "video_id"}
# rows per multi-row INSERT: 18 columns each stays well under PostgreSQL's 65,535 parameters
INSERT_CHUNK = 2000
YOUTUBE_WATCH = re.compile(r"https://www\.youtube\.com/watch\?v=([A-Za-z0-9_-]{11})")
# internal_id only names the image file; it is not stored
MUSEUM_FIELDS = DATE_FIELDS | {
    "name", "city", "rating", "review", "remark", "url", "tickets", "with", "internal_id",
}


class WorldImportError(Exception):
    pass


def _items(source: Path, name: str, fields: set[str]) -> list[dict[str, Any]]:
    path = source / "data" / "yaml" / f"{name}.yaml"
    with path.open(encoding="UTF8") as fp:
        items = yaml.safe_load(fp)["items"]
    for item in items:
        unknown = set(item) - fields
        if unknown:
            raise WorldImportError(f"{path}: {item.get('name')!r} has fields this import does not know: {sorted(unknown)}")
    return items


def _dates(item: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"date_timezone": item.get("date_timezone", "")}
    if "date_utcz" in item:
        stamp = datetime.datetime.fromisoformat(str(item["date_utcz"]))
        out["date_utcz"] = stamp.astimezone(datetime.UTC).replace(tzinfo=None)
    if "date_ymd" in item:
        out["date_ymd"] = datetime.date.fromisoformat(str(item["date_ymd"]))
    if "date_my" in item:
        value = str(item["date_my"])
        month, year = value.split("-")
        if len(month) != 2 or len(year) != 4:
            raise WorldImportError(f"{item['name']!r}: date_my {value!r} is not MM-YYYY")
        out["date_my"] = value
    if "date_y" in item:
        out["date_y"] = int(item["date_y"])
    return out


def _person_organizations(item: dict[str, Any]) -> list[str]:
    """ company in people.yaml: one organization name, or a list of them. """
    value = item.get("company", [])
    names = [value] if isinstance(value, str) else list(value)
    if len(set(names)) != len(names):
        raise WorldImportError(f"people.yaml: {item['name']!r} names an organization twice")
    return names


def _json_safe(value: Any) -> Any:
    """ YAML may hand over dates; JSON columns want strings. """
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def type_for(name: str) -> str:
    """ The type name an organization of organizations.yaml gets when the YAML does not say. """
    return ORGANIZATION_TYPE_BY_NAME.get(name, DEFAULT_ORGANIZATION_TYPE)


def split_name(name: str) -> tuple[str, str]:
    """
    A whole name as (first name, surname): split only when it is plainly two
    capitalized words ("Doron Veltzer", "Yaron Ben-Ami"); anything else ("Oded
    from MAFAT", "The Band", three words) is all first name, to split by hand.
    scripts/migrate.sh splits the names already in a database the same way.
    """
    match = TWO_WORD_NAME.fullmatch(name)
    if match is None or match.group(1) == "The":
        return name, ""
    return match.group(1), match.group(2)


def _person_type(person: Person) -> str | None:
    """
    A first guess at what a person is, from what the data already says;
    None when nothing does. Only ever used for people without a type.
    """
    if person.name.endswith(f" {FAMILY_NAME}") or FAMILY_DESCRIPTION.match(person.description):
        return "Family"
    if GIRLFRIEND_DESCRIPTION.match(person.description):
        return "Girlfriend"
    if person.organizations or CO_WORKER_DESCRIPTION.search(person.description):
        return "Co-Worker"
    if person.performed:
        return "Performer"
    if person.lectured:
        return "Lecturer"
    return None


def _starting_types[T: (OrganizationType, PersonType, RelationType)](
    session: Session, owner: User, model: type[T], starting: dict[str, str],
) -> tuple[dict[str, T], int]:
    """ owner's types of model by name, after adding those of starting they lack, and how many were added. """
    types = {t.name: t for t in session.scalars(select(model).where(model.owner_id == owner.id))}
    added = 0
    for name, description in starting.items():
        if name not in types:
            types[name] = model(owner_id=owner.id, name=name, description=description)
            session.add(types[name])
            added += 1
    return types, added


def give_types(session: Session, owner: User) -> dict[str, int]:
    """
    Add the starting organization and person types owner does not have yet,
    and give every organization and person of theirs without a type one
    (organizations by name, else Company; people by _person_type), leaving
    everything else as it is. Does not commit.
    """
    org_types, org_added = _starting_types(session, owner, OrganizationType, ORGANIZATION_TYPES)
    person_types, person_added = _starting_types(session, owner, PersonType, PERSON_TYPES)
    _, relation_added = _starting_types(session, owner, RelationType, dict(RELATION_TYPES.values()))
    added = org_added + person_added + relation_added
    typed = 0
    for organization in session.scalars(select(Organization).where(Organization.owner_id == owner.id, Organization.type_id.is_(None))):
        organization.type = org_types[type_for(organization.name)]
        typed += 1
    people = session.scalars(
        select(Person)
        .where(Person.owner_id == owner.id, ~Person.types.any())
        .options(selectinload(Person.organizations), selectinload(Person.performed), selectinload(Person.lectured))
    )
    people_typed = 0
    for person in people:
        name = _person_type(person)
        if name is not None:
            person.types = [person_types[name]]
            people_typed += 1
    session.flush()
    return {"types added": added, "organizations given a type": typed, "people given a type": people_typed}


def find_owner(session: Session, email: str, subject: str | None) -> User:
    users = session.execute(select(User).where(User.email == email)).scalars().all()
    if subject is not None:
        users = [u for u in users if u.google_sub == subject]
    if not users:
        raise WorldImportError(f"no account for {email}{f' with subject {subject}' if subject else ''}: sign in once first")
    if len(users) > 1:
        subjects = ", ".join(u.google_sub for u in users)
        raise WorldImportError(f"{email} has several accounts, pick one with --subject: {subjects}")
    return users[0]


def import_world(session: Session, owner: User, source: Path) -> dict[str, int]:
    """ Replace owner's concerts, museums, people, organizations and images with those under source. Does not commit. """
    people_items = _items(source, "people", PERSON_FIELDS)
    organization_items = _items(source, "organizations", ORGANIZATION_FIELDS)
    concert_items = _items(source, "concerts", CONCERT_FIELDS)
    museum_items = _items(source, "museums", MUSEUM_FIELDS)
    image_dir = source / "static" / "images"

    # the link rows explicitly: sqlite does not enforce ON DELETE CASCADE unless asked to
    concerts_of_owner = select(Concert.id).where(Concert.owner_id == owner.id)
    session.execute(delete(concert_companions).where(concert_companions.c.concert_id.in_(concerts_of_owner)))
    session.execute(delete(concert_performers).where(concert_performers.c.concert_id.in_(concerts_of_owner)))
    session.execute(delete(museum_companions).where(museum_companions.c.museum_id.in_(select(Museum.id).where(Museum.owner_id == owner.id))))
    session.execute(delete(audio_course_lecturers).where(
        audio_course_lecturers.c.audio_course_id.in_(select(AudioCourse.id).where(AudioCourse.owner_id == owner.id)),
    ))
    session.execute(delete(person_type_links).where(person_type_links.c.person_id.in_(select(Person.id).where(Person.owner_id == owner.id))))
    session.execute(delete(person_organizations).where(person_organizations.c.person_id.in_(select(Person.id).where(Person.owner_id == owner.id))))
    session.execute(delete(organization_relation_types).where(
        organization_relation_types.c.organization_id.in_(select(Organization.id).where(Organization.owner_id == owner.id)),
    ))
    for model in (AudioCourse, YouTubeVideo, Device, Concert, Museum, Person, Organization, OrganizationType, PersonType, RelationType, Image):
        session.execute(delete(model).where(model.owner_id == owner.id))
    session.flush()

    images: dict[str, Image] = {}

    def image(path: Path, required: bool) -> Image | None:
        filename = path.name
        if filename in images:
            return images[filename]
        if not path.exists():
            if required:
                raise WorldImportError(f"missing image {path}")
            return None
        data = path.read_bytes()
        content_type = mimetypes.guess_type(filename)[0]
        if content_type is None or not content_type.startswith("image/"):
            raise WorldImportError(f"{path}: not an image type")
        images[filename] = Image(
            owner_id=owner.id, filename=filename, content_type=content_type,
            sha256=hashlib.sha256(data).hexdigest(), data=data,
        )
        session.add(images[filename])
        return images[filename]

    types: dict[str, OrganizationType] = {}

    def organization_type(name: str) -> OrganizationType:
        if name not in types:
            types[name] = OrganizationType(owner_id=owner.id, name=name, description=ORGANIZATION_TYPES.get(name, ""))
            session.add(types[name])
        return types[name]

    for name in ORGANIZATION_TYPES:
        organization_type(name)

    relation_types: dict[str, RelationType] = {}

    def relation_type(word: str) -> RelationType:
        """ The relation type for a word of the functions field; one not in RELATION_TYPES is named after the word. """
        name, description = RELATION_TYPES.get(word, (word.replace("-", " ").capitalize(), ""))
        if name not in relation_types:
            relation_types[name] = RelationType(owner_id=owner.id, name=name, description=description)
            session.add(relation_types[name])
        return relation_types[name]

    for word in RELATION_TYPES:
        relation_type(word)

    organizations: dict[str, Organization] = {}
    for item in organization_items:
        if item["name"] in organizations:
            raise WorldImportError(f"organizations.yaml: {item['name']!r} appears twice")
        organization = Organization(
            owner_id=owner.id,
            name=item["name"],
            type=organization_type(item.get("type") or type_for(item["name"])),
            relations=[relation_type(word) for word in dict.fromkeys(item.get("functions", []))],
            **{key: item.get(key, "") for key in sorted(ORGANIZATION_COLUMNS - {"name", "type", "functions"})},
            details={key: _json_safe(item[key]) for key in sorted(ORGANIZATION_DETAILS) if key in item},
            # logos live in data/, as logos/<slug>.svg
            image=image(source / "data" / item["logo"], required=True) if "logo" in item else None,
        )
        organizations[organization.name] = organization
        session.add(organization)

    people: dict[str, Person] = {}
    for item in people_items:
        if item["name"] in people:
            raise WorldImportError(f"people.yaml: {item['name']!r} appears twice")
        names = _person_organizations(item)
        for name in names:
            if name not in organizations:
                organizations[name] = Organization(owner_id=owner.id, name=name, type=organization_type(DEFAULT_ORGANIZATION_TYPE))
                session.add(organizations[name])
        first_name, surname = split_name(item["name"])
        person = Person(
            owner_id=owner.id, first_name=first_name, surname=surname, description=item.get("description", ""),
            organizations=[organizations[name] for name in names],
        )
        people[item["name"]] = person
        session.add(person)

    listed = set(people)

    def with_people(item: dict[str, Any]) -> list[Person]:
        if len(set(item["with"])) != len(item["with"]):
            raise WorldImportError(f"{item['name']!r}: a name appears twice in with")
        missing = [name for name in item["with"] if name not in listed]
        if missing:
            raise WorldImportError(f"{item['name']!r}: with names not in people.yaml: {missing}")
        return [people[name] for name in item["with"]]

    def performers(item: dict[str, Any]) -> list[Person]:
        """ Who was on stage, as people: a name people.yaml does not have becomes a new person. """
        names = [name.strip() for name in item.get("performers", []) if name.strip()]
        for name in names:
            if name not in people:
                first_name, surname = split_name(name)
                people[name] = Person(owner_id=owner.id, first_name=first_name, surname=surname, description="")
                session.add(people[name])
        return [people[name] for name in dict.fromkeys(names)]

    for item in concert_items:
        session.add(Concert(
            owner_id=owner.id,
            name=item["name"],
            performers=performers(item),
            event=item.get("event", ""),
            genre=item.get("genre", ""),
            venue=item.get("venue", ""),
            city=item.get("city", ""),
            country=item.get("country", ""),
            tickets=item.get("tickets"),
            broadcast=bool(item.get("broadcast", False)),
            review=item.get("review", ""),
            remark=item.get("remark", ""),
            image=image(image_dir / item["image"], required=True) if "image" in item else None,
            image_source=item.get("image_source", ""),
            image_license=item.get("image_license", ""),
            image_author=item.get("image_author", ""),
            people=with_people(item),
            **_dates(item),
        ))

    # every visit of a museum shows the photo of its first (lowest internal_id) visit
    first_visit: dict[str, int] = {}
    for item in museum_items:
        first_visit[item["name"]] = min(first_visit.get(item["name"], item["internal_id"]), item["internal_id"])
    for item in museum_items:
        session.add(Museum(
            owner_id=owner.id,
            name=item["name"],
            city=item.get("city", ""),
            rating=item.get("rating"),
            review=item.get("review", ""),
            remark=item.get("remark", ""),
            url=item.get("url", ""),
            tickets=item.get("tickets"),
            image=image(image_dir / f"museum-{first_visit[item['name']]}.jpg", required=False),
            people=with_people(item),
            **_dates(item),
        ))
    session.flush()
    courses = import_audio_courses(session, owner, source)
    videos = import_youtube(session, owner, source)
    history = import_youtube_history(session, owner, source)
    typed = give_types(session, owner)
    return {
        "people": len(people) + courses["lecturers added"], "organizations": len(organizations), "organization types": len(types),
        "relation types": len(relation_types), "person types": len(PERSON_TYPES), "people with a type": typed["people given a type"],
        "concerts": len(concert_items), "museums": len(museum_items), "audio courses": courses["audio courses"],
        "YouTube videos": videos["YouTube videos"] + history["YouTube videos added"], "devices": courses["devices added"] + videos["devices added"],
        "images": len(images) + courses["images"],
    }


def _stamp(item: dict[str, Any], key: str) -> datetime.datetime | None:
    """ A UTC timestamp field of the YAML, as the naive UTC the columns keep. """
    if key not in item:
        return None
    return datetime.datetime.fromisoformat(str(item[key])).astimezone(datetime.UTC).replace(tzinfo=None)


def _course_cover(item: dict[str, Any]) -> str:
    """ The file name of a course's cover, by the ids veltzer.github.io names it with. """
    if "great_courses_id" in item:
        return f"audiocourse-gc-{item['great_courses_id']}.jpg"
    if "audible_asin" in item:
        return f"audiocourse-audible-{item['audible_asin']}.jpg"
    if "internal_id" in item:
        return f"audiocourse-internal-{item['internal_id']}.jpg"
    raise WorldImportError(f"audio_courses.yaml: {item['name']!r} has no id to find its cover by")


def import_audio_courses(session: Session, owner: User, source: Path) -> dict[str, int]:
    """
    Add owner's audio courses from source, with their covers; each lecturer
    is owner's person of that name, or a new person when there is none.
    Stops when owner has audio courses already. Does not commit.
    """
    items = _items(source, "audio_courses", AUDIO_COURSE_FIELDS)
    if session.scalar(select(AudioCourse.id).where(AudioCourse.owner_id == owner.id).limit(1)) is not None:
        raise WorldImportError("this account has audio courses already: delete them first, or run the full import")
    session.flush()
    by_name: dict[str, list[Person]] = {}
    for person in session.scalars(select(Person).where(Person.owner_id == owner.id)):
        by_name.setdefault(person.name, []).append(person)
    added = 0

    def lecturer(name: str) -> Person:
        nonlocal added
        found = by_name.get(name, [])
        if len(found) > 1:
            raise WorldImportError(f"audio_courses.yaml: {len(found)} people are called {name!r}; make the names differ first")
        if not found:
            first_name, surname = split_name(name)
            found = [Person(owner_id=owner.id, first_name=first_name, surname=surname, description="")]
            session.add(found[0])
            by_name[name] = found
            added += 1
        return found[0]

    device = Devices(session, owner)

    image_dir = source / "static" / "images"
    # a cover already stored (an earlier import of courses since deleted) is used again
    stored = {image.filename: image for image in session.scalars(select(Image).where(Image.owner_id == owner.id))}
    images = 0
    for item in items:
        names = [name.strip() for name in item["lecturers"] if name.strip()]
        if len(set(names)) != len(names):
            raise WorldImportError(f"audio_courses.yaml: {item['name']!r} names a lecturer twice")
        path = image_dir / _course_cover(item)
        if not path.exists():
            raise WorldImportError(f"missing image {path}")
        data = path.read_bytes()
        sha256 = hashlib.sha256(data).hexdigest()
        cover = stored.get(path.name)
        if cover is not None and cover.sha256 != sha256:
            raise WorldImportError(f"{path}: an image of that name is stored already, with other contents")
        if cover is None:
            cover = Image(owner_id=owner.id, filename=path.name, content_type="image/jpeg", sha256=sha256, data=data)
            session.add(cover)
            stored[path.name] = cover
            images += 1
        session.add(AudioCourse(
            owner_id=owner.id,
            name=item["name"],
            lecturers=[lecturer(name) for name in names],
            rating=item.get("rating"),
            review=item.get("review", ""),
            device=device(item.get("device", "")),
            listened_at=item.get("location", ""),
            started_utcz=_stamp(item, "date_started_utcz"),
            ended_utcz=_stamp(item, "date_ended_utcz"),
            progress=str(item.get("progress", "")),
            great_courses_id=item.get("great_courses_id"),
            great_courses_slug=item.get("great_courses_slug", ""),
            audible_asin=item.get("audible_asin", ""),
            image=cover,
            **_dates(item),
        ))
    session.flush()
    return {"audio courses": len(items), "lecturers added": added, "devices added": device.added, "images": images}


def import_youtube(session: Session, owner: User, source: Path) -> dict[str, int]:
    """ Add owner's YouTube videos from source. Stops when owner has YouTube videos already. Does not commit. """
    items = _items(source, "video_youtube", YOUTUBE_FIELDS)
    if session.scalar(select(YouTubeVideo.id).where(YouTubeVideo.owner_id == owner.id).limit(1)) is not None:
        raise WorldImportError("this account has YouTube videos already: delete them first, or run the full import")
    ids = [item["id"] for item in items]
    if len(set(ids)) != len(ids):
        raise WorldImportError("video_youtube.yaml: a video is listed twice")
    device = Devices(session, owner)
    for item in items:
        session.add(YouTubeVideo(
            owner_id=owner.id,
            youtube_id=item["id"],
            name=str(item["name"]),
            rating=item.get("rating"),
            review=item.get("review", ""),
            device=device(item.get("device", "")),
            watched_at=item.get("location", ""),
            **_dates(item),
        ))
    session.flush()
    return {"YouTube videos": len(items), "devices added": device.added}


def _history_items(source: Path) -> list[dict[str, Any]]:
    path = source / "static" / "data" / "youtube.json.gz"
    with gzip.open(path, "rt", encoding="UTF8") as fp:
        items = json.load(fp)["items"]
    for item in items:
        unknown = set(item) - YOUTUBE_HISTORY_FIELDS
        if unknown:
            raise WorldImportError(f"{path}: {item.get('webpage_url')!r} has fields this import does not know: {sorted(unknown)}")
        found = YOUTUBE_WATCH.fullmatch(item["webpage_url"])
        if found is None:
            raise WorldImportError(f"{path}: {item['webpage_url']!r} is not a YouTube video link")
        item["id"] = found.group(1)
        if item.get("status") not in (None, "missing"):
            raise WorldImportError(f"{path}: {item['id']}: unknown status {item['status']!r}")
    return items


def _history_details(item: dict[str, Any]) -> dict[str, Any]:
    """ What YouTube says about a video, as YouTubeVideo columns. """
    if item.get("status") == "missing":
        return {"channel": "", "category": "", "duration": None, "uploaded": None, "views": None, "unavailable": True}
    upload = item.get("upload_date")
    return {
        "channel": item.get("channel") or "",
        "category": item.get("categories") or "",
        "duration": item.get("duration"),
        "uploaded": datetime.date.fromisoformat(upload) if upload else None,
        "views": item.get("view_count"),
        "unavailable": False,
    }


def import_youtube_history(session: Session, owner: User, source: Path) -> dict[str, int]:
    """
    Add owner's YouTube watch history: a new row for each video owner does
    not have, YouTube's details on each one owner has. Safe to run again. Does not commit.
    """
    items = _history_items(source)
    ids = [item["id"] for item in items]
    if len(set(ids)) != len(ids):
        raise WorldImportError("youtube.json.gz: a video is listed twice")
    have = {v.youtube_id: v for v in session.scalars(select(YouTubeVideo).where(YouTubeVideo.owner_id == owner.id))}
    new: list[dict[str, Any]] = []
    updated = 0
    for item in items:
        details = _history_details(item)
        video = have.get(item["id"])
        if video is None:
            # "Metadata unavailable" is not a name: a video YouTube no longer has keeps none
            name = "" if details["unavailable"] else item["title"]
            new.append({
                "owner_id": owner.id, "youtube_id": item["id"], "name": name, "review": "", "watched_at": "",
                # every column, in every row: a multi-row INSERT takes the same ones for all
                "rating": None, "device_id": None, "date_utcz": None, "date_ymd": None, "date_my": "", "date_y": None,
                "date_timezone": "", **details,
            })
        else:
            for key, value in details.items():
                setattr(video, key, value)
            updated += 1
    session.flush()
    # multi-row INSERTs: 30,000 ORM adds, or a driver's executemany (pg8000
    # sends one statement per row), are 30,000 round trips to Cloud SQL
    for start in range(0, len(new), INSERT_CHUNK):
        session.execute(insert(YouTubeVideo).values(new[start:start + INSERT_CHUNK]))
    return {"YouTube videos added": len(new), "YouTube videos given details": updated}


class Devices:
    """ owner's devices by name: device(name) is the one of that name, made the first time it is named. """

    def __init__(self, session: Session, owner: User) -> None:
        self.session = session
        self.owner = owner
        self.by_name = {d.name: d for d in session.scalars(select(Device).where(Device.owner_id == owner.id))}
        self.added = 0

    def __call__(self, name: str) -> Device | None:
        if not name:
            return None
        if name not in self.by_name:
            self.by_name[name] = Device(owner_id=self.owner.id, name=name, description="")
            self.session.add(self.by_name[name])
            self.added += 1
        return self.by_name[name]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1] if __doc__ else None)
    parser.add_argument("--email", required=True, help="email of the account that will own the data")
    parser.add_argument("--subject", help="the account's subject (users.google_sub) when the email has several")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parent.parent.parent / "veltzer.github.io")
    parser.add_argument("--dry-run", action="store_true", help="do it all and print what was done, then roll it back")
    parser.add_argument(
        "--audio-courses", action="store_true",
        help="import only the audio courses, adding them to what the account has (stops if it has audio courses already)",
    )
    parser.add_argument(
        "--youtube", action="store_true",
        help="import only the YouTube videos, adding them to what the account has (stops if it has YouTube videos already)",
    )
    parser.add_argument(
        "--youtube-history", action="store_true",
        help="add the YouTube watch history to the videos the account has (new ones, and details on those there); safe to run again",
    )
    parser.add_argument(
        "--only-types", action="store_true",
        help="import nothing: only add the starting types and type the organizations and people that have none",
    )
    args = parser.parse_args()
    engine = make_engine()
    with Session(engine) as session:
        try:
            owner = find_owner(session, args.email, args.subject)
            if args.only_types:
                counts = give_types(session, owner)
            elif args.youtube_history:
                counts = import_youtube_history(session, owner, args.source)
            elif args.youtube:
                counts = import_youtube(session, owner, args.source)
            elif args.audio_courses:
                counts = import_audio_courses(session, owner, args.source)
                counts["people given a type"] = give_types(session, owner)["people given a type"]
            else:
                counts = import_world(session, owner, args.source)
        except WorldImportError as e:
            print(f"import_world: {e}", file=sys.stderr)
            return 1
        who = f"{owner.email} ({owner.google_sub})"
        if args.dry_run:
            session.rollback()
        else:
            session.commit()
    summary = ", ".join(f"{count} {what}" for what, count in counts.items())
    done = "typed" if args.only_types else "imported"
    print(f"{engine.url.render_as_string(hide_password=True)}: {done} for {who}: {summary}{' (dry run: rolled back)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
