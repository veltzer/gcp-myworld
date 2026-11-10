"""
JSON API for the concerts, museum visits, places, people and organizations of the
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

from myworld import auth, names
from myworld.api import ApiError, coordinates, json_body, opt_int, text
from myworld.models import (
    KINDS,
    RATING_MAX,
    RATING_MIN,
    STATUSES,
    YOUTUBE_ID_LENGTH,
    AudioCourse,
    City,
    Concert,
    Country,
    Device,
    Group,
    Image,
    Museum,
    Organization,
    OrganizationType,
    Person,
    PersonOrganization,
    PersonOrganizationType,
    PersonRelation,
    PersonRelationType,
    PersonType,
    Place,
    RelationType,
    UserWork,
    Work,
    YouTubeVideo,
    concert_performers,
    organization_relation_types,
    person_type_links,
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


def _date_json(row: Concert | Museum | AudioCourse | YouTubeVideo) -> dict[str, Any]:
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


def image_url(image_id: int | None) -> str | None:
    return None if image_id is None else flask.url_for("world.api_image", image_id=image_id)


def _names(people: list[Person]) -> list[str]:
    return sorted(p.name for p in people)


def _refs(rows: list[Person] | list[Organization] | list[PersonType] | list[RelationType] | list[Group] | list[Concert] | list[Place] | list[City]) -> list[dict[str, Any]]:
    """ Names with the ids the People and Organizations views link to, each row once (a person may be linked to one organization twice). """
    unique = {row.id: row for row in rows}.values()
    return [{"id": row.id, "name": row.name} for row in sorted(unique, key=lambda row: row.name)]


def concert_json(concert: Concert) -> dict[str, Any]:
    return {
        "id": concert.id,
        "name": concert.name,
        "performers": _refs(concert.performers),
        # the groups (bands) that performed
        "groups": _refs(concert.groups),
        "event": concert.event,
        "genre": concert.genre,
        **_date_json(concert),
        "date_timezone": concert.date_timezone,
        # where it was, a row of the Places page
        "place": None if concert.place is None else _place_ref(concert.place),
        "tickets": concert.tickets,
        "broadcast": concert.broadcast,
        "review": concert.review,
        "remark": concert.remark,
        "with": _names(concert.people),
        "people": _refs(concert.people),
        "image": image_url(concert.image_id),
        "image_source": concert.image_source,
        "image_license": concert.image_license,
        "image_author": concert.image_author,
    }


def country_ref(country: Country | None) -> dict[str, Any] | None:
    return None if country is None else {"id": country.id, "name": country.name}


def city_ref(city: City | None) -> dict[str, Any] | None:
    """ A city as other rows show it: its id, name, region and country; None for no city. """
    return None if city is None else {"id": city.id, "name": city.name, "region": city.region, "country": country_ref(city.country)}


def _picture_json(row: City | Country) -> dict[str, Any]:
    return {"image": image_url(row.image_id), "image_source": row.image_source, "image_license": row.image_license, "image_author": row.image_author}


def country_json(country: Country) -> dict[str, Any]:
    return {
        "id": country.id,
        "name": country.name,
        **_picture_json(country),
        "latitude": country.latitude,
        "longitude": country.longitude,
        "remark": country.remark,
        "cities": _refs(country.cities),
    }


def _address_parts(row: Place | Museum | Organization) -> dict[str, str]:
    return {"street": row.street, "neighbourhood": row.neighbourhood, "postcode": row.postcode}


def _apply_address(row: Place | Museum | Organization, body: dict[str, Any]) -> None:
    row.street = text(body, "street")
    row.neighbourhood = text(body, "neighbourhood")
    row.postcode = text(body, "postcode")


def _place_ref(place: Place) -> dict[str, Any]:
    return {"id": place.id, "name": place.name, "city": city_ref(place.city)}


def city_json(city: City) -> dict[str, Any]:
    # a museum visited twice is one museum here
    museums = {m.name: {"id": m.id, "name": m.name} for m in sorted(city.museums, key=lambda m: m.id)}
    return {
        **(city_ref(city) or {}),
        **_picture_json(city),
        "latitude": city.latitude,
        "longitude": city.longitude,
        "remark": city.remark,
        "places": _refs(city.places),
        "museums": sorted(museums.values(), key=lambda m: m["name"]),
        "organizations": _refs(city.organizations),
        "headquarters_of": _refs(city.headquarters_of),
    }


def place_json(place: Place) -> dict[str, Any]:
    # the concerts that were there, newest first
    concerts = _newest_first([{"id": c.id, "name": c.name, **_date_json(c)} for c in place.concerts])
    return {
        **_place_ref(place),
        # the address in one line, and its parts (the city carries region and country)
        "address": place.address,
        **_address_parts(place),
        "latitude": place.latitude,
        "longitude": place.longitude,
        "website": place.website,
        "remark": place.remark,
        "concerts": [{"id": c["id"], "name": c["name"]} for c in concerts],
    }


def group_json(group: Group) -> dict[str, Any]:
    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "website": group.website,
        "members": _refs(group.members),
        # the concerts it performed at, newest first
        "concerts": [{"id": c["id"], "name": c["name"]} for c in _newest_first([{"id": c.id, "name": c.name, **_date_json(c)} for c in group.concerts])],
    }


def museum_json(museum: Museum) -> dict[str, Any]:
    return {
        "id": museum.id,
        "name": museum.name,
        **_date_json(museum),
        "date_timezone": museum.date_timezone,
        "city": city_ref(museum.city),
        # the address in one line, and its parts (the city carries region and country)
        "address": museum.address,
        **_address_parts(museum),
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
        "image": image_url(museum.image_id),
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
        "image": image_url(course.image_id),
    }


def _course_url(course: AudioCourse) -> str:
    """ The course's page: where it is sold (The Great Courses, Audible), or else any page about it. """
    if course.great_courses_slug:
        return f"https://www.thegreatcourses.com/courses/{course.great_courses_slug}"
    if course.audible_asin:
        return f"https://www.audible.com/pd/{course.audible_asin}"
    return course.link


