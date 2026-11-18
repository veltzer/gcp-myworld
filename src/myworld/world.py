"""
JSON API for what the signed-in user keeps: concerts, museums and their
visits, audio courses, YouTube videos, people, organizations, places, groups,
cities and countries. For each: what a row looks like as JSON, how a request
body is applied to it, and the routes that list, add, edit and delete it.
Every query is filtered by owner_id, so a user only ever sees, and only ever
links to, their own rows.
"""

import dataclasses
import datetime
import re
import zoneinfo
from collections.abc import Callable
from typing import Any

import flask
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from myworld import auth, languages, names
from myworld.api import (
    ApiError,
    coordinates,
    json_body,
    opt_int,
    owned,
    owned_list,
    owned_ref,
    text,
)
from myworld.models import (
    DEFAULT_LOCALE,
    RATING_MAX,
    RATING_MIN,
    YOUTUBE_ID_LENGTH,
    AudioCourse,
    City,
    CityPhoto,
    Concert,
    Country,
    Device,
    Group,
    Museum,
    MuseumVisit,
    Organization,
    OrganizationType,
    Person,
    PersonName,
    PersonOrganization,
    PersonOrganizationType,
    PersonPhoto,
    PersonRelation,
    PersonRelationType,
    PersonType,
    Place,
    Region,
    RelationType,
    YouTubeVideo,
    region_for,
)
from myworld.pictures import (
    apply_image,
    apply_picture,
    drop_unused_images,
    image_url,
    photo_json,
    photo_rows,
    picture_json,
    sent_photos,
)

bp = flask.Blueprint("world", __name__)


def date_json(row: Concert | MuseumVisit | AudioCourse | YouTubeVideo) -> dict[str, Any]:
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




def shown_name(person: Person) -> str:
    """ What a person is called to the signed-in account: their name in the language it prefers (Settings) when they have one in it, else their English name. """
    return person.name_in(flask.g.user.locale)


def _name(row: Any) -> str:
    """ What a row is called: a person as shown_name says, anything else by its name. """
    name: str = shown_name(row) if isinstance(row, Person) else row.name
    return name


def _names(people: list[Person]) -> list[str]:
    return sorted(shown_name(p) for p in people)


def _refs(rows: list[Person] | list[Organization] | list[PersonType] | list[RelationType] | list[Group] | list[Concert] | list[Place] | list[City] | list[Museum]) -> list[dict[str, Any]]:
    """ Names with the ids the People and Organizations views link to, each row once (a person may be linked to one organization twice). """
    unique = {row.id: row for row in rows}.values()
    return sorted(({"id": row.id, "name": _name(row)} for row in unique), key=lambda ref: ref["name"])


def concert_json(concert: Concert) -> dict[str, Any]:
    return {
        "id": concert.id,
        "name": concert.name,
        "performers": _refs(concert.performers),
        # the groups (bands) that performed
        "groups": _refs(concert.groups),
        "event": concert.event,
        "genre": concert.genre,
        **date_json(concert),
        "date_timezone": concert.date_timezone,
        # where it was, a row of the Places page
        "place": None if concert.place is None else _place_ref(concert.place),
        "tickets": concert.tickets,
        "broadcast": concert.broadcast,
        "alone": concert.alone,
        "review": concert.review,
        "remark": concert.remark,
        "with": _names(concert.people),
        "people": _refs(concert.people),
        **picture_json(concert),
    }


def country_ref(country: Country | None) -> dict[str, Any] | None:
    return None if country is None else {"id": country.id, "name": country.name}


def city_ref(city: City | None) -> dict[str, Any] | None:
    """ A city as other rows show it: its id, name, region and country; None for no city. """
    return None if city is None else {"id": city.id, "name": city.name, "region": city.region, "country": country_ref(city.country)}




