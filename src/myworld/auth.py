"""
Sign-in: Google first, plus email and password and OAuth with other
providers.

Google uses Google Identity Services: the browser side is the standard GIS
button (see html/index.html): on success Google POSTs a signed ID token to
/auth/login together with a CSRF token that is also set as a cookie. The
server checks the two CSRF copies match, verifies the ID token signature
and audience with google-auth, and then keeps only our own user id in the
Flask session cookie.

Email accounts live entirely in our users table (werkzeug password
hashes). Other providers (GitHub so far) go through the plain OAuth 2.0
authorization code flow: /auth/oauth/<provider> redirects to the
provider, the callback exchanges the code for an access token and asks the
provider who the user is. A provider is offered only when its client id
and secret are set in the environment.

Users are matched by a provider-qualified subject (see User.google_sub),
never by email, since emails can change and be reassigned.
"""

import dataclasses
import functools
import hmac
import os
import secrets
import urllib.parse
from collections.abc import Callable
from typing import Any

import flask
import requests
import werkzeug
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash, generate_password_hash

from myworld.models import User

bp = flask.Blueprint("auth", __name__, url_prefix="/auth")

PASSWORD_MIN_LENGTH = 8
HTTP_TIMEOUT = 10


def client_id() -> str:
    return os.environ.get("GOOGLE_CLIENT_ID", "")


def dev_login_enabled() -> bool:
    """
    Local development without an OAuth client: /auth/dev-login signs in as
    any email. Only when MYWORLD_DEV_LOGIN=1 is set, and never on Cloud Run
    (which always sets K_SERVICE).
    """
    return os.environ.get("MYWORLD_DEV_LOGIN") == "1" and "K_SERVICE" not in os.environ


def verify_google_token(token: str) -> dict[str, Any]:
    """ Return the verified claims of a Google ID token, raising ValueError otherwise. """
    audience = client_id()
    if not audience:
        raise ValueError("GOOGLE_CLIENT_ID is not configured")
    return id_token.verify_oauth2_token(token, google_requests.Request(), audience)


def get_or_create_user(session: Session, claims: dict[str, Any]) -> User:
    user = session.query(User).filter_by(google_sub=claims["sub"]).one_or_none()
    if user is None:
        user = User(google_sub=claims["sub"])
        session.add(user)
    user.email = claims.get("email", "")
    user.name = claims.get("name", "")
    user.picture = claims.get("picture", "")
    session.commit()
    return user


def current_user() -> User | None:
    user_id = flask.session.get("user_id")
    if user_id is None:
        return None
    return flask.g.db.get(User, user_id)


def start_session(user: User) -> None:
    flask.session.clear()
    flask.session["user_id"] = user.id


def login_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        user = current_user()
        if user is None:
            return flask.jsonify({"error": "sign in first"}), 401
        flask.g.user = user
        return view(*args, **kwargs)
    return wrapped


@bp.errorhandler(werkzeug.exceptions.HTTPException)
def handle_http_error(error: werkzeug.exceptions.HTTPException) -> werkzeug.Response | tuple[flask.Response, int]:
    """ The email form talks JSON (fetch from app.js); the other routes are browser navigations. """
    if flask.request.path.startswith("/auth/email/"):
        return flask.jsonify({"error": error.description}), error.code or 500
    return error.get_response()


# ─── google ──────────────────────────────────────────────────────────────────

@bp.route("/login", methods=["POST"])
def login() -> werkzeug.Response:
    csrf_cookie = flask.request.cookies.get("g_csrf_token", "")
    csrf_body = flask.request.form.get("g_csrf_token", "")
    if not csrf_cookie or not hmac.compare_digest(csrf_cookie, csrf_body):
        flask.abort(400, "CSRF token mismatch")
    try:
        claims = verify_google_token(flask.request.form.get("credential", ""))
    except ValueError:
        flask.abort(401, "Invalid Google sign-in token")
    user = get_or_create_user(flask.g.db, claims)
    start_session(user)
    return flask.redirect(flask.url_for("views.library"))


# ─── email and password ──────────────────────────────────────────────────────

def _email_credentials() -> tuple[str, str]:
    """ The (email, password) pair from the JSON body, validated for shape only. """
    body = flask.request.get_json(silent=True)
    if not isinstance(body, dict):
        flask.abort(400, "expected a JSON object")
    email = body.get("email")
    password = body.get("password")
    if not isinstance(email, str) or not isinstance(password, str):
        flask.abort(400, "email and password are required")
    email = email.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@") or " " in email:
        flask.abort(400, "that does not look like an email address")
    return email, password


def _email_user(email: str) -> User | None:
    return flask.g.db.query(User).filter_by(google_sub=f"email:{email}").one_or_none()


def _signed_in(user: User) -> flask.Response:
    start_session(user)
    return flask.jsonify({"next": flask.url_for("views.library")})


@bp.route("/email/register", methods=["POST"])
def email_register() -> flask.Response:
    email, password = _email_credentials()
    if len(password) < PASSWORD_MIN_LENGTH:
        flask.abort(400, f"use at least {PASSWORD_MIN_LENGTH} characters for the password")
    if _email_user(email) is not None:
        flask.abort(409, "there is already an account with this email, sign in instead")
    user = User(
        google_sub=f"email:{email}",
        email=email,
        name=email.split("@")[0],
        password_hash=generate_password_hash(password),
    )
    flask.g.db.add(user)
    flask.g.db.commit()
    return _signed_in(user)


