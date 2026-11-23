"""
The user's Goodreads shelves, for the importers that read them. Goodreads
has had no API since 2020, and a profile that is not public shows its
shelves to no one signed out; what it does give each user is an RSS feed of
their shelves, at an address with a key of their own in it (My Books, the
RSS link at the bottom). The user pastes that address once on the Imports
page (/goodreads/connect): it is tried, and its key kept
(models.GoodreadsConnection), sealed with a key derived from SECRET_KEY, so
the database alone does not give it away. /goodreads/disconnect forgets it
(the key stays good at Goodreads: nothing there revokes it but a new one).

A shelf is read a page at a time (shelf_books), each book as the feed says
it (Book): its Goodreads id, title, author, ISBN, year, cover and the day
it was put on the shelf.
"""

import base64
import dataclasses
import datetime
import email.utils
import hashlib
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any

import flask
import requests
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from myworld import auth, podcasts
from myworld.api import ApiError, json_body, text
from myworld.models import GoodreadsConnection, User, utcnow

bp = flask.Blueprint("goodreads", __name__, url_prefix="/goodreads")

FEED = "https://www.goodreads.com/review/list_rss/{user}"
# what a pasted address has to be: a shelf feed, with its key
FEED_ADDRESS = re.compile(r"https?://(?:www\.)?goodreads\.com/review/list_rss/(\d+)(?:[-\w]*)?(?:\?.*)?$")
HTTP_TIMEOUT = 30
# Goodreads gives a feed's books 100 at a time; a shelf of more than this many pages is not read past them
MAX_PAGES = 100
USER_AGENT = "MyWorld/1.0 (+https://myworld.stream)"
# the cover Goodreads gives a book that has none
NO_COVER = "nophoto"


class GoodreadsError(Exception):
    """ Goodreads did not answer usefully, or the connection is gone. """


@dataclasses.dataclass(frozen=True)
class Book:
    goodreads_id: str
    title: str
    author: str
    isbn: str
    year: int | None
    image_url: str
    added: datetime.date | None


# ─── the kept key ───────────────────────────────────────────────────────────

