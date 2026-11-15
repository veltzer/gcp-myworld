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
from sqlalchemy.orm import selectinload

from myworld import auth, movies, world
from myworld.api import ApiError, json_body, opt_date, opt_int, text
from myworld.models import (
    DEFAULT_LOCALE,
    KINDS,
    LOCALES,
    RATING_MAX,
    RATING_MIN,
    STATUSES,
    Login,
    Person,
    PersonType,
    UserWork,
    Work,
    WorkTitle,
)

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
    work = entry.work
    return {
        "work_id": entry.work_id,
        "kind": work.kind,
        # the language the user read it in, and the title in it (the main title when it has none in it)
        "locale": entry.locale,
        "title": work.title_in(entry.locale),
        # the main title and its language, and the other titles, each in a language
        "main_title": work.title,
        "title_locale": work.title_locale,
        "titles": [{"locale": t.locale, "title": t.title} for t in work.titles],
        "creator": entry.work.creator,
        "year": entry.work.year,
        "imdb_id": entry.work.imdb_id,
        "tmdb_id": entry.work.tmdb_id,
        "rotten_tomatoes_id": entry.work.rotten_tomatoes_id,
        "goodreads_id": entry.work.goodreads_id,
        "isbn": entry.work.isbn,
        "openlibrary_id": entry.work.openlibrary_id,
        # who wrote it, as the user's people (the People view links to them), named in the language it was read in
        "authors": [{"id": p.id, "name": p.name_in(entry.locale)} for p in entry.authors],
        "simania_id": entry.work.simania_id,
        "image": world.image_url(entry.image_id),
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
    # the year it came out, on the shared work: only filled in, never changed
    year = opt_int(body, "year", -3000, 3000)
    if year is not None and entry.work.year is None:
        entry.work.year = year
    if "locale" in body:
        locale = text(body, "locale")
        if locale and locale not in LOCALES:
            raise ApiError(400, f"locale: unknown language {locale!r}")
        entry.locale = locale
    if "titles" in body:
        _add_titles(entry.work, body["titles"])
    # a cover is only ever replaced by a new upload, never blanked by omission
    image_id = world.owned_image(body)
    if image_id is not None:
        entry.image_id = image_id
    # the authors, ids of the user's people (any number), are set only when sent;
    # each is a Book Author, when the user keeps that profession
    if "authors" in body:
        entry.authors = world.owned_list(body, "authors", Person)
        # the shared work's author text, only filled in (another account may have it too)
        entry.work.creator = entry.work.creator or ", ".join(p.name for p in entry.authors)
        book_author = flask.g.db.scalars(select(PersonType).where(PersonType.owner_id == flask.g.user.id, PersonType.name == "Book Author")).first()
        for author in entry.authors if book_author else []:
            if book_author not in author.types:
                author.types.append(book_author)


def _add_titles(work: Work, value: Any) -> None:
    """ The titles sent, each in a language, added to the work's where it has none such; the work is shared, so none is taken away. """
    have = {(work.title_locale, work.title), *((t.locale, t.title) for t in work.titles)}
    for locale, title in world.localized("titles", value, "title", one_per_locale=False):
        if (locale, title) not in have:
            work.titles.append(WorkTitle(locale=locale, title=title))
            have.add((locale, title))


def _apply_work_ids(work: Work, body: dict[str, Any]) -> None:
    """ Catalog ids from the film search, filled in only where the work has none yet.

    A work is shared by every user who has it, so one user's request must not
    change the links every other user sees: an id once set is never replaced.
    """
    tmdb_id = opt_int(body, "tmdb_id", 1, 2**31 - 1)
    if tmdb_id is not None and work.tmdb_id is None:
        work.tmdb_id = tmdb_id
    for key in ("imdb_id", "rotten_tomatoes_id", "goodreads_id", "simania_id", "isbn", "openlibrary_id"):
        value = text(body, key)
        if value and not getattr(work, key):
            setattr(work, key, value)


def _own_entry(work_id: int) -> UserWork:
    entry = flask.g.db.get(UserWork, (flask.g.user.id, work_id))
    if entry is None:
        raise ApiError(404, "no such entry in your library")
    return entry


def _login_json(login: Login, current: Login, email: str) -> dict[str, Any]:
    """ One way of signing in, as the account panel shows it: the one in use first. """
    return {
        "method": login.method,
        "provider_id": login.provider_id,
        # what the provider reports, only when it is news: not the account's
        # email again, nor a password login's id (which is its email)
        "email": "" if login.email in (login.provider_id, email) else login.email,
        "last": login.last_login.date().isoformat() if login.last_login else "",
        "current": login.id == current.id,
        "verified": login.verified,
    }


def _account_json(login: Login) -> dict[str, Any]:
    """ Who is signed in, for the top bar and its account panel. """
    user = login.user
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "role": user.role,
        # the account panel: whether the email is proven theirs, since when, how this
        # session signed in, and every way they sign in
        "verified": user.verified,
        "since": user.created_at.date().isoformat(),
        "method": login.method,
        "logins": [_login_json(other, login, user.email) for other in sorted(user.logins, key=lambda o: (o.id != login.id, o.id))],
    }