def youtube_video_json(video: YouTubeVideo) -> dict[str, Any]:
    return {
        "id": video.id,
        "name": video.name,
        **_date_json(video),
        "date_timezone": video.date_timezone,
        "youtube_id": video.youtube_id,
        "rating": video.rating,
        "review": video.review,
        "device": None if video.device is None else {"id": video.device.id, "name": video.device.name},
        "watched_at": video.watched_at,
        "channel": video.channel,
        "category": video.category,
        "duration": video.duration,
        "uploaded": video.uploaded.isoformat() if video.uploaded else "",
        "views": video.views,
        "unavailable": video.unavailable,
        # the page and the thumbnail are YouTube's, by youtube_id: the page
        # builds their URLs itself, which keeps 30,000 rows a quarter shorter
    }


def person_json(person: Person) -> dict[str, Any]:
    return {
        "id": person.id,
        "name": person.name,
        # the account owner themselves
        "is_self": person.is_self,
        "honorific": person.honorific,
        "first_name": person.first_name,
        "middle_name": person.middle_name,
        "surname": person.surname,
        "types": _refs(person.types),
        # each organization they are linked to, once; and the links, each of a kind ("Worked at Schema")
        "organizations": _refs(person.organizations),
        "organization_links": [
            {"type_id": link.relation_type.id, "type": link.relation_type.name, "organization": {"id": link.organization.id, "name": link.organization.name},
             "name": f"{link.relation_type.name} {link.organization.name}"}
            for link in person.organization_links
        ],
        # how they are related to other people, each read from their side:
        # "Mother of Dana" (their own relations) and "Child of Ruth" (Ruth's)
        "relations": [_relation_json(r.relation_type.id, r.relation_type.name, r.other) for r in person.relations],
        "related": [_relation_json(r.relation_type.id, r.relation_type.inverse_name, r.person) for r in person.related],
        "description": person.description,
    }


def _relation_json(type_id: int, phrase: str, other: Person) -> dict[str, Any]:
    return {"type_id": type_id, "type": phrase, "person": {"id": other.id, "name": other.name}, "name": f"{phrase} {other.name}"}


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
        "city": city_ref(organization.city),
        "headquarters": city_ref(organization.headquarters),
        # the address in one line, and its parts (the city carries region and country)
        "address": organization.address,
        **_address_parts(organization),
        "latitude": organization.latitude,
        "longitude": organization.longitude,
        "what_happened": organization.what_happened,
        "remark": organization.remark,
        "image": image_url(organization.image_id),
        "people": _refs(organization.people),
        # how each is linked to it: "Dana Cohen (Worked at)"
        "person_links": [
            {"type_id": link.relation_type.id, "type": link.relation_type.name, "person": {"id": link.person.id, "name": link.person.name},
             "name": f"{link.person.name} ({link.relation_type.name})"}
            for link in sorted(organization.person_links, key=lambda link: (link.person.name, link.relation_type.name))
        ],
    }


def _newest_first(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: (item["date_sort"], item["name"]), reverse=True)


@bp.route("/api/concert-visits", methods=["GET"])
@auth.login_required
def api_concerts() -> flask.Response:
    query = select(Concert).where(Concert.owner_id == flask.g.user.id).options(
        selectinload(Concert.people), selectinload(Concert.performers), selectinload(Concert.place).selectinload(Place.city).selectinload(City.country), selectinload(Concert.groups),
    )
    concerts = flask.g.db.execute(query).scalars().all()
    return flask.jsonify(_newest_first([concert_json(c) for c in concerts]))


@bp.route("/api/audio-courses", methods=["GET"])
@auth.login_required
def api_audio_courses() -> flask.Response:
    query = select(AudioCourse).where(AudioCourse.owner_id == flask.g.user.id).options(selectinload(AudioCourse.lecturers), selectinload(AudioCourse.device))
    courses = flask.g.db.execute(query).scalars().all()
    # finished ones newest first; those in progress (no date yet) after them
    return flask.jsonify(_newest_first([audio_course_json(c) for c in courses]))


