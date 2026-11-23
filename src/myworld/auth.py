"""
Sign-in: Google first, plus email and password and OAuth with other
providers. Only a proven email gets an account: one the provider vouches
for, or for email sign-in one whose mailed link was followed. An address
merely typed into a form proves nothing and can be used for nothing.

Google uses Google Identity Services: the browser side is the standard GIS
button (see html/index.html): on success Google POSTs a signed ID token to
/auth/login together with a CSRF token that is also set as a cookie. The
server checks the two CSRF copies match, verifies the ID token signature
and audience with google-auth, and then keeps only our own user id in the
Flask session cookie.

Email sign-up asks for the address only and mails it a link (see
verification.py); the link leads to a page where its reader chooses the
password, which makes the email login. So only whoever reads the mailbox
ever sets a password for the address: had sign-up taken one, anyone could
register someone's address with a password of their own and get in once
its owner clicked the link. Asking again for an address that has a login
mails a link the same way, which is how a forgotten password is replaced.

Other providers (GitHub so far) go through the plain OAuth 2.0
authorization code flow: /auth/oauth/<provider> redirects to the
provider, the callback exchanges the code for an access token and asks the
provider who the user is. A provider is offered only when its client id
and secret are set in the environment.

Each way of signing in is a login (models.Login), found by its
provider-qualified subject, never by email, since emails can change and be
reassigned. A login leads to its user, the person, who is the same
whichever way they signed in: a login joins the user of its email,
which is proven (see sign_in). The Flask session holds
only the login's id.
"""

import dataclasses
import datetime
import functools
import hashlib
import hmac
import logging
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
from sqlalchemy import select
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash, generate_password_hash

from myworld.models import ROLE_ADMIN, EmailVerification, Login, User, utcnow
from myworld.verification import Mailer, VerificationError

bp = flask.Blueprint("auth", __name__, url_prefix="/auth")

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 10
PASSWORD_MIN_LENGTH = 8
# how long a mailed link works, and how soon another may be mailed to the same address
LINK_LIFETIME = datetime.timedelta(days=1)
RESEND_INTERVAL = datetime.timedelta(minutes=1)
# what the sign-in page says when the provider does not vouch for the email
UNVERIFIED = "{provider} did not confirm an email address for you: verify one with {provider} and sign in again"


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
    return dict(id_token.verify_oauth2_token(token, google_requests.Request(), audience))


class UnverifiedEmailError(Exception):
    """ The provider does not vouch for the person's email, so they get no account. """


def sign_in(session: Session, claims: dict[str, Any], password_hash: str | None = None) -> Login:
    """
    Find or make the login of claims["sub"] (provider-qualified), refresh
    what the provider reports (email, name, picture), and give it its user
    when it has none: the user of its email, made on first sight. A login
    keeps the user it joined. Only a proven email (claims["verified"]) is
    accepted: else UnverifiedEmailError, and nothing is stored. Commits;
    returns the login.
    """
    email = str(claims.get("email", "")).strip().lower()
    if not claims.get("verified") or not email:
        raise UnverifiedEmailError(claims["sub"])
    login = session.scalars(select(Login).where(Login.subject == claims["sub"])).one_or_none()
    now = utcnow()
    if login is None:
        login = Login(subject=claims["sub"], created_at=now)
        session.add(login)
    login.email = email
    login.name = claims.get("name", "") or ""
    login.picture = claims.get("picture", "") or ""
    if password_hash is not None:
        login.password_hash = password_hash
    login.last_login = now
    if login.user is None:
        # a new login is not flushed before it has its user
        with session.no_autoflush:
            user = session.scalars(select(User).where(User.email == email)).one_or_none()
        if user is None:
            user = User(email=email, name=login.name or email.split("@")[0], picture=login.picture, created_at=now)
            session.add(user)
        login.user = user
    user = login.user
    user.name = user.name or login.name
    user.picture = user.picture or login.picture
    user.last_login = now
    session.commit()
    return login


def current_login() -> Login | None:
    """ The login this session came through, or None when signed out. """
    login_id = flask.session.get("login_id")
    if login_id is None:
        return None
    login: Login | None = flask.g.db.get(Login, login_id)
    return login


def current_user() -> User | None:
    login = current_login()
    return None if login is None else login.user


def start_session(login: Login) -> None:
    flask.session.clear()
    flask.session["login_id"] = login.id


def login_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        user = current_user()
        if user is None:
            return flask.jsonify({"error": "sign in first"}), 401
        flask.g.user = user
        return view(*args, **kwargs)
    return wrapped


