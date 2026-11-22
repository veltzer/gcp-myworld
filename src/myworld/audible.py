"""
The user's Audible library: connecting My World to it, and reading it.

Audible has no public API. Its apps use one of their own, and this is a
small client of it, written for My World: Amazon's sign-in for a device
(OAuth 2.0 with PKCE), registering My World as a device of the account, and
reading the library, each request signed with the device's key.

Connecting (the Imports page): /audible/connect/start makes the address of
Amazon's sign-in page for a new device and keeps what proves the sign-in
was asked for here (the PKCE verifier, the device's serial) in the
session. The user signs in at Amazon themselves, in a tab of their own:
their password and their second factor are never seen by My World. Amazon
then ends on an address it has no page for (/ap/maplanding), whose query
holds a one-time code; the user pastes that address back, and
/audible/connect/finish trades the code for the device's tokens: its ADP
token and private key, which sign every request to the library (they do
not expire), and a refresh token, kept to deregister the device again.
They are kept (models.AudibleConnection) sealed with a key derived from
SECRET_KEY, so the database alone does not give them away.
/audible/disconnect deregisters the device at Amazon and forgets them.

The library's books come as library_items: the shape audible-cli's export
gives them (the fields veltzer.github.io's audible.yaml had), which
store_library writes as audio books whose source is "audible".
"""

import base64
import datetime
import hashlib
import os
import secrets
import urllib.parse
import uuid
from collections.abc import Callable
from typing import Any

import flask
import requests
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from sqlalchemy import select
from sqlalchemy.orm import Session

from myworld import auth
from myworld.api import ApiError, json_body, text
from myworld.models import (
    AudibleConnection,
    AudioBook,
    AudioBookHeard,
    AudioBookListen,
    AudioBookVersion,
    Image,
    User,
    utcnow,
)

bp = flask.Blueprint("audible", __name__, url_prefix="/audible")

SOURCE = "audible"
HTTP_TIMEOUT = 30


class AudibleError(Exception):
    """ Amazon or Audible did not answer usefully, or the connection is gone. """


# ─── the marketplace ────────────────────────────────────────────────────────

# The Audible store an account is at. Only the US store (audible.com) for
# now; another is a matter of its domains and ids.
MARKETPLACES: dict[str, dict[str, str]] = {
    "us": {
        "name": "audible.com",
        "amazon": "amazon.com",
        "audible": "audible.com",
        "marketplace_id": "AF2M0KC94RCEA",
        "assoc_handle": "amzn_audible_ios_us",
    },
}
DEFAULT_MARKETPLACE = "us"

# the device My World registers as: the Audible app on an iPhone, which is
# what Amazon's sign-in for a device and the library API are made for
DEVICE_TYPE = "A2CZJZGLK2JJVM"
APP_NAME = "Audible"
APP_VERSION = "3.56.2"
SOFTWARE_VERSION = "35602678"
OS_VERSION = "15.0.0"
DEVICE_MODEL = "iPhone"
# how the device is listed among the account's devices at Amazon ("Mark's My World")
DEVICE_NAME = "%FIRST_NAME%%FIRST_NAME_POSSESSIVE_STRING%%DUPE_STRATEGY_1ST%My World"


def marketplace(code: str) -> dict[str, str]:
    try:
        return MARKETPLACES[code]
    except KeyError as e:
        raise AudibleError(f"no Audible store {code!r}") from e


# ─── signing in (OAuth 2.0 for a device, with PKCE) ─────────────────────────

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def new_login() -> dict[str, str]:
    """ What a sign-in is begun with: a PKCE code verifier, and the serial of the device to be. """
    return {"verifier": _b64url(secrets.token_bytes(32)), "serial": uuid.uuid4().hex.upper()}


def client_id(serial: str) -> str:
    """ The OAuth client of a device: its serial and type, hex encoded, as Amazon asks for a device's. """
    return f"{serial}#{DEVICE_TYPE}".encode().hex()