@bp.route("/api/youtube-videos", methods=["GET"])
@auth.login_required
def api_youtube() -> flask.Response:
    query = select(YouTubeVideo).where(YouTubeVideo.owner_id == flask.g.user.id).options(selectinload(YouTubeVideo.device))
    videos = flask.g.db.execute(query).scalars().all()
    return flask.jsonify(_newest_first([youtube_video_json(v) for v in videos]))


@bp.route("/api/museum-visits", methods=["GET"])
@auth.login_required
def api_museums() -> flask.Response:
    query = select(Museum).where(Museum.owner_id == flask.g.user.id).options(selectinload(Museum.people), selectinload(Museum.city).selectinload(City.country))
    museums = flask.g.db.execute(query).scalars().all()
    return flask.jsonify(_newest_first([museum_json(m) for m in museums]))


@bp.route("/api/people", methods=["GET"])
@auth.login_required
def api_people() -> flask.Response:
    query = (
        select(Person)
        .where(Person.owner_id == flask.g.user.id)
        .options(
            selectinload(Person.organizations), selectinload(Person.types),
            selectinload(Person.organization_links).selectinload(PersonOrganization.relation_type),
            selectinload(Person.organization_links).selectinload(PersonOrganization.organization),
            selectinload(Person.relations).selectinload(PersonRelation.relation_type), selectinload(Person.relations).selectinload(PersonRelation.other),
            selectinload(Person.related).selectinload(PersonRelation.relation_type), selectinload(Person.related).selectinload(PersonRelation.person),
        )
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
        .options(
            selectinload(Organization.people), selectinload(Organization.type), selectinload(Organization.relations), selectinload(Organization.city).selectinload(City.country),
            selectinload(Organization.headquarters).selectinload(City.country),
            selectinload(Organization.person_links).selectinload(PersonOrganization.relation_type),
            selectinload(Organization.person_links).selectinload(PersonOrganization.person),
        )
        .order_by(Organization.name)
    )
    organizations = flask.g.db.execute(query).scalars().all()
    return flask.jsonify([organization_json(c) for c in organizations])


@bp.route("/api/places", methods=["GET"])
@auth.login_required
def api_places() -> flask.Response:
    query = select(Place).where(Place.owner_id == flask.g.user.id).options(selectinload(Place.concerts), selectinload(Place.city).selectinload(City.country)).order_by(Place.name, Place.id)
    places = flask.g.db.execute(query).scalars().all()
    return flask.jsonify([place_json(p) for p in places])


@bp.route("/api/groups", methods=["GET"])
@auth.login_required
def api_groups() -> flask.Response:
    query = select(Group).where(Group.owner_id == flask.g.user.id).options(selectinload(Group.members), selectinload(Group.concerts)).order_by(Group.name)
    groups = flask.g.db.execute(query).scalars().all()
    return flask.jsonify([group_json(g) for g in groups])


@bp.route("/api/cities", methods=["GET"])
@auth.login_required
def api_cities() -> flask.Response:
    query = (
        select(City).where(City.owner_id == flask.g.user.id)
        .options(
            selectinload(City.places), selectinload(City.museums), selectinload(City.organizations), selectinload(City.headquarters_of), selectinload(City.country),
        )
        .order_by(City.name, City.id)
    )
    return flask.jsonify([city_json(c) for c in flask.g.db.execute(query).scalars().all()])


@bp.route("/api/countries", methods=["GET"])
@auth.login_required
def api_countries() -> flask.Response:
    query = select(Country).where(Country.owner_id == flask.g.user.id).options(selectinload(Country.cities)).order_by(Country.name)
    return flask.jsonify([country_json(c) for c in flask.g.db.execute(query).scalars().all()])


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


def _dates(body: dict[str, Any], current: Concert | Museum | AudioCourse | YouTubeVideo | None = None) -> dict[str, Any]:
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


def owned_list[T: (Person, Organization, PersonType, RelationType, Group)](body: dict[str, Any], key: str, model: type[T]) -> list[T]:
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
    return owned_list(body, "people", Person)


def owned_image(body: dict[str, Any]) -> int | None:
    image_id = opt_int(body, "image_id", 1, 2**31 - 1)
    if image_id is None:
        return None
    image = flask.g.db.get(Image, image_id)
    if image is None or image.owner_id != flask.g.user.id:
        raise ApiError(400, "image_id: unknown image")
    return image_id


def _owned(model: type[Concert | Museum | AudioCourse | YouTubeVideo | Person | Organization | Place | Group | City | Country | OrganizationType | PersonType | RelationType | PersonRelationType | PersonOrganizationType | Device], row_id: int) -> Any:
    row = flask.g.db.get(model, row_id)
    if row is None or row.owner_id != flask.g.user.id:
        raise ApiError(404, "no such entry")
    return row


