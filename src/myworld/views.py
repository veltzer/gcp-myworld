"""
Pages (static HTML, the browser side is static/app.js) and the JSON API
it talks to.
"""

import datetime
import os
from typing import Any

import flask
import werkzeug
from sqlalchemy import select

from myworld import auth
from myworld.models import KINDS, RATING_MAX, RATING_MIN, STATUSES, UserWork, Work

bp = flask.Blueprint("views", __name__)

HTML_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "html")


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@bp.errorhandler(ApiError)
def handle_api_error(error: ApiError) -> tuple[flask.Response, int]:
    return flask.jsonify({"error": error.message}), error.status


# ─── pages ───────────────────────────────────────────────────────────────────

@bp.route("/", methods=["GET"])
def index() -> werkzeug.Response:
    if auth.current_user() is not None:
        return flask.redirect(flask.url_for("views.library"))
    return flask.send_from_directory(HTML_DIR, "index.html")


@bp.route("/library", methods=["GET"])
def library() -> werkzeug.Response:
    if auth.current_user() is None:
        return flask.redirect(flask.url_for("views.index"))
    return flask.send_from_directory(HTML_DIR, "library.html")


@bp.route("/app/version", methods=["GET"])
def version() -> flask.Response:
    info = dict(flask.current_app.config["build_info"])
    # Cloud Run injects the serving revision name at runtime.
    info["revision"] = os.environ.get("K_REVISION", "local")
    return flask.jsonify(info)


@bp.route("/app/health", methods=["GET"])
def health() -> flask.Response:
    flask.g.db.execute(select(1))
    return flask.jsonify({"status": "ok"})


# ─── api ─────────────────────────────────────────────────────────────────────

def _entry_json(entry: UserWork) -> dict[str, Any]:
    return {
        "work_id": entry.work_id,
        "kind": entry.work.kind,
        "title": entry.work.title,
        "creator": entry.work.creator,
        "year": entry.work.year,
        "status": entry.status,
        "rating": entry.rating,
        "started_on": entry.started_on.isoformat() if entry.started_on else None,
        "finished_on": entry.finished_on.isoformat() if entry.finished_on else None,
        "notes": entry.notes,
        "updated_at": entry.updated_at.isoformat(),
    }


def _json_body() -> dict[str, Any]:
    body = flask.request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ApiError(400, "expected a JSON object")
    return body


def _text(body: dict[str, Any], key: str, required: bool = False) -> str:
    value = body.get(key)
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ApiError(400, f"{key}: expected a string")
    value = value.strip()
    if required and not value:
        raise ApiError(400, f"{key}: required")
    return value


def _int(body: dict[str, Any], key: str, low: int, high: int) -> int | None:
    value = body.get(key)
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise ApiError(400, f"{key}: expected a number")
    try:
        number = int(value)
    except ValueError as e:
        raise ApiError(400, f"{key}: expected a number") from e
    if number < low or number > high:
        raise ApiError(400, f"{key}: must be between {low} and {high}")
    return number


def _date(body: dict[str, Any], key: str) -> datetime.date | None:
    value = _text(body, key)
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as e:
        raise ApiError(400, f"{key}: expected a date as YYYY-MM-DD") from e


def _kind(value: str) -> str:
    if value not in KINDS:
        raise ApiError(400, f"kind: unknown kind {value!r}")
    return value


def _apply_entry_fields(entry: UserWork, body: dict[str, Any]) -> None:
    status = _text(body, "status") or "done"
    if status not in STATUSES:
        raise ApiError(400, f"status: unknown status {status!r}")
    entry.status = status
    entry.rating = _int(body, "rating", RATING_MIN, RATING_MAX)
    entry.started_on = _date(body, "started_on")
    entry.finished_on = _date(body, "finished_on")
    entry.notes = _text(body, "notes")


def _own_entry(work_id: int) -> UserWork:
    entry = flask.g.db.get(UserWork, (flask.g.user.id, work_id))
    if entry is None:
        raise ApiError(404, "no such entry in your library")
    return entry


@bp.route("/api/config", methods=["GET"])
def api_config() -> flask.Response:
    """ Everything the browser side needs to render: who is signed in and the vocabularies. """
    user = auth.current_user()
    return flask.jsonify({
        "google_client_id": auth.client_id(),
        "dev_login": auth.dev_login_enabled(),
        "password_min_length": auth.PASSWORD_MIN_LENGTH,
        # every provider the page knows about, so it can grey out the ones this server cannot offer
        "providers": {key: p.configured for key, p in auth.OAUTH_PROVIDERS.items()},
        "kinds": {k: {"name": name, "plural": plural, "creator": creator} for k, (name, plural, creator) in KINDS.items()},
        "statuses": STATUSES,
        "rating_min": RATING_MIN,
        "rating_max": RATING_MAX,
        "user": None if user is None else {"email": user.email, "name": user.name, "picture": user.picture},
    })


@bp.route("/api/library", methods=["GET"])
@auth.login_required
def api_library_list() -> flask.Response:
    """ The signed-in user's entries, optionally only those of one kind. """
    query = select(UserWork).join(Work).where(UserWork.user_id == flask.g.user.id)
    kind = flask.request.args.get("kind")
    if kind is not None:
        query = query.where(Work.kind == _kind(kind))
    entries = flask.g.db.execute(query.order_by(UserWork.updated_at.desc())).scalars().all()
    return flask.jsonify([_entry_json(e) for e in entries])


@bp.route("/api/library", methods=["POST"])
@auth.login_required
def api_library_add() -> tuple[flask.Response, int]:
    body = _json_body()
    kind = _kind(_text(body, "kind", required=True))
    title = _text(body, "title", required=True)
    creator = _text(body, "creator")
    year = _int(body, "year", 0, 3000)
    db = flask.g.db
    work = db.execute(
        select(Work).where(Work.kind == kind, Work.title == title, Work.creator == creator, Work.year == year)
    ).scalar_one_or_none()
    if work is None:
        work = Work(kind=kind, title=title, creator=creator, year=year)
        db.add(work)
        db.flush()
    entry = db.get(UserWork, (flask.g.user.id, work.id))
    created = entry is None
    if entry is None:
        entry = UserWork(user_id=flask.g.user.id, work_id=work.id)
        db.add(entry)
    _apply_entry_fields(entry, body)
    db.commit()
    return flask.jsonify(_entry_json(entry)), 201 if created else 200


@bp.route("/api/library/<int:work_id>", methods=["PUT"])
@auth.login_required
def api_library_update(work_id: int) -> flask.Response:
    entry = _own_entry(work_id)
    _apply_entry_fields(entry, _json_body())
    flask.g.db.commit()
    return flask.jsonify(_entry_json(entry))


@bp.route("/api/library/<int:work_id>", methods=["DELETE"])
@auth.login_required
def api_library_delete(work_id: int) -> flask.Response:
    entry = _own_entry(work_id)
    flask.g.db.delete(entry)
    flask.g.db.commit()
    return flask.Response(status=204)
