"""
Pages (static HTML, the browser side is static/app.js and static/js/) and the JSON API
it talks to.
"""

import os
import re
from typing import Any

import flask
import requests
import werkzeug
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from myworld import auth, languages, movies, pictures, world
from myworld.api import ApiError, json_body, opt_date, opt_int, owned_list, text
from myworld.models import (
    DEFAULT_LOCALE,
    KINDS,
    RATING_MAX,
    RATING_MIN,
    ROLE_ADMIN,
    STATUSES,
    THEMES,
    USERNAME_MAX,
    USERNAME_MIN,
    USERNAME_PATTERN,
    USERNAMES_RESERVED,
    Login,
    Person,
    PersonType,
    Read,
    User,
    UserWork,
    Work,
    WorkTitle,
)

bp = flask.Blueprint("views", __name__)

HTML_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "html")


# ─── pages ───────────────────────────────────────────────────────────────────

def _page(name: str) -> werkzeug.Response:
    """
    A page of html/, which the browser asks for again every time: its
    scripts are no-cache, so a page kept from before a deploy would run the
    new scripts against the old markup (a form they look for not there).
    """
    response = flask.send_from_directory(HTML_DIR, name)
    response.headers["Cache-Control"] = "no-cache"
    return response


@bp.route("/", methods=["GET"])
def index() -> werkzeug.Response:
    if auth.current_user() is not None:
        return flask.redirect(flask.url_for("views.library"))
    # a shared link's card needs absolute URLs: this site as the visitor reached it
    # (behind Cloud Run's proxy the scheme is in X-Forwarded-Proto)
    scheme = flask.request.headers.get("X-Forwarded-Proto", flask.request.scheme).split(",")[0].strip()
    origin = f"{scheme}://{flask.request.host}"
    with open(os.path.join(HTML_DIR, "index.html"), encoding="utf-8") as f:
        page = f.read().replace("__ORIGIN__", origin)
    return flask.Response(page, mimetype="text/html", headers={"Cache-Control": "no-cache"})


@bp.route("/library", methods=["GET"])
def library() -> werkzeug.Response:
    if auth.current_user() is None:
        return flask.redirect(flask.url_for("views.index"))
    return _page("library.html")


@bp.route("/verify", methods=["GET"])
def verify() -> werkzeug.Response:
    """ Where the mailed link leads: choose the password of an email login (the token is read by app.js). """
    return _page("verify.html")


@bp.route("/privacy", methods=["GET"])
def privacy() -> werkzeug.Response:
    """ The privacy policy: what is kept and what is done with it (the OAuth consent screen links to it). """
    return _page("privacy.html")


@bp.route("/about", methods=["GET"])
def about() -> werkzeug.Response:
    """ What My World is, who wrote it, and the build serving: the commit, when it was built and deployed (app/version). """
    return _page("about.html")


@bp.route("/app/version", methods=["GET"])
def version() -> flask.Response:
    """ The build serving: deploy_date and git_describe (the deploy stamp), built_at, started_at and revision. """
    info = dict(flask.current_app.config["build_info"])
    # Cloud Run injects the serving revision name at runtime.
    info["revision"] = os.environ.get("K_REVISION", "local")
    info["started_at"] = flask.current_app.config["started_at"]
    return flask.jsonify(info)


@bp.route("/app/health", methods=["GET"])
def health() -> flask.Response:
    flask.g.db.execute(select(1))
    return flask.jsonify({"status": "ok"})


# ─── api ─────────────────────────────────────────────────────────────────────