def drop_unused_images() -> None:
    """ Photos and logos nothing shows any more (replaced or deleted) go too. """
    db = flask.g.db
    used = select(Concert.image_id).where(Concert.image_id.is_not(None)).union(
        select(Museum.image_id).where(Museum.image_id.is_not(None)),
        select(Organization.image_id).where(Organization.image_id.is_not(None)),
        select(AudioCourse.image_id).where(AudioCourse.image_id.is_not(None)),
        select(UserWork.image_id).where(UserWork.image_id.is_not(None)),
        select(City.image_id).where(City.image_id.is_not(None)),
        select(Country.image_id).where(Country.image_id.is_not(None)),
    )
    for image in db.execute(select(Image).where(Image.owner_id == flask.g.user.id, Image.id.not_in(used))).scalars():
        db.delete(image)


def _apply_concert(concert: Concert, body: dict[str, Any], current: Concert | None) -> None:
    concert.name = text(body, "name", required=True)
    concert.performers = owned_list(body, "performers", Person)
    concert.groups = owned_list(body, "groups", Group)
    concert.event = text(body, "event")
    concert.genre = text(body, "genre")
    concert.place = _owned_place(body)
    concert.tickets = opt_int(body, "tickets", 0, 1000)
    concert.broadcast = body.get("broadcast") is True
    concert.review = text(body, "review")
    concert.remark = text(body, "remark")
    # a photo is only ever replaced by a new upload, never blanked by omission
    image_id = owned_image(body)
    if image_id is not None:
        concert.image_id = image_id
    concert.image_source = text(body, "image_source")
    concert.image_license = text(body, "image_license")
    concert.image_author = text(body, "image_author")
    concert.people = _owned_people(body)
    for key, value in _dates(body, current).items():
        setattr(concert, key, value)


def _owned_place(body: dict[str, Any]) -> Place | None:
    """ body's place_id, one of the user's own places, or None for no place. """
    place_id = opt_int(body, "place_id", 1, 2**31 - 1)
    if place_id is None:
        return None
    place = flask.g.db.get(Place, place_id)
    if place is None or place.owner_id != flask.g.user.id:
        raise ApiError(400, "place_id: unknown place")
    return place


def _owned_city(body: dict[str, Any], key: str = "city_id") -> City | None:
    """ body's city_id (or key), one of the user's own cities, or None for no city. """
    city_id = opt_int(body, key, 1, 2**31 - 1)
    if city_id is None:
        return None
    city = flask.g.db.get(City, city_id)
    if city is None or city.owner_id != flask.g.user.id:
        raise ApiError(400, f"{key}: unknown city")
    return city


def _owned_country(body: dict[str, Any]) -> Country | None:
    """ body's country_id, one of the user's own countries, or None for no country. """
    country_id = opt_int(body, "country_id", 1, 2**31 - 1)
    if country_id is None:
        return None
    country = flask.g.db.get(Country, country_id)
    if country is None or country.owner_id != flask.g.user.id:
        raise ApiError(400, "country_id: unknown country")
    return country


def _apply_country(country: Country, body: dict[str, Any]) -> None:
    name = text(body, "name", required=True)
    clash = flask.g.db.execute(select(Country.id).where(Country.owner_id == flask.g.user.id, Country.name == name, Country.id != country.id)).first()
    if clash is not None:
        raise ApiError(409, f"{name} is already in Countries")
    country.name = name
    country.latitude, country.longitude = coordinates(body)
    country.remark = text(body, "remark")
    _apply_picture(country, body)


def _apply_picture(row: City | Country, body: dict[str, Any]) -> None:
    # a photo is only ever replaced by a new upload, never blanked by omission
    image_id = owned_image(body)
    if image_id is not None:
        row.image_id = image_id
    row.image_source = text(body, "image_source")
    row.image_license = text(body, "image_license")
    row.image_author = text(body, "image_author")


def _apply_city(city: City, body: dict[str, Any]) -> None:
    name = text(body, "name", required=True)
    region, country = text(body, "region"), _owned_country(body)
    clash = flask.g.db.execute(
        select(City.id).where(
            City.owner_id == flask.g.user.id, City.name == name, City.region == region,
            City.country_id == country.id if country else City.country_id.is_(None), City.id != city.id,
        )
    ).first()
    if clash is not None:
        raise ApiError(409, f"{name}{', ' + country.name if country else ''} is already in Cities")
    city.name, city.region, city.country = name, region, country
    city.latitude, city.longitude = coordinates(body)
    city.remark = text(body, "remark")
    _apply_picture(city, body)


def _apply_place(place: Place, body: dict[str, Any]) -> None:
    name = text(body, "name", required=True)
    city = _owned_city(body)
    clash = flask.g.db.execute(
        select(Place.id).where(
            Place.owner_id == flask.g.user.id, Place.name == name, Place.city_id == city.id if city else Place.city_id.is_(None), Place.id != place.id,
        )
    ).first()
    if clash is not None:
        raise ApiError(409, f"{name}{', ' + city.name if city else ''} is already in Places")
    place.name = name
    place.city = city
    _apply_address(place, body)
    place.latitude, place.longitude = coordinates(body)
    place.website = text(body, "website")
    place.remark = text(body, "remark")


