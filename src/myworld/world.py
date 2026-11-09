"""
JSON API for the concerts, museum visits, people and organizations of the
signed-in user, and the images they point at: list, add, edit and delete. Every query is filtered by
owner_id, so a user only ever sees, and only ever links to, their own rows.
"""

import datetime
import hashlib
import re
import zoneinfo
from typing import Any

import flask
import werkzeug
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from myworld import auth
from myworld.api import ApiError, coordinates, json_body, opt_int, text
from myworld.models import (
    KINDS,
    RATING_MAX,
    RATING_MIN,
    STATUSES,
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
    concert_performers,
    organization_relation_types,
    person_person_types,
)

bp = flask.Blueprint("world", __name__)

# images never change once imported (a new photo is a new row), so browsers may keep them
IMAGE_MAX_AGE = 7 * 24 * 3600
# uploads: what a browser can show, recognised by its first bytes, not by what the client claims
IMAGE_MAX_BYTES = 8 * 1024 * 1024
IMAGE_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/gif": (b"GIF87a", b"GIF89a"),
}
IMAGE_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}


def _date_json(row: Concert | Museum | AudioCourse) -> dict[str, Any]:
    """ The date as precisely as it is known, and a sortable key for it. """
    if row.date_utcz is not None:
        utc = row.date_utcz.replace(tzinfo=datetime.UTC)
        return {"date": utc.isoformat().replace("+00:00", "Z"), "date_precision": "time", "date_sort": utc.date().isoformat()}
    if row.date_ymd is not None:
        return {"date": row.date_ymd.isoformat(), "date_precision": "day", "date_sort": row.date_ymd.isoformat()}
    if row.date_my:
        month, year = row.date_my.split("-")
        return {"date": f"{year}-{month}", "date_precision": "month", "date_sort": f"{year}-{month}"}
    if row.date_y is not None:
        return {"date": str(row.date_y), "date_precision": "year", "date_sort": f"{row.date_y:04d}"}
    return {"date": None, "date_precision": None, "date_sort": ""}


def _image_url(image_id: int | None) -> str | None:
    return None if image_id is None else flask.url_for("world.api_image", image_id=image_id)


def _names(people: list[Person]) -> list[str]:
    return sorted(p.name for p in people)


def _refs(rows: list[Person] | list[Organization] | list[PersonType] | list[RelationType]) -> list[dict[str, Any]]:
    """ Names with the ids the People and Organizations views link to. """
    return [{"id": row.id, "name": row.name} for row in sorted(rows, key=lambda row: row.name)]


def concert_json(concert: Concert) -> dict[str, Any]:
    return {
        "id": concert.id,
        "name": concert.name,
        "performers": _refs(concert.performers),
        "event": concert.event,
        "genre": concert.genre,
        **_date_json(concert),
        "date_timezone": concert.date_timezone,
        "venue": concert.venue,
        "city": concert.city,
        "country": concert.country,
        "tickets": concert.tickets,
        "broadcast": concert.broadcast,
        "review": concert.review,
        "remark": concert.remark,
        "with": _names(concert.people),
        "people": _refs(concert.people),
        "image": _image_url(concert.image_id),
        "image_source": concert.image_source,
        "image_license": concert.image_license,
        "image_author": concert.image_author,
    }


def museum_json(museum: Museum) -> dict[str, Any]:
    return {
        "id": museum.id,
        "name": museum.name,
        **_date_json(museum),
        "date_timezone": museum.date_timezone,
        "city": museum.city,
        "address": museum.address,
        "latitude": museum.latitude,
        "longitude": museum.longitude,
        "rating": museum.rating,
        "review": museum.review,
        "remark": museum.remark,
        "url": museum.url,
        "tickets": museum.tickets,
        "alone": museum.alone,
        "with": _names(museum.people),
        "people": _refs(museum.people),
        "image": _image_url(museum.image_id),
    }


def _stamp_json(stamp: datetime.datetime | None) -> str:
    return "" if stamp is None else stamp.replace(tzinfo=datetime.UTC).isoformat().replace("+00:00", "Z")