def _entry_json(entry: UserWork) -> dict[str, Any]:
    work = entry.work
    # shown in the language the user prefers (Settings) when the work has a title in it, else in its main title's;
    # its authors, as people are everywhere, by their names in the language preferred
    preferred = entry.user.locale
    shown = work.locale_for(preferred)
    return {
        "work_id": entry.work_id,
        "kind": work.kind,
        # the title it is shown by, and the language the user read it in (last, see UserWork.last_read)
        "title": work.title_in(shown),
        "locale": entry.locale or "",
        # the main title and its language, and the other titles, each in a language
        "main_title": work.title,
        "title_locale": work.title_locale,
        "titles": [{"locale": t.locale, "title": t.title} for t in work.titles],
        "creator": entry.work.creator,
        "year": entry.work.year,
        # the language it was first written in, "" while not known
        "original_locale": work.original_locale or "",
        "imdb_id": entry.work.imdb_id,
        "tmdb_id": entry.work.tmdb_id,
        "rotten_tomatoes_id": entry.work.rotten_tomatoes_id,
        "goodreads_id": entry.work.goodreads_id,
        "isbn": entry.work.isbn,
        "openlibrary_id": entry.work.openlibrary_id,
        # who wrote it, as the user's people (the People view links to them), named in the language it was read in
        "authors": [{"id": p.id, "name": p.name_in(preferred)} for p in entry.authors],
        "simania_id": entry.work.simania_id,
        # the cover its card shows, and all of its covers (that one first)
        "image": pictures.image_url(entry.image_id),
        "covers": [{"id": image_id, "image": pictures.image_url(image_id)} for image_id in entry.cover_ids],
        "status": entry.status,
        "rating": entry.rating,
        "started_on": entry.started_on.isoformat() if entry.started_on else None,
        "finished_on": entry.finished_on.isoformat() if entry.finished_on else None,
        # every time it was read: the day and the language, either empty when not known
        "reads": [_read_json(read) for read in entry.reads],
        # the languages the user owns it in
        "owned": entry.owned,
        # true when the user says they own no copy of it (then owned is empty)
        # what the user thought of it, and anything else they keep about it
        "review": entry.review,
        "notes": entry.notes,
        "updated_at": entry.updated_at.isoformat(),
    }


def _kind(value: str) -> str:
    if value not in KINDS:
        raise ApiError(400, f"kind: unknown kind {value!r}")
    return value


def _read_locale(key: str, value: Any) -> str | None:
    """ A language sent for a read: one of the locales table, or none when empty. """
    if value is None or value == "":
        return None
    if value not in languages.known(flask.g.db):
        raise ApiError(400, f"{key}: unknown language {value!r}")
    return str(value)


def _read_json(read: Read) -> dict[str, Any]:
    return {
        "date": read.read_on.isoformat() if read.read_on else None,
        "locale": read.locale or "",
        "status": read.status,
        "rating": read.rating,
        "review": read.review,
        "started_on": read.started_on.isoformat() if read.started_on else None,
    }


def _status(body: dict[str, Any]) -> str:
    status = text(body, "status") or "done"
    if status not in STATUSES:
        raise ApiError(400, f"status: unknown status {status!r}")
    return status


# what a reading says besides its day and its language, as an entry edited without its reads sends it
READ_FIELDS = ("finished_on", "locale", "status", "rating", "review", "started_on")


def _apply_reads(entry: UserWork, body: dict[str, Any], new: bool = False) -> None:
    """
    The readings of the entry. `reads`, a list of {date, locale, status,
    rating, review, started_on} (any may be empty; no status is done),
    replaces them all. Without it, `finished_on`, `locale`, `status`,
    `rating`, `review` and `started_on` (each only when sent) are those of the
    reading the entry goes by, which is made when the entry has none: a new
    entry always has one, as that is where its status is.
    """
    if "reads" in body:
        value = body["reads"]
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise ApiError(400, "reads: expected a list of {date, locale, status, rating, review, started_on}")
        entry.reads = [_read_fields(Read(review=""), {**dict.fromkeys(READ_FIELDS), **item, "finished_on": item.get("date")}, "reads") for item in value]
        return
    if not new and not any(key in body for key in READ_FIELDS):
        return
    read = entry.last_read
    if read is None:
        read = Read(status="done", review="")
        entry.reads.append(read)
    _read_fields(read, body, "locale")


def _read_fields(read: Read, body: dict[str, Any], locale_key: str) -> Read:
    """ The fields of a reading that body has, set on it (locale_key names the language in an error). """
    if "finished_on" in body:
        read.read_on = opt_date(body, "finished_on")
    if "locale" in body:
        read.locale = _read_locale(locale_key, body["locale"])
    if "status" in body:
        read.status = _status(body)
    if "rating" in body:
        read.rating = opt_int(body, "rating", RATING_MIN, RATING_MAX)
    if "review" in body:
        read.review = text(body, "review")
    if "started_on" in body:
        read.started_on = opt_date(body, "started_on")
    return read


def _set_year(work: Work, year: int) -> None:
    """ The year a work came out, changed: no other work may be the same one by then. """
    clash = flask.g.db.execute(
        select(Work.id).where(Work.owner_id == work.owner_id, Work.kind == work.kind, Work.title == work.title, Work.creator == work.creator, Work.year == year, Work.id != work.id)
    ).first()
    if clash is not None:
        raise ApiError(409, f"year: there is already another {KINDS[work.kind][0].lower()} called {work.title} of the same {KINDS[work.kind][2].lower()} and year")
    work.year = year


