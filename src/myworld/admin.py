"""
What only an admin may do: run the checks over the whole database (see
checks.py), and see every account and give or take the admin
role. Regular accounts are users; an admin can make another account an
admin, and so delegate, or turn an admin back into a user, but the last
admin always stays one, so the site is never left without.
"""

from typing import Any

import flask
from sqlalchemy import func, select

from myworld import auth, checks
from myworld.api import ApiError, json_body
from myworld.models import ROLE_ADMIN, ROLES, User

bp = flask.Blueprint("admin", __name__)


def user_json(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "provider": user.provider,
        "role": user.role,
        "created_at": user.created_at.isoformat(timespec="seconds"),
    }


@bp.route("/api/users", methods=["GET"])
@auth.admin_required
def api_users() -> flask.Response:
    users = flask.g.db.execute(select(User).order_by(User.id)).scalars().all()
    return flask.jsonify([user_json(u) for u in users])


@bp.route("/api/users/<int:user_id>", methods=["PUT"])
@auth.admin_required
def api_user_update(user_id: int) -> flask.Response:
    user = flask.g.db.get(User, user_id)
    if user is None:
        raise ApiError(404, "no such account")
    role = json_body().get("role")
    if role not in ROLES:
        raise ApiError(400, f"role: one of {', '.join(ROLES)}")
    if user.role == ROLE_ADMIN and role != ROLE_ADMIN:
        admins = flask.g.db.scalar(select(func.count()).select_from(User).where(User.role == ROLE_ADMIN))
        if admins <= 1:
            raise ApiError(409, "this is the last admin: make another account an admin first")
    user.role = role
    flask.g.db.commit()
    return flask.jsonify(user_json(user))


@bp.route("/api/checks", methods=["GET"])
@auth.admin_required
def api_checks() -> flask.Response:
    """ The checks there are, to run one by one. """
    return flask.jsonify([
        {"name": c.name, "title": c.title, "description": c.description, "noun": c.noun}
        for c in checks.CHECKS.values()
    ])


@bp.route("/api/checks/<name>", methods=["GET"])
@auth.admin_required
def api_check_run(name: str) -> flask.Response:
    """ Run one check; it only reads, so this is a GET. """
    chosen = checks.CHECKS.get(name)
    if chosen is None:
        raise ApiError(404, f"no check called {name}")
    return flask.jsonify(checks.result_json(chosen, chosen.run(flask.g.db)))
