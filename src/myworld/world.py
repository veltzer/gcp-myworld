"""
Read-only JSON API for the concerts, museum visits and people of the
signed-in user, and the images they point at. Every query is filtered by
owner_id, so a user only ever sees their own rows.
"""

import datetime
from typing import Any

import flask
import werkzeug
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from myworld import auth
from myworld.models import Concert, Image, Museum, Person

bp = flask.Blueprint("world", __name__)

# images never change once imported (a new photo is a new row), so browsers may keep them
IMAGE_MAX_AGE = 7 * 24 * 3600


def _date_json(row: Concert | Museum) -> dict[str, Any]:
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


def _people_refs(people: list[Person]) -> list[dict[str, Any]]:
    """ Who was there, with the ids the People view links to. """
    return [{"id": p.id, "name": p.name} for p in sorted(people, key=lambda p: p.name)]


def concert_json(concert: Concert) -> dict[str, Any]:
    return {
        "id": concert.id,
        "name": concert.name,
        "performers": concert.performers,
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
        "people": _people_refs(concert.people),
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
        "rating": museum.rating,
        "review": museum.review,
        "remark": museum.remark,
        "url": museum.url,
        "tickets": museum.tickets,
        "with": _names(museum.people),
        "people": _people_refs(museum.people),
        "image": _image_url(museum.image_id),
    }


def person_json(person: Person) -> dict[str, Any]:
    return {
        "id": person.id,
        "name": person.name,
        "company": person.company,
        "description": person.description,
        "concerts": [{"id": c.id, "name": c.name, **_date_json(c)} for c in person.concerts],
        "museums": [{"id": m.id, "name": m.name, **_date_json(m)} for m in person.museums],
    }


def _newest_first(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: (item["date_sort"], item["name"]), reverse=True)


@bp.route("/api/concerts", methods=["GET"])
@auth.login_required
def api_concerts() -> flask.Response:
    query = select(Concert).where(Concert.owner_id == flask.g.user.id).options(selectinload(Concert.people))
    concerts = flask.g.db.execute(query).scalars().all()
    return flask.jsonify(_newest_first([concert_json(c) for c in concerts]))


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
        .options(selectinload(Person.concerts), selectinload(Person.museums))
        .order_by(Person.name)
    )
    people = flask.g.db.execute(query).scalars().all()
    return flask.jsonify([person_json(p) for p in people])


@bp.route("/api/images/<int:image_id>", methods=["GET"])
@auth.login_required
def api_image(image_id: int) -> werkzeug.Response:
    image = flask.g.db.get(Image, image_id)
    if image is None or image.owner_id != flask.g.user.id:
        return flask.Response(status=404)
    response = flask.Response(image.data, mimetype=image.content_type)
    response.headers["Cache-Control"] = f"private, max-age={IMAGE_MAX_AGE}"
    response.set_etag(image.sha256)
    return response.make_conditional(flask.request)