def _fernet() -> Fernet:
    secret = flask.current_app.config["SECRET_KEY"] if flask.has_app_context() else os.environ.get("SECRET_KEY", "")
    if not secret:
        raise GoodreadsError("SECRET_KEY is not set: no key to seal the Goodreads connection with")
    digest = hashlib.sha256(b"myworld goodreads connection\0" + secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def seal(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def unseal(sealed: str) -> str:
    try:
        return _fernet().decrypt(sealed.encode()).decode()
    except InvalidToken as e:
        # SECRET_KEY changed since it was kept
        raise GoodreadsError("the Goodreads connection can no longer be read: connect Goodreads again") from e


def connection(session: Session, owner: User) -> GoodreadsConnection | None:
    return session.get(GoodreadsConnection, owner.id)


def parse_address(address: str) -> tuple[str, str]:
    """ The user's Goodreads number and their feeds' key, from a shelf's RSS address; GoodreadsError when it is not one. """
    address = address.strip()
    found = FEED_ADDRESS.match(address)
    key = urllib.parse.parse_qs(urllib.parse.urlsplit(address).query).get("key", [""])[0]
    if found is None or not key:
        raise GoodreadsError(
            "that is not a Goodreads shelf's RSS address: on goodreads.com open My Books, and copy the RSS link at the bottom"
            " (https://www.goodreads.com/review/list_rss/<number>?key=...)",
        )
    return found.group(1), key


# ─── reading a shelf (the tests replace fetch) ──────────────────────────────

def fetch(url: str, params: dict[str, str]) -> bytes:
    """ One page of a feed. """
    try:
        response = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT)
    except requests.RequestException as e:
        raise GoodreadsError(f"Goodreads could not be reached: {e}") from e
    if response.status_code == 404:
        raise GoodreadsError("Goodreads does not know that feed (404): copy the RSS link from My Books again")
    if not response.ok:
        raise GoodreadsError(f"Goodreads answered {response.status_code}")
    return response.content


def _text(item: ET.Element, tag: str) -> str:
    return " ".join((item.findtext(tag) or "").split())


def _year(value: str) -> int | None:
    return int(value) if re.fullmatch(r"-?\d{1,4}", value) and value not in ("0", "-0") else None


def _day(value: str) -> datetime.date | None:
    """ An RSS date ("Wed, 12 Mar 2019 04:05:06 -0700") as the day it was where it was said; None when it is not one. """
    try:
        return email.utils.parsedate_to_datetime(value).date() if value else None
    except (TypeError, ValueError):
        return None


def parse_page(data: bytes) -> list[Book]:
    """ The books of one page of a shelf feed; GoodreadsError when it is not a feed (a sign-in page, say). """
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise GoodreadsError("Goodreads did not answer with a feed: is the RSS link right?") from e
    books = []
    for item in root.iterfind("./channel/item"):
        image = _text(item, "book_large_image_url") or _text(item, "book_image_url")
        books.append(Book(
            goodreads_id=_text(item, "book_id"),
            title=_text(item, "title"),
            author=_text(item, "author_name"),
            isbn=_text(item, "isbn")[:20],
            year=_year(_text(item, "book_published")),
            image_url="" if NO_COVER in image else image,
            added=_day(_text(item, "user_date_added")),
        ))
    return [book for book in books if book.goodreads_id and book.title]


def shelf_books(user: str, key: str, shelf: str) -> list[Book]:
    """ Every book of one of the user's shelves, page after page, each once, in the feed's order. """
    found: dict[str, Book] = {}
    for page in range(1, MAX_PAGES + 1):
        books = parse_page(fetch(FEED.format(user=user), {"key": key, "shelf": shelf, "page": str(page)}))
        new = [book for book in books if book.goodreads_id not in found]
        if not new:
            break
        for book in new:
            found[book.goodreads_id] = book
    return list(found.values())


def fetch_cover(url: str) -> tuple[bytes, str] | None:
    """ A book's cover and its type; None when there is none to be had (as a podcast's: podcasts.fetch_cover). """
    return podcasts.fetch_cover(url)


def kept_feed(session: Session, owner: User) -> tuple[str, str]:
    """ owner's Goodreads number and feeds' key; GoodreadsError when they have not connected Goodreads. """
    kept = connection(session, owner)
    if kept is None:
        raise GoodreadsError("Goodreads is not connected: connect it first")
    return kept.user_id, unseal(kept.feed_key)


# ─── connecting ─────────────────────────────────────────────────────────────

def status_json(session: Session, owner: User) -> dict[str, Any]:
    """ What the Imports page shows of the connection. """
    kept = connection(session, owner)
    return {
        "connected": kept is not None,
        "user_id": kept.user_id if kept else "",
        "connected_at": kept.connected_at.isoformat() if kept else None,
    }


@bp.route("/connect", methods=["POST"])
@auth.login_required
def connect() -> flask.Response:
    """ {"address": a shelf's RSS address}: tried (the first page of to-read), and its key kept. """
    try:
        user, key = parse_address(text(json_body(), "address", required=True))
        parse_page(fetch(FEED.format(user=user), {"key": key, "shelf": "to-read", "page": "1"}))
    except GoodreadsError as e:
        raise ApiError(400, str(e)) from e
    db = flask.g.db
    kept = connection(db, flask.g.user)
    if kept is None:
        kept = GoodreadsConnection(owner_id=flask.g.user.id)
        db.add(kept)
    kept.user_id = user
    kept.feed_key = seal(key)
    kept.connected_at = utcnow()
    db.commit()
    return flask.jsonify(status_json(db, flask.g.user))


@bp.route("/disconnect", methods=["POST"])
@auth.login_required
def disconnect() -> tuple[str, int]:
    db = flask.g.db
    kept = connection(db, flask.g.user)
    if kept is not None:
        db.delete(kept)
        db.commit()
    return "", 204


@bp.route("/status", methods=["GET"])
@auth.login_required
def status() -> flask.Response:
    return flask.jsonify(status_json(flask.g.db, flask.g.user))