def _apply_entry_fields(entry: UserWork, body: dict[str, Any], new: bool = False) -> None:
    # where the user is with it, their rating and review are those of its readings (_apply_reads)
    if "notes" in body or new:
        entry.notes = text(body, "notes")
    _apply_work_facts(entry.work, body)
    _apply_reads(entry, body, new)
    _apply_owned(entry, body)
    # an entry edited with its title sent says all the titles of its work; with only titles sent they are added
    if "title" in body and not new:
        _set_titles(entry.work, body)
    elif "titles" in body:
        _add_titles(entry.work, body["titles"])
    _apply_covers(entry, body)
    if "authors" in body:
        _apply_authors(entry, body)


def _apply_work_facts(work: Work, body: dict[str, Any]) -> None:
    """ What an entry says of its work: filled in or put right when sent, never emptied. """
    # the year it came out
    year = opt_int(body, "year", -3000, 3000)
    if year is not None and year != work.year:
        _set_year(work, year)
    # the language it was first written in
    original = text(body, "original_locale")
    if original:
        if original not in languages.known(flask.g.db):
            raise ApiError(400, f"original_locale: unknown language {original!r}")
        work.original_locale = original


def _apply_owned(entry: UserWork, body: dict[str, Any]) -> None:
    """ The languages the user owns it in; with none, they own no copy. """
    # owned, a list of languages, is every language the user owns it in; not sent, they stay
    if "owned" in body:
        owned = body["owned"]
        if not isinstance(owned, list) or not all(isinstance(locale, str) for locale in owned):
            raise ApiError(400, "owned: expected a list of languages")
        unknown = [locale for locale in owned if locale not in languages.known(flask.g.db)]
        if unknown:
            raise ApiError(400, f"owned: unknown language {unknown[0]!r}")
        entry.owned = owned


def _apply_covers(entry: UserWork, body: dict[str, Any]) -> None:
    """
    covers, a list of image ids, are all the entry's covers (the first is the
    one its card shows); without it image_id is a new first cover, and a
    cover is never blanked by omission.
    """
    if "covers" in body:
        if not isinstance(body["covers"], list):
            raise ApiError(400, "covers: expected a list of image ids")
        entry.cover_ids = pictures.owned_images("covers", body["covers"])
        return
    image_id = pictures.owned_image(body)
    if image_id is not None:
        entry.image_id = image_id


def _apply_authors(entry: UserWork, body: dict[str, Any]) -> None:
    """ The authors, ids of the user's people (any number); each is a Book Author, when the user keeps that profession. """
    entry.authors = owned_list(body, "authors", Person)
    # the work's author text, only filled in
    entry.work.creator = entry.work.creator or ", ".join(p.name for p in entry.authors)
    book_author = flask.g.db.scalars(select(PersonType).where(PersonType.owner_id == flask.g.user.id, PersonType.name == "Book Author")).first()
    for author in entry.authors if book_author else []:
        if book_author not in author.types:
            author.types.append(book_author)


def _add_titles(work: Work, value: Any) -> None:
    """
    The titles sent, one per language, added to the work's in the languages
    it has none in. None is taken away or changed here (the dialog, which
    sends them all, does that: _set_titles): a different title in a language
    it has one in is refused.
    """
    have = {work.title_locale: work.title, **{t.locale: t.title for t in work.titles}}
    for locale, title in world.localized("titles", value, "title", one_per_locale=True):
        if locale not in have:
            work.titles.append(WorkTitle(locale=locale, title=title))
            have[locale] = title
        elif have[locale] != title:
            name = languages.known(flask.g.db)[locale].name
            raise ApiError(400, f"titles: the book already has a title in {name} ({have[locale]}): one title per language")


