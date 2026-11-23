"""
What ties a person to the user: every row of the user's data that names
them (a concert they came to, a trip, a lecture they gave, a book they
wrote, ...), in one registry, PERSON_LINKS, read from the tables
themselves: each entry is a column that points at people.id, and the rows
are those of its table (a loan's borrower) or, for a table that only links
two others (concert_companions), those of the other table.

Everything that shows how a person is linked works from here: the person's
connections (GET /api/people/<id>/connections, the dialog behind the link
on their card) and the check that every person is linked to something
(checks.people). tests/connections_test.py fails when a column pointing at
people.id is neither in PERSON_LINKS nor in LINKED_ELSEWHERE or NOT_A_LINK:
a new table that names people cannot be left out of them by forgetting.
"""

import dataclasses
from collections.abc import Callable
from typing import Any

from sqlalchemy import Column, select, tuple_
from sqlalchemy.orm import Session

from myworld.models import (
    Base,
    FilmWatch,
    Person,
    UserWork,
    Visit,
    audio_course_lecturers,
    concert_companions,
    concert_performers,
    course_lecturers,
    film_watch_companions,
    group_members,
    lecture_companions,
    lecture_lecturers,
    library_entry_authors,
    person_organizations,
    rally_companions,
    trip_companions,
    visit_companions,
)


@dataclasses.dataclass(frozen=True)
class Link:
    # the column that points at people.id
    column: Column[Any]
    # what the dialog calls the group ("Trips you took together")
    label: str
    # the page the rows are on (a key of checks.DATASETS), for the links and for what a shared view shows
    view: str


PERSON_LINKS: tuple[Link, ...] = (
    Link(concert_companions.c.person_id, "Concerts you went to together", "concerts"),
    Link(concert_performers.c.person_id, "Concerts they performed at", "concerts"),
    Link(visit_companions.c.person_id, "Museums you visited together", "museums"),
    Link(trip_companions.c.person_id, "Trips you took together", "trips"),
    Link(lecture_companions.c.person_id, "Lectures you went to together", "lectures"),
    Link(lecture_lecturers.c.person_id, "Lectures they gave", "lectures"),
    Link(rally_companions.c.person_id, "Rallies you went to together", "rallies"),
    Link(film_watch_companions.c.person_id, "Films and series you watched together", "film-watches"),
    Link(Base.metadata.tables["film_watches"].c.recommended_by_id, "Films and series they recommended", "film-watches"),
    Link(audio_course_lecturers.c.person_id, "Audio courses they taught", "audio-courses"),
    Link(course_lecturers.c.person_id, "Courses they taught", "courses"),
    Link(library_entry_authors.c.person_id, "Books they wrote", "book"),
    Link(group_members.c.person_id, "Groups they are in", "groups"),
    Link(Base.metadata.tables["loans"].c.person_id, "Things you lent them", "loans"),
)

# columns pointing at people.id that link a person, shown from the person's own row
# (their card and the dialog read them from person_json): how they are related to
# other people, both ways, and the organizations they are at
LINKED_ELSEWHERE: dict[str, str] = {
    "person_relations.person_id": "their relations to other people (person_json: relations)",
    "person_relations.other_id": "other people's relations to them (person_json: related)",
    "person_organizations.person_id": "the organizations they are at (person_json: organization_links)",
}

# columns pointing at people.id that are the person themselves, not a link to anything
NOT_A_LINK: dict[str, str] = {
    "person_names.person_id": "their names in other languages",
    "person_photos.person_id": "their photos",
    "person_type_links.person_id": "their professions (a profession is not a link to the user's data)",
}

# the columns of LINKED_ELSEWHERE, for the people-used check
LINKED_ELSEWHERE_COLUMNS: tuple[Column[Any], ...] = (
    Base.metadata.tables["person_relations"].c.person_id,
    Base.metadata.tables["person_relations"].c.other_id,
    person_organizations.c.person_id,
)


def columns_to_people() -> list[str]:
    """ Every column of every table that points at people.id, as "table.column". """
    return sorted(
        f"{table.name}.{fk.parent.name}"
        for table in Base.metadata.sorted_tables
        for fk in table.foreign_keys
        if fk.column.table.name == "people"
    )


def _model_of(table: Any) -> Any:
    return next((m.class_ for m in Base.registry.mappers if m.local_table is table), None)


def rows_of(session: Session, link: Link, person: Person) -> list[Any]:
    """ The rows that name person through link: of its own table, or of the table a linking table links them to. """
    table = link.column.table
    model = _model_of(table)
    if model is not None:
        return list(session.scalars(select(model).where(link.column == person.id)))
    others = [fk for fk in table.foreign_keys if fk.column.table.name != "people"]
    target = _model_of(others[0].column.table)
    # a key of more than one column (a library entry is owner and work)
    pairs = select(*[fk.parent for fk in others]).where(link.column == person.id)
    key = tuple_(*[getattr(target, fk.column.name) for fk in others]) if len(others) > 1 else getattr(target, others[0].column.name)
    return list(session.scalars(select(target).where(key.in_(pairs))))


def reference(link: Link, row: Any) -> tuple[str, int, str]:
    """ Where a row is shown, and as what: (page, id there, name). """
    if isinstance(row, Visit):
        # a museum's card is the museum, with every visit to it
        return link.view, row.place_id or 0, row.place.name if row.place else ""
    if isinstance(row, UserWork):
        # a book is known by its work: #book/<work id>
        return link.view, row.work_id, row.work.title
    if isinstance(row, FilmWatch):
        return ("series-watches" if row.film.kind == "series" else "film-watches"), row.id, row.film.name
    return link.view, row.id, str(row.name)


def connections(session: Session, person: Person, shown: Callable[[str], bool], dated: Callable[[Any], dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Every group of rows that names person, each {label, view, items: [{id, name, view, date...}]},
    of the pages shown says may be shown; dated gives a row's date fields (empty for one with no date).
    """
    groups = []
    for link in PERSON_LINKS:
        items = []
        for row in rows_of(session, link, person):
            view, row_id, name = reference(link, row)
            if shown(view):
                items.append({"id": row_id, "name": name, "view": view, **dated(row)})
        if items:
            items.sort(key=lambda item: (item.get("date_sort") or "", item["name"]), reverse=True)
            groups.append({"label": link.label, "view": link.view, "items": items})
    return groups
