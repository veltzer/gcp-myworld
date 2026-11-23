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

veltzer.github.io no longer has any of these files (My World keeps them, since
2026-11-23): a source without one imports none of what it held.

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

Audio books came from data/yaml/audible.yaml (the books of the Audible
library, as Audible says them), their covers from
static/images/audible-<asin>.jpg; audio books are shared, and each is the
account's listen of the book's Audible version, found again by its ASIN.
The audio books heard elsewhere came from data/yaml/audio_books.yaml, as
an audio course is said (when finished or started, how far, where, on what
device); each is the account's listen of the book's MP3 version, the book
found again by its title and authors. veltzer.github.io no longer has either file (My
World keeps them now): a source without them imports no audio books, and
--audio-books reads them from a checkout of the site's history that has them.

YouTube videos come from data/yaml/video_youtube.yaml (the reviewed ones)
and static/data/youtube.json.gz (the watch history: what YouTube says about
each video, no date or review); a video in both is one row. Their
thumbnails are YouTube's own, so there is no image to import. Their devices
are the same list as the audio courses'. veltzer.github.io no longer has
either file (My World keeps them now): a source without them imports no
YouTube videos, and --youtube and --youtube-history read them from a
checkout of the site's history that has them.

Films come from data/yaml/video_features.yaml (each a time a film was
watched: when, where, on what, with whom, the rating and review), their
posters from static/images/movie-<imdb_id>.jpg; series (films of the kind
series) from data/yaml/video_series.yaml, each with the seasons seen and
not, their posters from static/images/series-<imdb_id>.jpg; and the films still to see
from ../data/json/movies_to_see.json (by IMDb id, with who recommended each
and its genre). A film is shared, found again by its IMDb id; what Wikidata
says of it (the title, the year, the directors) fills in what is missing,
and with TMDB_API_KEY set what The Movie Database says (the year, the
poster, its id there) fills in what is still missing. Each watch is the account's (one it has already, of the film on the same
date, is left as it is); a film to see is a watch of the status Want to see,
added when the account has none of that film. The people named are the
account's own, matched by name exactly; --films can run again.

Podcasts come from data/yaml/podcasts.yaml: each podcast with its cover
(static/images/podcast-<internal_id>.jpg) and the episodes of it heard
(chapters), each as its feed says it, go to the shared podcasts and
episodes (found again by the podcast's name and the episode's guid); the
user's rating and review of a podcast to their podcasts heard, and when,
where and on what each episode was heard to their episodes heard. Only
what is missing is added, so --podcasts can run again; the full import
includes them when the source has the file.

Certifications come from data/yaml/certifications.yaml: each names its
issuer by its id in organizations.yaml, and is issued by the account's
organization of that one's name. A certification is found again by its
name, so --certifications can run again; the full import includes them when
the source has the file.

Courses come from data/yaml/courses.yaml: each with the organization it was
taken through (provider) and the one that gave it (school), the account's
organizations of those names (one it does not have is added, a Company), who
taught it (the account's person of each name, or a new one) and when it was
finished. A course is found again by its name, so --courses can run again;
the full import includes them when the source has the file.

Trips come from data/yaml/trips.yaml (where to, the countries, when, how many
days, who came along, a remark), lectures from data/yaml/lectures.yaml (the
name, the description, the lecturers, where, the country, when, the rating,
the review, who came along) and rallies from data/yaml/political_rallies.yaml
(what it was, where, the country, when, the review, who came along). Who came
along are the account's people, found by name exactly (one not found stops
the import); an empty with is going alone. A lecturer is the account's person
of that name, or a new one. Each is found again by its name and date, so
--trips, --lectures and --rallies can run again; the full import includes
them when the source has the file.

The full import (no mode flag) replaces everything the user had in these
tables, in one transaction. It is meant for an empty account: when the
account has any of these rows already it stops, since replacing them would
lose every edit made in the app since the last import, unless
--replace-everything is given with the account's email again. The --books,
--audio-books, --podcasts, --films, --certifications, --courses, --trips, --lectures, --rallies, --youtube-history and --only-types modes add to what is
there and are safe to run again. Unknown fields in the YAML stop the import rather than being
dropped, so nothing is lost on the way in.

The user must have signed in at least once; pass the email they signed in
with (there is one account per email; --subject insists that it has that
login, e.g. google:1087...).

  scripts/import_world.py --email me@example.com [--source ../veltzer.github.io]

With --audio-courses only the audio courses are imported, added to what the
account already has and touching nothing else; it stops if the account has
audio courses already, rather than replace what was edited since. --youtube
does the same for the YouTube videos. --audio-books adds the Audible books
the account does not have yet and refreshes what Audible changes on those
it has (finished, how much was heard, the rating there), leaving the rest as
edited; it can run again. --books adds the books the account
does not have yet, and can run again. --youtube-history adds the watch
history to the videos there are: the ones not there yet as new rows, and
YouTube's details (channel, category, ...) on those already there; it can
run again.