def _set_titles(work: Work, body: dict[str, Any]) -> None:
    """
    All the titles of a work, as the dialog sends them: title and
    title_locale are the one it is known by, titles the others, one per
    language. A title not sent is taken away, and one sent in a language it
    has a title in replaces it.
    """
    locales = languages.known(flask.g.db)
    title = " ".join(text(body, "title", required=True).split())
    locale = text(body, "title_locale") or languages.locale_of(locales, title) or DEFAULT_LOCALE
    if locale not in locales:
        raise ApiError(400, f"title_locale: unknown language {locale!r}")
    if not languages.fits(locales[locale], title):
        raise ApiError(400, f"title_locale: the title is not written in {locales[locale].name}: choose the language it is in")
    others = dict(world.localized("titles", body.get("titles", []), "title", one_per_locale=True))
    if locale in others:
        raise ApiError(400, f"titles: two titles in {locales[locale].name}: one title per language")
    if title != work.title:
        clash = flask.g.db.execute(
            select(Work.id).where(Work.owner_id == work.owner_id, Work.kind == work.kind, Work.title == title, Work.creator == work.creator, Work.year == work.year, Work.id != work.id)
        ).first()
        if clash is not None:
            raise ApiError(409, f"{title} is already the title of another {KINDS[work.kind][0].lower()} of the same {KINDS[work.kind][2].lower()} and year")
    work.title, work.title_locale = title, locale
    kept = {row.locale: row for row in work.titles}
    rows = []
    for other_locale, other in others.items():
        row = kept.get(other_locale) or WorkTitle(locale=other_locale, title=other)
        row.title = other
        rows.append(row)
    work.titles = rows


