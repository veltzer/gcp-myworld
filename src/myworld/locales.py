"""
The languages (the locales table): the one list every account has, which
everyone sees and an admin keeps; what an account says in them is its own. A
language is known by its code, which what is said in it points at, so the
code never changes; the app's rows have a number, its place in the list.
"""

import hashlib
import html
import re
from typing import Any

import flask
from sqlalchemy import func, select

from myworld import auth, languages
from myworld.api import ApiError, json_body, require_edit_shared, text
from myworld.models import (
    DEFAULT_LOCALE,
    Locale,
    Owning,
    Person,
    PersonName,
    Read,
    User,
    Work,
    WorkTitle,
)

bp = flask.Blueprint("locales", __name__)

def _locale_uses(code: str, owner_id: int | None = None) -> int:
    """
    How much is said in a language, counting every column that points at
    locales.code: by the account owner_id, or by every account (what
    decides whether a language may go).
    """
    # each column, and how its row says whose it is
    uses = (
        (select(func.count()).select_from(Work).where(Work.title_locale == code), Work.owner_id),
        (select(func.count()).select_from(Work).where(Work.original_locale == code), Work.owner_id),
        (select(func.count()).select_from(WorkTitle).join(Work).where(WorkTitle.locale == code), Work.owner_id),
        (select(func.count()).select_from(Read).where(Read.locale == code), Read.owner_id),
        (select(func.count()).select_from(Owning).where(Owning.locale == code), Owning.owner_id),
        (select(func.count()).select_from(PersonName).join(Person).where(PersonName.locale == code), Person.owner_id),
        (select(func.count()).select_from(User).where(User.locale == code), User.id),
    )
    return sum(flask.g.db.scalar(query if owner_id is None else query.where(owner == owner_id)) or 0 for query, owner in uses)


def locale_json(locale: Locale) -> dict[str, Any]:
    return {
        "id": locale.position, "code": locale.code, "name": locale.name, "script": locale.script, "native": locale.native,
        # its picture: its own name in its own script, drawn (the address changes with what it shows)
        "image": f"/api/locales/{locale.position}/picture.svg?v={hashlib.sha256(_locale_picture(locale).encode()).hexdigest()[:12]}",
        # how much the signed-in account says in it: what the others say is theirs
        "description": f"{locale.code}, written in {locale.script} letters", "count": _locale_uses(locale.code, flask.g.user.id),
    }


def _locale(row_id: int) -> Locale:
    locale = flask.g.db.scalars(select(Locale).where(Locale.position == row_id)).first()
    if locale is None:
        raise ApiError(404, "no such language")
    return locale


def _admin_only() -> None:
    require_edit_shared("the languages are the same for every account")


def _apply_locale(locale: Locale, body: dict[str, Any]) -> None:
    name = text(body, "name", required=True)
    if flask.g.db.execute(select(Locale.code).where(Locale.name == name, Locale.code != locale.code)).first() is not None:
        raise ApiError(409, f"{name} is already one of the languages")
    script = text(body, "script", required=True).title()
    if script not in languages.scripts():
        raise ApiError(400, f"script: {script} is not a script letters are written in (Latin, Hebrew, Cyrillic, Arabic, Greek, ...)")
    native = text(body, "native")
    if languages.script_of(native) not in ("", script):
        raise ApiError(400, f"native: {native} is not written in {script} letters: it is what the language is called in itself")
    locale.name, locale.script, locale.native = name, script, native


# the ground of a language's picture: the same for every language, so the page is of one piece
PICTURE_GROUND = "#1d4ed8"


def _locale_picture(locale: Locale) -> str:
    """ The picture of a language, as SVG: what it is called in itself, in its own script, on the ground every language has. """
    shown = locale.native or locale.name
    size = max(34, min(96, 560 // max(len(shown), 1)))
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300" role="img">'
        f"<title>{html.escape(locale.name)}</title>"
        f'<rect width="400" height="300" fill="{PICTURE_GROUND}"/>'
        f'<text x="200" y="150" text-anchor="middle" dominant-baseline="central" fill="#fff" font-family="serif" font-size="{size}">{html.escape(shown)}</text>'
        f'<text x="200" y="270" text-anchor="middle" fill="#fff" fill-opacity="0.75" font-family="sans-serif" font-size="20">{html.escape(locale.script)}</text>'
        "</svg>"
    )


@bp.route("/api/locales/<int:row_id>/picture.svg", methods=["GET"])
@auth.login_required
def api_locale_picture(row_id: int) -> flask.Response:
    response = flask.Response(_locale_picture(_locale(row_id)), mimetype="image/svg+xml")
    # the address says what it shows (v), so it can be kept; a drawing runs nothing
    response.headers["Cache-Control"] = "private, max-age=31536000, immutable"
    response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    return response


@bp.route("/api/locales", methods=["GET"])
@auth.login_required
def api_locales() -> flask.Response:
    """ The languages, in the order the forms list them, each with how much is said in it. """
    return flask.jsonify([locale_json(locale) for locale in languages.known(flask.g.db).values()])


@bp.route("/api/locales", methods=["POST"])
@auth.login_required
def api_locales_add() -> tuple[flask.Response, int]:
    _admin_only()
    body = json_body()
    code = text(body, "code", required=True).lower()
    if not re.fullmatch(r"[a-z]{2,3}(-[a-z0-9]{2,6})?", code):
        raise ApiError(400, "code: a language code is two or three letters (he, en, yi), as ISO 639 names it")
    if flask.g.db.get(Locale, code) is not None:
        raise ApiError(409, f"{code} is already one of the languages")
    locale = Locale(code=code, position=(flask.g.db.scalar(select(func.max(Locale.position))) or 0) + 1)
    _apply_locale(locale, body)
    flask.g.db.add(locale)
    flask.g.db.commit()
    return flask.jsonify(locale_json(locale)), 201


@bp.route("/api/locales/<int:row_id>", methods=["PUT"])
@auth.login_required
def api_locales_update(row_id: int) -> flask.Response:
    _admin_only()
    locale = _locale(row_id)
    body = json_body()
    if text(body, "code").lower() not in ("", locale.code):
        raise ApiError(400, "code: the code of a language does not change: everything said in it points at it")
    _apply_locale(locale, body)
    flask.g.db.commit()
    return flask.jsonify(locale_json(locale))


@bp.route("/api/locales/<int:row_id>", methods=["DELETE"])
@auth.login_required
def api_locales_delete(row_id: int) -> flask.Response:
    """ Only a language nothing is said in, and never the one everything starts in. """
    _admin_only()
    locale = _locale(row_id)
    if locale.code == DEFAULT_LOCALE:
        raise ApiError(409, f"{locale.name} is the language everything starts in: it stays")
    used = _locale_uses(locale.code)
    if used:
        raise ApiError(409, f"{used} title{'s, names or readings are' if used > 1 else ', name or reading is'} in {locale.name}: change them first")
    flask.g.db.delete(locale)
    flask.g.db.commit()
    return flask.Response(status=204)
