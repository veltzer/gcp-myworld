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

Books come from data/yaml/books_read.yaml (with the rating and review of
data/yaml/text_books.yaml), their covers from
static/images/book-{goodreads,simania}-<id>.jpg. A book is a library entry:
its rating, review and finish date are those of its latest dated reading,
and what the entry has no field for (the other readings, the languages read
and owned, the names in other languages, the publisher, the remark) is
written into its notes.

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
does the same for the YouTube videos. --books adds the books the account
does not have yet, and can run again. --youtube-history adds the watch
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
import zoneinfo
from pathlib import Path
from typing import Any

# the myworld package is in src/, not installed: find it from any directory, no PYTHONPATH needed
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import yaml
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session, selectinload

from myworld import names as naming
from myworld.models import (
    AudioCourse,
    Concert,
    Device,
    Group,
    Image,
    Museum,
    Organization,
    OrganizationType,
    Person,
    PersonRelation,
    PersonRelationType,
    PersonType,
    Place,
    RelationType,
    User,
    UserWork,
    Work,
    YouTubeVideo,
    audio_course_lecturers,
    concert_companions,
    concert_groups,
    concert_performers,
    group_members,
    library_entry_authors,
    make_engine,
    museum_companions,
    organization_relation_types,
    person_organizations,
    person_type_links,
)