def _apply_work_ids(work: Work, body: dict[str, Any]) -> None:
    """ Catalog ids from the film search, filled in only where the work has none yet.

    An id once set is never replaced.
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
        # email again, nor an email or dev login's id (which is its email)
        "email": "" if login.email in (login.provider_id, email) else login.email,
        "last": login.last_login.date().isoformat() if login.last_login else "",
        "current": login.id == current.id,
    }


def _account_json(login: Login) -> dict[str, Any]:
    """ Who is signed in, for the top bar and its account panel. """
    user = login.user
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        # the name the account is known by; None until chosen, and the app asks for it first
        "username": user.username,
        "picture": user.picture,
        "role": user.role,
        # the language they prefer (Settings): what a book with several titles is shown by
        "locale": user.locale,
        # how the pages look (Settings): "system", "light" or "dark"
        "theme": user.theme,
        # an admin's lock on the shared data (Settings): whether they may change it by hand now
        "edit_shared": user.edit_shared,
        # the account panel: since when, how this session signed in, and every way they sign in
        "since": user.created_at.date().isoformat(),
        "method": login.method,
        "logins": [_login_json(other, login, user.email) for other in sorted(user.logins, key=lambda o: (o.id != login.id, o.id))],
    }


# the longest name a person may choose (also the Settings dialog's maxlength)
NAME_MAX_LENGTH = 60


@bp.route("/api/account/name", methods=["PUT"])
@auth.login_required
def api_account_name() -> flask.Response:
    """ The signed-in person chooses what they are called, whichever way they sign in. """
    name = " ".join(text(json_body(), "name").split())
    if not name or len(name) > NAME_MAX_LENGTH or not name.isprintable():
        raise ApiError(400, f"A name is 1 to {NAME_MAX_LENGTH} printable characters.")
    login = auth.current_login()
    assert login is not None
    login.user.name = name
    flask.g.db.commit()
    return flask.jsonify(_account_json(login))


@bp.route("/api/account/username", methods=["PUT"])
@auth.login_required
def api_account_username() -> flask.Response:
    """
    The signed-in person chooses their username: 3 to 30 lowercase letters,
    digits, ".", "-" and "_", starting with a letter (taken as typed, in
    lowercase); one account's alone (409 when another has it), and none of
    the names that would read as the site's own.
    """
    username = text(json_body(), "username").lower()
    if not re.fullmatch(USERNAME_PATTERN, username):
        raise ApiError(400, f"A username is {USERNAME_MIN} to {USERNAME_MAX} letters, digits, dots, dashes or underscores, starting with a letter.")
    if username in USERNAMES_RESERVED:
        raise ApiError(400, f"{username} is kept for the site: choose another")
    login = auth.current_login()
    assert login is not None
    taken = flask.g.db.scalars(select(User.id).where(User.username == username, User.id != login.user.id)).first()
    if taken is not None:
        raise ApiError(409, f"{username} is taken: choose another")
    login.user.username = username
    flask.g.db.commit()
    return flask.jsonify(_account_json(login))


@bp.route("/api/account/locale", methods=["PUT"])
@auth.login_required
def api_account_locale() -> flask.Response:
    """ The signed-in person chooses the language they prefer: a book with titles in several languages is shown by the one in it. """
    locale = text(json_body(), "locale")
    if locale not in languages.known(flask.g.db):
        raise ApiError(400, f"locale: unknown language {locale!r}")
    login = auth.current_login()
    assert login is not None
    login.user.locale = locale
    flask.g.db.commit()
    return flask.jsonify(_account_json(login))


@bp.route("/api/account/theme", methods=["PUT"])
@auth.login_required
def api_account_theme() -> flask.Response:
    """ The signed-in person chooses how the pages look: light, dark, or as their device does ("system"). """
    theme = text(json_body(), "theme")
    if theme not in THEMES:
        raise ApiError(400, f"theme: one of {', '.join(THEMES)}")
    login = auth.current_login()
    assert login is not None
    login.user.theme = theme
    flask.g.db.commit()
    return flask.jsonify(_account_json(login))


@bp.route("/api/account/edit-shared", methods=["PUT"])
@auth.login_required
def api_account_edit_shared() -> flask.Response:
    """
    An admin turns their lock on the shared data off ({"edit_shared": true}:
    they may change it by hand) or on again. It starts on, so shared data is
    not changed by accident; a regular user never may change it.
    """
    value = json_body().get("edit_shared")
    if not isinstance(value, bool):
        raise ApiError(400, "edit_shared: expected true or false")
    login = auth.current_login()
    assert login is not None
    if login.user.role != ROLE_ADMIN:
        raise ApiError(403, "only an admin may change the shared data")
    login.user.edit_shared = value
    flask.g.db.commit()
    return flask.jsonify(_account_json(login))


@bp.route("/api/config", methods=["GET"])
def api_config() -> flask.Response:
    """ Everything the browser side needs to render: who is signed in and the vocabularies. """
    login = auth.current_login()
    return flask.jsonify({**vocabularies(), "user": None if login is None else _account_json(login)})


def vocabularies() -> dict[str, Any]:
    """ What the page needs to render anyone's data: the kinds, statuses, languages, limits (a view's page too). """
    locales = languages.known(flask.g.db)
    return {
        "google_client_id": auth.client_id(),
        "dev_login": auth.dev_login_enabled(),
        "password_min_length": auth.PASSWORD_MIN_LENGTH,
        # every provider the page knows about, so it can grey out the ones this server cannot offer
        "providers": {key: p.configured for key, p in auth.OAUTH_PROVIDERS.items()},
        "tmdb": movies.configured(),
        "kinds": {k: {"name": name, "plural": plural, "creator": creator} for k, (name, plural, creator) in KINDS.items()},
        "statuses": STATUSES,
        # the languages (the locales table), and the script of each: the forms pick the language of what is typed by it
        "locales": {code: locale.name for code, locale in locales.items()},
        "locale_scripts": {code: locale.script for code, locale in locales.items()},
        "rating_min": RATING_MIN,
        "rating_max": RATING_MAX,
        "name_max_length": NAME_MAX_LENGTH,
    }


@bp.route("/api/library-entries", methods=["GET"])
@auth.login_required
def api_library_list() -> flask.Response:
    """ The signed-in user's entries, optionally only those of one kind. """
    query = select(UserWork).join(Work).where(UserWork.owner_id == flask.g.user.id)
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
    creator = text(body, "creator") or ", ".join(p.name for p in owned_list(body, "authors", Person))
    # a year before the common era is negative (Plato's Republic, -375)
    year = opt_int(body, "year", -3000, 3000)
    db = flask.g.db
    work = db.execute(
        select(Work).where(Work.owner_id == flask.g.user.id, Work.kind == kind, Work.title == title, Work.creator == creator, Work.year == year)
    ).scalar_one_or_none()
    if work is None:
        # the language sent, else the one the title's letters say, else English
        locales = languages.known(db)
        title_locale = text(body, "title_locale") or languages.locale_of(locales, title) or DEFAULT_LOCALE
        if title_locale not in locales:
            raise ApiError(400, f"title_locale: unknown language {title_locale!r}")
        if not languages.fits(locales[title_locale], title):
            raise ApiError(400, f"title_locale: the title is not written in {locales[title_locale].name}: choose the language it is in")
        work = Work(owner_id=flask.g.user.id, kind=kind, title=title, creator=creator, year=year, title_locale=title_locale)
        db.add(work)
    _apply_work_ids(work, body)
    db.flush()
    entry = db.get(UserWork, (flask.g.user.id, work.id))
    created = entry is None
    if entry is None:
        entry = UserWork(owner_id=flask.g.user.id, work_id=work.id, work=work)
        db.add(entry)
    _apply_entry_fields(entry, body, new=True)
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
    work = entry.work
    flask.g.db.delete(entry)
    flask.g.db.flush()
    # the work is the account's own, and it has it no more
    flask.g.db.delete(work)
    flask.g.db.flush()
    pictures.drop_unused_images()
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