def country_json(country: Country) -> dict[str, Any]:
    return {
        "id": country.id,
        "name": country.name,
        **picture_json(country),
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
    return {
        **(city_ref(city) or {}),
        # the photo its card shows, and all of its photos (that one first), each with its credit
        **picture_json(city),
        "photos": [photo_json(photo) for photo in ([city] if city.image_id is not None else []) + city.more_photos],
        "latitude": city.latitude,
        "longitude": city.longitude,
        "remark": city.remark,
        "places": _refs(city.places),
        "museums": _refs(city.museums),
        "organizations": _refs(city.organizations),
        "headquarters_of": _refs(city.headquarters_of),
    }


def place_json(place: Place) -> dict[str, Any]:
    # the concerts that were there, newest first
    concerts = _newest_first([{"id": c.id, "name": c.name, **date_json(c)} for c in place.concerts])
    return {
        **_place_ref(place),
        # the address in one line, and its parts (the city carries region and country)
        "address": place.address,
        **_address_parts(place),
        "latitude": place.latitude,
        "longitude": place.longitude,
        "website": place.website,
        "remark": place.remark,
        **picture_json(place),
        "concerts": [{"id": c["id"], "name": c["name"]} for c in concerts],
    }


def group_json(group: Group) -> dict[str, Any]:
    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "website": group.website,
        **picture_json(group),
        "members": _refs(group.members),
        # the concerts it performed at, newest first
        "concerts": [{"id": c["id"], "name": c["name"]} for c in _newest_first([{"id": c.id, "name": c.name, **date_json(c)} for c in group.concerts])],
    }


def _visit_json(visit: MuseumVisit) -> dict[str, Any]:
    return {
        "id": visit.id,
        **date_json(visit),
        "date_timezone": visit.date_timezone,
        "rating": visit.rating,
        "review": visit.review,
        "remark": visit.remark,
        "tickets": visit.tickets,
        "alone": visit.alone,
        "with": _names(visit.people),
        "people": _refs(visit.people),
    }


def museum_json(museum: Museum) -> dict[str, Any]:
    # the visits, the latest first (one with no date last)
    visits = sorted((_visit_json(visit) for visit in museum.visits), key=lambda visit: (visit["date_sort"], visit["id"]), reverse=True)
    rated = [visit["rating"] for visit in visits if visit["rating"] is not None]
    people = {person.id: person for visit in museum.visits for person in visit.people}
    return {
        "id": museum.id,
        "name": museum.name,
        "city": city_ref(museum.city),
        # the address in one line, and its parts (the city carries region and country)
        "address": museum.address,
        **_address_parts(museum),
        "latitude": museum.latitude,
        "longitude": museum.longitude,
        "url": museum.url,
        "image": image_url(museum.image_id),
        "visits": visits,
        # what its card, the sorting and the filters go by: when it was last visited, the rating
        # it was last given, and everyone the user ever went there with
        "date": visits[0]["date"] if visits else None,
        "date_precision": visits[0]["date_precision"] if visits else None,
        "date_sort": visits[0]["date_sort"] if visits else "",
        "rating": rated[0] if rated else None,
        "people": _refs(sorted(people.values(), key=lambda person: person.name)),
    }


def _stamp_json(stamp: datetime.datetime | None) -> str:
    return "" if stamp is None else stamp.replace(tzinfo=datetime.UTC).isoformat().replace("+00:00", "Z")