@bp.route("/email/login", methods=["POST"])
def email_login() -> flask.Response:
    email, password = _email_credentials()
    user = _email_user(email)
    # one message for both failures, so the form does not reveal which emails have accounts
    if user is None or user.password_hash is None or not check_password_hash(user.password_hash, password):
        flask.abort(401, "wrong email or password")
    return _signed_in(user)


# ─── other providers (oauth 2.0 authorization code) ─────────────────────────

@dataclasses.dataclass(frozen=True)
class OAuthProvider:
    key: str
    name: str
    authorize_url: str
    token_url: str
    userinfo_url: str
    scope: str

    @property
    def client_id(self) -> str:
        return os.environ.get(f"{self.key.upper()}_CLIENT_ID", "")

    @property
    def client_secret(self) -> str:
        return os.environ.get(f"{self.key.upper()}_CLIENT_SECRET", "")

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)


OAUTH_PROVIDERS: dict[str, OAuthProvider] = {
    "github": OAuthProvider(
        key="github",
        name="GitHub",
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        userinfo_url="https://api.github.com/user",
        scope="read:user user:email",
    ),
}


class OAuthError(Exception):
    pass


def _provider(key: str) -> OAuthProvider:
    provider = OAUTH_PROVIDERS.get(key)
    if provider is None or not provider.configured:
        flask.abort(404)
    return provider


def _callback_url(provider: OAuthProvider) -> str:
    # Cloud Run terminates TLS in front of the app, so build the https URL by hand there.
    scheme = "https" if "K_SERVICE" in os.environ else None
    return flask.url_for("auth.oauth_callback", provider=provider.key, _external=True, _scheme=scheme)


def exchange_code(provider: OAuthProvider, code: str, redirect_uri: str) -> str:
    """ Trade the authorization code for an access token. """
    response = requests.post(
        provider.token_url,
        data={
            "client_id": provider.client_id,
            "client_secret": provider.client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        headers={"Accept": "application/json"},
        timeout=HTTP_TIMEOUT,
    )
    token = response.json().get("access_token") if response.ok else None
    if not isinstance(token, str) or not token:
        raise OAuthError(f"{provider.name} did not issue an access token")
    return token


def fetch_claims(provider: OAuthProvider, token: str) -> dict[str, Any]:
    """ Ask the provider who the token belongs to, normalised to the Google claim names. """
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    response = requests.get(provider.userinfo_url, headers=headers, timeout=HTTP_TIMEOUT)
    if not response.ok:
        raise OAuthError(f"{provider.name} did not tell us who you are")
    info = response.json()
    # GitHub is the only provider so far; a second one gets its own branch here.
    email = info.get("email") or ""
    if not email:
        # the profile email is only public if the user chose so; the emails endpoint is not
        emails = requests.get(f"{provider.userinfo_url}/emails", headers=headers, timeout=HTTP_TIMEOUT)
        if emails.ok:
            email = next((e["email"] for e in emails.json() if e.get("primary") and e.get("verified")), "")
    return {
        "sub": f"{provider.key}:{info['id']}",
        "email": email,
        "name": info.get("name") or info.get("login") or "",
        "picture": info.get("avatar_url") or "",
    }


@bp.route("/oauth/<provider>", methods=["GET"])
def oauth_start(provider: str) -> werkzeug.Response:
    oauth = _provider(provider)
    state = secrets.token_urlsafe(32)
    flask.session["oauth_state"] = state
    params = {
        "client_id": oauth.client_id,
        "redirect_uri": _callback_url(oauth),
        "response_type": "code",
        "scope": oauth.scope,
        "state": state,
    }
    return flask.redirect(f"{oauth.authorize_url}?{urllib.parse.urlencode(params)}")


@bp.route("/oauth/<provider>/callback", methods=["GET"])
def oauth_callback(provider: str) -> werkzeug.Response:
    oauth = _provider(provider)
    expected = flask.session.pop("oauth_state", "")
    given = flask.request.args.get("state", "")
    if not expected or not hmac.compare_digest(expected, given):
        flask.abort(400, "OAuth state mismatch")
    code = flask.request.args.get("code", "")
    if not code:
        # the user said no on the provider's consent screen
        return flask.redirect(flask.url_for("views.index", error=f"{oauth.name} sign-in was cancelled"))
    try:
        token = exchange_code(oauth, code, _callback_url(oauth))
        claims = fetch_claims(oauth, token)
    except (OAuthError, requests.RequestException, ValueError, KeyError):
        return flask.redirect(flask.url_for("views.index", error=f"{oauth.name} sign-in failed, try again"))
    user = get_or_create_user(flask.g.db, claims)
    start_session(user)
    return flask.redirect(flask.url_for("views.library"))


# ─── development ─────────────────────────────────────────────────────────────

@bp.route("/dev-login", methods=["POST"])
def dev_login() -> werkzeug.Response:
    if not dev_login_enabled():
        flask.abort(404)
    email = flask.request.form.get("email", "").strip().lower()
    if not email:
        flask.abort(400, "email is required")
    claims = {"sub": f"dev:{email}", "email": email, "name": email.split("@")[0]}
    user = get_or_create_user(flask.g.db, claims)
    start_session(user)
    return flask.redirect(flask.url_for("views.library"))


@bp.route("/logout", methods=["POST"])
def logout() -> werkzeug.Response:
    flask.session.clear()
    return flask.redirect(flask.url_for("views.index"))