def audio_course_json(course: AudioCourse) -> dict[str, Any]:
    return {
        "id": course.id,
        "name": course.name,
        **_date_json(course),
        "date_timezone": course.date_timezone,
        # finished when it has a date, in progress when it was only started
        "status": "done" if _date_json(course)["date"] else ("in_progress" if course.started_utcz else ""),
        "lecturers": _refs(course.lecturers),
        "rating": course.rating,
        "review": course.review,
        "device": None if course.device is None else {"id": course.device.id, "name": course.device.name},
        "listened_at": course.listened_at,
        "started": _stamp_json(course.started_utcz),
        "ended": _stamp_json(course.ended_utcz),
        "progress": course.progress,
        "great_courses_id": course.great_courses_id,
        "great_courses_slug": course.great_courses_slug,
        "audible_asin": course.audible_asin,
        "link": course.link,
        "url": _course_url(course),
        "image": _image_url(course.image_id),
    }


def _course_url(course: AudioCourse) -> str:
    """ The course's page: where it is sold (The Great Courses, Audible), or else any page about it. """
    if course.great_courses_slug:
        return f"https://www.thegreatcourses.com/courses/{course.great_courses_slug}"
    if course.audible_asin:
        return f"https://www.audible.com/pd/{course.audible_asin}"
    return course.link


def person_json(person: Person) -> dict[str, Any]:
    return {
        "id": person.id,
        "name": person.name,
        "first_name": person.first_name,
        "surname": person.surname,
        "types": _refs(person.types),
        "organizations": _refs(person.organizations),
        "description": person.description,
    }


def organization_json(organization: Organization) -> dict[str, Any]:
    return {
        "id": organization.id,
        "name": organization.name,
        "type": None if organization.type is None else {"id": organization.type.id, "name": organization.type.name},
        # how it is related to the user: any number of their own relation types
        "relations": _refs(organization.relations),
        "status": organization.status,
        "website": organization.website,
        "location": organization.location,
        "address": organization.address,
        "latitude": organization.latitude,
        "longitude": organization.longitude,
        "what_happened": organization.what_happened,
        "remark": organization.remark,
        "image": _image_url(organization.image_id),
        "people": _refs(organization.people),
    }


def _newest_first(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: (item["date_sort"], item["name"]), reverse=True)


@bp.route("/api/concerts", methods=["GET"])
@auth.login_required
def api_concerts() -> flask.Response:
    query = select(Concert).where(Concert.owner_id == flask.g.user.id).options(selectinload(Concert.people), selectinload(Concert.performers))
    concerts = flask.g.db.execute(query).scalars().all()
    return flask.jsonify(_newest_first([concert_json(c) for c in concerts]))


@bp.route("/api/audio-courses", methods=["GET"])
@auth.login_required
def api_audio_courses() -> flask.Response:
    query = select(AudioCourse).where(AudioCourse.owner_id == flask.g.user.id).options(selectinload(AudioCourse.lecturers), selectinload(AudioCourse.device))
    courses = flask.g.db.execute(query).scalars().all()
    # finished ones newest first; those in progress (no date yet) after them
    return flask.jsonify(_newest_first([audio_course_json(c) for c in courses]))


@bp.route("/api/museums", methods=["GET"])
@auth.login_required
def api_museums() -> flask.Response:
    query = select(Museum).where(Museum.owner_id == flask.g.user.id).options(selectinload(Museum.people))
    museums = flask.g.db.execute(query).scalars().all()
    return flask.jsonify(_newest_first([museum_json(m) for m in museums]))


@bp.route("/api/people", methods=["GET"])
@auth.login_required
def api_people() -> flask.Response:
    query = (
        select(Person)
        .where(Person.owner_id == flask.g.user.id)
        .options(selectinload(Person.organizations), selectinload(Person.types))
        .order_by(Person.first_name, Person.surname, Person.id)
    )
    people = flask.g.db.execute(query).scalars().all()
    return flask.jsonify([person_json(p) for p in people])


