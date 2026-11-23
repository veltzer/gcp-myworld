"""
Checks of the courses each account took, and of the trips, lectures and
rallies it went to: who a course was taken through, who came along, the
countries a trip was in, who gave a lecture.
"""

from sqlalchemy import Column, select
from sqlalchemy.orm import Session

from myworld.checks.core import (
    Result,
    check,
    problem,
    rows,
)
from myworld.models import (
    Course,
    Lecture,
    Rally,
    Trip,
    lecture_companions,
    lecture_lecturers,
    rally_companions,
    trip_companions,
    trip_countries,
)


def _company(session: Session, model: type[Trip | Lecture | Rally], companion_rows: Column[int]) -> Result:
    """ Each row either has the people who came along or is marked alone, and none is both. """
    with_people = set(session.scalars(select(companion_rows)))
    found = rows(session, model)
    problems = []
    for row in found:
        if row.alone and row.id in with_people:
            problems.append(problem(row, "is marked alone but has people in With"))
        elif not row.alone and row.id not in with_people:
            problems.append(problem(row, "has no one in With and is not marked alone"))
    return Result(checked=len(found), problems=problems)


@check("trip-company", "Every trip says who you were with", "trips", "trips")
def check_trip_company(session: Session) -> Result:
    """ Every trip, of every account, either has the people who came along or is marked "I went alone"; none is both. """
    return _company(session, Trip, trip_companions.c.trip_id)


@check("trip-countries", "Every trip says the countries it was in", "trips", "trips")
def check_trip_countries(session: Session) -> Result:
    """ Every trip, of every account, names at least one country it was in. """
    been = set(session.scalars(select(trip_countries.c.trip_id)))
    found = rows(session, Trip)
    return Result(checked=len(found), problems=[problem(t, "has no country") for t in found if t.id not in been])


@check("lecture-company", "Every lecture says who you were with", "lectures", "lectures")
def check_lecture_company(session: Session) -> Result:
    """ Every lecture, of every account, either has the people who came along or is marked "I went alone"; none is both. """
    return _company(session, Lecture, lecture_companions.c.lecture_id)


@check("lecture-lecturers", "Every lecture says who gave it", "lectures", "lectures")
def check_lecture_lecturers(session: Session) -> Result:
    """ Every lecture, of every account, names at least one lecturer, a person of the account. """
    given = set(session.scalars(select(lecture_lecturers.c.lecture_id)))
    found = rows(session, Lecture)
    return Result(checked=len(found), problems=[problem(lecture, "has no lecturer") for lecture in found if lecture.id not in given])


@check("rally-company", "Every rally says who you were with", "rallies", "rallies")
def check_rally_company(session: Session) -> Result:
    """ Every rally, of every account, either has the people who came along or is marked "I went alone"; none is both. """
    return _company(session, Rally, rally_companions.c.rally_id)


@check("course-providers", "Every course says who it was taken through", "courses", "courses")
def check_course_providers(session: Session) -> Result:
    """ Every course, of every account, names the organization it was taken through, whose logo its card shows when no school is named. """
    found = rows(session, Course)
    return Result(checked=len(found), problems=[problem(c, "has no provider") for c in found if c.provider_id is None])