def _apply_group(group: Group, body: dict[str, Any]) -> None:
    name = text(body, "name", required=True)
    clash = flask.g.db.execute(select(Group.id).where(Group.owner_id == flask.g.user.id, Group.name == name, Group.id != group.id)).first()
    if clash is not None:
        raise ApiError(409, f"{name} is already in Groups")
    # looked up before anything is set on a new group, which is not in the session yet
    members = owned_list(body, "members", Person)
    group.name = name
    group.members = members
    group.description = text(body, "description")
    group.website = text(body, "website")


def _apply_museum(museum: Museum, body: dict[str, Any], current: Museum | None) -> None:
    museum.name = text(body, "name", required=True)
    museum.city = _owned_city(body)
    _apply_address(museum, body)
    museum.latitude, museum.longitude = coordinates(body)
    museum.rating = opt_int(body, "rating", RATING_MIN, RATING_MAX)
    museum.review = text(body, "review")
    museum.remark = text(body, "remark")
    museum.url = text(body, "url")
    museum.tickets = opt_int(body, "tickets", 0, 1000)
    image_id = owned_image(body)
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
    course.lecturers = owned_list(body, "lecturers", Person)
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
    image_id = owned_image(body)
    if image_id is not None:
        course.image_id = image_id
    for key, value in _dates(body, current).items():
        setattr(course, key, value)


YOUTUBE_ID = re.compile(rf"[A-Za-z0-9_-]{{{YOUTUBE_ID_LENGTH}}}")
# the id inside a pasted link: youtube.com/watch?v=ID, youtu.be/ID, youtube.com/shorts/ID, /embed/ID, /live/ID
YOUTUBE_LINK = re.compile(r"(?:[?&]v=|youtu\.be/|/(?:shorts|embed|live)/)([A-Za-z0-9_-]+)")


def youtube_id(value: str) -> str:
    """ The video id of what was typed: an id, or a link to the video. """
    found = YOUTUBE_LINK.search(value)
    if found:
        value = found.group(1)
    if not YOUTUBE_ID.fullmatch(value):
        raise ApiError(400, f"youtube_id: expected a video id ({YOUTUBE_ID_LENGTH} characters) or a link to the video")
    return value


def _apply_youtube_video(video: YouTubeVideo, body: dict[str, Any], current: YouTubeVideo | None) -> None:
    video.youtube_id = youtube_id(text(body, "youtube_id", required=True))
    clash = flask.g.db.execute(select(YouTubeVideo.id).where(
        YouTubeVideo.owner_id == flask.g.user.id, YouTubeVideo.youtube_id == video.youtube_id, YouTubeVideo.id != video.id,
    )).first()
    if clash is not None:
        raise ApiError(409, "that video is in your list already")
    # one YouTube no longer has may have no name: only its id is known
    video.name = text(body, "name", required=not video.unavailable)
    video.rating = opt_int(body, "rating", RATING_MIN, RATING_MAX)
    video.review = text(body, "review")
    video.device = _owned_type(Device, opt_int(body, "device_id", 1, 2**31 - 1))
    video.watched_at = text(body, "watched_at")
    for key, value in _dates(body, current).items():
        setattr(video, key, value)


def _apply_person(person: Person, body: dict[str, Any]) -> None:
    # two people may share a name, so there is no clash to look for
    # either name, or both, may be missing: someone with no name goes by the
    # description, so it is only a person with none of the three, who could
    # not be picked in any picker, that is refused
    person.honorific = text(body, "honorific")
    person.first_name = text(body, "first_name")
    person.middle_name = " ".join(text(body, "middle_name").split())
    person.surname = text(body, "surname")
    person.description = text(body, "description")
    # one word each; the middle name holds whatever comes between
    for key, value in (("honorific", person.honorific), ("first_name", person.first_name), ("surname", person.surname)):
        if names.has_space(value):
            raise ApiError(400, f"{key}: one word, without spaces (a surname of two words is hyphenated; more names go in the middle name)")
    if not person.first_name and not person.middle_name and not person.surname and not person.description:
        raise ApiError(400, "a person needs a name or a description")
    if "organization_links" in body:
        person.organization_links = _organization_links(person, body["organization_links"])
    elif "organizations" in body:
        person.organization_links = _links_to(person, owned_list(body, "organizations", Organization))
    person.types = owned_list(body, "type_ids", PersonType)
    if "relations" in body:
        person.relations = _person_relations(person, body["relations"])


