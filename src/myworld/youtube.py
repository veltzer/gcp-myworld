"""
The user's YouTube account, for the importers that read it: connecting it
(Google's OAuth 2.0 authorization code flow, for the youtube.readonly
scope), the token that is kept, and the calls to the YouTube Data API.

Signing in with Google only asks who the user is (an ID token, no access to
anything); reading their playlists needs their consent to more, asked
separately on the Imports page: /youtube/connect sends them to Google's
consent screen, /youtube/callback trades the code for a refresh token and
keeps it (models.YouTubeConnection), sealed with a key derived from
SECRET_KEY, so the database alone does not give it away. Each run of an
importer trades it for an access token, which lasts an hour and is never
kept. /youtube/disconnect revokes it at Google and forgets it.

It uses the web client that "Sign in with Google" uses (GOOGLE_CLIENT_ID),
with its secret (GOOGLE_CLIENT_SECRET): connecting is offered only when
both are set.
"""

import base64
import contextlib
import datetime as dt
import hashlib
import hmac
import os
import re
import secrets
import urllib.parse
from typing import TYPE_CHECKING, Any

import flask
import requests
from cryptography.fernet import Fernet, InvalidToken

from myworld import auth
from myworld.models import User, YouTubeConnection, utcnow

if TYPE_CHECKING:
    from collections.abc import Iterator

    import werkzeug
    from sqlalchemy.orm import Session

bp = flask.Blueprint("youtube", __name__, url_prefix="/youtube")

SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://www.googleapis.com/youtube/v3"
HTTP_TIMEOUT = 20
# the most ids or items one call of the API takes or gives
PAGE = 50
# where the Imports page is: the callback returns there
IMPORTS_PAGE = "/library#imports"


