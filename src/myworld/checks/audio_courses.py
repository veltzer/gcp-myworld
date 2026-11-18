"""
Checks of the audio courses.
"""

import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from myworld.checks.core import (
    Result,
    check,
    dated,
    problem,
    rows,
    twice,
)
from myworld.models import (
    AudioCourse,
    audio_course_lecturers,
)

# in progress for longer than this, a course is reported as stalled
STALLED_AFTER = datetime.timedelta(days=365)


@check("audio-course-lecturers", "Every audio course has a lecturer", "audio courses", "audio-courses")
def check_audio_course_lecturers(session: Session) -> Result:
    """ Every audio course, of every account, has at least one lecturer (a person). """
    taught = set(session.scalars(select(audio_course_lecturers.c.audio_course_id)))
    courses = rows(session, AudioCourse)
    return Result(checked=len(courses), problems=[problem(c, "has no lecturer") for c in courses if c.id not in taught])


@check("audio-course-devices", "Every audio course has a device", "audio courses", "audio-courses")
def check_audio_course_devices(session: Session) -> Result:
    """ Every audio course, of every account, says what it was played on (one of the account's devices). """
    courses = rows(session, AudioCourse)
    return Result(checked=len(courses), problems=[problem(c, "has no device") for c in courses if c.device_id is None])


@check("audio-course-status", "Every audio course is finished or in progress", "audio courses", "audio-courses")
def check_audio_course_status(session: Session) -> Result:
    """
    Every audio course, of every account, is either finished (it has a date)
    or in progress (it has a start), never neither.
    """
    courses = rows(session, AudioCourse)
    problems = [
        problem(c, "has neither a finished date nor a start: is it finished or in progress?")
        for c in courses
        if not dated(c) and c.started_utcz is None
    ]
    return Result(checked=len(courses), problems=problems)


@check("audio-course-reviews", "Every finished audio course is rated and reviewed", "finished audio courses", "audio-courses")
def check_audio_course_reviews(session: Session) -> Result:
    """ Every finished audio course, of every account, has a rating and a review; one still in progress need not. """
    finished = [c for c in rows(session, AudioCourse) if dated(c)]
    problems = []
    for course in finished:
        missing = [what for what, absent in (("rating", course.rating is None), ("review", not course.review.strip())) if absent]
        if missing:
            problems.append(problem(course, f"is finished but has no {' and no '.join(missing)}"))
    return Result(checked=len(finished), problems=problems)


@check("audio-course-covers", "Every audio course has a cover", "audio courses", "audio-courses")
def check_audio_course_covers(session: Session) -> Result:
    """ Every audio course, of every account, has a cover image. """
    courses = rows(session, AudioCourse)
    return Result(checked=len(courses), problems=[problem(c, "has no cover") for c in courses if c.image_id is None])


@check("audio-course-links", "Every audio course links to its page", "audio courses", "audio-courses")
def check_audio_course_links(session: Session) -> Result:
    """
    Every audio course, of every account, has a Great Courses slug, an
    Audible ASIN or a link (any page about it, for one no longer sold), so
    its card links to its page.
    """
    courses = rows(session, AudioCourse)
    problems = [
        problem(c, "has no Great Courses slug, Audible ASIN or link")
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
    running = [c for c in rows(session, AudioCourse) if not dated(c) and c.started_utcz is not None]
    problems = []
    for course in running:
        assert course.started_utcz is not None
        waited = now - course.started_utcz
        if waited > STALLED_AFTER:
            progress = f", at {course.progress}" if course.progress else ""
            problems.append(problem(course, f"in progress since {course.started_utcz.date().isoformat()} ({waited.days} days{progress})"))
    return Result(checked=len(running), problems=problems)


@check("audio-course-duplicates", "No audio course is listed twice", "audio courses", "audio-courses")
def check_audio_course_duplicates(session: Session) -> Result:
    """ No account has two audio courses of the same name (ignoring case and spaces at the ends). """
    courses = rows(session, AudioCourse)
    return Result(checked=len(courses), problems=twice(courses, lambda c: (c.owner_id, c.name.strip().lower()), "name", "audio course"))