def sign_in_url(login: dict[str, str], code: str = DEFAULT_MARKETPLACE) -> str:
    """ Amazon's sign-in page for a new device of the account, which ends at /ap/maplanding with a code. """
    store = marketplace(code)
    challenge = _b64url(hashlib.sha256(login["verifier"].encode()).digest())
    params = {
        "openid.oa2.response_type": "code",
        "openid.oa2.code_challenge_method": "S256",
        "openid.oa2.code_challenge": challenge,
        "openid.return_to": f"https://www.{store['amazon']}/ap/maplanding",
        "openid.assoc_handle": store["assoc_handle"],
        "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
        "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
        "pageId": "amzn_audible_ios",
        "accountStatusPolicy": "P1",
        "openid.mode": "checkid_setup",
        "openid.ns.oa2": "http://www.amazon.com/ap/ext/oauth/2",
        "openid.oa2.client_id": f"device:{client_id(login['serial'])}",
        "openid.ns.pape": "http://specs.openid.net/extensions/pape/1.0",
        "marketPlaceId": store["marketplace_id"],
        "openid.oa2.scope": "device_auth_access",
        "forceMobileLayout": "true",
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.pape.max_auth_age": "0",
    }
    return f"https://www.{store['amazon']}/ap/signin?{urllib.parse.urlencode(params)}"


def code_from(address: str) -> str:
    """ The one-time code in the address Amazon ended the sign-in on. """
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(address.strip()).query)
    codes = query.get("openid.oa2.authorization_code", [])
    if not codes or not codes[0]:
        raise AudibleError("that address has no sign-in code: paste the whole address of the page Amazon ended on, after signing in")
    return codes[0]


# ─── calls (the tests replace these two) ────────────────────────────────────

def amazon_post(url: str, *, json: dict[str, Any] | None = None, data: dict[str, str] | None = None,
                headers: dict[str, str] | None = None) -> dict[str, Any]:
    """ One call of Amazon's device endpoints (register, token, deregister). """
    try:
        response = requests.post(url, json=json, data=data, headers=headers, timeout=HTTP_TIMEOUT)
    except requests.RequestException as e:
        raise AudibleError(f"Amazon could not be reached: {e}") from e
    try:
        answer = response.json()
    except ValueError:
        answer = {}
    if not response.ok:
        said = answer.get("response", {}).get("error", {}).get("message") or answer.get("error_description") or response.reason
        raise AudibleError(f"Amazon answered {response.status_code}: {said}")
    if not isinstance(answer, dict):
        raise AudibleError("Amazon answered with something that is not an object")
    return answer


def api_get(url: str, headers: dict[str, str]) -> dict[str, Any]:
    """ One call of Audible's API. """
    try:
        response = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
    except requests.RequestException as e:
        raise AudibleError(f"Audible could not be reached: {e}") from e
    if response.status_code in (401, 403):
        raise AudibleError(f"Audible no longer accepts the connection ({response.status_code}): connect Audible again")
    if not response.ok:
        raise AudibleError(f"Audible answered {response.status_code}: {response.reason}")
    data = response.json()
    if not isinstance(data, dict):
        raise AudibleError("Audible answered with something that is not an object")
    return data


def fetch_cover(url: str) -> bytes | None:
    """ A cover image, as Audible's image server gives it; None when it gives none. """
    if not url.startswith("https://"):
        return None
    try:
        response = requests.get(url, timeout=HTTP_TIMEOUT)
    except requests.RequestException:
        return None
    if not response.ok or not response.headers.get("Content-Type", "").startswith("image/jpeg"):
        return None
    return response.content


# ─── the device ─────────────────────────────────────────────────────────────

def register(login: dict[str, str], code: str, store_code: str = DEFAULT_MARKETPLACE) -> dict[str, str]:
    """
    Register My World as a device of the account that signed in (code, the
    one-time code; login, what the sign-in began with): its tokens, and
    the name of the account.
    """
    store = marketplace(store_code)
    body = {
        "requested_token_type": ["bearer", "mac_dms"],
        "cookies": {"website_cookies": [], "domain": f".{store['amazon']}"},
        "registration_data": {
            "domain": "Device",
            "app_version": APP_VERSION,
            "device_serial": login["serial"],
            "device_type": DEVICE_TYPE,
            "device_name": DEVICE_NAME,
            "os_version": OS_VERSION,
            "software_version": SOFTWARE_VERSION,
            "device_model": DEVICE_MODEL,
            "app_name": APP_NAME,
        },
        "auth_data": {
            "client_id": client_id(login["serial"]),
            "authorization_code": code,
            "code_verifier": login["verifier"],
            "code_algorithm": "SHA-256",
            "client_domain": "DeviceLegacy",
        },
        "requested_extensions": ["device_info", "customer_info"],
    }
    answer = amazon_post(f"https://api.{store['amazon']}/auth/register", json=body)
    try:
        success = answer["response"]["success"]
        tokens = success["tokens"]
        kept = {
            "adp_token": tokens["mac_dms"]["adp_token"],
            "private_key": tokens["mac_dms"]["device_private_key"],
            "refresh_token": tokens["bearer"]["refresh_token"],
        }
    except (KeyError, TypeError) as e:
        raise AudibleError("Amazon registered no device: its answer had no tokens") from e
    name = (success.get("extensions") or {}).get("customer_info", {}).get("name", "")
    return {**kept, "name": str(name or "")}