@bp.route("/api/organizations", methods=["GET"])
@auth.login_required
def api_organizations() -> flask.Response:
    query = (
        select(Organization)
        .where(Organization.owner_id == flask.g.user.id)
        .options(selectinload(Organization.people), selectinload(Organization.type), selectinload(Organization.relations))
        .order_by(Organization.name)
    )
    organizations = flask.g.db.execute(query).scalars().all()
    return flask.jsonify([organization_json(c) for c in organizations])


@bp.route("/api/images/<int:image_id>", methods=["GET"])
@auth.login_required
def api_image(image_id: int) -> werkzeug.Response:
    image = flask.g.db.get(Image, image_id)
    if image is None or image.owner_id != flask.g.user.id:
        return flask.Response(status=404)
    response = flask.Response(image.data, mimetype=image.content_type)
    response.headers["Cache-Control"] = f"private, max-age={IMAGE_MAX_AGE}"
    # the imported logos are SVG: opened on their own they must not run scripts on this origin
    response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.set_etag(image.sha256)
    return response.make_conditional(flask.request)


# ─── adding ──────────────────────────────────────────────────────────────────

def _sniff(data: bytes) -> str | None:
    for content_type, signatures in IMAGE_SIGNATURES.items():
        if data.startswith(signatures):
            return content_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _dates(body: dict[str, Any], current: Concert | Museum | AudioCourse | None = None) -> dict[str, Any]:
    """
    The date as typed: YYYY, YYYY-MM or YYYY-MM-DD, stored at that precision,
    or nothing. date_timezone is where it happened (an IANA name). On an edit
    a date sent back exactly as it was shown leaves it as it is, so a stored
    timestamp keeps its time.
    """
    value = text(body, "date")
    zone = text(body, "date_timezone")
    if zone:
        try:
            zoneinfo.ZoneInfo(zone)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError) as e:
            raise ApiError(400, f"date_timezone: unknown time zone {zone!r}") from e
    out: dict[str, Any] = {"date_timezone": zone}
    if current is not None and value == (_date_json(current)["date"] or ""):
        return out
    out.update({"date_utcz": None, "date_ymd": None, "date_my": "", "date_y": None})
    if not value:
        return out
    if re.fullmatch(r"\d{4}", value):
        out["date_y"] = int(value)
        return out
    match = re.fullmatch(r"(\d{4})-(\d{2})", value)
    if match:
        if not 1 <= int(match.group(2)) <= 12:
            raise ApiError(400, "date: no such month")
        out["date_my"] = f"{match.group(2)}-{match.group(1)}"
        return out
    try:
        out["date_ymd"] = datetime.date.fromisoformat(value)
    except ValueError as e:
        raise ApiError(400, "date: expected YYYY, YYYY-MM or YYYY-MM-DD") from e
    return out