class YouTubeError(Exception):
    """ YouTube or Google did not answer usefully, or the connection is gone. """


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
        raise YouTubeError("SECRET_KEY is not set: no key to seal the YouTube connection with")
    digest = hashlib.sha256(b"myworld youtube connection\0" + secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def seal(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def unseal(sealed: str) -> str:
    try:
        return _fernet().decrypt(sealed.encode()).decode()
    except InvalidToken as e:
        # SECRET_KEY changed since it was kept
        raise YouTubeError("the YouTube connection can no longer be read: connect YouTube again") from e


def connection(session: Session, owner: User) -> YouTubeConnection | None:
    return session.get(YouTubeConnection, owner.id)


# ─── calls (the tests replace these two) ────────────────────────────────────

def token_post(data: dict[str, str]) -> dict[str, Any]:
    """ One call of Google's token endpoint. """
    response = requests.post(TOKEN_URL, data=data, timeout=HTTP_TIMEOUT)
    answer = response.json() if response.headers.get("Content-Type", "").startswith("application/json") else {}
    if not response.ok:
        if answer.get("error") == "invalid_grant":
            raise YouTubeError("Google no longer accepts the YouTube connection (revoked or expired): connect YouTube again")
        raise YouTubeError(f"Google's token endpoint answered {response.status_code}")
    return answer


def api_get(access_token: str, path: str, params: dict[str, str]) -> dict[str, Any]:
    """ One call of the YouTube Data API. """
    response = requests.get(f"{API}/{path}", params=params, headers={"Authorization": f"Bearer {access_token}"}, timeout=HTTP_TIMEOUT)
    if not response.ok:
        try:
            message = response.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = response.reason
        raise YouTubeError(f"YouTube answered {response.status_code} to {path}: {message}")
    data = response.json()
    if not isinstance(data, dict):
        raise YouTubeError(f"YouTube answered {path} with something that is not an object")
    return data


def revoke(token: str) -> None:
    """ Tell Google the token is no longer wanted; best effort, the tests replace it. """
    with contextlib.suppress(requests.RequestException):
        requests.post(REVOKE_URL, data={"token": token}, timeout=HTTP_TIMEOUT)


# ─── reading the account ────────────────────────────────────────────────────

class Client:
    """ The YouTube Data API as one user, with an access token traded for their refresh token. """

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
    """ The API as owner, who connected YouTube; YouTubeError when they did not, or it no longer works. """
    if not configured():
        raise YouTubeError("connecting YouTube is not set up on this site (GOOGLE_CLIENT_SECRET)")
    kept = connection(session, owner)
    if kept is None:
        raise YouTubeError("YouTube is not connected: connect it first")
    answer = token_post({
        "client_id": client_id(),
        "client_secret": client_secret(),
        "refresh_token": unseal(kept.refresh_token),
        "grant_type": "refresh_token",
    })
    token = answer.get("access_token")
    if not isinstance(token, str) or not token:
        raise YouTubeError("Google did not issue an access token")
    return Client(token)


# the playlist of the videos the user liked, as channels.list names it
LIKES = "likes"


def my_playlists(client: Client) -> list[tuple[str, str]]:
    """ The user's playlists, (id, title), by title; their liked videos first, as "Liked videos". """
    found: list[tuple[str, str]] = []
    for channel in client.items("channels", part="contentDetails", mine="true"):
        likes = ((channel.get("contentDetails") or {}).get("relatedPlaylists") or {}).get(LIKES)
        if likes:
            found.append((likes, "Liked videos"))
    playlists = [
        (item["id"], (item.get("snippet") or {}).get("title") or item["id"])
        for item in client.items("playlists", part="snippet", mine="true")
    ]
    return found + sorted(playlists, key=lambda p: p[1].casefold())


def channel_title(client: Client) -> str:
    for channel in client.items("channels", part="snippet", mine="true"):
        return (channel.get("snippet") or {}).get("title") or ""
    return ""


def playlist_video_ids(client: Client, playlist_id: str) -> list[str]:
    """ The ids of the videos of a playlist, in its order, each once. """
    ids: dict[str, None] = {}
    for item in client.items("playlistItems", part="contentDetails", playlistId=playlist_id):
        video = (item.get("contentDetails") or {}).get("videoId")
        if video:
            ids[video] = None
    return list(ids)


ISO_DURATION = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?")


def seconds(duration: str) -> int | None:
    """ An ISO 8601 duration as YouTube gives it ("PT1H2M3S") in seconds; None for none or nought (a live stream). """
    found = ISO_DURATION.fullmatch(duration or "")
    if found is None:
        return None
    days, hours, minutes, secs = (int(part or 0) for part in found.groups())
    total = ((days * 24 + hours) * 60 + minutes) * 60 + secs
    return total or None


def video_details(client: Client, ids: list[str]) -> dict[str, dict[str, Any]]:
    """
    What YouTube says of each video it still has, by id, as YouTubeVideo
    columns (name, channel, category, duration, uploaded, views); a video it
    no longer has (deleted, private) is not there.
    """
    found: dict[str, dict[str, Any]] = {}
    for start in range(0, len(ids), PAGE):
        chunk = ids[start:start + PAGE]
        for item in client.get("videos", part="snippet,contentDetails,statistics", id=",".join(chunk)).get("items") or []:
            snippet = item.get("snippet") or {}
            published = snippet.get("publishedAt") or ""
            views = (item.get("statistics") or {}).get("viewCount")
            found[item["id"]] = {
                "name": (snippet.get("title") or "")[:500],
                "channel": (snippet.get("channelTitle") or "")[:200],
                "category": snippet.get("categoryId") or "",
                "duration": seconds((item.get("contentDetails") or {}).get("duration") or ""),
                "uploaded": dt.date.fromisoformat(published[:10]) if published else None,
                "views": int(views) if views is not None else None,
            }
    # the categories come as numbers: one more call names them
    numbers = sorted({d["category"] for d in found.values() if d["category"]})
    names: dict[str, str] = {}
    for start in range(0, len(numbers), PAGE):
        for item in client.get("videoCategories", part="snippet", id=",".join(numbers[start:start + PAGE]), hl="en").get("items") or []:
            names[item["id"]] = (item.get("snippet") or {}).get("title") or ""
    for details in found.values():
        details["category"] = names.get(details["category"], "")[:100]
    return found


# ─── connecting ─────────────────────────────────────────────────────────────

def _callback_url() -> str:
    """ The callback registered with Google: always on the canonical host, as GitHub's is (auth._callback_url). """
    path = flask.url_for("youtube.callback")
    canonical = flask.current_app.config["CANONICAL_HOST"]
    if canonical:
        return f"https://{canonical}{path}"
    scheme = "https" if "K_SERVICE" in os.environ else None
    return flask.url_for("youtube.callback", _external=True, _scheme=scheme)


def _back(error: str = "") -> werkzeug.Response:
    """ To the Imports page, saying what went wrong when something did. """
    if not error:
        return flask.redirect(IMPORTS_PAGE)
    return flask.redirect(f"/library?{urllib.parse.urlencode({'youtube_error': error})}#imports")


@bp.route("/connect", methods=["GET"])
@auth.login_required
def connect() -> werkzeug.Response:
    if not configured():
        flask.abort(404)
    # the state names the host the connecting started on, for the callback to return to
    state = f"{secrets.token_urlsafe(32)}@{flask.request.host}"
    flask.session["youtube_state"] = state
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
    expected = flask.session.pop("youtube_state", "")
    if not expected or not hmac.compare_digest(expected, given):
        flask.abort(400, "OAuth state mismatch")
    user = auth.current_user()
    if user is None:
        return flask.redirect(flask.url_for("views.index"))
    code = flask.request.args.get("code", "")
    if not code:
        return _back("Connecting YouTube was cancelled")
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
            raise YouTubeError("Google did not give a refresh token")
        if SCOPE not in str(answer.get("scope", "")).split():
            raise YouTubeError("YouTube access was not granted: tick it on Google's consent screen")
        title = channel_title(Client(str(answer.get("access_token", ""))))
    except (YouTubeError, requests.RequestException, ValueError) as e:
        return _back(f"Connecting YouTube failed: {e}")
    db = flask.g.db
    kept = connection(db, user)
    if kept is None:
        kept = YouTubeConnection(owner_id=user.id)
        db.add(kept)
    kept.refresh_token = seal(refresh)
    kept.channel = title[:200]
    kept.connected_at = utcnow()
    db.commit()
    return _back()


@bp.route("/disconnect", methods=["POST"])
@auth.login_required
def disconnect() -> tuple[str, int]:
    db = flask.g.db
    kept = connection(db, flask.g.user)
    if kept is not None:
        with contextlib.suppress(YouTubeError):
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
        "channel": kept.channel if kept else "",
        "connected_at": kept.connected_at.isoformat() if kept else None,
    }


@bp.route("/status", methods=["GET"])
@auth.login_required
def status() -> flask.Response:
    return flask.jsonify(status_json(flask.g.db, flask.g.user))