The database is DATABASE_URL (default: the local sqlite file); for Cloud SQL
see doc/deploy.md.
"""

import argparse
import datetime
import email.utils
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
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session, selectinload

from myworld import audible, languages, movies
from myworld import names as naming
from myworld.addresses import parse_address
from myworld.cities import city_key, country_name, parse_location
from myworld.models import (
    CERTIFICATION_KINDS,
    CONCERT_VENUE_KIND,
    DEFAULT_LOCALE,
    MUSEUM_KIND,
    MUSEUM_VISIT,
    AudioBook,
    AudioBookHeard,
    AudioBookListen,
    AudioBookVersion,
    AudioCourse,
    Certification,
    City,
    Concert,
    Country,
    Course,
    Cover,
    Device,
    EpisodeHeard,
    Film,
    FilmWatch,
    Group,
    Image,
    Lecture,
    Organization,
    OrganizationType,
    Owning,
    Person,
    PersonName,
    PersonOrganization,
    PersonOrganizationType,
    PersonRelation,
    PersonRelationType,
    PersonType,
    Place,
    PlaceKind,
    Podcast,
    PodcastEpisode,
    PodcastHeard,
    Rally,
    Read,
    RelationType,
    Trip,
    User,
    UserWork,
    Visit,
    VisitType,
    Work,
    WorkTitle,
    YouTubeVideo,
    audio_course_lecturers,
    concert_companions,
    concert_groups,
    concert_performers,
    course_lecturers,
    film_watch_companions,
    group_members,
    lecture_companions,
    lecture_lecturers,
    library_entry_authors,
    make_engine,
    organization_relation_types,
    organization_type_links,
    person_organizations,
    person_type_links,
    rally_companions,
    region_for,
    trip_companions,
    trip_countries,
    visit_companions,
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
    "Publisher": "Publishes books, audio books, courses or broadcasts",
    "Training Company": "Sells courses to companies and hires teachers to give them",
}
DEFAULT_ORGANIZATION_TYPE = "Company"
# the type of an organization whose functions include publisher
PUBLISHER_TYPE = "Publisher"
# the type, besides Company, of an organization whose functions include training-provider
TRAINING_TYPE = "Training Company"
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
# how a person is linked to an organization, every import starts the user with;
# people.yaml's organizations are where the person worked
PERSON_ORGANIZATION_TYPES = {
    "Worked at": "Was employed there",
    "Studied at": "Was a student there",
    "Taught at": "Taught there",
    "Consulted for": "Was a consultant for them",
    "Founded": "Founded it",
    "Member of": "Was a member",
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
# company; a type field in the YAML (a type name, or a list of them) wins over this list
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
# audio_books.yaml: an audio book heard, not from a source's library, said as an audio course is
AUDIO_BOOK_FIELDS = DATE_FIELDS | {"name", "authors", "date_started_utcz", "location", "device", "progress"}
# a podcast, with its episodes heard (chapters), each as its feed says it, and when, where and on what it was heard;
# internal_id only names the podcast's cover (static/images/podcast-<internal_id>.jpg)
PODCAST_FIELDS = {"name", "url", "rss_feed", "rating", "review", "internal_id", "chapters"}
PODCAST_EPISODE_FIELDS = DATE_FIELDS | {
    "title", "description", "pubDate", "episode", "duration", "episodeType", "explicit", "enclosure_url", "image", "author", "guid", "location", "device",
}
# certifications.yaml: a certification held, its issuer by its id in organizations.yaml, and the day it was given (YYYY-MM-DD)
CERTIFICATION_FIELDS = {"id", "name", "organization", "kind", "date", "remark"}
COURSE_FIELDS = DATE_FIELDS | {"name", "provider", "school", "lecturers", "remark"}
TRIP_FIELDS = DATE_FIELDS | {"where", "countries", "duration_days", "remark", "with"}
LECTURE_FIELDS = DATE_FIELDS | {"name", "description", "lecturers", "location", "country", "rating", "review", "with"}
# a rally's description is what it was: its name here
RALLY_FIELDS = DATE_FIELDS | {"description", "location", "country", "review", "with"}
YOUTUBE_FIELDS = DATE_FIELDS | {"id", "name", "rating", "review", "device", "location"}
# video_features.yaml: a time a film was watched; the ids are its IMDb number ("0816692"), Wikidata item and Rotten Tomatoes page
FILM_FIELDS = DATE_FIELDS | {"name", "imdb_id", "wikidata_id", "rotten_tomatoes_id", "location", "device", "rating", "review", "with"}
# movies_to_see.json: a film to see, by its IMDb number, who recommended it and its genre
FILM_TO_SEE_FIELDS = {"imdb_id", "recommended_by", "genre"}
# video_series.yaml: a series watched, as a film is, with the seasons seen and those not
SERIES_FIELDS = DATE_FIELDS | {"name", "imdb_id", "wikidata_id", "rotten_tomatoes_id", "location", "device", "rating", "review", "seasons_seen", "seasons_not_seen"}
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


def _optional_items(source: Path, name: str, fields: set[str]) -> list[dict[str, Any]]:
    """ The items of data/yaml/<name>.yaml, or none when the source no longer has the file. """
    return _items(source, name, fields) if (source / "data" / "yaml" / f"{name}.yaml").exists() else []


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


def types_for(name: str, functions: list[str] | None = None) -> list[str]:
    """
    The type names an organization of organizations.yaml gets when the YAML
    does not say: its type by name (ORGANIZATION_TYPE_BY_NAME), and Publisher
    when its functions include publisher (BBC Radio is both); a training
    provider is a Training Company, and a Company too unless its name says
    otherwise; a Company when nothing says anything.
    """
    types = [ORGANIZATION_TYPE_BY_NAME[name]] if name in ORGANIZATION_TYPE_BY_NAME else []
    if "publisher" in (functions or []):
        types.append(PUBLISHER_TYPE)
    if "training-provider" in (functions or []):
        types = (types or [DEFAULT_ORGANIZATION_TYPE]) + [TRAINING_TYPE]
    return types or [DEFAULT_ORGANIZATION_TYPE]


def _yaml_types(item: dict[str, Any]) -> list[str]:
    """ The type field of an organization of organizations.yaml: a type name or a list of them, each once. """
    value = item.get("type") or []
    return list(dict.fromkeys([value] if isinstance(value, str) else value))


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
    if person.lectured or person.lectures_given or person.courses_given:
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


def _starting_types[T: (OrganizationType, PersonType, RelationType, PersonOrganizationType)](
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
    _, link_added = _starting_types(session, owner, PersonOrganizationType, PERSON_ORGANIZATION_TYPES)
    relation_types = {t.name: t for t in session.scalars(select(PersonRelationType).where(PersonRelationType.owner_id == owner.id))}
    person_relation_added = 0
    for name, (inverse, description) in PERSON_RELATION_TYPES.items():
        if name not in relation_types:
            relation_types[name] = PersonRelationType(owner_id=owner.id, name=name, inverse=inverse, description=description)
            session.add(relation_types[name])
            person_relation_added += 1
    added = org_added + person_added + relation_added + link_added + person_relation_added
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
    for organization in session.scalars(select(Organization).where(Organization.owner_id == owner.id, ~Organization.types.any())):
        organization.types = [org_types[name] for name in types_for(organization.name, [relation.name.lower() for relation in organization.relations])]
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
    users = session.execute(select(User).where(User.email == email).options(selectinload(User.logins))).scalars().all()
    if subject is not None:
        # a login's subject; a bare one is Google's, as it once was kept
        wanted = {subject, f"google:{subject}"}
        users = [u for u in users if any(login.subject in wanted for login in u.logins)]
    if not users:
        raise WorldImportError(f"no account for {email}{f' with subject {subject}' if subject else ''}: sign in once first")
    # one account per email (users.email is unique)
    return users[0]


# what the full import deletes and makes again, so what an account must not have unless it is replaced on purpose;
# the shared rows (countries, cities, places) are everyone's: never deleted, found again or added
REPLACED_MODELS = (
    AudioCourse, AudioBookListen, AudioBookHeard, EpisodeHeard, PodcastHeard, FilmWatch, YouTubeVideo, Device, Concert, Visit, Certification, Course, Trip, Lecture, Rally, Group, Person, Organization,
    OrganizationType, PersonType, RelationType, PersonRelationType, PersonOrganizationType, Image,
)


def _shared_image_ids(session: Session) -> set[int]:
    """ The images shared rows show: kept whoever uploaded them (a full import replaces only an account's own). """
    found: set[int] = set()
    for model in (Place, Podcast, AudioBookVersion, Film, City, Country):
        found |= {image_id for image_id in session.scalars(select(model.image_id)) if image_id is not None}
    return found


def existing_rows(session: Session, owner: User) -> dict[str, int]:
    """ How many rows of each table the full import would replace owner has, the empty ones left out. """
    counts = {
        model.__tablename__: session.scalar(select(func.count()).select_from(model).where(model.owner_id == owner.id)) or 0
        for model in REPLACED_MODELS
    }
    counts["books"] = session.scalar(select(func.count()).select_from(UserWork).where(
        UserWork.owner_id == owner.id, UserWork.work_id.in_(select(Work.id).where(Work.kind == "book")),
    )) or 0
    return {table: count for table, count in counts.items() if count}


def import_world(session: Session, owner: User, source: Path, replace: bool = False) -> dict[str, int]:
    """ Replace owner's concerts, museums, people, organizations and images with those under source. Does not commit.

    Stops when owner has any of these rows already, unless replace: the rows may hold edits made in the app.
    """
    existing = existing_rows(session, owner)
    if existing and not replace:
        what = ", ".join(f"{count} {table}" for table, count in existing.items())
        raise WorldImportError(
            f"the account has data already ({what}); the full import deletes it all and loses every edit made in the app."
            f" Add only what is missing with --books, --audio-books, --podcasts, --films, --certifications, --youtube-history or --only-types, or pass --replace-everything {owner.email} to replace it anyway",
        )
    # the site no longer keeps these (My World does, since 2026-11-23): a source without one has none of it to import
    people_items = _optional_items(source, "people", PERSON_FIELDS)
    organization_items = _optional_items(source, "organizations", ORGANIZATION_FIELDS)
    concert_items = _optional_items(source, "concerts", CONCERT_FIELDS)
    museum_items = _optional_items(source, "museums", MUSEUM_FIELDS)
    image_dir = source / "static" / "images"

    # the link rows explicitly: sqlite does not enforce ON DELETE CASCADE unless asked to
    concerts_of_owner = select(Concert.id).where(Concert.owner_id == owner.id)
    session.execute(delete(concert_companions).where(concert_companions.c.concert_id.in_(concerts_of_owner)))
    session.execute(delete(concert_performers).where(concert_performers.c.concert_id.in_(concerts_of_owner)))
    session.execute(delete(concert_groups).where(concert_groups.c.concert_id.in_(concerts_of_owner)))
    session.execute(delete(group_members).where(group_members.c.group_id.in_(select(Group.id).where(Group.owner_id == owner.id))))
    session.execute(delete(visit_companions).where(visit_companions.c.visit_id.in_(select(Visit.id).where(Visit.owner_id == owner.id))))
    session.execute(delete(course_lecturers).where(course_lecturers.c.course_id.in_(select(Course.id).where(Course.owner_id == owner.id))))
    session.execute(delete(trip_countries).where(trip_countries.c.trip_id.in_(select(Trip.id).where(Trip.owner_id == owner.id))))
    session.execute(delete(trip_companions).where(trip_companions.c.trip_id.in_(select(Trip.id).where(Trip.owner_id == owner.id))))
    session.execute(delete(lecture_companions).where(lecture_companions.c.lecture_id.in_(select(Lecture.id).where(Lecture.owner_id == owner.id))))
    session.execute(delete(lecture_lecturers).where(lecture_lecturers.c.lecture_id.in_(select(Lecture.id).where(Lecture.owner_id == owner.id))))
    session.execute(delete(rally_companions).where(rally_companions.c.rally_id.in_(select(Rally.id).where(Rally.owner_id == owner.id))))
    session.execute(delete(film_watch_companions).where(
        film_watch_companions.c.film_watch_id.in_(select(FilmWatch.id).where(FilmWatch.owner_id == owner.id)),
    ))
    session.execute(delete(audio_course_lecturers).where(
        audio_course_lecturers.c.audio_course_id.in_(select(AudioCourse.id).where(AudioCourse.owner_id == owner.id)),
    ))
    session.execute(delete(PersonRelation).where(PersonRelation.person_id.in_(select(Person.id).where(Person.owner_id == owner.id))))
    session.execute(delete(PersonName).where(PersonName.person_id.in_(select(Person.id).where(Person.owner_id == owner.id))))
    session.execute(delete(person_type_links).where(person_type_links.c.person_id.in_(select(Person.id).where(Person.owner_id == owner.id))))
    session.execute(delete(person_organizations).where(person_organizations.c.person_id.in_(select(Person.id).where(Person.owner_id == owner.id))))
    session.execute(delete(organization_relation_types).where(
        organization_relation_types.c.organization_id.in_(select(Organization.id).where(Organization.owner_id == owner.id)),
    ))
    session.execute(delete(organization_type_links).where(
        organization_type_links.c.organization_id.in_(select(Organization.id).where(Organization.owner_id == owner.id)),
    ))
    # every person goes, so every author link of owner's library entries does too
    session.execute(delete(library_entry_authors).where(library_entry_authors.c.owner_id == owner.id))
    # the books are added again below, and what hangs on them goes with them (said here, as not
    # every database deletes it by itself); other library entries lose their cover, as every image goes
    books = select(Work.id).where(Work.kind == "book")
    for model in (Read, Cover, Owning):
        session.execute(delete(model).where(model.owner_id == owner.id, model.work_id.in_(books)))
    session.execute(delete(UserWork).where(
        UserWork.owner_id == owner.id, UserWork.work_id.in_(select(Work.id).where(Work.kind == "book")),
    ))
    for entry in session.scalars(select(UserWork).where(UserWork.owner_id == owner.id, UserWork.image_id.is_not(None))):
        entry.image_id = None
    session.flush()
    shared_images = _shared_image_ids(session)
    for model in REPLACED_MODELS:
        doomed = delete(model).where(model.owner_id == owner.id)
        session.execute(doomed.where(model.id.not_in(shared_images)) if model is Image and shared_images else doomed)
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

    city = Cities(session, owner)
    organizations: dict[str, Organization] = {}
    for item in organization_items:
        if item["name"] in organizations:
            raise WorldImportError(f"organizations.yaml: {item['name']!r} appears twice")
        organization = Organization(
            owner_id=owner.id,
            name=item["name"],
            types=[organization_type(name) for name in _yaml_types(item) or types_for(item["name"], item.get("functions"))],
            relations=[relation_type(word) for word in dict.fromkeys(item.get("functions", []))],
            **{key: item.get(key, "") for key in sorted(ORGANIZATION_COLUMNS - {"name", "type", "functions", "address", "remark"})},
            **_address(item.get("address", ""), item.get("remark", ""), city.of_location(item.get("location", "")), city),
            headquarters=city.of_location(item.get("location", "")),
            details={key: _json_safe(item[key]) for key in sorted(ORGANIZATION_DETAILS) if key in item},
            # logos live in data/, as logos/<slug>.svg
            image=image(source / "data" / item["logo"], required=True) if "logo" in item else None,
        )
        organizations[organization.name] = organization
        session.add(organization)

    link_kinds, _ = _starting_types(session, owner, PersonOrganizationType, PERSON_ORGANIZATION_TYPES)
    people: dict[str, Person] = {}
    for item in people_items:
        if item["name"] in people:
            raise WorldImportError(f"people.yaml: {item['name']!r} appears twice")
        names = _person_organizations(item)
        for name in names:
            if name not in organizations:
                organizations[name] = Organization(owner_id=owner.id, name=name, types=[organization_type(DEFAULT_ORGANIZATION_TYPE)])
                session.add(organizations[name])
        honorific, first_name, middle_name, surname = split_name(item["name"])
        person = Person(
            owner_id=owner.id, honorific=honorific, first_name=first_name, middle_name=middle_name, surname=surname, description=item.get("description", ""),
            organization_links=[PersonOrganization(relation_type=link_kinds["Worked at"], organization=organizations[name]) for name in names],
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

    place = Places(session, owner, city)
    for item in concert_items:
        session.add(Concert(
            owner_id=owner.id,
            name=item["name"],
            performers=performers(item),
            event=item.get("event", ""),
            genre=item.get("genre", ""),
            place=(at := place(item.get("venue", ""), item.get("city", ""), item.get("country", ""))),
            tickets=item.get("tickets"),
            broadcast=bool(item.get("broadcast", False)),
            review=item.get("review", ""),
            # what is known of the place but not on it (a shared place has no remark): the concert says it
            remark="\n".join(filter(None, (item.get("remark", ""), place.notes.get(at) if at else ""))),
            image=image(image_dir / item["image"], required=True) if "image" in item else None,
            image_source=item.get("image_source", ""),
            image_license=item.get("image_license", ""),
            image_author=item.get("image_author", ""),
            people=with_people(item),
            **_dates(item),
        ))

    # a museum is a shared place of the kind Museum, one whatever the times it was visited: found
    # again by its name and city, or made with the city, website and photo of its first (lowest
    # internal_id) visit; every item is a visit of the account, of the type Museum visit
    museum_kind = session.scalars(select(PlaceKind).where(PlaceKind.name == MUSEUM_KIND)).one()
    museum_visit = session.scalars(select(VisitType).where(VisitType.name == MUSEUM_VISIT)).one()
    museums: dict[str, Place] = {}
    for item in sorted(museum_items, key=lambda item: item["internal_id"]):
        if item["name"] not in museums:
            where = city(item.get("city", ""), "", "")
            found = place.find(item["name"], where)
            if found is None:
                found = Place(name=item["name"], city=where, website=item.get("url", ""))
                photo = image(image_dir / f"museum-{item['internal_id']}.jpg", required=False)
                if photo is not None:
                    session.flush()
                    found.image_id = photo.id
                session.add(found)
                place.remember(found)
            if museum_kind not in found.kinds:
                found.kinds.append(museum_kind)
            museums[item["name"]] = found
    for item in museum_items:
        session.add(Visit(
            owner_id=owner.id,
            place=museums[item["name"]],
            type=museum_visit,
            rating=item.get("rating"),
            review=item.get("review", ""),
            remark=item.get("remark", ""),
            tickets=item.get("tickets"),
            people=with_people(item),
            **_dates(item),
        ))
    session.flush()
    courses = import_audio_courses(session, owner, source)
    # the site no longer keeps them (My World does): a source without them has none to import
    has_audio_books = any((source / "data" / "yaml" / name).exists() for name in AUDIO_BOOK_FILES)
    audio_books = import_audio_books(session, owner, source) if has_audio_books else {"audio books added": 0, "images": 0, "devices added": 0}
    podcasts = import_podcasts(session, owner, source) if _podcasts_path(source).exists() else {"podcasts added": 0, "podcast episodes added": 0, "covers added": 0, "devices added": 0}
    # the site no longer keeps them either: a source without one imports none of it
    has_videos = (source / "data" / "yaml" / "video_youtube.yaml").exists()
    videos = import_youtube(session, owner, source) if has_videos else {"YouTube videos": 0, "devices added": 0}
    history = import_youtube_history(session, owner, source) if _history_path(source).exists() else {"YouTube videos added": 0}
    films = import_films(session, owner, source) if _films_path(source).exists() else {"films added": 0, "film watches added": 0, "posters added": 0, "devices added": 0}
    books = import_books(session, owner, source)
    certifications = import_certifications(session, owner, source) if _certifications_path(source).exists() else {"certifications added": 0}
    courses_taken = import_courses(session, owner, source) if _yaml_path(source, "courses").exists() else {"courses added": 0, "lecturers added": 0}
    outings = {
        what: OUTINGS[what](session, owner, source) if _yaml_path(source, file).exists() else {f"{what} added": 0, "lecturers added": 0}
        for what, file in OUTING_FILES.items()
    }
    typed = give_types(session, owner)
    return {
        "people": len(people) + courses["lecturers added"] + books["authors added"] + sum(o.get("lecturers added", 0) for o in outings.values()) + courses_taken["lecturers added"], "organizations": len(organizations), "organization types": len(types),
        "relation types": len(relation_types), "person types": len(PERSON_TYPES), "people with a profession": typed["people given a profession"], "people related to the user": typed["people given a relation"],
        "concerts": len(concert_items), "places": place.added, "museums": len(museums), "museum visits": len(museum_items), "audio courses": courses["audio courses"],
        "audio books": audio_books["audio books added"],
        "podcasts": podcasts["podcasts added"], "podcast episodes": podcasts["podcast episodes added"],
        "films": films["films added"], "film watches": films["film watches added"],
        "certifications": certifications["certifications added"],
        "courses": courses_taken["courses added"],
        **{what: outings[what][f"{what} added"] for what in OUTING_FILES},
        "YouTube videos": videos["YouTube videos"] + history["YouTube videos added"], "devices": courses["devices added"] + audio_books["devices added"] + podcasts["devices added"] + films["devices added"] + videos["devices added"],
        "books": books["books"], "images": len(images) + courses["images"] + audio_books["images"] + podcasts["covers added"] + films["posters added"] + books["covers"],
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





AUDIO_BOOK_FILES = ("audible.yaml", "audio_books.yaml")


def import_audio_books(session: Session, owner: User, source: Path) -> dict[str, int]:
    """
    Add owner's audio books from source: those of the Audible library
    (audible.yaml, _import_audible) and those heard elsewhere
    (audio_books.yaml, _import_heard), whichever of the two is there; both
    can run again. Does not commit.
    """
    yaml_dir = source / "data" / "yaml"
    if not any((yaml_dir / name).exists() for name in AUDIO_BOOK_FILES):
        raise WorldImportError(f"{yaml_dir}: neither {' nor '.join(AUDIO_BOOK_FILES)} is there (veltzer.github.io no longer keeps them; its git history does)")
    counts = {"audio books added": 0, "audio books refreshed": 0, "images": 0, "devices added": 0}
    for name, part in (("audible.yaml", _import_audible), ("audio_books.yaml", _import_heard)):
        if (yaml_dir / name).exists():
            for key, count in part(session, owner, yaml_dir / name, source).items():
                counts[key] += count
    return counts


def _import_heard(session: Session, owner: User, path: Path, source: Path) -> dict[str, int]:
    """
    Add the audio books owner heard elsewhere (audio_books.yaml) as their
    listens of the books' MP3 versions: a book (shared) found by its title
    and authors (the file says no subtitle: of one so found, the first), or
    else added, and its MP3 version, or else added; one
    owner heard already is left as it is. Does not commit.
    """
    items = _items(source, "audio_books", AUDIO_BOOK_FIELDS)
    books: dict[tuple[str, str], AudioBook] = {}
    for found in session.scalars(select(AudioBook).options(selectinload(AudioBook.versions)).order_by(AudioBook.id)):
        books.setdefault((found.name, found.authors), found)
    listened = set(session.scalars(select(AudioBookListen.version_id).where(AudioBookListen.owner_id == owner.id)))
    heard = set(session.scalars(select(AudioBookHeard.book_id).where(AudioBookHeard.owner_id == owner.id)))
    device = Devices(session, owner)
    added = 0
    for item in items:
        name = str(item["name"]).strip()
        authors = [str(a).strip() for a in item.get("authors", []) if str(a).strip()]
        if any("," in a for a in authors):
            raise WorldImportError(f"{path}: {name!r} has an author with a comma, which the authors' list would split")
        book = books.get((name, ", ".join(authors)))
        if book is None:
            book = AudioBook(name=name, authors=", ".join(authors))
            session.add(book)
            books[name, book.authors] = book
            added += 1
        version = next((v for v in book.versions if v.kind == "mp3"), None)
        if version is None:
            version = AudioBookVersion(book=book, kind="mp3")
            session.add(version)
            session.flush()
        if version.id in listened:
            continue
        dates = _dates(item)
        session.add(AudioBookListen(
            owner_id=owner.id,
            version=version,
            finished=any(dates.get(key) for key in ("date_utcz", "date_ymd", "date_my", "date_y")),
            started_utcz=_stamp(item, "date_started_utcz"),
            progress=str(item.get("progress", "")),
            listened_at=str(item.get("location", "")),
            device=device(str(item.get("device", ""))),
            **dates,
        ))
        listened.add(version.id)
        if book.id not in heard:
            session.add(AudioBookHeard(owner_id=owner.id, book=book))
            heard.add(book.id)
    session.flush()
    return {"audio books added": added, "devices added": device.added}


def _import_audible(session: Session, owner: User, path: Path, source: Path) -> dict[str, int]:
    """
    Add the books of owner's Audible library from source (audible.yaml, as
    audible-cli exports it) as the Audible library importer does
    (audible.store_library), their covers from
    static/images/audible-<asin>.jpg. Safe to run again. Does not commit.
    """
    with path.open(encoding="UTF8") as fp:
        items = yaml.safe_load(fp)["items"]
    image_dir = source / "static" / "images"

    def cover(asin: str, _url: str) -> bytes | None:
        file = image_dir / f"audible-{asin}.jpg"
        return file.read_bytes() if file.exists() else None

    try:
        audible.check_items(items, str(path))
        return audible.store_library(session, owner, items, cover)
    except audible.AudibleError as e:
        raise WorldImportError(str(e)) from e


def _check_fields(path: Path, what: str, item: dict[str, Any], fields: set[str]) -> None:
    unknown = set(item) - fields
    if unknown:
        raise WorldImportError(f"{path}: {what} has fields this import does not know: {sorted(unknown)}")


def _english_first(alternatives: list[dict[str, Any]]) -> dict[str, Any]:
    """ Of a name given in several languages, the English one, or else the first. """
    return next((a for a in alternatives if a["language"] == "english"), alternatives[0])


def _language(code: str) -> str:
    return code.capitalize()


# books_read.yaml's languages as the app's (LOCALES); "unknown" is none
YAML_LOCALES = {
    "english": "en", "hebrew": "he", "arabic": "ar", "yiddish": "yi", "french": "fr", "german": "de", "spanish": "es",
    "italian": "it", "portuguese": "pt", "russian": "ru", "czech": "cs", "greek": "el", "unknown": "",
}


def _locale(language: str) -> str:
    """ The app's language code for a language of books_read.yaml ("hebrew" is "he"). """
    if language not in YAML_LOCALES:
        raise WorldImportError(f"books_read.yaml: unknown language {language!r}")
    return YAML_LOCALES[language]


def _named_parts(item: dict[str, Any], title: str) -> list[str]:
    """
    What notes once said of a book's other titles and its authors' other
    names, which are their own fields now: an import before them wrote these
    into the notes, and _strip_parts takes them out again.
    """
    parts = [f"{_language(name['language'])} title: {name['name']}" for name in item["names"] if name["name"] != title]
    for alternatives in item["authors"]:
        shown = _english_first(alternatives)
        parts += [f"Author in {_language(other['language'])}: {other['name']}" for other in alternatives if other is not shown]
    return parts


def _strip_parts(notes: str, parts: list[str]) -> str:
    """ notes ("A. B. C", as _book_notes joins them) without the sentences that are exactly one of parts. """
    for part in parts:
        part = part.rstrip(".")
        if notes == part:
            notes = ""
        elif notes.startswith(f"{part}. "):
            notes = notes[len(part) + 2:]
        elif f". {part}. " in notes:
            notes = notes.replace(f". {part}. ", ". ", 1)
        elif notes.endswith(f". {part}"):
            notes = notes[:-len(part) - 2]
    return notes


def _reading_day(reading: dict[str, Any]) -> datetime.date | None:
    """ The day a reading ended, where the reader was (its timezone). """
    if reading.get("undated"):
        return None
    stamp = datetime.datetime.fromisoformat(str(reading["date"]))
    return stamp.astimezone(zoneinfo.ZoneInfo(reading.get("timezone") or "UTC")).date()


def _book_notes(item: dict[str, Any]) -> str:
    """ What a library entry has no field for, in a few sentences (what the user thought of it is its review). """
    parts = []
    readings = item["readings"]
    if len(readings) > 1 or any(r["language"] != item["language"] for r in readings):
        described = []
        for reading in readings:
            day = _reading_day(reading)
            described.append(f"{_language(reading['language'])} ({day.isoformat() if day else 'date unknown'})")
        parts.append(f"Read in {'; '.join(described)}")
    if item["language"] not in ("english", "unknown"):
        parts.append(f"Written in {_language(item['language'])}")
    # the other titles and the authors' other names are fields of their own (titles, people's names)
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
    each book owner does not have yet (a work of owner's left without one is
    reused), so it can run again. An entry owner has already only
    gets its cover, when it has none and source has one now, its authors,
    when it has none, and the language it was read in, when it has none.
    Each author is owner's person of that name, or a new person, and is a
    Book Author (a person type). A book's titles in other languages are
    added to its work, and an author's names in them to the person, where
    they are missing; an entry's notes lose what an import before them said
    of these there. Does not commit.
    """
    items = _book_items(source)
    image_dir = source / "static" / "images"
    stored = {image.filename: image for image in session.scalars(select(Image).where(Image.owner_id == owner.id))}
    added = skipped = images = uncovered = covered = credited = people_added = typed = 0
    titled = named = localized = tidied = 0
    person_types, _ = _starting_types(session, owner, PersonType, {"Book Author": PERSON_TYPES["Book Author"]})
    book_author = person_types["Book Author"]
    by_name: dict[str, list[Person]] = {}
    for person in session.scalars(select(Person).where(Person.owner_id == owner.id).options(selectinload(Person.types), selectinload(Person.names))):
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

    def other_names(item: dict[str, Any], authors: list[Person]) -> None:
        """ Each author's names in other languages than the one they go by, where the person has none in that language. """
        nonlocal named
        for alternatives, person in zip(item["authors"], authors, strict=True):
            shown = _english_first(alternatives)
            for other in alternatives:
                locale = _locale(other["language"])
                if other is shown or not locale or locale == DEFAULT_LOCALE or any(n.locale == locale for n in person.names):
                    continue
                in_locale = PersonName(locale=locale, name="")
                in_locale.set_whole(other["name"])
                person.names.append(in_locale)
                named += 1

    def other_titles(item: dict[str, Any], work: Work, main: dict[str, Any]) -> None:
        """ The book's titles in other languages than its main one, added to its work in the languages it has none in (one title per language). """
        nonlocal titled
        have = {work.title_locale, *(t.locale for t in work.titles)}
        for name in item["names"]:
            locale = _locale(name["language"])
            if name is main or not locale or locale in have:
                continue
            work.titles.append(WorkTitle(locale=locale, title=name["name"]))
            have.add(locale)
            titled += 1

    def read_in(item: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """ The reading an entry is of (the latest dated, else the last listed), and the language it was in. """
        readings = item["readings"]
        dated = sorted((r for r in readings if not r.get("undated")), key=lambda r: str(r["date"]))
        main = dated[-1] if dated else readings[-1] if readings else None
        return main, _locale(main["language"]) if main else ""

    def reads_of(item: dict[str, Any]) -> list[Read]:
        """
        Every reading of the book, as a read of the entry: its day, its language,
        its rating and its review, where known. A book rated only in the text
        list has that rating and review on the reading it goes by; one never
        read has a reading that says it is wanted.
        """
        main = read_in(item)[0]
        reads = []
        for reading in item["readings"]:
            rating = reading.get("rating")
            review = str(reading["review"]).rstrip(".") if reading.get("review") else ""
            if reading is main and rating is None and item.get("text_rating") is not None:
                rating = item["text_rating"]
                review = ". ".join(part for part in (item.get("text_review", ""), review) if part)
            reads.append(Read(read_on=_reading_day(reading), locale=_locale(reading["language"]) or None, status="done", rating=rating, review=review))
        return reads or [Read(status="wishlist", review="")]

    locales = languages.known(session)
    for item in items:
        main_name = _english_first(item["names"])
        title = main_name["name"]
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
                work = session.scalars(select(Work).where(Work.owner_id == owner.id, Work.kind == "book", column == str(value))).first()
        if work is None:
            work = session.scalars(select(Work).where(
                Work.owner_id == owner.id, Work.kind == "book", Work.title == title, Work.creator == creator, Work.year.is_(None),
            )).one_or_none()
        if work is None:
            work = Work(owner_id=owner.id, kind="book", title=title, creator=creator, year=None, title_locale=_locale(main_name["language"]) or languages.locale_of(locales, title) or DEFAULT_LOCALE)
            session.add(work)
        # the author and the catalog ids are only filled in, never overwritten
        work.creator = work.creator or creator
        work.goodreads_id = work.goodreads_id or str(goodreads_id)
        work.simania_id = work.simania_id or str(simania_id)
        work.isbn = work.isbn or str(item.get("isbn", ""))
        session.flush()
        other_titles(item, work, main_name)
        entry = session.get(UserWork, (owner.id, work.id))
        if entry is not None:
            skipped += 1
            # its reads, for an entry imported before there were any
            if not entry.reads and item["readings"]:
                entry.reads = reads_of(item)
                localized += bool(entry.locale)
            # what notes said of the other titles and names, now fields of their own
            stripped = _strip_parts(entry.notes, _named_parts(item, title))
            if stripped != entry.notes:
                entry.notes = stripped
                tidied += 1
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
            # the authors' names in other languages, of the people linked by their English name
            linked = {naming.key(person.name): person for person in entry.authors}
            if all(naming.key(name) in linked for name in names):
                other_names(item, [linked[naming.key(name)] for name in names])
            continue
        cover = book_cover(goodreads_id, simania_id)
        session.add(UserWork(
            owner_id=owner.id,
            work_id=work.id,
            notes=_book_notes(item),
            image_id=cover.id if cover else None,
            reads=reads_of(item),
            owned=[locale for locale in dict.fromkeys(_locale(o["language"]) for o in item.get("ownings", [])) if locale],
            authors=(authors := [author(name) for name in names]),
        ))
        other_names(item, authors)
        added += 1
        uncovered += cover is None
    session.flush()
    return {
        "books": added, "books there already": skipped, "covers": images,
        "covers given to books there already": covered, "books with no cover": uncovered,
        "authors added": people_added, "people made book authors": typed, "authors given to books there already": credited,
        "titles in other languages": titled, "author names in other languages": named,
        "languages given to books there already": localized, "notes tidied": tidied,
    }


NOT_KEPT = "veltzer.github.io no longer keeps it; its git history does"


def _podcasts_path(source: Path) -> Path:
    return source / "data" / "yaml" / "podcasts.yaml"


def _published(value: str, where: str) -> datetime.datetime:
    """ A feed's pubDate ("Wed, 28 Oct 2020 13:00:00 -0000"), as the naive UTC the columns keep. """
    try:
        stamp = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError) as e:
        raise WorldImportError(f"{where}: pubDate {value!r} is not a date") from e
    if stamp.tzinfo is None:
        return stamp
    return stamp.astimezone(datetime.UTC).replace(tzinfo=None)


def import_podcasts(session: Session, owner: User, source: Path) -> dict[str, int]:
    """
    Add the podcasts of podcasts.yaml to the shared ones, with their covers
    (static/images/podcast-<internal_id>.jpg) and the episodes heard, and
    owner's listening to them: a podcast is found again by its name and an
    episode in it by its feed's guid (both shared, everyone's), and owner's
    podcast heard (rating, review) and episodes heard (when, where, on what
    device) are added where owner has none yet. Only what is missing is
    added, so it runs again safely and keeps what was edited. Does not commit.
    """
    path = _podcasts_path(source)
    if not path.exists():
        raise WorldImportError(f"{path} is not there ({NOT_KEPT})")
    items = _items(source, "podcasts", PODCAST_FIELDS)
    image_dir = source / "static" / "images"
    have = {p.name: p for p in session.scalars(select(Podcast).options(selectinload(Podcast.heard), selectinload(Podcast.episodes).selectinload(PodcastEpisode.heard)))}
    device = Devices(session, owner)
    counts = {"podcasts added": 0, "podcast episodes added": 0, "covers added": 0, "podcasts heard added": 0, "episodes heard added": 0}
    for item in items:
        name = str(item["name"]).strip()
        podcast = have.get(name)
        if podcast is None:
            podcast = Podcast(name=name, url=item.get("url", ""), rss_feed=item.get("rss_feed", ""))
            session.add(podcast)
            have[name] = podcast
            counts["podcasts added"] += 1
        cover = image_dir / f"podcast-{item['internal_id']}.jpg" if "internal_id" in item else None
        if podcast.image_id is None and podcast.image is None and cover is not None and cover.exists():
            data = cover.read_bytes()
            podcast.image = Image(owner_id=owner.id, filename=cover.name, content_type="image/jpeg", sha256=hashlib.sha256(data).hexdigest(), data=data)
            counts["covers added"] += 1
        if not any(row.owner_id == owner.id for row in podcast.heard):
            podcast.heard.append(PodcastHeard(owner_id=owner.id, rating=item.get("rating"), review=item.get("review", "")))
            counts["podcasts heard added"] += 1
        episodes = {e.guid: e for e in podcast.episodes if e.guid}
        for chapter in item.get("chapters", []):
            unknown = set(chapter) - PODCAST_EPISODE_FIELDS
            where = f"{path}: {name!r}, {chapter.get('title')!r}"
            if unknown:
                raise WorldImportError(f"{where} has fields this import does not know: {sorted(unknown)}")
            guid = str(chapter["guid"]) if chapter.get("guid") else None
            episode = episodes.get(guid) if guid is not None else None
            if episode is None:
                episode = PodcastEpisode(
                    name=str(chapter["title"]),
                    description=str(chapter.get("description", "")),
                    published_utcz=_published(str(chapter["pubDate"]), where) if chapter.get("pubDate") else None,
                    number=chapter.get("episode"),
                    duration=chapter.get("duration"),
                    episode_type=str(chapter.get("episodeType", "")),
                    explicit=str(chapter.get("explicit", "")),
                    enclosure_url=str(chapter.get("enclosure_url", "")),
                    image_url=str(chapter.get("image", "")),
                    author=str(chapter.get("author", "")),
                    guid=guid,
                )
                podcast.episodes.append(episode)
                if guid is not None:
                    episodes[guid] = episode
                counts["podcast episodes added"] += 1
            if any(heard.owner_id == owner.id for heard in episode.heard):
                continue
            episode.heard.append(EpisodeHeard(
                owner_id=owner.id,
                listened_at=str(chapter.get("location", "")),
                device=device(str(chapter.get("device", ""))),
                **_dates({**chapter, "name": chapter.get("title")}),
            ))
            counts["episodes heard added"] += 1
    session.flush()
    return {**counts, "devices added": device.added}


def _certifications_path(source: Path) -> Path:
    return source / "data" / "yaml" / "certifications.yaml"


def import_certifications(session: Session, owner: User, source: Path) -> dict[str, int]:
    """
    Add the certifications of certifications.yaml that owner does not have
    yet (found again by name), each issued by owner's organization of the
    name organizations.yaml gives its issuer's id. Safe to run again. Does
    not commit.
    """
    items = _items(source, "certifications", CERTIFICATION_FIELDS)
    with (source / "data" / "yaml" / "organizations.yaml").open(encoding="UTF8") as fp:
        issuer_names = {o["id"]: o["name"] for o in yaml.safe_load(fp)["items"]}
    organizations = {o.name: o for o in session.scalars(select(Organization).where(Organization.owner_id == owner.id))}
    have = set(session.scalars(select(Certification.name).where(Certification.owner_id == owner.id)))
    added = 0
    for item in items:
        if item["name"] in have:
            continue
        name = issuer_names.get(item["organization"])
        if name is None or name not in organizations:
            raise WorldImportError(f"certification {item['name']!r}: its issuer, organization {item['organization']}, is not one of the account's organizations")
        kind = item.get("kind", "")
        if kind and kind not in CERTIFICATION_KINDS:
            raise WorldImportError(f"certification {item['name']!r}: kind {kind!r} is not one of {CERTIFICATION_KINDS}")
        session.add(Certification(
            owner_id=owner.id, name=item["name"], organization=organizations[name], kind=kind, remark=item.get("remark", ""),
            date_ymd=datetime.date.fromisoformat(str(item["date"])) if "date" in item else None,
        ))
        have.add(item["name"])
        added += 1
    session.flush()
    return {"certifications added": added}


def _yaml_path(source: Path, name: str) -> Path:
    return source / "data" / "yaml" / f"{name}.yaml"


class _Company:
    """
    The account's people by name, for who came along (each must be there:
    one not found stops the import) and for lecturers (one not found is
    added). Two people of one name stop it too: which one is meant is not
    known.
    """

    def __init__(self, session: Session, owner: User, file: str) -> None:
        self.session, self.owner, self.file = session, owner, file
        self.by_name: dict[str, list[Person]] = {}
        for person in session.scalars(select(Person).where(Person.owner_id == owner.id)):
            self.by_name.setdefault(naming.key(person.name), []).append(person)
        self.added = 0

    def _one(self, name: str) -> Person | None:
        found = self.by_name.get(naming.key(name), [])
        if len(found) > 1:
            raise WorldImportError(f"{self.file}: {len(found)} people are called {name!r}; make the names differ first")
        return found[0] if found else None

    def came(self, item: dict[str, Any], what: str) -> list[Person]:
        names = list(dict.fromkeys(item.get("with") or []))
        missing = [name for name in names if self._one(name) is None]
        if missing:
            raise WorldImportError(f"{self.file}: {what!r}: with names people the account does not have: {missing}")
        return [p for name in names if (p := self._one(name)) is not None]

    def lecturer(self, name: str) -> Person:
        found = self._one(name)
        if found is None:
            honorific, first_name, middle_name, surname = split_name(name)
            found = Person(owner_id=self.owner.id, honorific=honorific, first_name=first_name, middle_name=middle_name, surname=surname, description="")
            self.session.add(found)
            self.by_name[naming.key(name)] = [found]
            self.added += 1
        return found


def _date_key(row: Trip | Lecture | Rally) -> tuple[Any, ...]:
    """ A row's date as the columns keep it, to find a row again by its name and date. """
    return (row.date_utcz, row.date_ymd, row.date_my or "", row.date_y)


def _item_date_key(item: dict[str, Any], name: str) -> tuple[Any, ...]:
    dates = _dates({**item, "name": name})
    return (dates.get("date_utcz"), dates.get("date_ymd"), dates.get("date_my", ""), dates.get("date_y"))


def import_courses(session: Session, owner: User, source: Path) -> dict[str, int]:
    """
    Add the courses of courses.yaml that owner does not have yet (found
    again by name), each with the organizations it was taken through and
    from (owner's of those names; one owner does not have is added, a
    Company) and who taught it (owner's person of each name, or a new one).
    Safe to run again. Does not commit.
    """
    items = _items(source, "courses", COURSE_FIELDS)
    company = _Company(session, owner, "courses.yaml")
    organizations = {o.name: o for o in session.scalars(select(Organization).where(Organization.owner_id == owner.id))}
    have = set(session.scalars(select(Course.name).where(Course.owner_id == owner.id)))
    added = organizations_added = 0

    def organization(name: str) -> Organization | None:
        nonlocal organizations_added
        if not name:
            return None
        if name not in organizations:
            kind = session.scalars(select(OrganizationType).where(OrganizationType.owner_id == owner.id, OrganizationType.name == DEFAULT_ORGANIZATION_TYPE)).first()
            organizations[name] = Organization(owner_id=owner.id, name=name, types=[kind] if kind else [])
            session.add(organizations[name])
            organizations_added += 1
        return organizations[name]

    for item in items:
        if item["name"] in have:
            continue
        session.add(Course(
            owner_id=owner.id, name=item["name"], provider=organization(item.get("provider", "")), school=organization(item.get("school", "")),
            lecturers=[company.lecturer(name) for name in dict.fromkeys(item.get("lecturers") or [])], remark=item.get("remark", ""), **_dates(item),
        ))
        have.add(item["name"])
        added += 1
    session.flush()
    return {"courses added": added, "lecturers added": company.added, "organizations added": organizations_added}


def import_trips(session: Session, owner: User, source: Path) -> dict[str, int]:
    """
    Add the trips of trips.yaml that owner does not have yet (found again by
    where to and when), with their countries and who came along. Safe to
    run again. Does not commit.
    """
    items = _items(source, "trips", TRIP_FIELDS)
    company = _Company(session, owner, "trips.yaml")
    have = {(t.name, _date_key(t)) for t in session.scalars(select(Trip).where(Trip.owner_id == owner.id))}
    cities = Cities(session, owner)
    added = 0
    for item in items:
        key = (item["where"], _item_date_key(item, item["where"]))
        if key in have:
            continue
        people = company.came(item, item["where"])
        countries = [c for name in dict.fromkeys(item.get("countries") or []) if (c := cities.country(name)) is not None]
        session.add(Trip(
            owner_id=owner.id, name=item["where"], countries=countries, days=item.get("duration_days"), remark=item.get("remark", ""),
            people=people, alone="with" in item and not people, **_dates({**item, "name": item["where"]}),
        ))
        have.add(key)
        added += 1
    session.flush()
    return {"trips added": added}


def import_lectures(session: Session, owner: User, source: Path) -> dict[str, int]:
    """
    Add the lectures of lectures.yaml that owner does not have yet (found
    again by name and date), with who gave them (the account's person of
    each name, or a new one) and who came along. Safe to run again. Does not
    commit.
    """
    items = _items(source, "lectures", LECTURE_FIELDS)
    company = _Company(session, owner, "lectures.yaml")
    have = {(lecture.name, _date_key(lecture)) for lecture in session.scalars(select(Lecture).where(Lecture.owner_id == owner.id))}
    cities = Cities(session, owner)
    added = 0
    for item in items:
        key = (item["name"], _item_date_key(item, item["name"]))
        if key in have:
            continue
        people = company.came(item, item["name"])
        session.add(Lecture(
            owner_id=owner.id, name=item["name"], description=" ".join(item.get("description", "").split()),
            lecturers=[company.lecturer(name) for name in dict.fromkeys(item.get("lecturers") or [])],
            location=item.get("location", ""), country=cities.country(item.get("country", "")), rating=item.get("rating"),
            review=item.get("review", ""), people=people, alone="with" in item and not people, **_dates(item),
        ))
        have.add(key)
        added += 1
    session.flush()
    return {"lectures added": added, "lecturers added": company.added}


def import_rallies(session: Session, owner: User, source: Path) -> dict[str, int]:
    """
    Add the rallies of political_rallies.yaml that owner does not have yet
    (found again by what it was and when), with who came along. Safe to run
    again. Does not commit.
    """
    items = _items(source, "political_rallies", RALLY_FIELDS)
    company = _Company(session, owner, "political_rallies.yaml")
    have = {(r.name, _date_key(r)) for r in session.scalars(select(Rally).where(Rally.owner_id == owner.id))}
    cities = Cities(session, owner)
    added = 0
    for item in items:
        name = item["description"]
        key = (name, _item_date_key(item, name))
        if key in have:
            continue
        people = company.came(item, name)
        session.add(Rally(
            owner_id=owner.id, name=name, location=item.get("location", ""), country=cities.country(item.get("country", "")),
            review=item.get("review", ""), people=people, alone="with" in item and not people, **_dates({**item, "name": name}),
        ))
        have.add(key)
        added += 1
    session.flush()
    return {"rallies added": added}


# the trips, lectures and rallies: the file each comes from, and its import
OUTING_FILES = {"trips": "trips", "lectures": "lectures", "rallies": "political_rallies"}
OUTINGS = {"trips": import_trips, "lectures": import_lectures, "rallies": import_rallies}


def import_youtube(session: Session, owner: User, source: Path) -> dict[str, int]:
    """ Add owner's YouTube videos from source. Stops when owner has YouTube videos already. Does not commit. """
    if not (source / "data" / "yaml" / "video_youtube.yaml").exists():
        raise WorldImportError(f"{source / 'data' / 'yaml' / 'video_youtube.yaml'} is not there ({NOT_KEPT})")
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


def _films_path(source: Path) -> Path:
    return source / "data" / "yaml" / "video_features.yaml"


def _series_path(source: Path) -> Path:
    return source / "data" / "yaml" / "video_series.yaml"


def _films_to_see_path(source: Path) -> Path:
    """ The films still to see: in the data repository beside the site's. """
    return source.parent / "data" / "json" / "movies_to_see.json"


def _imdb(value: Any, where: str) -> str:
    """ An IMDb id as the films keep it ("tt0816692"), from the number the sources write ("0816692"). """
    number = str(value).removeprefix("tt")
    if not re.fullmatch(r"\d{7,9}", number):
        raise WorldImportError(f"{where}: {value!r} is not an IMDb id")
    return f"tt{number}"


def _to_see_items(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="UTF8") as fp:
        items = json.load(fp)
    if not isinstance(items, list):
        raise WorldImportError(f"{path}: expected a list of films")
    for item in items:
        unknown = set(item) - FILM_TO_SEE_FIELDS
        if unknown:
            raise WorldImportError(f"{path}: {item.get('imdb_id')!r} has fields this import does not know: {sorted(unknown)}")
    return items


def import_films(session: Session, owner: User, source: Path) -> dict[str, int]:
    """
    Add the films of video_features.yaml, the series of video_series.yaml
    (films of the kind series, each watch with the seasons seen and not)
    and the films of movies_to_see.json to the shared ones, with their
    posters, and owner's watches of them: a film is
    found again by its IMDb id (one there gets only the ids it lacks), and
    what Wikidata says fills in the title, year and directors a film has
    not, and TMDB (when its key is there) the year, poster and TMDB id. A watch is added unless owner has one of that film on that date; a
    film to see unless owner has any watch of it. Safe to run again. Does
    not commit.
    """
    path = _films_path(source)
    if not path.exists():
        raise WorldImportError(f"{path} is not there")
    sources = [(path, _items(source, "video_features", FILM_FIELDS), "film", "movie")]
    if _series_path(source).exists():
        sources.append((_series_path(source), _items(source, "video_series", SERIES_FIELDS), "series", "series"))
    to_see_path = _films_to_see_path(source)
    to_see = _to_see_items(to_see_path) if to_see_path.exists() else []
    image_dir = source / "static" / "images"
    films = {f.imdb_id: f for f in session.scalars(select(Film).options(selectinload(Film.watches))) if f.imdb_id}
    people: dict[str, list[Person]] = {}
    for known in session.scalars(select(Person).where(Person.owner_id == owner.id).options(selectinload(Person.names))):
        people.setdefault(naming.key(known.name), []).append(known)

    def person(name: str, where: str) -> Person:
        """ owner's one person called name: the import stops when there is none, or several. """
        found = people.get(naming.key(name), [])
        if len(found) != 1:
            raise WorldImportError(f"{where}: {len(found) or 'no'} people of the account are called {name!r}" + ("; make the names differ first" if found else "; add them on the People page first"))
        return found[0]

    device = Devices(session, owner)
    counts = {
        "films added": 0, "series added": 0, "films filled from Wikidata": 0, "posters added": 0,
        "film watches added": 0, "series watches added": 0, "films to see added": 0, "films filled from TMDB": 0,
    }

    def film(imdb: str, name: str = "", kind: str = "film", prefix: str = "movie") -> Film:
        """ The film of an IMDb id (of the kind it is there, whatever kind is said), or a new one of kind, with its poster. """
        found = films.get(imdb)
        if found is None:
            found = Film(kind=kind, name=name, imdb_id=imdb, genres=[], watches=[])
            session.add(found)
            films[imdb] = found
            counts["series added" if kind == "series" else "films added"] += 1
        if found.image_id is None and found.image is None:
            poster = image_dir / f"{prefix}-{imdb.removeprefix('tt')}.jpg"
            if poster.exists():
                data = poster.read_bytes()
                found.image = Image(owner_id=owner.id, filename=poster.name, content_type="image/jpeg", sha256=hashlib.sha256(data).hexdigest(), data=data)
                counts["posters added"] += 1
        return found

    def _import_watch(item: dict[str, Any], where: str, kind: str, prefix: str) -> None:
        """ A watch of the yaml (a film's, or a series' with its seasons), unless owner has one of that film on that date. """
        watched = film(_imdb(item["imdb_id"], where), str(item["name"]).strip(), kind, prefix)
        # only what the film lacks: what an admin typed in stays
        if not watched.wikidata_id:
            watched.wikidata_id = str(item.get("wikidata_id") or "")
        if not watched.rotten_tomatoes_id:
            watched.rotten_tomatoes_id = str(item.get("rotten_tomatoes_id") or "")
        dates = _dates(item)
        empty = {"date_utcz": None, "date_ymd": None, "date_my": "", "date_y": None}
        if any(w.owner_id == owner.id and all((getattr(w, key) or empty[key]) == dates.get(key, empty[key]) for key in empty) for w in watched.watches):
            return
        companions = item.get("with") or []
        if len(set(companions)) != len(companions):
            raise WorldImportError(f"{where}: a name appears twice in with")
        watched.watches.append(FilmWatch(
            owner_id=owner.id,
            status="done",
            rating=item.get("rating"),
            review=str(item.get("review") or ""),
            watched_at=str(item.get("location") or ""),
            device=device(str(item.get("device") or "")),
            people=[person(name, where) for name in companions],
            seasons_seen=sorted({int(n) for n in item.get("seasons_seen") or []}),
            seasons_not_seen=sorted({int(n) for n in item.get("seasons_not_seen") or []}),
            **dates,
        ))
        counts["series watches added" if kind == "series" else "film watches added"] += 1

    for at, items, kind, prefix in sources:
        for item in items:
            _import_watch(item, f"{at}: {item['name']!r}", kind, prefix)

    for item in to_see:
        where = f"{to_see_path}: {item.get('imdb_id')!r}"
        wanted = film(_imdb(item["imdb_id"], where))
        genre = str(item.get("genre") or "").strip()
        if genre and genre not in wanted.genres:
            wanted.genres = [*wanted.genres, genre]
        if any(w.owner_id == owner.id for w in wanted.watches):
            continue
        recommended = str(item.get("recommended_by") or "").strip()
        wanted.watches.append(FilmWatch(owner_id=owner.id, status="wishlist", recommended_by=person(recommended, where) if recommended else None))
        counts["films to see added"] += 1
    # what Wikidata says of the films that lack a title, a year or directors (it is asked about those alone)
    lacking = [f for f in films.values() if f.imdb_id and (not f.name or f.year is None or not f.directors or not f.wikidata_id)]
    if lacking:
        try:
            said = movies.wikidata_films([f.imdb_id for f in lacking if f.imdb_id])
        except (movies.MovieLookupError, OSError, ValueError, KeyError) as e:
            raise WorldImportError(f"Wikidata: {e}") from e
        for found in lacking:
            facts = said.get(found.imdb_id or "")
            if facts is None:
                continue
            before = (found.name, found.year, found.directors, found.wikidata_id)
            found.name = found.name or facts["title"]
            found.year = found.year if found.year is not None else facts["year"]
            found.directors = found.directors or facts["directors"]
            found.wikidata_id = found.wikidata_id or facts["wikidata_id"]
            counts["films filled from Wikidata"] += before != (found.name, found.year, found.directors, found.wikidata_id)
    # and what TMDB says (when its key is there) of those still without a year, a poster or their TMDB id
    if movies.configured():
        for found in [f for f in films.values() if f.imdb_id and (f.year is None or (f.image_id is None and f.image is None) or f.tmdb_id is None)]:
            try:
                facts = movies.tmdb_find(found.imdb_id or "")
                data = movies.poster_bytes(facts["poster_url"]) if facts and facts["poster_url"] and found.image_id is None and found.image is None else None
            except (movies.MovieLookupError, OSError, ValueError, KeyError) as e:
                raise WorldImportError(f"TMDB: {found.imdb_id}: {e}") from e
            if facts is None:
                continue
            found.year = found.year if found.year is not None else facts["year"]
            found.tmdb_id = found.tmdb_id if found.tmdb_id is not None else facts["tmdb_id"]
            if data is not None:
                found.image = Image(owner_id=owner.id, filename=f"tmdb-{found.imdb_id}.jpg", content_type="image/jpeg", sha256=hashlib.sha256(data).hexdigest(), data=data)
                counts["posters added"] += 1
            counts["films filled from TMDB"] += 1
    nameless = [f.imdb_id for f in films.values() if not f.name]
    if nameless:
        raise WorldImportError(f"neither the sources nor Wikidata name the films {nameless}")
    session.flush()
    return {**counts, "devices added": device.added}


def _history_path(source: Path) -> Path:
    return source / "static" / "data" / "youtube.json.gz"


def _history_items(source: Path) -> list[dict[str, Any]]:
    path = _history_path(source)
    if not path.exists():
        raise WorldImportError(f"{path} is not there ({NOT_KEPT})")
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


def _address(address: str, remark: str, city: City | None, cities: Cities) -> dict[str, Any]:
    """
    An organization's address of organizations.yaml in its parts, its city
    (the one the address is in, where the user knew it; else the one its
    location names, its headquarters), and its remark: the address as
    written is added to the remark when it says more than the parts hold.
    """
    country = city.country.name if city and city.country else ""
    parsed = parse_address(address, {key[0] for key in cities.cities}, country) if address.strip() else None
    if parsed is None:
        return {"street": "", "neighbourhood": "", "postcode": "", "city": city, "remark": remark}
    if parsed["city"]:
        city = cities(str(parsed["city"]), str(parsed["region"]), str(parsed["country"]))
    street, neighbourhood, postcode, whole = str(parsed["street"]), str(parsed["neighbourhood"]), str(parsed["postcode"]), bool(parsed["whole"])
    note = "" if whole else f"Address as written: {address}"
    return {
        "street": street, "neighbourhood": neighbourhood, "postcode": postcode, "city": city,
        "remark": f"{remark} {note}".strip() if note else remark,
    }


class Cities:
    """
    The cities and countries (shared, everyone's): city(name, region,
    country) is the city of that name in that country (however spaced or
    hyphenated), made the first time it is named, with its country; a city
    named without a country is the one city of that name there is, if there
    is one. None for no name.
    """

    def __init__(self, session: Session, owner: User) -> None:
        self.session = session
        self.owner = owner
        self.countries = {c.name.casefold(): c for c in session.scalars(select(Country))}
        self.cities = {
            city_key(c.name, c.country.name if c.country else ""): c
            for c in session.scalars(select(City).options(selectinload(City.country)))
        }

    def country(self, name: str) -> Country | None:
        name = country_name(name)
        if not name:
            return None
        if name.casefold() not in self.countries:
            self.countries[name.casefold()] = Country(name=name)
            self.session.add(self.countries[name.casefold()])
        return self.countries[name.casefold()]

    def __call__(self, name: str, region: str, country: str) -> City | None:
        name = name.strip()
        if not name:
            return None
        if not country.strip():
            same = [c for (n, _), c in self.cities.items() if n == city_key(name, "")[0]]
            if len(same) == 1:
                return same[0]
        key = city_key(name, country)
        if key not in self.cities:
            land = self.country(country)
            self.cities[key] = City(name=name, region_row=region_for(self.session, region, land), country=land)
            self.session.add(self.cities[key])
        return self.cities[key]

    def of_location(self, location: str) -> City | None:
        """ The city an organization's location names ("Santa Clara, California, USA (Nvidia)"). """
        found = parse_location(location)
        return None if found is None else self(*found)


class Places:
    """
    The places (shared, everyone's) by name and city: place(venue, city,
    country) is the one there, made the first time it is named, of the kind
    Concert venue; a concert with a city but no venue is at a place named
    after the city, one with neither at none. What is known of a place but
    cannot be on it (a shared place has no remark) is in notes, for the
    concert to say.
    """

    def __init__(self, session: Session, owner: User, cities: Cities) -> None:
        self.session = session
        self.owner = owner
        self.cities = cities
        # keyed by the city object, which a new place's city is too before it has an id
        self.by_name: dict[tuple[str, int | None], Place] = {
            (p.name, id(p.city) if p.city else None): p
            for p in session.scalars(select(Place).options(selectinload(Place.city), selectinload(Place.kinds)))
        }
        self.venue = session.scalars(select(PlaceKind).where(PlaceKind.name == CONCERT_VENUE_KIND)).one()
        self.notes: dict[Place, str] = {}
        self.added = 0

    def find(self, name: str, city: City | None) -> Place | None:
        return self.by_name.get((name, id(city) if city is not None else None))

    def remember(self, place: Place) -> None:
        """ A place made elsewhere (a museum): found again by name and city; counted where it is made. """
        self.by_name[(place.name, id(place.city) if place.city is not None else None)] = place

    def __call__(self, venue: str, city: str, country: str) -> Place | None:
        name = venue.strip() or city.strip()
        if not name:
            return None
        where = self.cities(city, "", country)
        key = (name, id(where) if where is not None else None)
        if key not in self.by_name:
            self.by_name[key] = Place(name=name, city=where)
            self.session.add(self.by_name[key])
            self.added += 1
        found = self.by_name[key]
        if self.venue not in found.kinds:
            found.kinds.append(self.venue)
        # a country with no city is said by the concert: a place's country is its city's
        if where is None and country.strip():
            self.notes[found] = f"About the place: in {country_name(country)}; the city is not known."
        return found

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1] if __doc__ else None)
    parser.add_argument("--email", required=True, help="email of the account that will own the data")
    parser.add_argument("--subject", help="insist that the account has this login (logins.subject, e.g. google:1087...)")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parent.parent.parent / "veltzer.github.io")
    parser.add_argument("--dry-run", action="store_true", help="do it all and print what was done, then roll it back")
    parser.add_argument(
        "--audio-courses", action="store_true",
        help="import only the audio courses, adding them to what the account has (stops if it has audio courses already)",
    )
    parser.add_argument(
        "--audio-books", action="store_true",
        help="import only the audio books (the Audible library and those heard elsewhere), adding those the account does not have yet and refreshing what Audible changes on the rest; safe to run again",
    )
    parser.add_argument(
        "--podcasts", action="store_true",
        help="import only the podcasts and the episodes of them heard, adding what the account does not have yet; safe to run again",
    )
    parser.add_argument(
        "--films", action="store_true",
        help="import only the films and series watched and the films to see (from ../data), adding what the account does not have yet; safe to run again",
    )
    parser.add_argument(
        "--certifications", action="store_true",
        help="import only the certifications, adding those the account does not have yet (their issuers must be its organizations already); safe to run again",
    )
    parser.add_argument(
        "--courses", action="store_true",
        help="import only the courses (courses.yaml), adding those the account does not have yet; safe to run again",
    )
    for what, file in OUTING_FILES.items():
        parser.add_argument(
            f"--{what}", action="store_true",
            help=f"import only the {what} ({file}.yaml), adding those the account does not have yet (who came along must be its people already); safe to run again",
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
    parser.add_argument(
        "--replace-everything", metavar="EMAIL",
        help="let the full import delete and replace an account that has data already, losing every edit made in the app; give the account's email again to confirm",
    )
    args = parser.parse_args()
    if args.replace_everything is not None and args.replace_everything != args.email:
        parser.error("--replace-everything must repeat the --email of the account to replace")
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
            elif args.audio_books:
                counts = import_audio_books(session, owner, args.source)
            elif args.podcasts:
                counts = import_podcasts(session, owner, args.source)
            elif args.films:
                counts = import_films(session, owner, args.source)
            elif args.certifications:
                counts = import_certifications(session, owner, args.source)
            elif args.courses:
                counts = import_courses(session, owner, args.source)
                counts["people given a profession"] = give_types(session, owner)["people given a profession"]
            elif any(getattr(args, what) for what in OUTINGS):
                counts = {}
                for what, run in OUTINGS.items():
                    if getattr(args, what):
                        counts |= run(session, owner, args.source)
                counts["people given a profession"] = give_types(session, owner)["people given a profession"]
            elif args.youtube:
                counts = import_youtube(session, owner, args.source)
            elif args.audio_courses:
                counts = import_audio_courses(session, owner, args.source)
                counts["people given a profession"] = give_types(session, owner)["people given a profession"]
            else:
                counts = import_world(session, owner, args.source, replace=args.replace_everything is not None)
        except WorldImportError as e:
            print(f"import_world: {e}", file=sys.stderr)
            return 1
        who = f"{owner.email} (account {owner.id})"
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
