"""
What every check is made of: a problem, a result, the register the checks
are in, and the readers they share.
"""

import dataclasses
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from myworld.models import (
    AUDIO_BOOK_KINDS,
    KINDS,
    AudioBook,
    AudioBookHeard,
    AudioBookListen,
    AudioBookVersion,
    AudioCourse,
    Certification,
    City,
    Concert,
    Country,
    Device,
    EpisodeHeard,
    Film,
    FilmWatch,
    Group,
    Organization,
    OrganizationType,
    Person,
    PersonOrganizationType,
    PersonRelationType,
    PersonType,
    Place,
    PlaceKind,
    Podcast,
    PodcastEpisode,
    PodcastHeard,
    RelationType,
    UserWork,
    Visit,
    VisitType,
    Work,
    YouTubeVideo,
    is_shared,
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
    "museums": "Museum visits",
    "audio-courses": "Audio courses",
    "audio-books-heard": "Your audio books",
    "audio-book-listens": "Audio book listens",
    "podcasts-heard": "Your podcasts",
    "episodes-heard": "Episodes heard",
    "film-watches": "Film watches",
    "series-watches": "Series watches",
    "youtube": "YouTube",
    "chess": "Chess",
    "certifications": "Certifications",
    "people": "People",
    "groups": "Groups",
    "places": "Places",
    "podcasts": "Podcasts",
    "podcast-episodes": "Podcast episodes",
    "audio-books": "Audio books",
    "audio-book-versions": "Audio book versions",
    "films": "Films",
    "series": "Series",
    "cities": "Cities",
    "countries": "Countries",
    "currencies": "Currencies",
    "place-kinds": "Place kinds",
    "visit-types": "Visit types",
    "organizations": "Organizations",
    "organization-types": "Organization tags",
    "person-types": "Professions",
    "relation-types": "Org relation types",
    "person-relation-types": "Person relation types",
    "person-organization-types": "Person-org relation types",
    "devices": "Devices",
    "locales": "Languages",
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


# ─── what the checks share ──────────────────────────────────────────────────

def one_of(dataset: str) -> str:
    """ What one row of a small list is called: "profession", "organization relation type". """
    return DATASETS[dataset].lower().removesuffix("s").replace("org ", "organization ")


# what a row is called in a problem, and the page of the app it is on
SUBJECTS: dict[type, tuple[str, str]] = {
    Concert: ("concert", "concerts"),
    AudioCourse: ("audio course", "audio-courses"),
    AudioBook: ("audio book", "audio-books"),
    AudioBookVersion: ("audio book version", "audio-book-versions"),
    AudioBookHeard: ("audio book of yours", "audio-books-heard"),
    AudioBookListen: ("audio book listen", "audio-book-listens"),
    Podcast: ("podcast", "podcasts"),
    PodcastEpisode: ("podcast episode", "podcast-episodes"),
    PodcastHeard: ("podcast of yours", "podcasts-heard"),
    EpisodeHeard: ("episode heard", "episodes-heard"),
    Film: ("film", "films"),
    FilmWatch: ("film watch", "film-watches"),
    YouTubeVideo: ("YouTube video", "youtube"),
    Certification: ("certification", "certifications"),
    Person: ("person", "people"),
    Organization: ("organization", "organizations"),
    Group: ("group", "groups"),
    Place: ("place", "places"),
    City: ("city", "cities"),
    Country: ("country", "countries"),
    PlaceKind: ("place kind", "place-kinds"),
    VisitType: ("visit type", "visit-types"),
    OrganizationType: (one_of("organization-types"), "organization-types"),
    PersonType: (one_of("person-types"), "person-types"),
    RelationType: (one_of("relation-types"), "relation-types"),
    PersonRelationType: (one_of("person-relation-types"), "person-relation-types"),
    PersonOrganizationType: (one_of("person-organization-types"), "person-organization-types"),
    Device: (one_of("devices"), "devices"),
}


def rows[T](session: Session, model: type[T]) -> list[T]:
    """ Every row of a model, of every account: by account (a shared model has none), then by name, then as added. """
    table: Any = model
    name = (table.first_name, table.surname) if model is Person else (table.name,)
    owner = () if is_shared(model) else (table.owner_id,)
    return list(session.scalars(select(table).order_by(*owner, *name, table.id)))


def problem(row: Any, message: str) -> Problem:
    """ What is wrong with a row, told as every check tells it: "Barby, Tel Aviv (place 12, account 1)", and where the row is in the app. """
    if isinstance(row, Visit):
        # a visit is found at its museum (a place), on the account's Museum visits page
        place = row.place
        name = place.name if place else "No place"
        return Problem(f"{name} ({row.type.name.lower()} {row.id}, account {row.owner_id})", message, f"museums/{place.id}" if place else "", row.owner_id)
    if isinstance(row, UserWork):
        kind = row.work.kind
        return Problem(f"{row.work.title} ({KINDS[kind][0].lower()} {row.work_id}, account {row.owner_id})", message, f"{kind}/{row.work_id}", row.owner_id)
    noun, view = SUBJECTS[type(row)]
    # a series is a film of another kind, on pages of its own
    series = (isinstance(row, Film) and row.kind == "series") or (isinstance(row, FilmWatch) and row.film.kind == "series")
    if series:
        noun, view = noun.replace("film", "series"), view.replace("film", "series").replace("seriess", "series")
    # one heard is told by the name of what was heard
    if isinstance(row, PodcastHeard):
        name = row.podcast.name
    elif isinstance(row, EpisodeHeard):
        name = row.episode.name
    elif isinstance(row, FilmWatch):
        name = row.film.name
    elif isinstance(row, AudioBookHeard):
        name = row.book.name
    elif isinstance(row, AudioBookVersion):
        name = f"{row.book.name} ({AUDIO_BOOK_KINDS.get(row.kind, row.kind)})"
    elif isinstance(row, AudioBookListen):
        name = f"{row.version.book.name} ({AUDIO_BOOK_KINDS.get(row.version.kind, row.version.kind)})"
    else:
        name = row.name
    # a place is told with its city and a city with its country: two may share a name
    if isinstance(row, Place) and row.city:
        name = f"{name}, {row.city.name}"
    if isinstance(row, City) and row.country:
        name = f"{name}, {row.country.name}"
    if is_shared(type(row)):
        # everyone's: any admin opens it
        return Problem(f"{name} ({noun} {row.id}, shared)", message, f"{view}/{row.id}", None)
    return Problem(f"{name} ({noun} {row.id}, account {row.owner_id})", message, f"{view}/{row.id}", row.owner_id)


def same[T](found: list[T], key: Callable[[T], Any]) -> list[list[T]]:
    """ The rows that have the same key as another, together: every list is of two or more. """
    seen: dict[Any, list[T]] = {}
    for row in found:
        seen.setdefault(key(row), []).append(row)
    return [group for group in seen.values() if len(group) > 1]


def twice(found: list[Any], key: Callable[[Any], Any], what: str, noun: str = "") -> list[Problem]:
    """ A problem for every row that has the same key as another: "has the same name as 1 other museum of the account". """
    return [
        problem(row, f"has the same {what} as {len(group) - 1} other{' ' + noun if noun else ''}{'s' if len(group) > 2 else ''} of the account")
        for group in same(found, key)
        for row in group
    ]


def squashed(name: str) -> str:
    """ A name as it is compared: whatever its case, and however it is spaced. """
    return " ".join(name.casefold().split())


def dated(course: AudioCourse | EpisodeHeard | FilmWatch | YouTubeVideo | Concert) -> bool:
    """ Whether it has a date, at any precision: the day it was finished. """
    return course.date_utcz is not None or course.date_ymd is not None or bool(course.date_my) or course.date_y is not None


def ids(session: Session, *columns: Any) -> set[int]:
    """ The non-null values of the given id columns, together. """
    found: set[int] = set()
    for column in columns:
        found |= {value for value in session.scalars(select(column)) if value is not None}
    return found


def entries_of(session: Session, kind: str) -> list[UserWork]:
    """ Every account's library entries of a kind, with their works. """
    query = select(UserWork).join(Work).where(Work.kind == kind).order_by(UserWork.owner_id, Work.title, Work.id)
    return list(session.scalars(query))