def _organization_links(person: Person, value: Any) -> list[PersonOrganization]:
    """
    A person's links to organizations from [{"type_id", "organization_id"}, ...]:
    each a person-org relation type and an organization of the user's; one
    already there is kept as it is.
    """
    if not isinstance(value, list) or not all(isinstance(r, dict) for r in value):
        raise ApiError(400, "organization_links: expected a list of {type_id, organization_id}")
    kept = {(link.relation_type_id, link.organization_id): link for link in person.organization_links}
    out: dict[tuple[int, int], PersonOrganization] = {}
    for item in value:
        type_id, organization_id = item.get("type_id"), item.get("organization_id")
        if not all(isinstance(i, int) and not isinstance(i, bool) for i in (type_id, organization_id)):
            raise ApiError(400, "organization_links: type_id and organization_id are ids")
        kind = flask.g.db.get(PersonOrganizationType, type_id)
        if kind is None or kind.owner_id != flask.g.user.id:
            raise ApiError(400, "organization_links: unknown kind of link")
        organization = flask.g.db.get(Organization, organization_id)
        if organization is None or organization.owner_id != flask.g.user.id:
            raise ApiError(400, "organization_links: unknown organization")
        out[type_id, organization_id] = kept.get((type_id, organization_id)) or PersonOrganization(relation_type=kind, organization=organization)
    return list(out.values())


def _links_to(person: Person, organizations: list[Organization]) -> list[PersonOrganization]:
    """
    Links to exactly these organizations, for a client that sends only which:
    the links already there to them are kept, a new one is of the user's
    first kind ("Worked at" when they have it).
    """
    wanted = {o.id for o in organizations}
    links = [link for link in person.organization_links if link.organization_id in wanted]
    linked = {link.organization_id for link in links}
    missing = [o for o in organizations if o.id not in linked]
    if missing:
        kinds = flask.g.db.execute(select(PersonOrganizationType).where(PersonOrganizationType.owner_id == flask.g.user.id)).scalars().all()
        if not kinds:
            raise ApiError(400, "organizations: add a kind of link first (Types, Person-org relations)")
        kind = next((k for k in kinds if k.name == "Worked at"), min(kinds, key=lambda k: k.name))
        links += [PersonOrganization(relation_type=kind, organization=o) for o in missing]
    return links


def _person_relations(person: Person, value: Any) -> list[PersonRelation]:
    """
    A person's own relations from [{"type_id", "person_id"}, ...]: each a
    person relation type and a person of the user's, never the person
    themselves; one already there is kept as it is.
    """
    if not isinstance(value, list) or not all(isinstance(r, dict) for r in value):
        raise ApiError(400, "relations: expected a list of {type_id, person_id}")
    kept = {(r.relation_type_id, r.other_id): r for r in person.relations}
    out: dict[tuple[int, int], PersonRelation] = {}
    for item in value:
        type_id, other_id = item.get("type_id"), item.get("person_id")
        if not all(isinstance(i, int) and not isinstance(i, bool) for i in (type_id, other_id)):
            raise ApiError(400, "relations: type_id and person_id are ids")
        kind = flask.g.db.get(PersonRelationType, type_id)
        if kind is None or kind.owner_id != flask.g.user.id:
            raise ApiError(400, "relations: unknown relation type")
        other = flask.g.db.get(Person, other_id)
        if other is None or other.owner_id != flask.g.user.id:
            raise ApiError(400, "relations: unknown person")
        if other_id == person.id:
            raise ApiError(400, "relations: a person is not related to themselves")
        out[type_id, other_id] = kept.get((type_id, other_id)) or PersonRelation(relation_type=kind, other=other)
    return list(out.values())


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
    relations = owned_list(body, "relation_ids", RelationType)
    image_id = owned_image(body)
    organization.relations = relations
    organization.status = text(body, "status")
    organization.website = text(body, "website")
    organization.location = text(body, "location")
    organization.city = _owned_city(body)
    organization.headquarters = _owned_city(body, "headquarters_id")
    _apply_address(organization, body)
    organization.latitude, organization.longitude = coordinates(body)
    organization.what_happened = text(body, "what_happened")
    organization.remark = text(body, "remark")
    if image_id is not None:
        organization.image_id = image_id


@bp.route("/api/concert-visits", methods=["POST"])
@auth.login_required
def api_concerts_add() -> tuple[flask.Response, int]:
    concert = Concert(owner_id=flask.g.user.id)
    _apply_concert(concert, json_body(), None)
    flask.g.db.add(concert)
    flask.g.db.commit()
    return flask.jsonify(concert_json(concert)), 201


@bp.route("/api/concert-visits/<int:row_id>", methods=["PUT"])
@auth.login_required
def api_concerts_update(row_id: int) -> flask.Response:
    concert = _owned(Concert, row_id)
    _apply_concert(concert, json_body(), concert)
    flask.g.db.flush()
    drop_unused_images()
    flask.g.db.commit()
    return flask.jsonify(concert_json(concert))


@bp.route("/api/museum-visits", methods=["POST"])
@auth.login_required
def api_museums_add() -> tuple[flask.Response, int]:
    museum = Museum(owner_id=flask.g.user.id)
    _apply_museum(museum, json_body(), None)
    flask.g.db.add(museum)
    flask.g.db.commit()
    return flask.jsonify(museum_json(museum)), 201


@bp.route("/api/museum-visits/<int:row_id>", methods=["PUT"])
@auth.login_required
def api_museums_update(row_id: int) -> flask.Response:
    museum = _owned(Museum, row_id)
    _apply_museum(museum, json_body(), museum)
    flask.g.db.flush()
    drop_unused_images()
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
    drop_unused_images()
    flask.g.db.commit()
    return flask.jsonify(audio_course_json(course))