def admin_required(view: Callable[..., Any]) -> Callable[..., Any]:
    """ Like login_required, for what only an admin (users.role) may do. """
    @functools.wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        user = current_user()
        if user is None:
            return flask.jsonify({"error": "sign in first"}), 401
        if user.role != ROLE_ADMIN:
            return flask.jsonify({"error": "only an admin may do this"}), 403
        flask.g.user = user
        return view(*args, **kwargs)
    return wrapped


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
    try:
        login = sign_in(flask.g.db, {
            "sub": f"google:{claims['sub']}", "email": claims.get("email", ""), "name": claims.get("name", ""),
            "picture": claims.get("picture", ""), "verified": bool(claims.get("email_verified")),
        })
    except UnverifiedEmailError:
        return flask.redirect(flask.url_for("views.index", error=UNVERIFIED.format(provider="Google")))
    start_session(login)
    return flask.redirect(flask.url_for("views.library"))


# ─── email and password ──────────────────────────────────────────────────────

@bp.errorhandler(werkzeug.exceptions.HTTPException)
def handle_http_error(error: werkzeug.exceptions.HTTPException) -> werkzeug.Response | tuple[flask.Response, int]:
    """ The email forms talk JSON (fetch from app.js); the other routes are browser navigations. """
    if flask.request.path.startswith("/auth/email/"):
        return flask.jsonify({"error": error.description}), error.code or 500
    return error.get_response()


def mailer() -> Mailer:
    """ What mails the verification links (verification.IdentityPlatform on Cloud Run). """
    sender: Mailer = flask.current_app.config["MAILER"]
    return sender


def _body() -> dict[str, Any]:
    body = flask.request.get_json(silent=True)
    if not isinstance(body, dict):
        flask.abort(400, "expected a JSON object")
    return body


def _email(body: dict[str, Any]) -> str:
    """ The address in the body, validated for shape only. """
    email = body.get("email")
    if not isinstance(email, str):
        flask.abort(400, "an email address is required")
    email = email.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@") or " " in email or len(email) > 320:
        flask.abort(400, "that does not look like an email address")
    return email


def _age(moment: datetime.datetime) -> datetime.timedelta:
    """ How long ago moment was; the database hands back UTC without its zone. """
    return utcnow() - (moment if moment.tzinfo else moment.replace(tzinfo=datetime.UTC))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _pending(token: object) -> EmailVerification:
    """ The verification a link's token belongs to, while the link still works; else 400. """
    if not isinstance(token, str) or not token:
        flask.abort(400, "this link is not complete: open the one in the mail")
    pending: EmailVerification | None = flask.g.db.scalars(
        select(EmailVerification).where(EmailVerification.token_hash == _token_hash(token))
    ).one_or_none()
    if pending is None or _age(pending.sent_at) > LINK_LIFETIME:
        flask.abort(400, "this link was used or has expired: ask for a new one")
    return pending


def _verify_url(token: str) -> str:
    # Cloud Run terminates TLS in front of the app, so build the https URL by hand there.
    scheme = "https" if "K_SERVICE" in os.environ else None
    return flask.url_for("views.verify", token=token, _external=True, _scheme=scheme)


@bp.route("/email/register", methods=["POST"])
def email_register() -> flask.Response:
    """
    Mail the address a link to choose a password with. The answer is the
    same whether or not the address has an account, so the form does not
    reveal who signs in here.
    """
    email = _email(_body())
    sent = f"We mailed a link to {email}. Open it to choose your password; until then the address cannot sign in."
    pending = flask.g.db.get(EmailVerification, email)
    now = utcnow()
    if pending is not None and _age(pending.sent_at) < RESEND_INTERVAL:
        return flask.jsonify({"message": sent})
    token = secrets.token_urlsafe(32)
    try:
        mailer().send(email, _verify_url(token))
    except (VerificationError, requests.RequestException, ValueError) as error:
        logger.warning("verification mail to %s failed: %s", email, error)
        flask.abort(503, "the mail could not be sent: try again in a minute")
    if pending is None:
        pending = EmailVerification(email=email)
        flask.g.db.add(pending)
    # a new link voids the one mailed before
    pending.token_hash = _token_hash(token)
    pending.sent_at = now
    flask.g.db.commit()
    return flask.jsonify({"message": sent})


@bp.route("/email/verify", methods=["POST"])
def email_verify() -> flask.Response:
    """ Which address a link is for, so its page can say so before asking for the password. """
    return flask.jsonify({"email": _pending(_body().get("token")).email})


