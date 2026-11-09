"""
Pages (static HTML, the browser side is static/app.js) and the JSON API
it talks to.
"""

import os
from typing import Any

import flask
import requests
import werkzeug
from sqlalchemy import select

from myworld import auth, movies
from myworld.api import ApiError, json_body, opt_date, opt_int, text
from myworld.models import KINDS, RATING_MAX, RATING_MIN, STATUSES, UserWork, Work

bp = flask.Blueprint("views", __name__)

HTML_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "html")


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
        "imdb_id": entry.work.imdb_id,
        "tmdb_id": entry.work.tmdb_id,
        "rotten_tomatoes_id": entry.work.rotten_tomatoes_id,
        "status": entry.status,
        "rating": entry.rating,
        "started_on": entry.started_on.isoformat() if entry.started_on else None,
        "finished_on": entry.finished_on.isoformat() if entry.finished_on else None,
        "notes": entry.notes,
        "updated_at": entry.updated_at.isoformat(),
    }


def _kind(value: str) -> str:
    if value not in KINDS:
        raise ApiError(400, f"kind: unknown kind {value!r}")
    return value


def _apply_entry_fields(entry: UserWork, body: dict[str, Any]) -> None:
    status = text(body, "status") or "done"
    if status not in STATUSES:
        raise ApiError(400, f"status: unknown status {status!r}")
    entry.status = status
    entry.rating = opt_int(body, "rating", RATING_MIN, RATING_MAX)
    entry.started_on = opt_date(body, "started_on")
    entry.finished_on = opt_date(body, "finished_on")
    entry.notes = text(body, "notes")


def _apply_work_ids(work: Work, body: dict[str, Any]) -> None:
    """ Catalog ids from the film search; only ever filled in, never blanked. """
    imdb_id = text(body, "imdb_id")
    if imdb_id:
        work.imdb_id = imdb_id
    tmdb_id = opt_int(body, "tmdb_id", 1, 2**31 - 1)
    if tmdb_id is not None:
        work.tmdb_id = tmdb_id
    rotten_tomatoes_id = text(body, "rotten_tomatoes_id")
    if rotten_tomatoes_id:
        work.rotten_tomatoes_id = rotten_tomatoes_id


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
        "tmdb": movies.configured(),
        "kinds": {k: {"name": name, "plural": plural, "creator": creator} for k, (name, plural, creator) in KINDS.items()},
        "statuses": STATUSES,
        "rating_min": RATING_MIN,
        "rating_max": RATING_MAX,
        "user": None if user is None else {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "picture": user.picture,
            "role": user.role,
            # how they signed in, and who that provider says they are: the account menu
            "provider": user.provider,
            "provider_id": user.provider_id,
        },
    })


@bp.route("/api/library-entries", methods=["GET"])
@auth.login_required
def api_library_list() -> flask.Response:
    """ The signed-in user's entries, optionally only those of one kind. """
    query = select(UserWork).join(Work).where(UserWork.user_id == flask.g.user.id)
    kind = flask.request.args.get("kind")
    if kind is not None:
        query = query.where(Work.kind == _kind(kind))
    entries = flask.g.db.execute(query.order_by(UserWork.updated_at.desc())).scalars().all()
    return flask.jsonify([_entry_json(e) for e in entries])


@bp.route("/api/library-entries", methods=["POST"])
@auth.login_required
def api_library_add() -> tuple[flask.Response, int]:
    body = json_body()
    kind = _kind(text(body, "kind", required=True))
    title = text(body, "title", required=True)
    creator = text(body, "creator")
    year = opt_int(body, "year", 0, 3000)
    db = flask.g.db
    work = db.execute(
        select(Work).where(Work.kind == kind, Work.title == title, Work.creator == creator, Work.year == year)
    ).scalar_one_or_none()
    if work is None:
        work = Work(kind=kind, title=title, creator=creator, year=year)
        db.add(work)
    _apply_work_ids(work, body)
    db.flush()
    entry = db.get(UserWork, (flask.g.user.id, work.id))
    created = entry is None
    if entry is None:
        entry = UserWork(user_id=flask.g.user.id, work_id=work.id)
        db.add(entry)
    _apply_entry_fields(entry, body)
    db.commit()
    return flask.jsonify(_entry_json(entry)), 201 if created else 200


@bp.route("/api/library-entries/<int:work_id>", methods=["PUT"])
@auth.login_required
def api_library_update(work_id: int) -> flask.Response:
    entry = _own_entry(work_id)
    _apply_entry_fields(entry, json_body())
    flask.g.db.commit()
    return flask.jsonify(_entry_json(entry))


@bp.route("/api/library-entries/<int:work_id>", methods=["DELETE"])
@auth.login_required
def api_library_delete(work_id: int) -> flask.Response:
    entry = _own_entry(work_id)
    flask.g.db.delete(entry)
    flask.g.db.commit()
    return flask.Response(status=204)


# ─── film lookups ────────────────────────────────────────────────────────────

def _movies_available() -> None:
    if not movies.configured():
        raise ApiError(503, "film lookups are not configured on this server (TMDB_API_KEY)")


@bp.route("/api/movies/search", methods=["GET"])
@auth.login_required
def api_movies_search() -> flask.Response:
    """ Candidate films on The Movie Database for a title. """
    _movies_available()
    query = flask.request.args.get("q", "").strip()
    if not query:
        raise ApiError(400, "q: required")
    try:
        return flask.jsonify(movies.search(query))
    except (movies.MovieLookupError, requests.RequestException, KeyError, ValueError) as e:
        raise ApiError(502, "The Movie Database did not answer, try again") from e


@bp.route("/api/movies/<int:tmdb_id>", methods=["GET"])
@auth.login_required
def api_movies_details(tmdb_id: int) -> flask.Response:
    """ One film, normalised for the add form: title, director, year and its catalog ids. """
    _movies_available()
    try:
        return flask.jsonify(movies.details(tmdb_id))
    except (movies.MovieLookupError, requests.RequestException, KeyError, ValueError) as e:
        raise ApiError(502, "The Movie Database did not answer, try again") from e