@bp.route("/api/youtube-videos", methods=["POST"])
@auth.login_required
def api_youtube_add() -> tuple[flask.Response, int]:
    video = YouTubeVideo(owner_id=flask.g.user.id)
    _apply_youtube_video(video, json_body(), None)
    flask.g.db.add(video)
    flask.g.db.commit()
    return flask.jsonify(youtube_video_json(video)), 201


@bp.route("/api/youtube-videos/<int:row_id>", methods=["PUT"])
@auth.login_required
def api_youtube_update(row_id: int) -> flask.Response:
    video = _owned(YouTubeVideo, row_id)
    _apply_youtube_video(video, json_body(), video)
    flask.g.db.commit()
    return flask.jsonify(youtube_video_json(video))


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
    drop_unused_images()
    flask.g.db.commit()
    return flask.jsonify(organization_json(organization))


@bp.route("/api/cities", methods=["POST"])
@auth.login_required
def api_cities_add() -> tuple[flask.Response, int]:
    city = City(owner_id=flask.g.user.id)
    _apply_city(city, json_body())
    flask.g.db.add(city)
    flask.g.db.commit()
    return flask.jsonify(city_json(city)), 201


@bp.route("/api/cities/<int:row_id>", methods=["PUT"])
@auth.login_required
def api_cities_update(row_id: int) -> flask.Response:
    city = _owned(City, row_id)
    _apply_city(city, json_body())
    flask.g.db.commit()
    return flask.jsonify(city_json(city))


@bp.route("/api/countries", methods=["POST"])
@auth.login_required
def api_countries_add() -> tuple[flask.Response, int]:
    country = Country(owner_id=flask.g.user.id)
    _apply_country(country, json_body())
    flask.g.db.add(country)
    flask.g.db.commit()
    return flask.jsonify(country_json(country)), 201


@bp.route("/api/countries/<int:row_id>", methods=["PUT"])
@auth.login_required
def api_countries_update(row_id: int) -> flask.Response:
    country = _owned(Country, row_id)
    _apply_country(country, json_body())
    flask.g.db.commit()
    return flask.jsonify(country_json(country))


@bp.route("/api/places", methods=["POST"])
@auth.login_required
def api_places_add() -> tuple[flask.Response, int]:
    place = Place(owner_id=flask.g.user.id)
    _apply_place(place, json_body())
    flask.g.db.add(place)
    flask.g.db.commit()
    return flask.jsonify(place_json(place)), 201


@bp.route("/api/places/<int:row_id>", methods=["PUT"])
@auth.login_required
def api_places_update(row_id: int) -> flask.Response:
    place = _owned(Place, row_id)
    _apply_place(place, json_body())
    flask.g.db.commit()
    return flask.jsonify(place_json(place))


@bp.route("/api/groups", methods=["POST"])
@auth.login_required
def api_groups_add() -> tuple[flask.Response, int]:
    group = Group(owner_id=flask.g.user.id)
    _apply_group(group, json_body())
    flask.g.db.add(group)
    flask.g.db.commit()
    return flask.jsonify(group_json(group)), 201


@bp.route("/api/groups/<int:row_id>", methods=["PUT"])
@auth.login_required
def api_groups_update(row_id: int) -> flask.Response:
    group = _owned(Group, row_id)
    _apply_group(group, json_body())
    flask.g.db.commit()
    return flask.jsonify(group_json(group))


@bp.route("/api/<any('concert-visits', 'museum-visits', 'audio-courses', 'youtube-videos', people, organizations, places, groups, cities, countries):what>/<int:row_id>", methods=["DELETE"])
@auth.login_required
def api_world_delete(what: str, row_id: int) -> flask.Response:
    model = {"concert-visits": Concert, "museum-visits": Museum, "audio-courses": AudioCourse, "youtube-videos": YouTubeVideo, "people": Person, "organizations": Organization, "places": Place, "groups": Group, "cities": City, "countries": Country}[what]
    # the ORM also removes the row's links (to people, to organizations, to concerts and museums);
    # the concerts at a deleted place are kept, with no place
    flask.g.db.delete(_owned(model, row_id))
    flask.g.db.flush()
    drop_unused_images()
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


# the YouTube channels on the Stats page: the ones watched most
TOP_CHANNELS = 15