def access_token(refresh_token: str, store_code: str = DEFAULT_MARKETPLACE) -> str:
    """ An access token (an hour's) for the device, from its refresh token. """
    store = marketplace(store_code)
    answer = amazon_post(f"https://api.{store['amazon']}/auth/token", data={
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "source_token": refresh_token,
        "requested_token_type": "access_token",
        "source_token_type": "refresh_token",
    })
    token = answer.get("access_token")
    if not token:
        raise AudibleError("Amazon gave no access token")
    return str(token)


def deregister(refresh_token: str, store_code: str = DEFAULT_MARKETPLACE) -> None:
    """ Take My World off the account's devices at Amazon; best effort. """
    store = marketplace(store_code)
    try:
        token = access_token(refresh_token, store_code)
        amazon_post(f"https://api.{store['amazon']}/auth/deregister", json={"deregister_all_existing_accounts": False},
                    headers={"Authorization": f"Bearer {token}"})
    except AudibleError:
        pass


def _private_key(pem: str) -> rsa.RSAPrivateKey:
    text_key = pem.strip()
    if not text_key.startswith("-----BEGIN"):
        text_key = f"-----BEGIN RSA PRIVATE KEY-----\n{text_key}\n-----END RSA PRIVATE KEY-----"
    try:
        key = serialization.load_pem_private_key(text_key.encode(), password=None)
    except (ValueError, TypeError, UnsupportedAlgorithm) as e:
        raise AudibleError("the device's key can no longer be read: connect Audible again") from e
    if not isinstance(key, rsa.RSAPrivateKey):
        raise AudibleError("the device's key is not an RSA key: connect Audible again")
    return key