def audio_course_json(course: AudioCourse) -> dict[str, Any]:
    return {
        "id": course.id,
        "name": course.name,
        **date_json(course),
        "date_timezone": course.date_timezone,
        # finished when it has a date, in progress when it was only started
        "status": "done" if date_json(course)["date"] else ("in_progress" if course.started_utcz else ""),
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
        **date_json(video),
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
        # what they are shown by: their name in the language the account prefers, else the English one
        "name": shown_name(person),
        "english_name": person.name,
        # the account owner themselves
        "is_self": person.is_self,
        "honorific": person.honorific,
        "first_name": person.first_name,
        "middle_name": person.middle_name,
        "surname": person.surname,
        # their name in other languages ("he": "חיים שפירא"), each in its parts; the English one is the name parts above
        "names": [
            {"locale": n.locale, "name": n.name, "honorific": n.honorific, "first_name": n.first_name, "middle_name": n.middle_name, "surname": n.surname}
            for n in person.names
        ],
        # their photos, each with its credit: the first is the default, the one their card shows
        "image": image_url(person.photos[0].image_id) if person.photos else None,
        "photos": [photo_json(photo) for photo in person.photos],
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
    return {"type_id": type_id, "type": phrase, "person": {"id": other.id, "name": shown_name(other)}, "name": f"{phrase} {shown_name(other)}"}


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
            {"type_id": link.relation_type.id, "type": link.relation_type.name, "person": {"id": link.person.id, "name": shown_name(link.person)},
             "name": f"{shown_name(link.person)} ({link.relation_type.name})"}
            for link in sorted(organization.person_links, key=lambda link: (shown_name(link.person), link.relation_type.name))
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
    query = select(Museum).where(Museum.owner_id == flask.g.user.id).options(
        selectinload(Museum.visits).selectinload(MuseumVisit.people), selectinload(Museum.city).selectinload(City.country),
    )
    museums = flask.g.db.execute(query).scalars().all()
    return flask.jsonify(_newest_first([museum_json(m) for m in museums]))


@bp.route("/api/people", methods=["GET"])
@auth.login_required
def api_people() -> flask.Response:
    query = (
        select(Person)
        .where(Person.owner_id == flask.g.user.id)
        .options(
            selectinload(Person.organizations), selectinload(Person.types), selectinload(Person.names),
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


@bp.route("/api/regions", methods=["GET"])
@auth.login_required
def api_regions() -> flask.Response:
    """ The regions the user's cities say, each with its country and its cities: what the city form offers. """
    query = select(Region).where(Region.owner_id == flask.g.user.id).options(selectinload(Region.cities), selectinload(Region.country)).order_by(Region.name, Region.id)
    return flask.jsonify([
        {"id": region.id, "name": region.name, "country": country_ref(region.country), "cities": _refs(region.cities)}
        for region in flask.g.db.execute(query).scalars().all()
    ])


@bp.route("/api/countries", methods=["GET"])
@auth.login_required
def api_countries() -> flask.Response:
    query = select(Country).where(Country.owner_id == flask.g.user.id).options(selectinload(Country.cities)).order_by(Country.name)
    return flask.jsonify([country_json(c) for c in flask.g.db.execute(query).scalars().all()])




# ─── adding ──────────────────────────────────────────────────────────────────



def _apply_dates(row: Concert | MuseumVisit | AudioCourse | YouTubeVideo, body: dict[str, Any]) -> None:
    """
    The date as typed: YYYY, YYYY-MM or YYYY-MM-DD, stored at that precision,
    or nothing. date_timezone is where it happened (an IANA name). A date
    sent back exactly as the row shows it leaves it as it is, so a stored
    timestamp keeps its time.
    """
    value = text(body, "date")
    zone = text(body, "date_timezone")
    if zone:
        try:
            zoneinfo.ZoneInfo(zone)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError) as e:
            raise ApiError(400, f"date_timezone: unknown time zone {zone!r}") from e
    row.date_timezone = zone
    if value == (date_json(row)["date"] or ""):
        return
    utcz, ymd, my, y = None, None, "", None
    month = re.fullmatch(r"(\d{4})-(\d{2})", value)
    if re.fullmatch(r"\d{4}", value):
        y = int(value)
    elif month:
        if not 1 <= int(month.group(2)) <= 12:
            raise ApiError(400, "date: no such month")
        my = f"{month.group(2)}-{month.group(1)}"
    elif value:
        try:
            ymd = datetime.date.fromisoformat(value)
        except ValueError as e:
            raise ApiError(400, "date: expected YYYY, YYYY-MM or YYYY-MM-DD") from e
    row.date_utcz, row.date_ymd, row.date_my, row.date_y = utcz, ymd, my, y




def _owned_people(body: dict[str, Any]) -> list[Person]:
    return owned_list(body, "people", Person)












def _apply_concert(concert: Concert, body: dict[str, Any]) -> None:
    concert.name = text(body, "name", required=True)
    concert.performers = owned_list(body, "performers", Person)
    concert.groups = owned_list(body, "groups", Group)
    concert.event = text(body, "event")
    concert.genre = text(body, "genre")
    concert.place = owned_ref(body, "place_id", Place, "place")
    concert.tickets = opt_int(body, "tickets", 0, 1000)
    concert.broadcast = body.get("broadcast") is True
    concert.review = text(body, "review")
    concert.remark = text(body, "remark")
    # a photo is only ever replaced by a new upload, never blanked by omission
    apply_picture(concert, body)
    concert.people = _owned_people(body)
    concert.alone = body.get("alone") is True
    if concert.alone and concert.people:
        raise ApiError(400, "a concert gone to alone has no one in With")
    _apply_dates(concert, body)








def _apply_country(country: Country, body: dict[str, Any]) -> None:
    name = text(body, "name", required=True)
    clash = flask.g.db.execute(select(Country.id).where(Country.owner_id == flask.g.user.id, Country.name == name, Country.id != country.id)).first()
    if clash is not None:
        raise ApiError(409, f"{name} is already in Countries")
    country.name = name
    country.latitude, country.longitude = coordinates(body)
    country.remark = text(body, "remark")
    apply_picture(country, body)






def _apply_city(city: City, body: dict[str, Any]) -> None:
    name = text(body, "name", required=True)
    country = owned_ref(body, "country_id", Country, "country")
    # its region, by name: the row of that name in that country, made when a city first says it
    region = region_for(flask.g.db, flask.g.user.id, text(body, "region"), country)
    clash = flask.g.db.execute(
        select(City.id).where(
            City.owner_id == flask.g.user.id, City.name == name,
            City.region_id == region.id if region is not None and region.id is not None else City.region_id.is_(None),
            City.country_id == country.id if country else City.country_id.is_(None), City.id != city.id,
        )
    ).first()
    # (a region made just now has no city in it yet)
    if clash is not None and (region is None or region.id is not None):
        raise ApiError(409, f"{name}{', ' + country.name if country else ''} is already in Cities")
    city.name, city.region_row, city.country = name, region, country
    city.latitude, city.longitude = coordinates(body)
    city.remark = text(body, "remark")
    if "photos" in body:
        # all its photos, replacing those it had: the first is the one its card shows
        # (cities.image_id and its credit), the others follow it
        photos = sent_photos(body["photos"])
        city.image_id, (city.image_source, city.image_license, city.image_author) = photos[0] if photos else (None, ("", "", ""))
        city.more_photos = photo_rows(city.more_photos, CityPhoto, photos[1:])
    else:
        apply_picture(city, body)


def _apply_place(place: Place, body: dict[str, Any]) -> None:
    name = text(body, "name", required=True)
    city = owned_ref(body, "city_id", City, "city")
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
    apply_picture(place, body)


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
    apply_picture(group, body)


def _apply_visit(visit: MuseumVisit, body: dict[str, Any]) -> None:
    visit.rating = opt_int(body, "rating", RATING_MIN, RATING_MAX)
    visit.review = text(body, "review")
    visit.remark = text(body, "remark")
    visit.tickets = opt_int(body, "tickets", 0, 1000)
    visit.people = _owned_people(body)
    visit.alone = body.get("alone") is True
    if visit.alone and visit.people:
        raise ApiError(400, "a visit made alone has no one in With")
    _apply_dates(visit, body)


def _apply_museum(museum: Museum, body: dict[str, Any]) -> None:
    name = text(body, "name", required=True)
    city = owned_ref(body, "city_id", City, "city")
    clash = flask.g.db.execute(
        select(Museum.id).where(
            Museum.owner_id == flask.g.user.id, Museum.name == name, Museum.city_id == city.id if city else Museum.city_id.is_(None), Museum.id != museum.id,
        )
    ).first()
    if clash is not None:
        raise ApiError(409, f"{name}{', ' + city.name if city else ''} is already in Museums: add the visit to it")
    museum.name = name
    museum.city = city
    _apply_address(museum, body)
    museum.latitude, museum.longitude = coordinates(body)
    museum.url = text(body, "url")
    apply_image(museum, body)
    # visits, sent, are all the visits of the museum: one with the id of a visit it has is
    # that visit, changed; the others are new, and those it had that are not sent are gone.
    # Not sent, they stay
    if "visits" not in body:
        return
    sent = body["visits"]
    if not isinstance(sent, list) or not all(isinstance(item, dict) for item in sent):
        raise ApiError(400, "visits: expected a list of visits")
    had = {visit.id: visit for visit in museum.visits}
    visits = []
    for item in sent:
        visit_id = item.get("id")
        if visit_id is not None and (visit_id not in had or visit_id in {visit.id for visit in visits}):
            raise ApiError(400, "visits: unknown visit")
        visit = had[visit_id] if visit_id is not None else MuseumVisit()
        _apply_visit(visit, item)
        visits.append(visit)
    museum.visits = visits


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


def _apply_audio_course(course: AudioCourse, body: dict[str, Any]) -> None:
    course.name = text(body, "name", required=True)
    course.lecturers = owned_list(body, "lecturers", Person)
    course.rating = opt_int(body, "rating", RATING_MIN, RATING_MAX)
    course.review = text(body, "review")
    course.device = owned_ref(body, "device_id", Device, "device")
    course.listened_at = text(body, "listened_at")
    course.started_utcz = _stamp(body, "started", course.started_utcz)
    course.ended_utcz = _stamp(body, "ended", course.ended_utcz)
    course.progress = text(body, "progress")
    course.great_courses_id = opt_int(body, "great_courses_id", 1, 2**31 - 1)
    course.great_courses_slug = text(body, "great_courses_slug")
    course.audible_asin = text(body, "audible_asin")
    course.link = text(body, "link")
    if course.link and not course.link.startswith(("https://", "http://")):
        raise ApiError(400, "link: expected an http(s) URL")
    apply_image(course, body)
    _apply_dates(course, body)


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


def _apply_youtube_video(video: YouTubeVideo, body: dict[str, Any]) -> None:
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
    video.device = owned_ref(body, "device_id", Device, "device")
    video.watched_at = text(body, "watched_at")
    _apply_dates(video, body)


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
    if "names" in body:
        _apply_person_names(person, body["names"])
    if "photos" in body:
        # all their photos, replacing those they had, in this order: the first is the default
        person.photos = photo_rows(person.photos, PersonPhoto, sent_photos(body["photos"]))
        for position, photo in enumerate(person.photos):
            photo.position = position
    if "relations" in body:
        person.relations = _person_relations(person, body["relations"])


def localized(key: str, value: Any, field: str, one_per_locale: bool) -> list[tuple[str, str]]:
    """
    [{"locale", field}, ...] as (locale, text) pairs, each once: a language
    of the locales table and a text not empty, written in that language's
    script; one_per_locale refuses two in one language.
    """
    locales = languages.known(flask.g.db)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ApiError(400, f"{key}: expected a list of {{locale, {field}}}")
    out: dict[tuple[str, str], None] = {}
    for item in value:
        locale, words = item.get("locale"), item.get(field)
        if locale not in locales:
            raise ApiError(400, f"{key}: unknown language {locale!r}")
        if not isinstance(words, str) or not words.strip():
            raise ApiError(400, f"{key}: a {field} is needed in {locales[locale].name}")
        if not languages.fits(locales[locale], words):
            raise ApiError(400, f"{key}: {words.strip()!r} is not written in {locales[locale].name}: choose the language it is in")
        out[locale, " ".join(words.split())] = None
    pairs = list(out)
    if one_per_locale and len({locale for locale, _ in pairs}) != len(pairs):
        raise ApiError(400, f"{key}: one {field} per language")
    return pairs


NAME_PARTS = ("honorific", "first_name", "middle_name", "surname")


def _apply_person_names(person: Person, value: Any) -> None:
    """
    A person's names in other languages than English, replacing those they
    had (a row kept per language, renamed in place): [{locale, honorific,
    first_name, middle_name, surname}, ...], one per language, each part
    written in that language; or {locale, name}, the whole name, which is
    split into its parts.
    """
    locales = languages.known(flask.g.db)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ApiError(400, "names: expected a list of {locale, honorific, first_name, middle_name, surname}")
    kept = {n.locale: n for n in person.names}
    rows: dict[str, PersonName] = {}
    for item in value:
        locale = item.get("locale")
        if locale not in locales:
            raise ApiError(400, f"names: unknown language {locale!r}")
        if locale == DEFAULT_LOCALE:
            raise ApiError(400, "names: the English name is the person's own name parts")
        if locale in rows:
            raise ApiError(400, "names: one name per language")
        row = kept.get(locale) or PersonName(locale=locale, name="")
        if any(part in item for part in NAME_PARTS):
            honorific, first, middle, surname = (" ".join(text(item, part).split()) for part in NAME_PARTS)
            for key, part in (("honorific", honorific), ("first_name", first), ("surname", surname)):
                if names.has_space(part):
                    raise ApiError(400, f"names: {key}: one word, without spaces (more names go in the middle name)")
            row.set_parts(honorific, first, middle, surname)
        else:
            row.set_whole(text(item, "name"))
        if not row.name:
            raise ApiError(400, f"names: a name is needed in {locales[locale].name}")
        # each part by itself: a surname in other letters does not hide behind the rest
        strange = next((part for part in (row.honorific, row.first_name, row.middle_name, row.surname) if not languages.fits(locales[locale], part)), None)
        if strange is not None:
            raise ApiError(400, f"names: {strange!r} is not written in {locales[locale].name}: choose the language it is in")
        rows[locale] = row
    person.names = list(rows.values())




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
    organization.type = owned_ref(body, "type_id", OrganizationType, "type")
    # looked up before anything is set on a new organization, which is not in the session yet
    relations = owned_list(body, "relation_ids", RelationType)
    organization.relations = relations
    organization.status = text(body, "status")
    organization.website = text(body, "website")
    organization.location = text(body, "location")
    organization.city = owned_ref(body, "city_id", City, "city")
    organization.headquarters = owned_ref(body, "headquarters_id", City, "city")
    _apply_address(organization, body)
    organization.latitude, organization.longitude = coordinates(body)
    organization.what_happened = text(body, "what_happened")
    organization.remark = text(body, "remark")
    apply_image(organization, body)


# ─── the routes that add, edit and delete ───────────────────────────────────

@dataclasses.dataclass(frozen=True)
class _View:
    """ What the routes below need of a view: its rows, how a request body is applied to one, and what one looks like as JSON. """
    model: type[Any]
    apply: Callable[[Any, dict[str, Any]], None]
    json: Callable[[Any], dict[str, Any]]


# the path of a view (/api/<path>) -> the view
VIEWS: dict[str, _View] = {
    "concert-visits": _View(Concert, _apply_concert, concert_json),
    # a museum, with its visits
    "museum-visits": _View(Museum, _apply_museum, museum_json),
    "audio-courses": _View(AudioCourse, _apply_audio_course, audio_course_json),
    "youtube-videos": _View(YouTubeVideo, _apply_youtube_video, youtube_video_json),
    "people": _View(Person, _apply_person, person_json),
    "organizations": _View(Organization, _apply_organization, organization_json),
    "places": _View(Place, _apply_place, place_json),
    "groups": _View(Group, _apply_group, group_json),
    "cities": _View(City, _apply_city, city_json),
    "countries": _View(Country, _apply_country, country_json),
}
def drop_unused_regions() -> None:
    """ A region no city says any more (its last city moved, or was deleted) goes too. """
    used = select(City.region_id).where(City.region_id.is_not(None))
    for region in flask.g.db.scalars(select(Region).where(Region.owner_id == flask.g.user.id, Region.id.not_in(used))):
        flask.g.db.delete(region)


# the paths, as the part of a route that takes any of them
WHAT = f"<any({', '.join(repr(path) for path in VIEWS)}):what>"


@bp.route(f"/api/{WHAT}", methods=["POST"])
@auth.login_required
def api_world_add(what: str) -> tuple[flask.Response, int]:
    view = VIEWS[what]
    row = view.model(owner_id=flask.g.user.id)
    view.apply(row, json_body())
    flask.g.db.add(row)
    flask.g.db.commit()
    return flask.jsonify(view.json(row)), 201


@bp.route(f"/api/{WHAT}/<int:row_id>", methods=["PUT"])
@auth.login_required
def api_world_update(what: str, row_id: int) -> flask.Response:
    view = VIEWS[what]
    row = owned(view.model, row_id)
    view.apply(row, json_body())
    # a picture taken away or replaced goes, with its image; so does a region no city says any more
    flask.g.db.flush()
    drop_unused_images()
    drop_unused_regions()
    flask.g.db.commit()
    return flask.jsonify(view.json(row))


@bp.route(f"/api/{WHAT}/<int:row_id>", methods=["DELETE"])
@auth.login_required
def api_world_delete(what: str, row_id: int) -> flask.Response:
    # the ORM also removes the row's links (to people, to organizations, to concerts and museums);
    # the concerts at a deleted place are kept, with no place
    flask.g.db.delete(owned(VIEWS[what].model, row_id))
    flask.g.db.flush()
    drop_unused_images()
    drop_unused_regions()
    flask.g.db.commit()
    return flask.Response(status=204)
