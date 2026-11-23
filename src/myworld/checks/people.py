"""
Checks of the people.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from myworld import languages, names
from myworld.checks.core import (
    Result,
    check,
    entries_of,
    ids,
    problem,
    rows,
    squashed,
    twice,
)
from myworld.models import (
    Person,
    PersonPhoto,
    PersonRelation,
    audio_course_lecturers,
    concert_companions,
    concert_performers,
    course_lecturers,
    group_members,
    lecture_companions,
    lecture_lecturers,
    library_entry_authors,
    person_organizations,
    person_type_links,
    rally_companions,
    trip_companions,
    visit_companions,
)


@check("people-known", "Every person has a profession or a relation", "people", "people")
def check_people_known(session: Session) -> Result:
    """
    Every person, of every account, says how they are known: a profession
    (a person type: performer, book author, ...), a relation to another
    person (friend of, mother of, ...) or an organization they are at.
    """
    known = (
        set(session.scalars(select(person_type_links.c.person_id)))
        | set(session.scalars(select(PersonRelation.person_id)))
        | set(session.scalars(select(PersonRelation.other_id)))
        | set(session.scalars(select(person_organizations.c.person_id)))
    )
    people = rows(session, Person)
    problems = [
        problem(person, "has no profession, relation or organization")
        for person in people
        if person.id not in known
    ]
    return Result(checked=len(people), problems=problems)


@check("people-names", "Every name is an honorific, first name, middle name and surname", "people", "people")
def check_person_names(session: Session) -> Result:
    """
    Every person's honorific, first name and surname, of every account, is
    one word (a surname of two words hyphenated, more names in the middle name).
    What scripts/tidy_names.py could not split is listed: mostly a band or
    a description kept whole in the first name, to fix by hand.
    """
    people = rows(session, Person)
    problems = []
    for person in people:
        spaced = [what for what, value in (("honorific", person.honorific), ("first name", person.first_name), ("surname", person.surname)) if names.has_space(value)]
        if spaced:
            problems.append(problem(person, f"{' and '.join(spaced)} has spaces"))
    return Result(checked=len(people), problems=problems)


@check("people-english-names", "Every person has an English name, or a description", "people", "people")
def check_person_english_names(session: Session) -> Result:
    """
    Every person, of every account, has an English name: the honorific, first
    name, middle name and surname, written in Latin letters (a name in
    another language is one of their other names). Someone whose name is not
    known has none, and then has a description to be known by.
    """
    people = rows(session, Person)
    problems = []
    for person in people:
        parts = " ".join(part for part in (person.honorific, person.first_name, person.middle_name, person.surname) if part)
        script = languages.script_of(parts)
        if not parts.strip() and person.description.strip():
            continue
        if script != "Latin":
            message = "has neither a name nor a description" if not parts.strip() else f"the name is written in {script or 'no'} letters, not in English"
            problems.append(problem(person, message))
    return Result(checked=len(people), problems=problems)


@check("people-hebrew-names", "Every author of a book in Hebrew has a Hebrew name", "authors of books in Hebrew", "people")
def check_person_hebrew_names(session: Session) -> Result:
    """
    Every person, of every account, who wrote a book that has a title in
    Hebrew (its main title or one in another language) has a name in Hebrew
    among their names: the one the book is shown with in Hebrew.
    """
    authors: dict[int, tuple[Person, str]] = {}
    for book in entries_of(session, "book"):
        if "he" in {book.work.title_locale, *(t.locale for t in book.work.titles)}:
            for person in book.authors:
                authors.setdefault(person.id, (person, book.work.title))
    problems = [
        problem(person, f"wrote {title}, which has a Hebrew title, but has no Hebrew name")
        for person, title in sorted(authors.values(), key=lambda found: (found[0].owner_id, found[0].id))
        if not any(name.locale == "he" for name in person.names)
    ]
    return Result(checked=len(authors), problems=problems)


@check("people-name-languages", "Every name in a language is in that language", "names", "people")
def check_person_name_languages(session: Session) -> Result:
    """
    Every person's name in another language, of every account, is written in
    the script of the language it says: a name in Hebrew letters is not
    Russian. scripts/fix_languages.py sets the language its letters say.
    """
    people = rows(session, Person)
    locales = languages.known(session)
    problems, checked = [], 0
    for person in people:
        for other in person.names:
            checked += 1
            if not languages.fits(locales[other.locale], other.name):
                message = f"the name {other.name!r} says {locales[other.locale].name} but is written in {languages.script_of(other.name)} letters"
                problems.append(problem(person, message))
    return Result(checked=checked, problems=problems)


@check("people-photos", "Every person with a profession has a photo", "people with a profession", "people")
def check_people_photos(session: Session) -> Result:
    """
    Every person with a profession (a performer, a book author, a lecturer:
    someone an encyclopedia may show), of every account, has a photo
    (scripts/fetch_pictures.py --only people takes Wikipedia's).
    """
    typed = set(session.scalars(select(person_type_links.c.person_id)))
    pictured = set(session.scalars(select(PersonPhoto.person_id)))
    people = [person for person in rows(session, Person) if person.id in typed]
    return Result(checked=len(people), problems=[problem(person, "has no photo") for person in people if person.id not in pictured])


@check("people-duplicates", "No person is listed twice", "people", "people")
def check_people_duplicates(session: Session) -> Result:
    """ No account has two people of the same name (ignoring case and spaces); one with no name is told by their description. """
    people = rows(session, Person)
    return Result(checked=len(people), problems=twice(people, lambda p: (p.owner_id, squashed(p.name)), "name"))


@check("people-used", "Every person is linked to something", "people", "people")
def check_people_used(session: Session) -> Result:
    """
    Every person, of every account, is someone to something: went along to
    a concert, a visit (a museum, ...), a trip, a lecture or a rally, performed, wrote a book, lectured a course, taught a course or gave a lecture, is in
    a group or at an organization, or is related to someone. The user's own
    row is theirs whatever it is linked to.
    """
    used = ids(
        session, concert_companions.c.person_id, concert_performers.c.person_id, visit_companions.c.person_id, library_entry_authors.c.person_id,
        audio_course_lecturers.c.person_id, trip_companions.c.person_id, course_lecturers.c.person_id, lecture_companions.c.person_id, lecture_lecturers.c.person_id,
        rally_companions.c.person_id, group_members.c.person_id, person_organizations.c.person_id, PersonRelation.person_id, PersonRelation.other_id,
    )
    people = rows(session, Person)
    return Result(checked=len(people), problems=[problem(person, "is linked to nothing") for person in people if person.id not in used and not person.is_self])
