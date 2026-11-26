"""
The user's Google Calendar, for the importers that read it: connecting it
(Google's OAuth 2.0 authorization code flow, for the calendar.readonly
scope), the token that is kept, and the calls to the Google Calendar API.

It works as the YouTube connection does (myworld.youtube): signing in with
Google only says who the user is, and reading their calendars needs their
consent to more, asked on the Imports page. /calendar/connect sends them to
Google's consent screen, /calendar/callback trades the code for a refresh
token and keeps it (models.CalendarConnection), sealed with a key derived
from SECRET_KEY (its own: a YouTube token's key does not open it), so the
database alone does not give it away. Each run of an importer trades it for
an access token, which lasts an hour and is never kept.
/calendar/disconnect revokes it at Google and forgets it.

It uses the web client that "Sign in with Google" uses (GOOGLE_CLIENT_ID),
with its secret (GOOGLE_CLIENT_SECRET): connecting is offered only when
both are set. (Not named calendar: that would hide Python's own module.)
"""

import base64
import contextlib
import hashlib
import hmac
import os
import secrets
import urllib.parse
from typing import TYPE_CHECKING, Any

import flask
import requests
from cryptography.fernet import Fernet, InvalidToken

from myworld import auth
from myworld.models import CalendarConnection, User, utcnow

if TYPE_CHECKING:
    from collections.abc import Iterator

    import werkzeug
    from sqlalchemy.orm import Session

bp = flask.Blueprint("gcalendar", __name__, url_prefix="/calendar")

SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/calendar/v3"
HTTP_TIMEOUT = 20
# the most items one call of the API gives (the API allows up to 2500 events, 250 calendars)
PAGE = 250
# where the Imports page is: the callback returns there
IMPORTS_PAGE = "/library#imports"


class CalendarError(Exception):
    """ Google did not answer usefully, or the connection is gone. """


def client_id() -> str:
    return auth.client_id()


def client_secret() -> str:
    return os.environ.get("GOOGLE_CLIENT_SECRET", "")


def configured() -> bool:
    return bool(client_id() and client_secret())


# ─── the kept token ─────────────────────────────────────────────────────────

