"""
"Sign in with Google" using Google Identity Services.

The browser side is the standard GIS button (see templates/index.html): on
success Google POSTs a signed ID token to /auth/login together with a CSRF
token that is also set as a cookie. The server checks the two CSRF copies
match, verifies the ID token signature and audience with google-auth, and
then keeps only our own user id in the Flask session cookie.

Users are matched by the Google "sub" claim, never by email, since emails
can change and be reassigned.
"""

import functools
import hmac
import os
from collections.abc import Callable
from typing import Any

import flask
import werkzeug
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from sqlalchemy.orm import Session

from myworld.models import User

bp = flask.Blueprint("auth", __name__, url_prefix="/auth")


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


def login_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        user = current_user()
        if user is None:
            return flask.jsonify({"error": "sign in first"}), 401
        flask.g.user = user
        return view(*args, **kwargs)
    return wrapped


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
    flask.session.clear()
    flask.session["user_id"] = user.id
    return flask.redirect(flask.url_for("views.library"))


@bp.route("/dev-login", methods=["POST"])
def dev_login() -> werkzeug.Response:
    if not dev_login_enabled():
        flask.abort(404)
    email = flask.request.form.get("email", "").strip().lower()
    if not email:
        flask.abort(400, "email is required")
    claims = {"sub": f"dev:{email}", "email": email, "name": email.split("@")[0]}
    user = get_or_create_user(flask.g.db, claims)
    flask.session.clear()
    flask.session["user_id"] = user.id
    return flask.redirect(flask.url_for("views.library"))


@bp.route("/logout", methods=["POST"])
def logout() -> werkzeug.Response:
    flask.session.clear()
    return flask.redirect(flask.url_for("views.index"))