def _youtube_by(column: Any, limit: int | None = None) -> list[dict[str, Any]]:
    """ The user's YouTube videos counted by column (channel, category), most first; those without one are left out. """
    rows = flask.g.db.execute(
        select(column, func.count()).where(YouTubeVideo.owner_id == flask.g.user.id, column != "")
        .group_by(column).order_by(func.count().desc(), column).limit(limit),
    ).all()
    return [{"name": name, "count": count} for name, count in rows]


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
            name = kind.name if kind else "No profession"
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
        "youtube_videos": count(YouTubeVideo),
        "people": len(people),
        "organizations": len(organizations),
        "places": count(Place),
        "cities": count(City),
        "countries": count(Country),
        "groups": count(Group),
        "organization_types": count(OrganizationType),
        "person_types": count(PersonType),
        "relation_types": count(RelationType),
        "person_relation_types": count(PersonRelationType),
        "person_organization_types": count(PersonOrganizationType),
        "devices": count(Device),
        "images": count(Image),
        "people_by_type": _by_type(people_by_type),
        "organizations_by_type": _by_type(organizations_by_type),
        "organizations_by_relation": _by_type(organizations_by_relation),
        "concerts_by_year": _per_year(list(concerts)),
        "museums_by_year": _per_year(list(museums)),
        "youtube_by_channel": _youtube_by(YouTubeVideo.channel, TOP_CHANNELS),
        "youtube_by_category": _youtube_by(YouTubeVideo.category),
    })


# ─── the enumerations: organization, person and relation types ────────────

type TypeModel = OrganizationType | PersonType | RelationType | PersonRelationType | PersonOrganizationType | Device

# path -> (type model, what the typed rows are called); an organization has one
# type (organizations.type_id) and any number of relation types
# (organization_relation_types), a person any number of types (person_type_links)
TYPES: dict[str, tuple[type[TypeModel], str]] = {
    "organization-types": (OrganizationType, "organization"),
    "person-types": (PersonType, "person"),
    "relation-types": (RelationType, "organization"),
    # how people are related to each other ("Mother of"): used by relations between two people
    "person-relation-types": (PersonRelationType, "relation"),
    # how a person is linked to an organization ("Worked at")
    "person-organization-types": (PersonOrganizationType, "link"),
    # not a type of a thing, but kept the same way: a list of the user's own, each used by some rows
    "devices": (Device, "recording"),
}


def _type_links(what: str) -> Any:
    """ One row per typed row of the user and one of its types: (type_id). """
    if what == "organization-types":
        return select(Organization.type_id.label("type_id")).where(Organization.owner_id == flask.g.user.id)
    if what == "devices":
        # audio courses and YouTube videos both point to a device
        return select(AudioCourse.device_id.label("type_id")).where(AudioCourse.owner_id == flask.g.user.id).union_all(
            select(YouTubeVideo.device_id.label("type_id")).where(YouTubeVideo.owner_id == flask.g.user.id),
        )
    if what == "person-organization-types":
        return (
            select(PersonOrganization.relation_type_id.label("type_id"))
            .join(Person, Person.id == PersonOrganization.person_id)
            .where(Person.owner_id == flask.g.user.id)
        )
    if what == "person-relation-types":
        return (
            select(PersonRelation.relation_type_id.label("type_id"))
            .join(Person, Person.id == PersonRelation.person_id)
            .where(Person.owner_id == flask.g.user.id)
        )
    if what == "relation-types":
        return (
            select(organization_relation_types.c.relation_type_id.label("type_id"))
            .join(Organization, Organization.id == organization_relation_types.c.organization_id)
            .where(Organization.owner_id == flask.g.user.id)
        )
    return (
        select(person_type_links.c.person_type_id.label("type_id"))
        .join(Person, Person.id == person_type_links.c.person_id)
        .where(Person.owner_id == flask.g.user.id)
    )


def type_json(kind: TypeModel, count: int) -> dict[str, Any]:
    out = {"id": kind.id, "name": kind.name, "description": kind.description, "count": count}
    if isinstance(kind, PersonRelationType):
        out["inverse"] = kind.inverse
    return out


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
    if isinstance(kind, PersonRelationType):
        kind.inverse = text(body, "inverse")


@bp.route("/api/<any('organization-types', 'person-types', 'relation-types', 'person-relation-types', 'person-organization-types', devices):what>", methods=["GET"])
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


@bp.route("/api/<any('organization-types', 'person-types', 'relation-types', 'person-relation-types', 'person-organization-types', devices):what>", methods=["POST"])
@auth.login_required
def api_types_add(what: str) -> tuple[flask.Response, int]:
    model = TYPES[what][0]
    kind = model(owner_id=flask.g.user.id)
    _apply_type(model, kind, json_body())
    flask.g.db.add(kind)
    flask.g.db.commit()
    return flask.jsonify(type_json(kind, 0)), 201


@bp.route("/api/<any('organization-types', 'person-types', 'relation-types', 'person-relation-types', 'person-organization-types', devices):what>/<int:row_id>", methods=["PUT"])
@auth.login_required
def api_types_update(what: str, row_id: int) -> flask.Response:
    model = TYPES[what][0]
    kind = _owned(model, row_id)
    _apply_type(model, kind, json_body())
    flask.g.db.commit()
    return flask.jsonify(type_json(kind, _type_uses(what, kind)))


@bp.route("/api/<any('organization-types', 'person-types', 'relation-types', 'person-relation-types', 'person-organization-types', devices):what>/<int:row_id>", methods=["DELETE"])
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
    return flask.jsonify({"id": image.id, "url": image_url(image.id)}), 201 if created else 200