def _fernet() -> Fernet:
    secret = flask.current_app.config["SECRET_KEY"] if flask.has_app_context() else os.environ.get("SECRET_KEY", "")
    if not secret:
        raise CalendarError("SECRET_KEY is not set: no key to seal the Google Calendar connection with")
    digest = hashlib.sha256(b"myworld google calendar connection\0" + secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def seal(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def unseal(sealed: str) -> str:
    try:
        return _fernet().decrypt(sealed.encode()).decode()
    except InvalidToken as e:
        # SECRET_KEY changed since it was kept
        raise CalendarError("the Google Calendar connection can no longer be read: connect Google Calendar again") from e


def connection(session: Session, owner: User) -> CalendarConnection | None:
    return session.get(CalendarConnection, owner.id)


# ─── calls (the tests replace these three) ──────────────────────────────────

def token_post(data: dict[str, str]) -> dict[str, Any]:
    """ One call of Google's token endpoint. """
    response = requests.post(TOKEN_URL, data=data, timeout=HTTP_TIMEOUT)
    answer = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else {}
    if not response.ok:
        if answer.get("error") == "invalid_grant":
            raise CalendarError("Google no longer accepts the Google Calendar connection (revoked or expired): connect Google Calendar again")
        raise CalendarError(f"Google's token endpoint answered {response.status_code}")
    return answer


def api_get(access_token: str, path: str, params: dict[str, str]) -> dict[str, Any]:
    """ One call of the Google Calendar API. """
    response = requests.get(f"{API}/{path}", params=params, headers={"Authorization": f"Bearer {access_token}"}, timeout=HTTP_TIMEOUT)
    if not response.ok:
        try:
            message = response.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = response.reason
        raise CalendarError(f"Google Calendar answered {response.status_code} to {path}: {message}")
    data = response.json()
    if not isinstance(data, dict):
        raise CalendarError(f"Google Calendar answered {path} with something that is not an object")
    return data


def revoke(token: str) -> None:
    """ Tell Google the token is no longer wanted; best effort. """
    with contextlib.suppress(requests.RequestException):
        requests.post(REVOKE_URL, data={"token": token}, timeout=HTTP_TIMEOUT)


# ─── reading the account ────────────────────────────────────────────────────

class Client:
    """ The Google Calendar API as one user, with an access token traded for their refresh token. """

    def __init__(self, access_token: str) -> None:
        self.access_token = access_token

    def get(self, path: str, **params: str) -> dict[str, Any]:
        return api_get(self.access_token, path, params)

    def items(self, path: str, **params: str) -> Iterator[dict[str, Any]]:
        """ Every item of a listing, page after page. """
        page = ""
        while True:
            data = self.get(path, maxResults=str(PAGE), **params, **({"pageToken": page} if page else {}))
            yield from data.get("items") or []
            page = data.get("nextPageToken") or ""
            if not page:
                return


def client_for(session: Session, owner: User) -> Client:
    """ The API as owner, who connected Google Calendar; CalendarError when they did not, or it no longer works. """
    if not configured():
        raise CalendarError("connecting Google Calendar is not set up on this site (GOOGLE_CLIENT_SECRET)")
    kept = connection(session, owner)
    if kept is None:
        raise CalendarError("Google Calendar is not connected: connect it first")
    answer = token_post({
        "client_id": client_id(),
        "client_secret": client_secret(),
        "refresh_token": unseal(kept.refresh_token),
        "grant_type": "refresh_token",
    })
    token = answer.get("access_token")
    if not isinstance(token, str) or not token:
        raise CalendarError("Google did not issue an access token")
    return Client(token)


def account_name(client: Client) -> str:
    """ Whose calendar it is: the primary calendar's name, which Google makes the account's email. """
    return str(client.get("calendars/primary").get("summary") or "")


def my_calendars(client: Client) -> list[tuple[str, str]]:
    """ The calendars the user sees, (id, name), the primary one first and then by name. """
    found = [
        (item["id"], item.get("summaryOverride") or item.get("summary") or item["id"], bool(item.get("primary")))
        for item in client.items("users/me/calendarList")
    ]
    found.sort(key=lambda c: (not c[2], c[1].casefold()))
    return [(calendar_id, name) for calendar_id, name, _ in found]


# ─── connecting ─────────────────────────────────────────────────────────────

def _callback_url() -> str:
    """ The callback registered with Google: always on the canonical host, as YouTube's is. """
    path = flask.url_for("gcalendar.callback")
    canonical = flask.current_app.config["CANONICAL_HOST"]
    if canonical:
        return f"https://{canonical}{path}"
    scheme = "https" if "K_SERVICE" in os.environ else None
    return flask.url_for("gcalendar.callback", _external=True, _scheme=scheme)


def _back(error: str = "") -> werkzeug.Response:
    """ To the Imports page, saying what went wrong when something did. """
    if not error:
        return flask.redirect(IMPORTS_PAGE)
    return flask.redirect(f"/library?{urllib.parse.urlencode({'calendar_error': error})}#imports")


@bp.route("/connect", methods=["GET"])
@auth.login_required
def connect() -> werkzeug.Response:
    if not configured():
        flask.abort(404)
    # the state names the host the connecting started on, for the callback to return to
    state = f"{secrets.token_urlsafe(32)}@{flask.request.host}"
    flask.session["calendar_state"] = state
    params = {
        "client_id": client_id(),
        "redirect_uri": _callback_url(),
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
        # a refresh token, for the imports to come, and every time: one is given only with consent
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "login_hint": flask.g.user.email,
    }
    return flask.redirect(f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}")


@bp.route("/callback", methods=["GET"])
def callback() -> werkzeug.Response:
    if not configured():
        flask.abort(404)
    given = flask.request.args.get("state", "")
    # one that started on an alias host goes back there, where its session is (as auth.oauth_callback)
    started_on = given.rpartition("@")[2]
    config = flask.current_app.config
    if flask.request.host == config["CANONICAL_HOST"] and started_on in config["ALIAS_HOSTS"]:
        return flask.redirect(urllib.parse.urlsplit(flask.request.url)._replace(scheme="https", netloc=started_on).geturl())
    expected = flask.session.pop("calendar_state", "")
    if not expected or not hmac.compare_digest(expected, given):
        flask.abort(400, "OAuth state mismatch")
    user = auth.current_user()
    if user is None:
        return flask.redirect(flask.url_for("views.index"))
    code = flask.request.args.get("code", "")
    if not code:
        return _back("Connecting Google Calendar was cancelled")
    try:
        answer = token_post({
            "client_id": client_id(),
            "client_secret": client_secret(),
            "code": code,
            "redirect_uri": _callback_url(),
            "grant_type": "authorization_code",
        })
        refresh = answer.get("refresh_token")
        if not isinstance(refresh, str) or not refresh:
            raise CalendarError("Google did not give a refresh token")
        if SCOPE not in str(answer.get("scope", "")).split():
            raise CalendarError("Google Calendar access was not granted: tick it on Google's consent screen")
        name = account_name(Client(str(answer.get("access_token", ""))))
    except (CalendarError, requests.RequestException, ValueError) as e:
        return _back(f"Connecting Google Calendar failed: {e}")
    db = flask.g.db
    kept = connection(db, user)
    if kept is None:
        kept = CalendarConnection(owner_id=user.id)
        db.add(kept)
    kept.refresh_token = seal(refresh)
    kept.account = name[:200]
    kept.connected_at = utcnow()
    db.commit()
    return _back()


@bp.route("/disconnect", methods=["POST"])
@auth.login_required
def disconnect() -> tuple[str, int]:
    db = flask.g.db
    kept = connection(db, flask.g.user)
    if kept is not None:
        with contextlib.suppress(CalendarError):
            revoke(unseal(kept.refresh_token))
        db.delete(kept)
        db.commit()
    return "", 204


def status_json(session: Session, owner: User) -> dict[str, Any]:
    """ What the Imports page shows of the connection. """
    kept = connection(session, owner)
    return {
        "configured": configured(),
        "connected": kept is not None,
        "account": kept.account if kept else "",
        "connected_at": kept.connected_at.isoformat() if kept else None,
    }


@bp.route("/status", methods=["GET"])
@auth.login_required
def status() -> flask.Response:
    return flask.jsonify(status_json(flask.g.db, flask.g.user))
