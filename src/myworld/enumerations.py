"""
The small lists a user keeps: the types of organizations and of people, the
kinds of relation, and the devices. Each is a name and a description, used
by some rows, and is only deleted when nothing uses it.
"""

from typing import Any

import flask
from sqlalchemy import func, select

from myworld import auth
from myworld.api import ApiError, json_body, owned, text
from myworld.models import (
    AudioBookListen,
    AudioCourse,
    Device,
    EpisodeHeard,
    Organization,
    OrganizationType,
    Person,
    PersonOrganization,
    PersonOrganizationType,
    PersonRelation,
    PersonRelationType,
    PersonType,
    RelationType,
    YouTubeVideo,
    organization_relation_types,
    person_type_links,
)
from myworld.pictures import apply_picture, picture_json

bp = flask.Blueprint("enumerations", __name__)

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
        # audio courses, audio book listens, episodes heard and YouTube videos point to a device
        return select(AudioCourse.device_id.label("type_id")).where(AudioCourse.owner_id == flask.g.user.id).union_all(
            select(AudioBookListen.device_id.label("type_id")).where(AudioBookListen.owner_id == flask.g.user.id),
            select(EpisodeHeard.device_id.label("type_id")).where(EpisodeHeard.owner_id == flask.g.user.id),
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
    if isinstance(kind, (Device, PersonType)):
        out.update(picture_json(kind))
    return out


def _type_uses(what: str, kind: TypeModel) -> int:
    links = _type_links(what).subquery()
    return flask.g.db.scalar(select(func.count()).select_from(links).where(links.c.type_id == kind.id)) or 0


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
    if isinstance(kind, (Device, PersonType)):
        apply_picture(kind, body)


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
    kind = owned(model, row_id)
    _apply_type(model, kind, json_body())
    flask.g.db.commit()
    return flask.jsonify(type_json(kind, _type_uses(what, kind)))


@bp.route("/api/<any('organization-types', 'person-types', 'relation-types', 'person-relation-types', 'person-organization-types', devices):what>/<int:row_id>", methods=["DELETE"])
@auth.login_required
def api_types_delete(what: str, row_id: int) -> flask.Response:
    """ Only a type nothing is: a row never silently loses its type. """
    model, noun = TYPES[what]
    kind = owned(model, row_id)
    used = _type_uses(what, kind)
    if used:
        raise ApiError(409, f"{used} {noun}{'s are' if used > 1 else ' is'} {kind.name}: change them first")
    flask.g.db.delete(kind)
    flask.g.db.commit()
    return flask.Response(status=204)