def _owned_list[T: (Person, Organization, PersonType, RelationType)](body: dict[str, Any], key: str, model: type[T]) -> list[T]:
    """ body[key], a list of ids of the user's own rows of model, as those rows. """
    ids = body.get(key) or []
    if not isinstance(ids, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        raise ApiError(400, f"{key}: expected a list of ids")
    if not ids:
        return []
    rows = flask.g.db.execute(
        select(model).where(model.owner_id == flask.g.user.id, model.id.in_(ids))
    ).scalars().all()
    if len(rows) != len(set(ids)):
        raise ApiError(400, f"{key}: unknown {model.__name__.lower()}")
    return list(rows)


def _owned_people(body: dict[str, Any]) -> list[Person]:
    return _owned_list(body, "people", Person)


def _owned_image(body: dict[str, Any]) -> int | None:
    image_id = opt_int(body, "image_id", 1, 2**31 - 1)
    if image_id is None:
        return None
    image = flask.g.db.get(Image, image_id)
    if image is None or image.owner_id != flask.g.user.id:
        raise ApiError(400, "image_id: unknown image")
    return image_id


def _owned(model: type[Concert | Museum | AudioCourse | Person | Organization | OrganizationType | PersonType | RelationType | Device], row_id: int) -> Any:
    row = flask.g.db.get(model, row_id)
    if row is None or row.owner_id != flask.g.user.id:
        raise ApiError(404, "no such entry")
    return row


def _drop_unused_images() -> None:
    """ Photos and logos nothing shows any more (replaced or deleted) go too. """
    db = flask.g.db
    used = select(Concert.image_id).where(Concert.image_id.is_not(None)).union(
        select(Museum.image_id).where(Museum.image_id.is_not(None)),
        select(Organization.image_id).where(Organization.image_id.is_not(None)),
        select(AudioCourse.image_id).where(AudioCourse.image_id.is_not(None)),
    )
    for image in db.execute(select(Image).where(Image.owner_id == flask.g.user.id, Image.id.not_in(used))).scalars():
        db.delete(image)


def _apply_concert(concert: Concert, body: dict[str, Any], current: Concert | None) -> None:
    concert.name = text(body, "name", required=True)
    concert.performers = _owned_list(body, "performers", Person)
    concert.event = text(body, "event")
    concert.genre = text(body, "genre")
    concert.venue = text(body, "venue")
    concert.city = text(body, "city")
    concert.country = text(body, "country")
    concert.tickets = opt_int(body, "tickets", 0, 1000)
    concert.broadcast = body.get("broadcast") is True
    concert.review = text(body, "review")
    concert.remark = text(body, "remark")
    # a photo is only ever replaced by a new upload, never blanked by omission
    image_id = _owned_image(body)
    if image_id is not None:
        concert.image_id = image_id
    concert.image_source = text(body, "image_source")
    concert.image_license = text(body, "image_license")
    concert.image_author = text(body, "image_author")
    concert.people = _owned_people(body)
    for key, value in _dates(body, current).items():
        setattr(concert, key, value)


def _apply_museum(museum: Museum, body: dict[str, Any], current: Museum | None) -> None:
    museum.name = text(body, "name", required=True)
    museum.city = text(body, "city")
    museum.address = text(body, "address")
    museum.latitude, museum.longitude = coordinates(body)
    museum.rating = opt_int(body, "rating", RATING_MIN, RATING_MAX)
    museum.review = text(body, "review")
    museum.remark = text(body, "remark")
    museum.url = text(body, "url")
    museum.tickets = opt_int(body, "tickets", 0, 1000)
    image_id = _owned_image(body)
    if image_id is not None:
        museum.image_id = image_id
    museum.people = _owned_people(body)
    museum.alone = body.get("alone") is True
    if museum.alone and museum.people:
        raise ApiError(400, "a visit made alone has no one in With")
    for key, value in _dates(body, current).items():
        setattr(museum, key, value)


def _stamp(body: dict[str, Any], key: str, current: datetime.datetime | None) -> datetime.datetime | None:
    """ A moment as YYYY-MM-DD or a full UTC timestamp; sent back as shown, it is kept as it was. """
    value = text(body, key)
    if not value:
        return None
    if value == _stamp_json(current):
        return current
    try:
        if len(value) == 10:
            return datetime.datetime.fromisoformat(value)
        return datetime.datetime.fromisoformat(value).astimezone(datetime.UTC).replace(tzinfo=None)
    except ValueError as e:
        raise ApiError(400, f"{key}: expected YYYY-MM-DD") from e


def _apply_audio_course(course: AudioCourse, body: dict[str, Any], current: AudioCourse | None) -> None:
    course.name = text(body, "name", required=True)
    course.lecturers = _owned_list(body, "lecturers", Person)
    course.rating = opt_int(body, "rating", RATING_MIN, RATING_MAX)
    course.review = text(body, "review")
    course.device = _owned_type(Device, opt_int(body, "device_id", 1, 2**31 - 1))
    course.listened_at = text(body, "listened_at")
    course.started_utcz = _stamp(body, "started", current.started_utcz if current else None)
    course.ended_utcz = _stamp(body, "ended", current.ended_utcz if current else None)
    course.progress = text(body, "progress")
    course.great_courses_id = opt_int(body, "great_courses_id", 1, 2**31 - 1)
    course.great_courses_slug = text(body, "great_courses_slug")
    course.audible_asin = text(body, "audible_asin")
    course.link = text(body, "link")
    if course.link and not course.link.startswith(("https://", "http://")):
        raise ApiError(400, "link: expected an http(s) URL")
    image_id = _owned_image(body)
    if image_id is not None:
        course.image_id = image_id
    for key, value in _dates(body, current).items():
        setattr(course, key, value)


def _apply_person(person: Person, body: dict[str, Any]) -> None:
    # two people may share a name, so there is no clash to look for
    # either name, or both, may be missing: someone with no name goes by the
    # description, so it is only a person with none of the three, who could
    # not be picked in any picker, that is refused
    person.first_name = text(body, "first_name")
    person.surname = text(body, "surname")
    person.description = text(body, "description")
    if not person.first_name and not person.surname and not person.description:
        raise ApiError(400, "a person needs a first name, a surname or a description")
    person.organizations = _owned_list(body, "organizations", Organization)
    person.types = _owned_list(body, "type_ids", PersonType)


def _apply_organization(organization: Organization, body: dict[str, Any]) -> None:
    name = text(body, "name", required=True)
    clash = flask.g.db.execute(
        select(Organization.id).where(Organization.owner_id == flask.g.user.id, Organization.name == name, Organization.id != organization.id)
    ).first()
    if clash is not None:
        raise ApiError(409, f"{name} is already in Organizations")
    organization.name = name
    type_id = opt_int(body, "type_id", 1, 2**31 - 1)
    organization.type = _owned_type(OrganizationType, type_id)
    # looked up before anything is set on a new organization, which is not in the session yet
    relations = _owned_list(body, "relation_ids", RelationType)
    image_id = _owned_image(body)
    organization.relations = relations
    organization.status = text(body, "status")
    organization.website = text(body, "website")
    organization.location = text(body, "location")
    organization.address = text(body, "address")
    organization.latitude, organization.longitude = coordinates(body)
    organization.what_happened = text(body, "what_happened")
    organization.remark = text(body, "remark")
    if image_id is not None:
        organization.image_id = image_id


@bp.route("/api/concerts", methods=["POST"])
@auth.login_required
def api_concerts_add() -> tuple[flask.Response, int]:
    concert = Concert(owner_id=flask.g.user.id)
    _apply_concert(concert, json_body(), None)
    flask.g.db.add(concert)
    flask.g.db.commit()
    return flask.jsonify(concert_json(concert)), 201


@bp.route("/api/concerts/<int:row_id>", methods=["PUT"])
@auth.login_required
def api_concerts_update(row_id: int) -> flask.Response:
    concert = _owned(Concert, row_id)
    _apply_concert(concert, json_body(), concert)
    flask.g.db.flush()
    _drop_unused_images()
    flask.g.db.commit()
    return flask.jsonify(concert_json(concert))


@bp.route("/api/museums", methods=["POST"])
@auth.login_required
def api_museums_add() -> tuple[flask.Response, int]:
    museum = Museum(owner_id=flask.g.user.id)
    _apply_museum(museum, json_body(), None)
    flask.g.db.add(museum)
    flask.g.db.commit()
    return flask.jsonify(museum_json(museum)), 201


@bp.route("/api/museums/<int:row_id>", methods=["PUT"])
@auth.login_required
def api_museums_update(row_id: int) -> flask.Response:
    museum = _owned(Museum, row_id)
    _apply_museum(museum, json_body(), museum)
    flask.g.db.flush()
    _drop_unused_images()
    flask.g.db.commit()
    return flask.jsonify(museum_json(museum))


@bp.route("/api/audio-courses", methods=["POST"])
@auth.login_required
def api_audio_courses_add() -> tuple[flask.Response, int]:
    course = AudioCourse(owner_id=flask.g.user.id)
    _apply_audio_course(course, json_body(), None)
    flask.g.db.add(course)
    flask.g.db.commit()
    return flask.jsonify(audio_course_json(course)), 201


@bp.route("/api/audio-courses/<int:row_id>", methods=["PUT"])
@auth.login_required
def api_audio_courses_update(row_id: int) -> flask.Response:
    course = _owned(AudioCourse, row_id)
    _apply_audio_course(course, json_body(), course)
    flask.g.db.flush()
    _drop_unused_images()
    flask.g.db.commit()
    return flask.jsonify(audio_course_json(course))


@bp.route("/api/people", methods=["POST"])
@auth.login_required
def api_people_add() -> tuple[flask.Response, int]:
    person = Person(owner_id=flask.g.user.id)
    _apply_person(person, json_body())
    flask.g.db.add(person)
    flask.g.db.commit()
    return flask.jsonify(person_json(person)), 201


@bp.route("/api/people/<int:row_id>", methods=["PUT"])
@auth.login_required
def api_people_update(row_id: int) -> flask.Response:
    person = _owned(Person, row_id)
    _apply_person(person, json_body())
    flask.g.db.commit()
    return flask.jsonify(person_json(person))


@bp.route("/api/organizations", methods=["POST"])
@auth.login_required
def api_organizations_add() -> tuple[flask.Response, int]:
    organization = Organization(owner_id=flask.g.user.id)
    _apply_organization(organization, json_body())
    flask.g.db.add(organization)
    flask.g.db.commit()
    return flask.jsonify(organization_json(organization)), 201


@bp.route("/api/organizations/<int:row_id>", methods=["PUT"])
@auth.login_required
def api_organizations_update(row_id: int) -> flask.Response:
    organization = _owned(Organization, row_id)
    _apply_organization(organization, json_body())
    flask.g.db.flush()
    _drop_unused_images()
    flask.g.db.commit()
    return flask.jsonify(organization_json(organization))


@bp.route("/api/<any(concerts, museums, 'audio-courses', people, organizations):what>/<int:row_id>", methods=["DELETE"])
@auth.login_required
def api_world_delete(what: str, row_id: int) -> flask.Response:
    model = {"concerts": Concert, "museums": Museum, "audio-courses": AudioCourse, "people": Person, "organizations": Organization}[what]
    # the ORM also removes the row's links (to people, to organizations, to concerts and museums)
    flask.g.db.delete(_owned(model, row_id))
    flask.g.db.flush()
    _drop_unused_images()
    flask.g.db.commit()
    return flask.Response(status=204)


# ─── stats ──────────────────────────────────────────────────────────────────

def _per_year(rows: list[Concert] | list[Museum]) -> list[dict[str, int]]:
    """ How many rows fall in each year that has any, oldest first; undated rows are left out. """
    years: dict[int, int] = {}
    for row in rows:
        key = _date_json(row)["date_sort"][:4]
        if key:
            years[int(key)] = years.get(int(key), 0) + 1
    return [{"year": year, "count": years[year]} for year in sorted(years)]


def _by_type(counts: dict[str, int]) -> list[dict[str, Any]]:
    return [{"name": name, "count": count} for name, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


@bp.route("/api/stats", methods=["GET"])
@auth.login_required
def api_stats() -> flask.Response:
    """ How many of everything the user has, and a few breakdowns. """
    db = flask.g.db
    me = flask.g.user.id

    def count(model: Any) -> int:
        return db.scalar(select(func.count()).select_from(model).where(model.owner_id == me)) or 0

    library = []
    rows = db.execute(
        select(Work.kind, UserWork.status, func.count())
        .join(Work, Work.id == UserWork.work_id)
        .where(UserWork.user_id == me)
        .group_by(Work.kind, UserWork.status)
    ).all()
    for kind, (_, plural, _) in KINDS.items():
        by_status = {STATUSES[status]: n for k, status, n in rows if k == kind}
        library.append({"kind": kind, "label": plural, "total": sum(by_status.values()), "by_status": by_status})
    concerts = db.execute(select(Concert).where(Concert.owner_id == me)).scalars().all()
    museums = db.execute(select(Museum).where(Museum.owner_id == me)).scalars().all()
    people = db.execute(select(Person).where(Person.owner_id == me).options(selectinload(Person.types))).scalars().all()
    organizations = db.execute(
        select(Organization).where(Organization.owner_id == me).options(selectinload(Organization.type), selectinload(Organization.relations))
    ).scalars().all()
    people_by_type: dict[str, int] = {}
    for person in people:
        for kind in person.types or [None]:
            name = kind.name if kind else "No type"
            people_by_type[name] = people_by_type.get(name, 0) + 1
    organizations_by_relation: dict[str, int] = {}
    for organization in organizations:
        for relation in organization.relations or [None]:
            name = relation.name if relation else "No relation"
            organizations_by_relation[name] = organizations_by_relation.get(name, 0) + 1
    organizations_by_type: dict[str, int] = {}
    for organization in organizations:
        name = organization.type.name if organization.type else "No type"
        organizations_by_type[name] = organizations_by_type.get(name, 0) + 1
    performers = db.scalar(
        select(func.count(func.distinct(concert_performers.c.person_id)))
        .join(Concert, Concert.id == concert_performers.c.concert_id)
        .where(Concert.owner_id == me)
    ) or 0
    return flask.jsonify({
        "library": library,
        "concerts": len(concerts),
        "performers": performers,
        "museum_visits": len(museums),
        "museums": len({m.name for m in museums}),
        "audio_courses": count(AudioCourse),
        "people": len(people),
        "organizations": len(organizations),
        "organization_types": count(OrganizationType),
        "person_types": count(PersonType),
        "relation_types": count(RelationType),
        "devices": count(Device),
        "images": count(Image),
        "people_by_type": _by_type(people_by_type),
        "organizations_by_type": _by_type(organizations_by_type),
        "organizations_by_relation": _by_type(organizations_by_relation),
        "concerts_by_year": _per_year(list(concerts)),
        "museums_by_year": _per_year(list(museums)),
    })


# ─── the enumerations: organization, person and relation types ────────────

type TypeModel = OrganizationType | PersonType | RelationType | Device

# path -> (type model, what the typed rows are called); an organization has one
# type (organizations.type_id) and any number of relation types
# (organization_relation_types), a person any number of types (person_person_types)
TYPES: dict[str, tuple[type[TypeModel], str]] = {
    "organization-types": (OrganizationType, "organization"),
    "person-types": (PersonType, "person"),
    "relation-types": (RelationType, "organization"),
    # not a type of a thing, but kept the same way: a list of the user's own, each used by some rows
    "devices": (Device, "audio course"),
}


def _type_links(what: str) -> Any:
    """ One row per typed row of the user and one of its types: (type_id). """
    if what == "organization-types":
        return select(Organization.type_id.label("type_id")).where(Organization.owner_id == flask.g.user.id)
    if what == "devices":
        return select(AudioCourse.device_id.label("type_id")).where(AudioCourse.owner_id == flask.g.user.id)
    if what == "relation-types":
        return (
            select(organization_relation_types.c.relation_type_id.label("type_id"))
            .join(Organization, Organization.id == organization_relation_types.c.organization_id)
            .where(Organization.owner_id == flask.g.user.id)
        )
    return (
        select(person_person_types.c.type_id.label("type_id"))
        .join(Person, Person.id == person_person_types.c.person_id)
        .where(Person.owner_id == flask.g.user.id)
    )


def type_json(kind: TypeModel, count: int) -> dict[str, Any]:
    return {"id": kind.id, "name": kind.name, "description": kind.description, "count": count}


def _type_uses(what: str, kind: TypeModel) -> int:
    links = _type_links(what).subquery()
    return flask.g.db.scalar(select(func.count()).select_from(links).where(links.c.type_id == kind.id)) or 0


def _owned_type[T: (OrganizationType, PersonType, Device)](model: type[T], type_id: int | None) -> T | None:
    """ The user's own type type_id of model, or None for no type. """
    if type_id is None:
        return None
    kind = flask.g.db.get(model, type_id)
    if kind is None or kind.owner_id != flask.g.user.id:
        raise ApiError(400, "type_id: unknown type")
    return kind


def _apply_type(model: type[TypeModel], kind: TypeModel, body: dict[str, Any]) -> None:
    name = text(body, "name", required=True)
    clash = flask.g.db.execute(
        select(model.id).where(model.owner_id == flask.g.user.id, model.name == name, model.id != kind.id)
    ).first()
    if clash is not None:
        raise ApiError(409, f"{name} is already one of the types")
    kind.name = name
    kind.description = text(body, "description")


@bp.route("/api/<any('organization-types', 'person-types', 'relation-types', devices):what>", methods=["GET"])
@auth.login_required
def api_types(what: str) -> flask.Response:
    """ The user's enumeration, with how many rows are of each type. """
    model = TYPES[what][0]
    links = _type_links(what).subquery()
    used = select(links.c.type_id, func.count().label("n")).group_by(links.c.type_id).subquery()
    rows = flask.g.db.execute(
        select(model, func.coalesce(used.c.n, 0))
        .outerjoin(used, used.c.type_id == model.id)
        .where(model.owner_id == flask.g.user.id)
        .order_by(model.name)
    ).all()
    return flask.jsonify([type_json(kind, n) for kind, n in rows])


@bp.route("/api/<any('organization-types', 'person-types', 'relation-types', devices):what>", methods=["POST"])
@auth.login_required
def api_types_add(what: str) -> tuple[flask.Response, int]:
    model = TYPES[what][0]
    kind = model(owner_id=flask.g.user.id)
    _apply_type(model, kind, json_body())
    flask.g.db.add(kind)
    flask.g.db.commit()
    return flask.jsonify(type_json(kind, 0)), 201


@bp.route("/api/<any('organization-types', 'person-types', 'relation-types', devices):what>/<int:row_id>", methods=["PUT"])
@auth.login_required
def api_types_update(what: str, row_id: int) -> flask.Response:
    model = TYPES[what][0]
    kind = _owned(model, row_id)
    _apply_type(model, kind, json_body())
    flask.g.db.commit()
    return flask.jsonify(type_json(kind, _type_uses(what, kind)))


@bp.route("/api/<any('organization-types', 'person-types', 'relation-types', devices):what>/<int:row_id>", methods=["DELETE"])
@auth.login_required
def api_types_delete(what: str, row_id: int) -> flask.Response:
    """ Only a type nothing is: a row never silently loses its type. """
    model, noun = TYPES[what]
    kind = _owned(model, row_id)
    used = _type_uses(what, kind)
    if used:
        raise ApiError(409, f"{used} {noun}{'s are' if used > 1 else ' is'} {kind.name}: change them first")
    flask.g.db.delete(kind)
    flask.g.db.commit()
    return flask.Response(status=204)


@bp.route("/api/images", methods=["POST"])
@auth.login_required
def api_images_add() -> tuple[flask.Response, int]:
    """ Upload a photo (multipart, field "file"); the answer's id goes into image_id. """
    upload = flask.request.files.get("file")
    if upload is None:
        raise ApiError(400, "file: required")
    data = upload.read(IMAGE_MAX_BYTES + 1)
    if len(data) > IMAGE_MAX_BYTES:
        raise ApiError(413, f"file: larger than {IMAGE_MAX_BYTES // (1024 * 1024)} MB")
    content_type = _sniff(data)
    if content_type is None:
        raise ApiError(400, "file: not a JPEG, PNG, GIF or WebP image")
    sha256 = hashlib.sha256(data).hexdigest()
    filename = f"upload-{sha256[:16]}{IMAGE_EXTENSIONS[content_type]}"
    db = flask.g.db
    image = db.execute(select(Image).where(Image.owner_id == flask.g.user.id, Image.filename == filename)).scalar_one_or_none()
    created = image is None
    if image is None:
        image = Image(owner_id=flask.g.user.id, filename=filename, content_type=content_type, sha256=sha256, data=data)
        db.add(image)
        db.commit()
    return flask.jsonify({"id": image.id, "url": _image_url(image.id)}), 201 if created else 200
