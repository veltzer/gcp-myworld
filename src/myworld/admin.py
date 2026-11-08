"""
What only an admin may do: see every account and give or take the admin
role. Regular accounts are users; an admin can make another account an
admin, and so delegate, or turn an admin back into a user, but the last
admin always stays one, so the site is never left without.
"""

from typing import Any

import flask
from sqlalchemy import func, select

from myworld import auth
from myworld.api import ApiError, json_body
from myworld.models import ROLE_ADMIN, ROLES, User

bp = flask.Blueprint("admin", __name__)


def _provider(user: User) -> str:
    """ How the account signs in, from its subject (see User.google_sub). """
    prefix, colon, _ = user.google_sub.partition(":")
    return prefix if colon else "google"


def user_json(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "provider": _provider(user),
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