def signed_headers(method: str, path: str, body: str, adp_token: str, private_key: str, now: datetime.datetime | None = None) -> dict[str, str]:
    """
    The headers that sign a request as the device: the method, the path
    (with its query), the moment, the body and the ADP token, one a line,
    signed with the device's key (RSA, SHA-256), said with the moment.
    """
    moment = (now or datetime.datetime.now(datetime.UTC)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    data = f"{method}\n{path}\n{moment}\n{body}\n{adp_token}"
    signature = _private_key(private_key).sign(data.encode(), padding.PKCS1v15(), hashes.SHA256())
    return {
        "x-adp-token": adp_token,
        "x-adp-alg": "SHA256withRSA:1.0",
        "x-adp-signature": f"{base64.b64encode(signature).decode()}:{moment}",
    }


# ─── the kept tokens ────────────────────────────────────────────────────────

def _fernet() -> Fernet:
    secret = flask.current_app.config["SECRET_KEY"] if flask.has_app_context() else os.environ.get("SECRET_KEY", "")
    if not secret:
        raise AudibleError("SECRET_KEY is not set: no key to seal the Audible connection with")
    digest = hashlib.sha256(b"myworld audible connection\0" + str(secret).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def seal(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def unseal(sealed: str) -> str:
    try:
        return _fernet().decrypt(sealed.encode()).decode()
    except InvalidToken as e:
        # SECRET_KEY changed since it was kept
        raise AudibleError("the Audible connection can no longer be read: connect Audible again") from e


def connection(session: Session, owner: User) -> AudibleConnection | None:
    return session.get(AudibleConnection, owner.id)


# ─── reading the library ────────────────────────────────────────────────────

# what the library is asked to say of each book
RESPONSE_GROUPS = (
    "contributors,media,product_attrs,product_desc,product_details,product_extended_attrs,"
    "rating,series,category_ladders,is_finished,percent_complete,order_details"
)
# the books asked for at a time
PAGE = 1000


class Client:
    """ Audible's API as the device My World registered for one user. """

    def __init__(self, kept: AudibleConnection) -> None:
        self.store = marketplace(kept.marketplace)
        self.adp_token = unseal(kept.adp_token)
        self.private_key = unseal(kept.private_key)

    def get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        full = f"{path}?{urllib.parse.urlencode(params)}"
        headers = {"Accept": "application/json", "client-id": "0", **signed_headers("GET", full, "", self.adp_token, self.private_key)}
        return api_get(f"https://api.{self.store['audible']}{full}", headers)


def client_for(session: Session, owner: User) -> Client:
    kept = connection(session, owner)
    if kept is None:
        raise AudibleError("Audible is not connected: connect it on the Imports page")
    return Client(kept)


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def library_item(item: dict[str, Any]) -> dict[str, Any]:
    """ A book of the library API, as audible-cli's export says it (the fields store_library reads). """
    series = (item.get("series") or [{}])[0] or {}
    distribution = (item.get("rating") or {}).get("overall_distribution") or {}
    return {
        "asin": _text(item.get("asin")),
        "title": _text(item.get("title")),
        "subtitle": _text(item.get("subtitle")),
        "authors": ", ".join(_text(a.get("name")) for a in item.get("authors") or []),
        "narrators": ", ".join(_text(n.get("name")) for n in item.get("narrators") or []),
        "series_title": _text(series.get("title")),
        "series_sequence": _text(series.get("sequence")),
        # each ladder is a genre's path from its top genre down, one after another
        "genres": [_text(rung.get("name")) for ladder in item.get("category_ladders") or [] for rung in ladder.get("ladder") or []],
        "runtime_length_min": _text(item.get("runtime_length_min")),
        "is_finished": bool(item.get("is_finished")),
        "percent_complete": _text(item.get("percent_complete")),
        "rating": _text(distribution.get("display_average_rating")),
        "num_ratings": _text(distribution.get("num_ratings")),
        "date_added": _text((item.get("library_status") or {}).get("date_added")),
        "release_date": _text(item.get("release_date")),
        "cover_url": _text((item.get("product_images") or {}).get("500")),
        "purchase_date": _text(item.get("purchase_date")),
    }


def library(client: Client) -> list[dict[str, Any]]:
    """ Every book of the library, as library_item says it. """
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        answer = client.get("/1.0/library", {
            "num_results": str(PAGE), "page": str(page), "response_groups": RESPONSE_GROUPS, "image_sizes": "500", "sort_by": "-PurchaseDate",
        })
        found = answer.get("items") or []
        items.extend(library_item(item) for item in found)
        if len(found) < PAGE:
            return items
        page += 1


# ─── storing it ─────────────────────────────────────────────────────────────

# what an item of the library says (audible-cli's export, veltzer.github.io's audible.yaml)
ITEM_FIELDS = {
    "asin", "title", "subtitle", "authors", "narrators", "series_title", "series_sequence", "genres", "runtime_length_min",
    "is_finished", "percent_complete", "rating", "num_ratings", "date_added", "release_date", "cover_url", "purchase_date",
}


def _optional(value: Any, kind: type[int | float]) -> int | float | None:
    """ A number the library writes as a string, None when it writes nothing. """
    written = _text(value).strip()
    if not written:
        return None
    return int(float(written)) if kind is int else float(written)


def _stamp(value: Any) -> datetime.datetime | None:
    """ A moment the library writes ("2021-08-10T08:55:06.867Z"), as the naive UTC the columns keep. """
    written = _text(value).strip()
    if not written:
        return None
    return datetime.datetime.fromisoformat(written).astimezone(datetime.UTC).replace(tzinfo=None)


def _genres(item: dict[str, Any]) -> list[str]:
    """ A book's genres as the library lists them, repeats too: each genre's path from its top genre down. """
    return [_text(g).strip() for g in item.get("genres", []) if _text(g).strip()]


def _version_values(item: dict[str, Any]) -> dict[str, Any]:
    """ What Audible says of a book (its Audible version) that the app does not edit: refreshed on every import. """
    return {
        "cover_url": _text(item.get("cover_url")).strip(),
        "source_rating": _optional(item.get("rating"), float),
        "source_ratings": _optional(item.get("num_ratings"), int),
    }


def _listen_values(item: dict[str, Any]) -> dict[str, Any]:
    """ What the library says of the user's own listening to a book that the app does not edit: refreshed on every import. """
    return {
        "purchased_utcz": _stamp(item.get("purchase_date")),
        "finished": bool(item.get("is_finished")),
        "percent_heard": _optional(item.get("percent_complete"), float),
    }


def _changes(row: Any, values: dict[str, Any]) -> list[str]:
    """ The keys of values row has another value of. """
    return [key for key, value in values.items() if getattr(row, key) != value]


def _refresh(row: Any, values: dict[str, Any]) -> bool:
    """ row given values where they differ; whether any did. """
    changed = {key: value for key, value in values.items() if getattr(row, key) != value}
    for key, value in changed.items():
        setattr(row, key, value)
    return bool(changed)


def check_items(items: list[dict[str, Any]], where: str) -> None:
    """ Every item says only what an item of the library says, has an ASIN and a title, and no ASIN comes twice; AudibleError otherwise. """
    for item in items:
        unknown = set(item) - ITEM_FIELDS
        if unknown:
            raise AudibleError(f"{where}: {item.get('title')!r} has fields this import does not know: {sorted(unknown)}")
        if not item.get("asin") or not _text(item.get("title")).strip():
            raise AudibleError(f"{where}: {item.get('title')!r} has no ASIN or no title")
    asins = [_text(item["asin"]) for item in items]
    if len(set(asins)) != len(asins):
        raise AudibleError(f"{where}: an ASIN is listed twice")


def store_library(
    session: Session, owner: User, items: list[dict[str, Any]], cover: Callable[[str, str], bytes | None], say: Callable[[str], None] = lambda _line: None,
) -> dict[str, int]:
    """
    The books of owner's Audible library (items, as library_item says
    them). Audio books are shared: a book's Audible version is found by its
    ASIN, or else the book by its title, subtitle and authors, or by its
    title and authors when it has no subtitle (it is given Audible's), or
    else the book is added; and the Audible version is added to it, with its
    cover (cover(asin, cover_url): the image's bytes, or None); one there
    already with no cover (Audible's image server failed when it was added)
    is given it now. Of a version there already, only what
    Audible changes is refreshed (_version_values), so whatever was edited
    in the app stays; genres an earlier import kept each once only are given
    back as the library lists them. owner's listen of the version (and the
    book in their Your audio books) is added when they have none, and what
    the library says of their listening refreshed (_listen_values). Safe to
    run again. Does not commit. What it does to each book is said, a line
    each (say: the run's log), but of a book left as it was.
    """
    versions = {v.asin: v for v in session.scalars(select(AudioBookVersion).where(AudioBookVersion.kind == SOURCE, AudioBookVersion.asin.is_not(None)))}
    every = list(session.scalars(select(AudioBook)))
    books = {(b.name, b.subtitle, b.authors): b for b in every}
    # a book said without its subtitle (heard as MP3 files, ...) is found by its title and authors
    unsubtitled = {(b.name, b.authors): b for b in every if not b.subtitle}
    listens = {listen.version_id: listen for listen in session.scalars(select(AudioBookListen).where(AudioBookListen.owner_id == owner.id))}
    heard = {row.book_id for row in session.scalars(select(AudioBookHeard).where(AudioBookHeard.owner_id == owner.id))}
    stored = {image.filename: image for image in session.scalars(select(Image).where(Image.owner_id == owner.id, Image.filename.like("audible-%")))}
    added = refreshed = images = 0
    for item in items:
        asin = _text(item["asin"])
        version = versions.get(asin)
        changed = False
        title = f"{_text(item['title']).strip()} ({asin})"
        if version is not None:
            values = _version_values(item)
            genres = _genres(item)
            # kept each once by an earlier import, and not edited since: as the library lists them
            if version.genres != genres and version.genres == list(dict.fromkeys(genres)):
                values["genres"] = genres
            fields = _changes(version, values)
            changed = _refresh(version, values)
            if fields:
                say(f"~ {title}: Audible's {', '.join(fields)}")
            # one added while Audible's image server failed has none: it is asked again
            if version.image_id is None and version.image is None:
                filename = f"audible-{asin}.jpg"
                image = stored.get(filename)
                if image is None:
                    data = cover(asin, _text(item.get("cover_url")).strip() or version.cover_url)
                    if data is not None:
                        image = Image(owner_id=owner.id, filename=filename, content_type="image/jpeg", sha256=hashlib.sha256(data).hexdigest(), data=data)
                        session.add(image)
                        stored[filename] = image
                        images += 1
                if image is not None:
                    version.image = image
                    changed = True
                say(f"~ {title}: {'cover added' if image is not None else 'still no cover: Audible gave none'}")
        else:
            name, subtitle, authors = _text(item["title"]).strip(), _text(item.get("subtitle")).strip(), _text(item.get("authors")).strip()
            book = books.get((name, subtitle, authors))
            if book is None and (name, authors) in unsubtitled:
                book = unsubtitled.pop((name, authors))
                book.subtitle = subtitle
                books[name, subtitle, authors] = book
            filename = f"audible-{asin}.jpg"
            image = stored.get(filename)
            if image is None:
                data = cover(asin, _text(item.get("cover_url")).strip())
                if data is not None:
                    image = Image(owner_id=owner.id, filename=filename, content_type="image/jpeg", sha256=hashlib.sha256(data).hexdigest(), data=data)
                    session.add(image)
                    stored[filename] = image
                    images += 1
            new_book = book is None
            if book is None:
                book = AudioBook(
                    name=name,
                    subtitle=subtitle,
                    authors=authors,
                    series=_text(item.get("series_title")).strip(),
                    series_sequence=_text(item.get("series_sequence")).strip(),
                )
                session.add(book)
                books[name, subtitle, authors] = book
                added += 1
            release = _text(item.get("release_date")).strip()
            version = AudioBookVersion(
                book=book,
                kind=SOURCE,
                asin=asin,
                narrators=_text(item.get("narrators")).strip(),
                genres=_genres(item),
                minutes=_optional(item.get("runtime_length_min"), int),
                released=datetime.date.fromisoformat(release) if release else None,
                image=image,
                **_version_values(item),
            )
            session.add(version)
            session.flush()
            versions[asin] = version
            say(f"+ {title}: added, {'a new book' if new_book else 'a version of the book there'}, "
                f"{'with its cover' if image is not None else 'no cover: Audible gave none'}")
        listen = listens.get(version.id)
        if listen is None:
            listen = AudioBookListen(owner_id=owner.id, version=version, added_utcz=_stamp(item.get("date_added")), **_listen_values(item))
            session.add(listen)
            listens[version.id] = listen
            say(f"  + your listen of {title}")
        else:
            fields = _changes(listen, _listen_values(item))
            changed = _refresh(listen, _listen_values(item)) or changed
            if fields:
                say(f"~ {title}: your listening ({', '.join(fields)})")
        if version.book_id not in heard:
            session.add(AudioBookHeard(owner_id=owner.id, book_id=version.book_id))
            heard.add(version.book_id)
        refreshed += changed
    session.flush()
    return {"audio books added": added, "audio books refreshed": refreshed, "images": images}


# ─── the routes ─────────────────────────────────────────────────────────────

def status_json(session: Session, owner: User) -> dict[str, Any]:
    """ What the Imports page shows of the connection. """
    kept = connection(session, owner)
    return {
        "connected": kept is not None,
        "name": kept.name if kept else "",
        "store": marketplace(kept.marketplace)["name"] if kept else "",
        "connected_at": kept.connected_at.isoformat() if kept else None,
    }


@bp.route("/connect/start", methods=["POST"])
@auth.login_required
def connect_start() -> flask.Response:
    """ The address of Amazon's sign-in page for this connection; what proves it was asked for here stays in the session. """
    login = new_login()
    flask.session["audible_login"] = login
    return flask.jsonify({"url": sign_in_url(login)})


@bp.route("/connect/finish", methods=["POST"])
@auth.login_required
def connect_finish() -> flask.Response:
    """ {"address": the address Amazon ended the sign-in on}: register the device, and keep its tokens. """
    login = flask.session.get("audible_login")
    if not isinstance(login, dict) or not login.get("verifier") or not login.get("serial"):
        raise ApiError(400, "no sign-in was begun here: press Connect Audible again")
    address = text(json_body(), "address", required=True)
    try:
        device = register(login, code_from(address))
    except AudibleError as e:
        raise ApiError(400, str(e)) from e
    flask.session.pop("audible_login", None)
    db = flask.g.db
    kept = connection(db, flask.g.user)
    if kept is not None:
        # connected again: the device before goes
        deregister(unseal(kept.refresh_token), kept.marketplace)
        db.delete(kept)
        db.flush()
    db.add(AudibleConnection(
        owner_id=flask.g.user.id, marketplace=DEFAULT_MARKETPLACE, name=device["name"], connected_at=utcnow(),
        adp_token=seal(device["adp_token"]), private_key=seal(device["private_key"]), refresh_token=seal(device["refresh_token"]),
    ))
    db.commit()
    return flask.jsonify(status_json(db, flask.g.user))


@bp.route("/disconnect", methods=["POST"])
@auth.login_required
def disconnect() -> tuple[str, int]:
    db = flask.g.db
    kept = connection(db, flask.g.user)
    if kept is not None:
        try:
            deregister(unseal(kept.refresh_token), kept.marketplace)
        except AudibleError:
            pass
        db.delete(kept)
        db.commit()
    return "", 204


@bp.route("/status", methods=["GET"])
@auth.login_required
def status() -> flask.Response:
    return flask.jsonify(status_json(flask.g.db, flask.g.user))