@bp.route("/email/password", methods=["POST"])
def email_password() -> flask.Response:
    """
    The link's reader chooses the password: the address is proven, so this
    makes (or gives a new password to) its email login, which joins the
    account of the address, and signs in.
    """
    body = _body()
    pending = _pending(body.get("token"))
    password = body.get("password")
    if not isinstance(password, str) or len(password) < PASSWORD_MIN_LENGTH:
        flask.abort(400, f"use at least {PASSWORD_MIN_LENGTH} characters for the password")
    email = pending.email
    flask.g.db.delete(pending)
    login = sign_in(flask.g.db, {"sub": f"email:{email}", "email": email, "name": email.split("@")[0], "verified": True},
                    password_hash=generate_password_hash(password))
    try:
        mailer().forget(email)
    except (VerificationError, requests.RequestException, ValueError) as error:
        logger.warning("could not clean up after verifying %s: %s", email, error)
    start_session(login)
    return flask.jsonify({"next": flask.url_for("views.library")})


@bp.route("/email/login", methods=["POST"])
def email_login() -> flask.Response:
    body = _body()
    email = _email(body)
    password = body.get("password")
    login: Login | None = flask.g.db.scalars(select(Login).where(Login.subject == f"email:{email}")).one_or_none()
    # one message for every failure, so the form does not reveal which emails have accounts
    if login is None or login.password_hash is None or not isinstance(password, str) or not check_password_hash(login.password_hash, password):
        flask.abort(401, "wrong email or password (a new address signs in only after you open the link we mailed it)")
    login.last_login = login.user.last_login = utcnow()
    flask.g.db.commit()
    start_session(login)
    return flask.jsonify({"next": flask.url_for("views.library")})


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
    """
    The callback registered with the provider. A GitHub OAuth app takes one
    callback URL only, so it is always the one on the canonical host, also
    for a sign-in that started on an alias host: oauth_callback hands that
    one back to where it started.
    """
    path = flask.url_for("auth.oauth_callback", provider=provider.key)
    canonical = flask.current_app.config["CANONICAL_HOST"]
    if canonical:
        return f"https://{canonical}{path}"
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
    # Only the verified primary address counts: the profile email is whatever
    # the user typed there and is not necessarily verified.
    email = ""
    emails = requests.get(f"{provider.userinfo_url}/emails", headers=headers, timeout=HTTP_TIMEOUT)
    if emails.ok:
        email = next((e["email"] for e in emails.json() if e.get("primary") and e.get("verified")), "")
    return {
        "sub": f"{provider.key}:{info['id']}",
        "email": email,
        "name": info.get("name") or info.get("login") or "",
        "picture": info.get("avatar_url") or "",
        "verified": bool(email),
    }


@bp.route("/oauth/<provider>", methods=["GET"])
def oauth_start(provider: str) -> werkzeug.Response:
    oauth = _provider(provider)
    # the state names the host the sign-in started on, for oauth_callback to return to
    state = f"{secrets.token_urlsafe(32)}@{flask.request.host}"
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
    given = flask.request.args.get("state", "")
    # A sign-in that started on an alias host comes back to the canonical one (_callback_url),
    # where its session is not: pass the answer on to the alias, which holds the state to
    # check it against. Only our own alias hosts are ever redirected to.
    started_on = given.rpartition("@")[2]
    config = flask.current_app.config
    if flask.request.host == config["CANONICAL_HOST"] and started_on in config["ALIAS_HOSTS"]:
        return flask.redirect(urllib.parse.urlsplit(flask.request.url)._replace(scheme="https", netloc=started_on).geturl())
    expected = flask.session.pop("oauth_state", "")
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
    try:
        login = sign_in(flask.g.db, claims)
    except UnverifiedEmailError:
        return flask.redirect(flask.url_for("views.index", error=UNVERIFIED.format(provider=oauth.name)))
    start_session(login)
    return flask.redirect(flask.url_for("views.library"))


# ─── development ─────────────────────────────────────────────────────────────

@bp.route("/dev-login", methods=["POST"])
def dev_login() -> werkzeug.Response:
    if not dev_login_enabled():
        flask.abort(404)
    email = flask.request.form.get("email", "").strip().lower()
    if not email:
        flask.abort(400, "email is required")
    # local only: the address typed is taken as proven, so joining can be tried out
    start_session(sign_in(flask.g.db, {"sub": f"dev:{email}", "email": email, "name": email.split("@")[0], "verified": True}))
    return flask.redirect(flask.url_for("views.library"))


@bp.route("/logout", methods=["POST"])
def logout() -> werkzeug.Response:
    flask.session.clear()
    return flask.redirect(flask.url_for("views.index"))
