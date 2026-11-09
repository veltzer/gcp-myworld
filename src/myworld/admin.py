"""
What only an admin may do: run the checks over the whole database (see
checks.py), see the structure of the database as the database itself
reports it, and see every account and give or take the admin
role. Regular accounts are users; an admin can make another account an
admin, and so delegate, or turn an admin back into a user, but the last
admin always stays one, so the site is never left without.
"""

from typing import Any

import flask
import sqlalchemy
from sqlalchemy import func, select

from myworld import auth, checks
from myworld.api import ApiError, json_body
from myworld.models import ROLE_ADMIN, ROLES, Base, User

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


# ─── the structure of the database ──────────────────────────────────────────

def _column_json(column: dict[str, Any], primary: list[str]) -> dict[str, Any]:
    default = column.get("default")
    return {
        "name": column["name"],
        "type": str(column["type"]),
        "nullable": bool(column["nullable"]),
        "default": "" if default is None else str(default),
        "primary_key": column["name"] in primary,
    }


def table_json(inspector: Any, name: str, rows: int) -> dict[str, Any]:
    """ One table as the database reports it, and how it differs from the model the code has. """
    primary = inspector.get_pk_constraint(name).get("constrained_columns") or []
    columns = [_column_json(c, primary) for c in inspector.get_columns(name)]
    model = Base.metadata.tables.get(name)
    in_model: set[str] = set() if model is None else {str(c.name) for c in model.columns}
    in_database: set[str] = {str(c["name"]) for c in columns}
    return {
        "name": name,
        "rows": rows,
        "columns": columns,
        "foreign_keys": [
            {
                "name": fk.get("name") or "",
                "columns": fk["constrained_columns"],
                "table": fk["referred_table"],
                "referred": fk["referred_columns"],
                "on_delete": (fk.get("options") or {}).get("ondelete") or "",
            }
            for fk in inspector.get_foreign_keys(name)
        ],
        "indexes": [
            {"name": ix["name"] or "", "columns": [c for c in ix["column_names"] if c], "unique": bool(ix["unique"])}
            for ix in inspector.get_indexes(name)
        ],
        "unique": [{"name": u.get("name") or "", "columns": u["column_names"]} for u in inspector.get_unique_constraints(name)],
        "checks": [{"name": c.get("name") or "", "sql": c["sqltext"]} for c in inspector.get_check_constraints(name)],
        # drift: what a migration has not caught up with (or left behind)
        "in_model": model is not None,
        "only_in_database": sorted(in_database - in_model) if model is not None else [],
        "only_in_model": sorted(in_model - in_database),
    }


@bp.route("/api/schema", methods=["GET"])
@auth.admin_required
def api_schema() -> flask.Response:
    """ Every table, read from the database's own catalog (SQLAlchemy's inspector), with its row count. """
    db = flask.g.db
    engine = db.get_bind()
    inspector = sqlalchemy.inspect(engine)
    names = sorted(inspector.get_table_names())
    tables = [
        table_json(inspector, name, db.scalar(select(func.count()).select_from(sqlalchemy.table(name))) or 0)
        for name in names
    ]
    return flask.jsonify({
        "dialect": engine.dialect.name,
        "server_version": ".".join(str(part) for part in engine.dialect.server_version_info or ()),
        "tables": tables,
        # tables the code has that the database does not: create_all makes them at the next start
        "missing": sorted(set(Base.metadata.tables) - set(names)),
    })