@bp.route("/api/config", methods=["GET"])
def api_config() -> flask.Response:
    """ Everything the browser side needs to render: who is signed in and the vocabularies. """
    login = auth.current_login()
    return flask.jsonify({
        "google_client_id": auth.client_id(),
        "dev_login": auth.dev_login_enabled(),
        "password_min_length": auth.PASSWORD_MIN_LENGTH,
        # every provider the page knows about, so it can grey out the ones this server cannot offer
        "providers": {key: p.configured for key, p in auth.OAUTH_PROVIDERS.items()},
        "tmdb": movies.configured(),
        "kinds": {k: {"name": name, "plural": plural, "creator": creator} for k, (name, plural, creator) in KINDS.items()},
        "statuses": STATUSES,
        "locales": LOCALES,
        "rating_min": RATING_MIN,
        "rating_max": RATING_MAX,
        "user": None if login is None else _account_json(login),
    })


@bp.route("/api/library-entries", methods=["GET"])
@auth.login_required
def api_library_list() -> flask.Response:
    """ The signed-in user's entries, optionally only those of one kind. """
    query = select(UserWork).join(Work).where(UserWork.user_id == flask.g.user.id)
    kind = flask.request.args.get("kind")
    if kind is not None:
        query = query.where(Work.kind == _kind(kind))
    entries = flask.g.db.execute(query.options(
        selectinload(UserWork.authors).selectinload(Person.names), selectinload(UserWork.work).selectinload(Work.titles),
    ).order_by(UserWork.updated_at.desc())).scalars().all()
    return flask.jsonify([_entry_json(e) for e in entries])


@bp.route("/api/library-entries", methods=["POST"])
@auth.login_required
def api_library_add() -> tuple[flask.Response, int]:
    body = json_body()
    kind = _kind(text(body, "kind", required=True))
    title = text(body, "title", required=True)
    # a book's author text is its authors' names, as the import writes it ("Kernighan, Ritchie"), when none is sent
    creator = text(body, "creator") or ", ".join(p.name for p in world.owned_list(body, "authors", Person))
    # a year before the common era is negative (Plato's Republic, -375)
    year = opt_int(body, "year", -3000, 3000)
    db = flask.g.db
    work = db.execute(
        select(Work).where(Work.kind == kind, Work.title == title, Work.creator == creator, Work.year == year)
    ).scalar_one_or_none()
    if work is None:
        title_locale = text(body, "title_locale") or DEFAULT_LOCALE
        if title_locale not in LOCALES:
            raise ApiError(400, f"title_locale: unknown language {title_locale!r}")
        work = Work(kind=kind, title=title, creator=creator, year=year, title_locale=title_locale)
        db.add(work)
    _apply_work_ids(work, body)
    db.flush()
    entry = db.get(UserWork, (flask.g.user.id, work.id))
    created = entry is None
    if entry is None:
        entry = UserWork(user_id=flask.g.user.id, work_id=work.id, work=work)
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
    flask.g.db.flush()
    world.drop_unused_images()
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
