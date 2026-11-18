"""
The languages (the locales table): the same for every account, as the works
are: everyone sees them, an admin keeps them. A language is known by its
code, which what is said in it points at, so the code never changes; the
app's rows have a number, its place in the list.
"""

import hashlib
import html
import re
from typing import Any

import flask
from sqlalchemy import func, select

from myworld import auth, languages
from myworld.api import ApiError, json_body, text
from myworld.models import (
    DEFAULT_LOCALE,
    ROLE_ADMIN,
    Locale,
    Owning,
    PersonName,
    Read,
    User,
    Work,
    WorkTitle,
)

bp = flask.Blueprint("locales", __name__)

# everything that says a language: the columns that point at locales.code
LOCALE_USES = (
    Work.title_locale, Work.original_locale, WorkTitle.locale, Read.locale, Owning.locale, PersonName.locale, User.locale,
)


def _locale_uses(code: str) -> int:
    return sum(flask.g.db.scalar(select(func.count()).where(column == code)) or 0 for column in LOCALE_USES)


def locale_json(locale: Locale) -> dict[str, Any]:
    return {
        "id": locale.position, "code": locale.code, "name": locale.name, "script": locale.script, "native": locale.native,
        # its picture: its own name in its own script, drawn (the address changes with what it shows)
        "image": f"/api/locales/{locale.position}/picture.svg?v={hashlib.sha256(_locale_picture(locale).encode()).hexdigest()[:12]}",
        "description": f"{locale.code}, written in {locale.script} letters", "count": _locale_uses(locale.code),
    }


def _locale(row_id: int) -> Locale:
    locale = flask.g.db.scalars(select(Locale).where(Locale.position == row_id)).first()
    if locale is None:
        raise ApiError(404, "no such language")
    return locale


def _admin_only() -> None:
    if flask.g.user.role != ROLE_ADMIN:
        raise ApiError(403, "the languages are the same for every account: only an admin changes them")


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


# the ground of a language's picture, by its script: languages of one script look alike
PICTURE_GROUNDS = ("#1d4ed8", "#b45309", "#047857", "#7c3aed", "#be123c", "#0e7490", "#4d7c0f", "#a21caf")


def _locale_picture(locale: Locale) -> str:
    """ The picture of a language, as SVG: what it is called in itself, in its own script, on the colour of that script. """
    shown = locale.native or locale.name
    ground = PICTURE_GROUNDS[int(hashlib.sha256(locale.script.encode()).hexdigest(), 16) % len(PICTURE_GROUNDS)]
    size = max(34, min(96, 560 // max(len(shown), 1)))
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 300" role="img">'
        f"<title>{html.escape(locale.name)}</title>"
        f'<rect width="400" height="300" fill="{ground}"/>'
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