DATE_FIELDS = {"date_utcz", "date_ymd", "date_my", "date_y", "date_timezone"}
# books_read.yaml: a book, its names (one per language), its authors (each a
# list of the author's name in several languages), each reading and each copy owned
BOOK_FIELDS = {"names", "authors", "language", "readings", "ownings", "remark", "publisher", "isbn"}
BOOK_NAME_FIELDS = {"language", "name", "goodreads_id", "simania_id"}
BOOK_READING_FIELDS = {"language", "undated", "date", "timezone", "rating", "review"}
BOOK_OWNING_FIELDS = {"language"}
# text_books.yaml: a rating and review for a book of books_read.yaml
TEXT_BOOK_FIELDS = {"name", "authors", "review", "rating"}
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
# the professions (person types) every import starts the user with; how a
# person is related to the user is a person relation instead (to the user's
# own person, see self_person)
PERSON_TYPES = {
    "Performer": "Someone seen on stage",
    "Lecturer": "Someone who taught a course I took",
    "Book Author": "Someone who wrote a book I read or own",
}
# how people are related to each other, every import starts the user with:
# name -> (inverse, how it reads from the other side; description)
PERSON_RELATION_TYPES = {
    "Mother of": ("Child of", "She gave birth to them or raised them"),
    "Father of": ("Child of", "He fathered them or raised them"),
    "Son of": ("Parent of", "He is their son"),
    "Daughter of": ("Parent of", "She is their daughter"),
    "Brother of": ("Sibling of", "He shares a parent with them"),
    "Sister of": ("Sibling of", "She shares a parent with them"),
    "Husband of": ("Spouse of", "He is married to them"),
    "Wife of": ("Spouse of", "She is married to them"),
    "Relative of": ("", "Family, how exactly not said"),
    "Girlfriend of": ("Boyfriend of", "A girlfriend, now or before"),
    "Co-worker of": ("", "Worked together"),
    "Friend of": ("", "A friend who is not a relative"),
    "Acquaintance of": ("", "Knows them, not a friend"),
    "Neighbour of": ("", "Lives or lived next door"),
}
# person types that are really how someone is related to the user: give_types
# makes each a person relation to the user's own person and drops the type
TYPE_TO_RELATION = {
    "Family": "Relative of",
    "Girlfriend": "Girlfriend of",
    "Co-Worker": "Co-worker of",
    "Friend": "Friend of",
    "Acquaintance": "Acquaintance of",
    "Neighbour": "Neighbour of",
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
# what _profession and _relation_to_user read a person from
FAMILY_NAME = "Veltzer"
FAMILY_DESCRIPTION = re.compile(r"my (brother|sister|mother|father|son|daughter|wife|husband|cousin|uncle|aunt)\b", re.IGNORECASE)
GIRLFRIEND_DESCRIPTION = re.compile(r"(ex-)?girlfriend\b", re.IGNORECASE)
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


def split_name(name: str) -> tuple[str, str, str, str]:
    """
    A whole name as (honorific, first name, middle name, surname), split as
    myworld.names.split_name does ("Jeffrey L. Kasser", "Al Di Meola"
    becoming Di-Meola); what is not plainly a person's name ("Oded from
    MAFAT", "The Band") is all first name, for the people-names check to list.
    """
    return naming.split_name(name) or ("", name, "", "")


def _profession(person: Person) -> str | None:
    """ A first guess at a person's profession, from what the data says; None when nothing does. """
    if person.performed:
        return "Performer"
    if person.lectured:
        return "Lecturer"
    if person.wrote:
        return "Book Author"
    return None


def _relation_to_user(person: Person) -> str | None:
    """ A first guess at how a person is related to the user (a person relation type); None when nothing says. """
    if person.name.endswith(f" {FAMILY_NAME}") or FAMILY_DESCRIPTION.match(person.description):
        return "Relative of"
    if GIRLFRIEND_DESCRIPTION.match(person.description):
        return "Girlfriend of"
    if person.organizations or CO_WORKER_DESCRIPTION.search(person.description):
        return "Co-worker of"
    return None


def self_person(session: Session, owner: User) -> Person:
    """
    owner's own person, the one others are related to: the one marked so, else
    the one with owner's name (then marked), else a new one. Does not commit.
    """
    me = session.scalars(select(Person).where(Person.owner_id == owner.id, Person.is_self)).first()
    if me is not None:
        return me
    named = [p for p in session.scalars(select(Person).where(Person.owner_id == owner.id)) if owner.name and naming.key(p.name) == naming.key(owner.name)]
    if len(named) == 1:
        named[0].is_self = True
        return named[0]
    honorific, first_name, middle_name, surname = split_name(owner.name or owner.email)
    me = Person(owner_id=owner.id, honorific=honorific, first_name=first_name, middle_name=middle_name, surname=surname,
                description="Me", is_self=True)
    session.add(me)
    session.flush()
    return me


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
    Add the starting organization types, professions, organization relation
    types and person relation types owner does not have yet; make owner's own
    person (self_person); turn the person types that are really relations
    (TYPE_TO_RELATION: Friend, Co-Worker, ...) into person relations to it and
    drop them; then give what has none a first guess: every organization a
    type (by name, else Company), every person without a profession one
    (_profession), and every person related to no one a relation to owner
    (_relation_to_user). Everything else is left as it is. Does not commit.
    """
    org_types, org_added = _starting_types(session, owner, OrganizationType, ORGANIZATION_TYPES)
    professions, person_added = _starting_types(session, owner, PersonType, PERSON_TYPES)
    _, relation_added = _starting_types(session, owner, RelationType, dict(RELATION_TYPES.values()))
    relation_types = {t.name: t for t in session.scalars(select(PersonRelationType).where(PersonRelationType.owner_id == owner.id))}
    person_relation_added = 0
    for name, (inverse, description) in PERSON_RELATION_TYPES.items():
        if name not in relation_types:
            relation_types[name] = PersonRelationType(owner_id=owner.id, name=name, inverse=inverse, description=description)
            session.add(relation_types[name])
            person_relation_added += 1
    added = org_added + person_added + relation_added + person_relation_added
    session.flush()
    me = self_person(session, owner)
    people = session.scalars(
        select(Person)
        .where(Person.owner_id == owner.id)
        .options(
            selectinload(Person.types), selectinload(Person.relations), selectinload(Person.related), selectinload(Person.organizations),
            selectinload(Person.performed), selectinload(Person.lectured), selectinload(Person.wrote),
        )
    ).all()

    def relate(person: Person, name: str) -> bool:
        kind = relation_types[name]
        if person is me or any(r.relation_type is kind and r.other is me for r in person.relations):
            return False
        person.relations.append(PersonRelation(relation_type=kind, other=me))
        return True

    made_relations = 0
    for name, relation in TYPE_TO_RELATION.items():
        kind = session.scalars(select(PersonType).where(PersonType.owner_id == owner.id, PersonType.name == name)).first()
        if kind is None:
            continue
        for person in people:
            if kind in person.types:
                person.types.remove(kind)
                made_relations += relate(person, relation)
        session.delete(kind)
    typed = 0
    for organization in session.scalars(select(Organization).where(Organization.owner_id == owner.id, Organization.type_id.is_(None))):
        organization.type = org_types[type_for(organization.name)]
        typed += 1
    given_profession = given_relation = 0
    for person in people:
        if person is me:
            continue
        name = _profession(person)
        if name is not None and not person.types:
            person.types = [professions[name]]
            given_profession += 1
        relation = _relation_to_user(person)
        if relation is not None and not person.relations and not person.related:
            given_relation += relate(person, relation)
    session.flush()
    return {
        "types added": added, "organizations given a type": typed, "people given a profession": given_profession,
        "people given a relation": given_relation, "person types made relations": made_relations,
    }


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
    session.execute(delete(concert_groups).where(concert_groups.c.concert_id.in_(concerts_of_owner)))
    session.execute(delete(group_members).where(group_members.c.group_id.in_(select(Group.id).where(Group.owner_id == owner.id))))
    session.execute(delete(museum_companions).where(museum_companions.c.museum_id.in_(select(Museum.id).where(Museum.owner_id == owner.id))))
    session.execute(delete(audio_course_lecturers).where(
        audio_course_lecturers.c.audio_course_id.in_(select(AudioCourse.id).where(AudioCourse.owner_id == owner.id)),
    ))
    session.execute(delete(PersonRelation).where(PersonRelation.person_id.in_(select(Person.id).where(Person.owner_id == owner.id))))
    session.execute(delete(person_type_links).where(person_type_links.c.person_id.in_(select(Person.id).where(Person.owner_id == owner.id))))
    session.execute(delete(person_organizations).where(person_organizations.c.person_id.in_(select(Person.id).where(Person.owner_id == owner.id))))
    session.execute(delete(organization_relation_types).where(
        organization_relation_types.c.organization_id.in_(select(Organization.id).where(Organization.owner_id == owner.id)),
    ))
    # every person goes, so every author link of owner's library entries does too
    session.execute(delete(library_entry_authors).where(library_entry_authors.c.user_id == owner.id))
    # the books are added again below; other library entries lose their cover, as every image goes
    session.execute(delete(UserWork).where(
        UserWork.user_id == owner.id, UserWork.work_id.in_(select(Work.id).where(Work.kind == "book")),
    ))
    for entry in session.scalars(select(UserWork).where(UserWork.user_id == owner.id, UserWork.image_id.is_not(None))):
        entry.image_id = None
    session.flush()
    for model in (AudioCourse, YouTubeVideo, Device, Concert, Place, Group, Museum, Person, Organization, OrganizationType, PersonType, RelationType, PersonRelationType, Image):
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
        honorific, first_name, middle_name, surname = split_name(item["name"])
        person = Person(
            owner_id=owner.id, honorific=honorific, first_name=first_name, middle_name=middle_name, surname=surname, description=item.get("description", ""),
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
                honorific, first_name, middle_name, surname = split_name(name)
                people[name] = Person(owner_id=owner.id, honorific=honorific, first_name=first_name, middle_name=middle_name, surname=surname, description="")
                session.add(people[name])
        return [people[name] for name in dict.fromkeys(names)]

    place = Places(session, owner)
    for item in concert_items:
        session.add(Concert(
            owner_id=owner.id,
            name=item["name"],
            performers=performers(item),
            event=item.get("event", ""),
            genre=item.get("genre", ""),
            place=place(item.get("venue", ""), item.get("city", ""), item.get("country", "")),
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
    books = import_books(session, owner, source)
    typed = give_types(session, owner)
    return {
        "people": len(people) + courses["lecturers added"] + books["authors added"], "organizations": len(organizations), "organization types": len(types),
        "relation types": len(relation_types), "person types": len(PERSON_TYPES), "people with a profession": typed["people given a profession"], "people related to the user": typed["people given a relation"],
        "concerts": len(concert_items), "places": place.added, "museums": len(museum_items), "audio courses": courses["audio courses"],
        "YouTube videos": videos["YouTube videos"] + history["YouTube videos added"], "devices": courses["devices added"] + videos["devices added"],
        "books": books["books"], "images": len(images) + courses["images"] + books["covers"],
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
        by_name.setdefault(naming.key(person.name), []).append(person)
    added = 0

    def lecturer(name: str) -> Person:
        nonlocal added
        found = by_name.get(naming.key(name), [])
        if len(found) > 1:
            raise WorldImportError(f"audio_courses.yaml: {len(found)} people are called {name!r}; make the names differ first")
        if not found:
            honorific, first_name, middle_name, surname = split_name(name)
            found = [Person(owner_id=owner.id, honorific=honorific, first_name=first_name, middle_name=middle_name, surname=surname, description="")]
            session.add(found[0])
            by_name[naming.key(name)] = found
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


def _check_fields(path: Path, what: str, item: dict[str, Any], fields: set[str]) -> None:
    unknown = set(item) - fields
    if unknown:
        raise WorldImportError(f"{path}: {what} has fields this import does not know: {sorted(unknown)}")


def _english_first(alternatives: list[dict[str, Any]]) -> dict[str, Any]:
    """ Of a name given in several languages, the English one, or else the first. """
    return next((a for a in alternatives if a["language"] == "english"), alternatives[0])


def _language(code: str) -> str:
    return code.capitalize()


def _reading_day(reading: dict[str, Any]) -> datetime.date | None:
    """ The day a reading ended, where the reader was (its timezone). """
    if reading.get("undated"):
        return None
    stamp = datetime.datetime.fromisoformat(str(reading["date"]))
    return stamp.astimezone(zoneinfo.ZoneInfo(reading.get("timezone") or "UTC")).date()


def _book_notes(item: dict[str, Any], title: str, main: dict[str, Any] | None) -> str:
    """ What a library entry has no field for, in a few sentences. """
    parts = []
    if main is not None and main.get("review"):
        parts.append(str(main["review"]))
    readings = item["readings"]
    if len(readings) > 1 or any(r["language"] != item["language"] for r in readings):
        described = []
        for reading in readings:
            day = _reading_day(reading)
            detail = [day.isoformat() if day else "date unknown"]
            if reading is not main and reading.get("rating") is not None:
                detail.append(f"rated {reading['rating']}")
            if reading is not main and reading.get("review"):
                detail.append(str(reading["review"]))
            described.append(f"{_language(reading['language'])} ({', '.join(detail)})")
        parts.append(f"Read in {'; '.join(described)}")
    owned = sorted({_language(o["language"]) for o in item.get("ownings", [])})
    if owned:
        parts.append(f"Owned in {' and '.join(owned)}")
    if item["language"] not in ("english", "unknown"):
        parts.append(f"Written in {_language(item['language'])}")
    for name in item["names"]:
        if name["name"] != title:
            parts.append(f"{_language(name['language'])} title: {name['name']}")
    for alternatives in item["authors"]:
        shown = _english_first(alternatives)
        for other in alternatives:
            if other is not shown:
                parts.append(f"Author in {_language(other['language'])}: {other['name']}")
    if item.get("publisher"):
        parts.append(f"Publisher: {item['publisher']}")
    if item.get("remark"):
        parts.append(str(item["remark"]))
    return ". ".join(part.rstrip(".") for part in parts)


def _book_items(source: Path) -> list[dict[str, Any]]:
    """ books_read.yaml, every level checked for fields this import does not know, with text_books.yaml's ratings in. """
    path = source / "data" / "yaml" / "books_read.yaml"
    with path.open(encoding="UTF8") as fp:
        items = yaml.safe_load(fp)["items"]
    for item in items:
        what = repr(item["names"][0]["name"])
        _check_fields(path, what, item, BOOK_FIELDS)
        for name in item["names"]:
            _check_fields(path, f"a name of {what}", name, BOOK_NAME_FIELDS)
        for reading in item["readings"]:
            _check_fields(path, f"a reading of {what}", reading, BOOK_READING_FIELDS)
            if not reading.get("undated") and "date" not in reading:
                raise WorldImportError(f"{path}: a reading of {what} has neither a date nor undated")
        for owning in item.get("ownings", []):
            _check_fields(path, f"a copy of {what}", owning, BOOK_OWNING_FIELDS)
    by_name = {name["name"]: item for item in items for name in item["names"]}
    for text_book in _items(source, "text_books", TEXT_BOOK_FIELDS):
        book = by_name.get(text_book["name"])
        if book is None:
            raise WorldImportError(f"text_books.yaml: {text_book['name']!r} is not in books_read.yaml")
        book["text_rating"] = text_book.get("rating")
        book["text_review"] = text_book.get("review", "")
    return items


def import_books(session: Session, owner: User, source: Path) -> dict[str, int]:
    """
    Add owner's books from source, with their covers: a library entry for
    each book owner does not have yet (the work, which is shared, is reused
    when there is one), so it can run again. An entry owner has already only
    gets its cover, when it has none and source has one now, and its
    authors, when it has none. Each author is owner's person of that name,
    or a new person, and is a Book Author (a person type). Does not commit.
    """
    items = _book_items(source)
    image_dir = source / "static" / "images"
    stored = {image.filename: image for image in session.scalars(select(Image).where(Image.owner_id == owner.id))}
    added = skipped = images = uncovered = covered = credited = people_added = typed = 0
    person_types, _ = _starting_types(session, owner, PersonType, {"Book Author": PERSON_TYPES["Book Author"]})
    book_author = person_types["Book Author"]
    by_name: dict[str, list[Person]] = {}
    for person in session.scalars(select(Person).where(Person.owner_id == owner.id).options(selectinload(Person.types))):
        by_name.setdefault(naming.key(person.name), []).append(person)

    def author(name: str) -> Person:
        """ owner's person called name, made a Book Author; a new one when there is none. """
        nonlocal people_added, typed
        found = by_name.get(naming.key(name), [])
        if len(found) > 1:
            raise WorldImportError(f"books_read.yaml: {len(found)} people are called {name!r}; make the names differ first")
        if not found:
            honorific, first_name, middle_name, surname = split_name(name)
            found = [Person(owner_id=owner.id, honorific=honorific, first_name=first_name, middle_name=middle_name, surname=surname, description="", types=[])]
            session.add(found[0])
            by_name[naming.key(name)] = found
            people_added += 1
        if book_author not in found[0].types:
            found[0].types.append(book_author)
            typed += 1
        return found[0]

    def book_cover(goodreads_id: str, simania_id: str) -> Image | None:
        """ The book's cover, stored once per owner; None when veltzer.github.io has none (a few books). """
        nonlocal images
        name = f"book-goodreads-{goodreads_id}.jpg" if goodreads_id else f"book-simania-{simania_id}.jpg" if simania_id else ""
        path = image_dir / name
        if not name or not path.exists():
            return None
        data = path.read_bytes()
        sha256 = hashlib.sha256(data).hexdigest()
        cover = stored.get(name)
        if cover is not None and cover.sha256 != sha256:
            raise WorldImportError(f"{path}: an image of that name is stored already, with other contents")
        if cover is None:
            cover = Image(owner_id=owner.id, filename=name, content_type="image/jpeg", sha256=sha256, data=data)
            session.add(cover)
            session.flush()
            stored[name] = cover
            images += 1
        return cover

    for item in items:
        title = _english_first(item["names"])["name"]
        creator = ", ".join(_english_first(alternatives)["name"] for alternatives in item["authors"])
        goodreads_id = next((n["goodreads_id"] for n in item["names"] if n.get("goodreads_id")), "")
        simania_id = next((n["simania_id"] for n in item["names"] if n.get("simania_id")), "")
        names = [_english_first(alternatives)["name"] for alternatives in item["authors"]]
        if len(set(names)) != len(names):
            raise WorldImportError(f"books_read.yaml: {title!r} names an author twice")
        # the book's work: by its catalog id, so an author added to the yaml since finds it, else by title and author
        work = None
        for column, value in ((Work.goodreads_id, goodreads_id), (Work.simania_id, simania_id)):
            if work is None and value:
                work = session.scalars(select(Work).where(Work.kind == "book", column == str(value))).first()
        if work is None:
            work = session.scalars(select(Work).where(
                Work.kind == "book", Work.title == title, Work.creator == creator, Work.year.is_(None),
            )).one_or_none()
        if work is None:
            work = Work(kind="book", title=title, creator=creator, year=None)
            session.add(work)
        # the author and the catalog ids are only filled in, never overwritten
        work.creator = work.creator or creator
        work.goodreads_id = work.goodreads_id or str(goodreads_id)
        work.simania_id = work.simania_id or str(simania_id)
        work.external_id = work.external_id or str(item.get("isbn", ""))
        session.flush()
        entry = session.get(UserWork, (owner.id, work.id))
        if entry is not None:
            skipped += 1
            # a cover added to veltzer.github.io since: given to an entry that has none
            if entry.image_id is None:
                cover = book_cover(goodreads_id, simania_id)
                if cover is not None:
                    entry.image_id = cover.id
                    covered += 1
            # the authors, as people, of an entry that has none (one imported before they were people)
            if not entry.authors and names:
                entry.authors = [author(name) for name in names]
                credited += 1
            continue
        cover = book_cover(goodreads_id, simania_id)
        readings = item["readings"]
        # the latest dated reading, or else the last one listed
        dated = sorted((r for r in readings if not r.get("undated")), key=lambda r: str(r["date"]))
        main = dated[-1] if dated else readings[-1] if readings else None
        rating = main.get("rating") if main else None
        notes = _book_notes(item, title, main)
        if rating is None and item.get("text_rating") is not None:
            rating = item["text_rating"]
            notes = ". ".join(part for part in (item.get("text_review", ""), notes) if part)
        session.add(UserWork(
            user_id=owner.id,
            work_id=work.id,
            status="done" if readings else "wishlist",
            rating=rating,
            finished_on=_reading_day(main) if main else None,
            notes=notes,
            image_id=cover.id if cover else None,
            authors=[author(name) for name in names],
        ))
        added += 1
        uncovered += cover is None
    session.flush()
    return {
        "books": added, "books there already": skipped, "covers": images,
        "covers given to books there already": covered, "books with no cover": uncovered,
        "authors added": people_added, "people made book authors": typed, "authors given to books there already": credited,
    }


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


class Places:
    """
    owner's places by name and city: place(venue, city, country) is the one
    there, made the first time it is named; a concert with a city but no
    venue is at a place named after the city, one with neither at none.
    """

    def __init__(self, session: Session, owner: User) -> None:
        self.session = session
        self.owner = owner
        self.by_name = {(p.name, p.city): p for p in session.scalars(select(Place).where(Place.owner_id == owner.id))}
        self.added = 0

    def __call__(self, venue: str, city: str, country: str) -> Place | None:
        name, city = venue.strip() or city.strip(), city.strip()
        if not name:
            return None
        if (name, city) not in self.by_name:
            self.by_name[name, city] = Place(owner_id=self.owner.id, name=name, city=city, country=country.strip())
            self.session.add(self.by_name[name, city])
            self.added += 1
        return self.by_name[name, city]


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
        "--books", action="store_true",
        help="import only the books, adding those the account does not have yet; safe to run again",
    )
    parser.add_argument(
        "--youtube-history", action="store_true",
        help="add the YouTube watch history to the videos the account has (new ones, and details on those there); safe to run again",
    )
    parser.add_argument(
        "--only-types", action="store_true",
        help="import nothing: only add the starting types, make the user's own person, turn relation-like person types into relations to it, and give a first guess to what has no type, profession or relation",
    )
    args = parser.parse_args()
    engine = make_engine()
    with Session(engine) as session:
        try:
            owner = find_owner(session, args.email, args.subject)
            if args.only_types:
                counts = give_types(session, owner)
            elif args.books:
                counts = import_books(session, owner, args.source)
            elif args.youtube_history:
                counts = import_youtube_history(session, owner, args.source)
            elif args.youtube:
                counts = import_youtube(session, owner, args.source)
            elif args.audio_courses:
                counts = import_audio_courses(session, owner, args.source)
                counts["people given a profession"] = give_types(session, owner)["people given a profession"]
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
