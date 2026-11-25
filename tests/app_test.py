"""
End to end tests of the myworld app through webtest.
"""

import re
import urllib.parse
from pathlib import Path

import pytest
import webtest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from myworld import auth, create_app
from myworld.models import EmailVerification, Login
from myworld.verification import VerificationError
from tests.conftest import FakeMailer, sign_in


def test_index_anonymous(app: webtest.TestApp) -> None:
    response = app.get("/")
    assert response.status_int == 200
    assert 'data-page="index"' in response.text


def test_static_assets(app: webtest.TestApp) -> None:
    assert app.get("/static/app.js").status_int == 200
    assert app.get("/static/style.css").status_int == 200


def test_version(app: webtest.TestApp) -> None:
    response = app.get("/app/version")
    assert response.status_int == 200
    for key in ("deploy_date", "git_describe", "built_at", "started_at", "revision"):
        assert key in response.json
    # when this server started, in UTC
    assert response.json["started_at"].endswith("+00:00")


def test_the_about_page_and_no_build_in_the_footers(app: webtest.TestApp) -> None:
    # the build serving is on the About page alone: the other pages are the same for every build
    about = app.get("/about")
    assert 'data-page="about"' in about.text
    assert 'id="about-facts"' in about.text
    for path in ("/", "/privacy", "/verify", "/about"):
        page = app.get(path).text
        assert 'id="build"' not in page
        assert 'href="/about"' in page


def test_favicon_ico_is_the_site_icon(app: webtest.TestApp) -> None:
    # clients that ask for /favicon.ico without reading the page get the icon the pages name
    response = app.get("/favicon.ico")
    assert response.content_type == "image/svg+xml"
    assert response.body == app.get("/static/favicon.svg").body
    assert "max-age=86400" in response.headers["Cache-Control"]


def test_health(app: webtest.TestApp) -> None:
    assert app.get("/app/health").json == {"status": "ok"}


def test_canonical_host_redirect(app: webtest.TestApp, engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CANONICAL_HOST", "myworld.example")
    canonical = webtest.TestApp(create_app(engine))
    # any other hostname (the run.app ones in practice) is sent to the custom domain, path and query kept
    response = canonical.get("/library?x=1", extra_environ={"HTTP_HOST": "myworld-123.us-central1.run.app"})
    assert response.status_int == 308
    assert response.location == "https://myworld.example/library?x=1"
    # the custom domain itself is served as usual
    response = canonical.get("/", extra_environ={"HTTP_HOST": "myworld.example"})
    assert response.status_int == 200
    # probes that address the service directly still get their answer
    response = canonical.get("/app/health", extra_environ={"HTTP_HOST": "myworld-123.us-central1.run.app"})
    assert response.json == {"status": "ok"}
    # an alias host is served as it is, and its links stay on it
    monkeypatch.setenv("ALIAS_HOSTS", "myworld.alias.example other.example")
    aliased = webtest.TestApp(create_app(engine))
    response = aliased.get("/", extra_environ={"HTTP_HOST": "myworld.alias.example"})
    assert response.status_int == 200
    assert 'content="http://myworld.alias.example/"' in response.text
    response = aliased.get("/library", extra_environ={"HTTP_HOST": "other.example"})
    assert (response.status_int, response.location) == (302, "/")
    response = aliased.get("/library", extra_environ={"HTTP_HOST": "stranger.example"})
    assert (response.status_int, response.location) == (308, "https://myworld.example/library")
    # unset in development, where the app answers on whatever host it is reached on
    assert app.get("/", extra_environ={"HTTP_HOST": "127.0.0.1:8080"}).status_int == 200


def test_config_anonymous(app: webtest.TestApp) -> None:
    config = app.get("/api/config").json
    assert config["user"] is None
    assert config["google_client_id"].endswith(".apps.googleusercontent.com")
    assert config["dev_login"] is False
    # films, series, albums and games come back with the data they are imported from
    assert list(config["kinds"]) == ["book"]
    assert "done" in config["statuses"]


def test_library_requires_login(app: webtest.TestApp) -> None:
    response = app.get("/library")
    assert response.status_int == 302
    assert response.location is not None
    assert response.location.endswith("/")
    app.get("/api/library-entries", status=401)
    app.post_json("/api/library-entries", {"kind": "book", "title": "x"}, status=401)


def test_pages_are_asked_for_again(app: webtest.TestApp) -> None:
    # the scripts are no-cache: a page kept from before a deploy would run them against old markup
    for path in ("/", "/privacy", "/verify", "/about"):
        assert app.get(path).headers["Cache-Control"] == "no-cache"
    sign_in(app)
    assert app.get("/library").headers["Cache-Control"] == "no-cache"


def test_login_rejects_csrf_mismatch(app: webtest.TestApp) -> None:
    app.set_cookie("g_csrf_token", "one")
    app.post("/auth/login", {"credential": "x", "g_csrf_token": "two"}, status=400)


def test_login_rejects_bad_token(app: webtest.TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(_token: str) -> dict[str, str]:
        raise ValueError("bad")
    monkeypatch.setattr(auth, "verify_google_token", reject)
    app.set_cookie("g_csrf_token", "csrf")
    app.post("/auth/login", {"credential": "x", "g_csrf_token": "csrf"}, status=401)


def test_login_then_index_redirects(app: webtest.TestApp) -> None:
    sign_in(app)
    assert app.get("/").status_int == 302
    assert app.get("/library").status_int == 200
    config = app.get("/api/config").json
    assert config["user"]["email"] == "alice@example.com"
    # the account panel: how this session signed in, and every way this person signs in
    assert config["user"]["method"] == "google"
    [login] = config["user"]["logins"]
    assert (login["method"], login["provider_id"], login["current"], login["email"]) == ("google", "1234567890", True, "")
    app.post("/auth/logout")
    assert app.get("/api/config").json["user"] is None


def test_dev_login_disabled_by_default(app: webtest.TestApp) -> None:
    app.post("/auth/dev-login", {"email": "x@y.z"}, status=404)


def test_dev_login(app: webtest.TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYWORLD_DEV_LOGIN", "1")
    assert app.get("/api/config").json["dev_login"] is True
    app.post("/auth/dev-login", {"email": "dev@example.com"}, status=302)
    assert app.get("/api/config").json["user"]["email"] == "dev@example.com"
    monkeypatch.setenv("K_SERVICE", "myworld")
    app.post("/auth/dev-login", {"email": "dev@example.com"}, status=404)


def test_add_edit_delete(app: webtest.TestApp) -> None:
    sign_in(app)
    assert app.get("/api/library-entries?kind=book").json == []

    response = app.post_json("/api/library-entries", {
        "kind": "book", "title": "Dune", "creator": "Frank Herbert", "year": "1965",
        "status": "done", "rating": 9, "finished_on": "2026-01-15", "notes": "spice",
    })
    assert response.status_int == 201
    entry = response.json
    assert entry["title"] == "Dune"
    assert entry["year"] == 1965
    assert entry["rating"] == 9
    assert entry["finished_on"] == "2026-01-15"
    work_id = entry["work_id"]

    [listed] = app.get("/api/library-entries?kind=book").json
    assert listed["work_id"] == work_id
    # films are not a collection (yet)
    app.get("/api/library-entries?kind=film", status=400)

    # adding the same work again updates the existing entry
    response = app.post_json("/api/library-entries", {"kind": "book", "title": "Dune", "creator": "Frank Herbert", "year": 1965, "rating": 10})
    assert response.status_int == 200
    assert response.json["work_id"] == work_id
    assert len(app.get("/api/library-entries").json) == 1

    updated = app.put_json(f"/api/library-entries/{work_id}", {"status": "abandoned", "rating": "", "notes": "gave up"}).json
    assert updated["status"] == "abandoned"
    assert updated["rating"] is None
    assert updated["notes"] == "gave up"

    app.delete(f"/api/library-entries/{work_id}", status=204)
    assert app.get("/api/library-entries").json == []
    app.delete(f"/api/library-entries/{work_id}", status=404)


def test_validation(app: webtest.TestApp) -> None:
    sign_in(app)
    bad = [
        {"kind": "book", "title": ""},
        {"kind": "scroll", "title": "x"},
        {"kind": "book", "title": "x", "rating": 11},
        {"kind": "book", "title": "x", "rating": "lots"},
        {"kind": "book", "title": "x", "status": "meh"},
        {"kind": "book", "title": "x", "finished_on": "yesterday"},
        {"kind": "book", "title": "x", "year": -3001},
        {"kind": "book", "title": ["x"]},
    ]
    for body in bad:
        response = app.post_json("/api/library-entries", body, status=400)
        assert "error" in response.json
    app.post("/api/library-entries", "not json", status=400)
    app.get("/api/library-entries?kind=scroll", status=400)


def test_users_are_isolated(app: webtest.TestApp) -> None:
    sign_in(app, sub="alice")
    entry = app.post_json("/api/library-entries", {"kind": "book", "title": "Alien", "creator": "Alan Dean Foster", "year": 1979}).json
    work_id = entry["work_id"]

    app.post("/auth/logout")
    sign_in(app, sub="bob")
    assert app.get("/api/library-entries").json == []
    # bob cannot touch alice's entry
    app.put_json(f"/api/library-entries/{work_id}", {"status": "done"}, status=404)
    app.delete(f"/api/library-entries/{work_id}", status=404)

    # bob adding the same book gets a work of his own: nothing is shared, and what he says of it is his
    entry = app.post_json("/api/library-entries", {"kind": "book", "title": "Alien", "creator": "Alan Dean Foster", "year": 1979, "rating": 7}).json
    assert entry["work_id"] != work_id
    assert entry["rating"] == 7
    entry = app.put_json(f"/api/library-entries/{entry['work_id']}", {"title": "Aliens", "year": 1986, "titles": [{"locale": "he", "title": "הנוסע השמיני"}]}).json
    assert (entry["title"], entry["year"]) == ("Aliens", 1986)
    app.post("/auth/logout")
    sign_in(app, sub="alice")
    [entry] = app.get("/api/library-entries").json
    assert (entry["work_id"], entry["title"], entry["year"], entry["titles"], entry["rating"]) == (work_id, "Alien", 1979, [], None)
    # and the languages count what alice says in them, not what bob does
    assert next(row for row in app.get("/api/locales").json if row["code"] == "he")["count"] == 0
    # an entry deleted takes its work with it: added again, it is a new one
    app.delete(f"/api/library-entries/{work_id}", status=204)
    again = app.post_json("/api/library-entries", {"kind": "book", "title": "Alien", "creator": "Alan Dean Foster", "year": 1979}).json
    assert again["work_id"] not in (work_id, entry["work_id"])


def test_work_ids_are_only_filled(app: webtest.TestApp) -> None:
    """ A work's catalog ids: a missing one is given, one it has is never changed; and another account's work is another row. """
    book = {"kind": "book", "title": "Solaris", "creator": "Stanislaw Lem", "year": 1961}
    sign_in(app, sub="alice")
    entry = app.post_json("/api/library-entries", {**book, "goodreads_id": "95558"}).json
    assert (entry["goodreads_id"], entry["simania_id"]) == ("95558", "")
    # added again: the empty id is filled in, the set one stays
    entry = app.post_json("/api/library-entries", {**book, "goodreads_id": "666", "simania_id": "1234"}, status=200).json
    assert (entry["goodreads_id"], entry["simania_id"]) == ("95558", "1234")

    app.post("/auth/logout")
    sign_in(app, sub="bob")
    # bob's Solaris is his own: it has the ids he gives it, not alice's
    entry = app.post_json("/api/library-entries", {**book, "goodreads_id": "666"}, status=201).json
    assert (entry["goodreads_id"], entry["simania_id"]) == ("666", "")

    app.post("/auth/logout")
    sign_in(app, sub="alice")
    [entry] = app.get("/api/library-entries").json
    assert (entry["goodreads_id"], entry["simania_id"]) == ("95558", "1234")


# ─── email and password, only for a mailed address ───────────────────────────

def mailed_token(mailer: FakeMailer, email: str) -> str:
    """ The token of the last link mailed to email. """
    link = [link for to, link in mailer.sent if to == email][-1]
    assert link.startswith("http://localhost/verify?token=")
    return link.split("token=")[1]


def register(app: webtest.TestApp, mailer: FakeMailer, email: str, password: str = "correct horse") -> webtest.TestResponse:
    """ Ask for a link, follow it, choose the password: signed in. """
    app.post_json("/auth/email/register", {"email": email})
    token = mailed_token(mailer, email.strip().lower())
    return app.post_json("/auth/email/password", {"token": token, "password": password})


def test_email_sign_up_needs_the_mailed_link(app: webtest.TestApp, mailer: FakeMailer, engine: Engine) -> None:
    """ Asking for an address gives no account and no way in: only the link's reader chooses the password. """
    assert app.get("/api/config").json["password_min_length"] == auth.PASSWORD_MIN_LENGTH
    response = app.post_json("/auth/email/register", {"email": "  Carol@Example.com "})
    assert "mailed a link to carol@example.com" in response.json["message"]
    assert [to for to, _ in mailer.sent] == ["carol@example.com"]
    # nothing to sign in to yet, nor a user
    assert app.get("/api/config").json["user"] is None
    app.post_json("/auth/email/login", {"email": "carol@example.com", "password": "correct horse"}, status=401)
    with Session(engine) as session:
        assert session.scalars(select(Login)).all() == []
    # the link's page says for which address, then the password is chosen
    token = mailed_token(mailer, "carol@example.com")
    assert app.get("/verify").status_int == 200
    assert app.post_json("/auth/email/verify", {"token": token}).json == {"email": "carol@example.com"}
    response = app.post_json("/auth/email/password", {"token": token, "password": "correct horse"})
    assert response.json["next"].endswith("/library")
    user = app.get("/api/config").json["user"]
    assert (user["email"], user["name"], user["method"]) == ("carol@example.com", "carol", "email")
    assert mailer.forgotten == ["carol@example.com"]
    # the link worked once
    app.post_json("/auth/email/password", {"token": token, "password": "another one"}, status=400)
    app.post("/auth/logout")
    app.post_json("/auth/email/login", {"email": "carol@example.com", "password": "correct horse"}, status=200)
    assert app.get("/api/config").json["user"]["email"] == "carol@example.com"


def test_email_bad_input(app: webtest.TestApp, mailer: FakeMailer) -> None:
    for body in ({"email": "not an email"}, {}, {"email": ["carol@example.com"]}):
        assert "error" in app.post_json("/auth/email/register", body, status=400).json
    app.post("/auth/email/register", "not json", status=400)
    assert not mailer.sent
    for token in ("", "forged", None):
        assert "link" in app.post_json("/auth/email/verify", {"token": token}, status=400).json["error"]
    app.post_json("/auth/email/register", {"email": "carol@example.com"})
    token = mailed_token(mailer, "carol@example.com")
    assert "8 characters" in app.post_json("/auth/email/password", {"token": token, "password": "short"}, status=400).json["error"]
    assert app.get("/api/config").json["user"] is None


def test_a_new_link_voids_the_old_and_waits_a_minute(app: webtest.TestApp, mailer: FakeMailer, engine: Engine) -> None:
    app.post_json("/auth/email/register", {"email": "carol@example.com"})
    first = mailed_token(mailer, "carol@example.com")
    # asking again at once mails nothing more
    app.post_json("/auth/email/register", {"email": "carol@example.com"})
    assert len(mailer.sent) == 1
    with Session(engine) as session:
        pending = session.get(EmailVerification, "carol@example.com")
        assert pending is not None
        pending.sent_at -= auth.RESEND_INTERVAL
        session.commit()
    app.post_json("/auth/email/register", {"email": "carol@example.com"})
    second = mailed_token(mailer, "carol@example.com")
    assert second != first
    app.post_json("/auth/email/verify", {"token": first}, status=400)
    app.post_json("/auth/email/verify", {"token": second}, status=200)
    # and a link works for a day
    with Session(engine) as session:
        pending = session.get(EmailVerification, "carol@example.com")
        assert pending is not None
        pending.sent_at -= auth.LINK_LIFETIME
        session.commit()
    assert "expired" in app.post_json("/auth/email/verify", {"token": second}, status=400).json["error"]


def test_email_login_rejects_wrong_credentials(app: webtest.TestApp, mailer: FakeMailer) -> None:
    register(app, mailer, "carol@example.com")
    app.post("/auth/logout")
    unknown = app.post_json("/auth/email/login", {"email": "nobody@example.com", "password": "correct horse"}, status=401)
    wrong = app.post_json("/auth/email/login", {"email": "carol@example.com", "password": "wrong horse"}, status=401)
    # the same message either way, so the form does not reveal which emails have accounts
    assert unknown.json["error"] == wrong.json["error"]
    assert app.get("/api/config").json["user"] is None


def test_mailed_address_joins_its_account(app: webtest.TestApp, mailer: FakeMailer) -> None:
    """ The address is proven, so the password joins the Google account of it: one person, one account. """
    sign_in(app)
    google_id = app.get("/api/config").json["user"]["id"]
    app.post("/auth/logout")
    register(app, mailer, "alice@example.com")
    user = app.get("/api/config").json["user"]
    assert (user["id"], user["method"]) == (google_id, "email")
    assert [login["method"] for login in user["logins"]] == ["email", "google"]


def test_forgotten_password_is_replaced_by_mail(app: webtest.TestApp, mailer: FakeMailer, engine: Engine) -> None:
    """ Asking for a link for an address with a login answers the same, and the link sets a new password. """
    register(app, mailer, "carol@example.com", "old password")
    app.post("/auth/logout")
    with Session(engine) as session:
        # past the minute between mails
        for pending in session.scalars(select(EmailVerification)):
            pending.sent_at -= auth.RESEND_INTERVAL
        session.commit()
    register(app, mailer, "carol@example.com", "new password")
    app.post("/auth/logout")
    app.post_json("/auth/email/login", {"email": "carol@example.com", "password": "old password"}, status=401)
    app.post_json("/auth/email/login", {"email": "carol@example.com", "password": "new password"}, status=200)


def test_mail_failure_is_said(app: webtest.TestApp, mailer: FakeMailer, monkeypatch: pytest.MonkeyPatch, engine: Engine) -> None:
    def fail(_email: str, _continue_url: str) -> None:
        raise VerificationError("down")
    monkeypatch.setattr(mailer, "send", fail)
    assert "could not be sent" in app.post_json("/auth/email/register", {"email": "carol@example.com"}, status=503).json["error"]
    with Session(engine) as session:
        assert session.get(EmailVerification, "carol@example.com") is None


def test_google_unverified_email_is_refused(app: webtest.TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    """ Google not vouching for the email: back to the sign-in page with why, and no account is made. """
    monkeypatch.setattr(auth, "verify_google_token", lambda token: {"sub": token, "email": "eve@example.com", "email_verified": False})
    app.set_cookie("g_csrf_token", "csrf")
    response = app.post("/auth/login", {"credential": "666", "g_csrf_token": "csrf"})
    assert response.status_int == 302
    assert response.location is not None
    assert "error=Google+did+not+confirm" in response.location
    assert app.get("/api/config").json["user"] is None


def test_mailed_address_reaches_the_data_of_its_account(app: webtest.TestApp, mailer: FakeMailer) -> None:
    """ The Google account's library is the library of the same address's email login. """
    sign_in(app)
    app.post_json("/api/library-entries", {"kind": "book", "title": "Dune"})
    app.post("/auth/logout")
    register(app, mailer, "alice@example.com")
    assert [entry["title"] for entry in app.get("/api/library-entries").json] == ["Dune"]


# ─── other providers ─────────────────────────────────────────────────────────

def test_providers_unconfigured(app: webtest.TestApp) -> None:
    config = app.get("/api/config").json
    assert config["providers"] == {"github": False}
    app.get("/auth/oauth/github", status=404)
    app.get("/auth/oauth/github/callback?code=x&state=y", status=404)
    app.get("/auth/oauth/facebook", status=404)


def configure_github(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_CLIENT_ID", "gh-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "gh-secret")


def test_oauth_start(app: webtest.TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    configure_github(monkeypatch)
    assert app.get("/api/config").json["providers"]["github"] is True
    response = app.get("/auth/oauth/github")
    assert response.status_int == 302
    assert response.location is not None
    assert response.location.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=gh-id" in response.location
    assert "redirect_uri=http%3A%2F%2Flocalhost%2Fauth%2Foauth%2Fgithub%2Fcallback" in response.location
    assert "state=" in response.location


def test_oauth_callback(app: webtest.TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    configure_github(monkeypatch)
    exchanged: list[tuple[str, str]] = []

    def fake_exchange(provider: auth.OAuthProvider, code: str, redirect_uri: str) -> str:
        exchanged.append((provider.key, code))
        assert redirect_uri.endswith("/auth/oauth/github/callback")
        return "access-token"

    def fake_claims(provider: auth.OAuthProvider, token: str) -> dict[str, str | bool]:
        assert (provider.key, token) == ("github", "access-token")
        return {"sub": "github:42", "email": "dave@example.com", "name": "Dave", "picture": "", "verified": True}

    monkeypatch.setattr(auth, "exchange_code", fake_exchange)
    monkeypatch.setattr(auth, "fetch_claims", fake_claims)

    # the state must be the one we handed out, and a failed attempt consumes it
    app.get("/auth/oauth/github/callback?code=abc&state=forged", status=400)
    app.get("/auth/oauth/github")
    app.get("/auth/oauth/github/callback?code=abc&state=forged", status=400)
    start = app.get("/auth/oauth/github")
    assert start.location is not None
    state = start.location.split("state=")[1].split("&")[0]
    response = app.get(f"/auth/oauth/github/callback?code=abc&state={state}")
    assert response.status_int == 302
    assert response.location is not None
    assert response.location.endswith("/library")
    assert exchanged == [("github", "abc")]
    user = app.get("/api/config").json["user"]
    assert {k: user[k] for k in ("id", "email", "name", "role", "method")} == {
        "id": 1, "email": "dave@example.com", "name": "Dave", "role": "user", "method": "github",
    }
    assert [(login["method"], login["provider_id"]) for login in user["logins"]] == [("github", "42")]


def test_oauth_from_alias_host(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    """ GitHub knows one callback URL, the canonical host's, which hands the answer back to the alias. """
    configure_github(monkeypatch)
    monkeypatch.setenv("CANONICAL_HOST", "myworld.example")
    monkeypatch.setenv("ALIAS_HOSTS", "myworld.alias.example")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    redirects: list[str] = []

    def fake_exchange(_provider: auth.OAuthProvider, _code: str, redirect_uri: str) -> str:
        redirects.append(redirect_uri)
        return "access-token"

    def fake_claims(_provider: auth.OAuthProvider, _token: str) -> dict[str, str | bool]:
        return {"sub": "github:42", "email": "dave@example.com", "name": "Dave", "picture": "", "verified": True}

    monkeypatch.setattr(auth, "exchange_code", fake_exchange)
    monkeypatch.setattr(auth, "fetch_claims", fake_claims)
    app = webtest.TestApp(create_app(engine))
    alias = {"HTTP_HOST": "myworld.alias.example"}
    canonical = {"HTTP_HOST": "myworld.example"}

    start = app.get("/auth/oauth/github", extra_environ=alias)
    assert start.location is not None
    assert "redirect_uri=https%3A%2F%2Fmyworld.example%2Fauth%2Foauth%2Fgithub%2Fcallback" in start.location
    state = start.location.split("state=")[1].split("&")[0]
    # GitHub answers on the canonical host, which passes the answer on untouched
    response = app.get(f"/auth/oauth/github/callback?code=abc&state={state}", extra_environ=canonical)
    assert response.status_int == 302
    assert response.location == f"https://myworld.alias.example/auth/oauth/github/callback?code=abc&state={urllib.parse.unquote(state)}"
    assert not redirects
    # a state naming a host that is not ours is never redirected to
    app.get("/auth/oauth/github/callback?code=abc&state=x@evil.example", extra_environ=canonical, status=400)
    # the alias checks the state it handed out and signs in there
    response = app.get(f"/auth/oauth/github/callback?code=abc&state={state}", extra_environ=alias)
    assert (response.status_int, response.location) == (302, "/library")
    assert redirects == ["https://myworld.example/auth/oauth/github/callback"]


def test_oauth_callback_failures_return_to_landing(app: webtest.TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    configure_github(monkeypatch)

    def failing_exchange(_provider: auth.OAuthProvider, _code: str, _redirect_uri: str) -> str:
        raise auth.OAuthError("nope")

    monkeypatch.setattr(auth, "exchange_code", failing_exchange)
    start = app.get("/auth/oauth/github")
    assert start.location is not None
    state = start.location.split("state=")[1].split("&")[0]
    # the user cancelled on GitHub: no code
    response = app.get(f"/auth/oauth/github/callback?state={state}&error=access_denied")
    assert response.status_int == 302
    assert response.location is not None
    assert "error=" in response.location
    assert "cancelled" in response.location

    start = app.get("/auth/oauth/github")
    assert start.location is not None
    state = start.location.split("state=")[1].split("&")[0]
    response = app.get(f"/auth/oauth/github/callback?code=abc&state={state}")
    assert response.status_int == 302
    assert response.location is not None
    assert "failed" in response.location
    assert app.get("/api/config").json["user"] is None


# ─── one person, many ways to sign in ────────────────────────────────────────

def github_as(monkeypatch: pytest.MonkeyPatch, app: webtest.TestApp, claims: dict[str, str | bool]) -> None:
    """ Go through GitHub's sign-in, GitHub saying claims. """
    configure_github(monkeypatch)
    monkeypatch.setattr(auth, "exchange_code", lambda _provider, _code, _redirect_uri: "token")
    monkeypatch.setattr(auth, "fetch_claims", lambda _provider, _token: claims)
    start = app.get("/auth/oauth/github")
    assert start.location is not None
    state = start.location.split("state=")[1].split("&")[0]
    app.get(f"/auth/oauth/github/callback?code=c&state={state}", status=302)


def test_logins_of_one_verified_email_are_one_account(app: webtest.TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in(app)
    first = app.get("/api/config").json["user"]
    app.post("/auth/logout")
    # GitHub vouches for the same address (any case): the same account, with both ways
    github_as(monkeypatch, app, {"sub": "github:7", "email": "Alice@Example.com", "name": "alice-gh", "picture": "", "verified": True})
    user = app.get("/api/config").json["user"]
    assert (user["id"], user["method"]) == (first["id"], "github")
    assert [(login["method"], login["current"]) for login in user["logins"]] == [("github", True), ("google", False)]
    # and Google again reaches it too
    app.post("/auth/logout")
    sign_in(app)
    assert [login["method"] for login in app.get("/api/config").json["user"]["logins"]] == ["google", "github"]


def github_as_location(app: webtest.TestApp, monkeypatch: pytest.MonkeyPatch, claims: dict[str, str | bool]) -> str:
    """ Go through GitHub's sign-in, GitHub saying claims; where it lands. """
    configure_github(monkeypatch)
    monkeypatch.setattr(auth, "exchange_code", lambda _provider, _code, _redirect_uri: "token")
    monkeypatch.setattr(auth, "fetch_claims", lambda _provider, _token: claims)
    start = app.get("/auth/oauth/github")
    assert start.location is not None
    state = start.location.split("state=")[1].split("&")[0]
    response = app.get(f"/auth/oauth/github/callback?code=c&state={state}", status=302)
    assert response.location is not None
    return response.location


def test_unverified_email_is_refused(app: webtest.TestApp, monkeypatch: pytest.MonkeyPatch, engine: Engine) -> None:
    """ An email the provider does not vouch for gets no account, nor into the account of that email. """
    sign_in(app)
    app.post("/auth/logout")
    unverified: list[dict[str, str | bool]] = [
        {"sub": "github:8", "email": "alice@example.com", "name": "x", "picture": "", "verified": False},
        {"sub": "github:9", "email": "", "name": "y", "picture": "", "verified": True},
    ]
    for claims in unverified:
        location = github_as_location(app, monkeypatch, claims)
        assert "error=GitHub+did+not+confirm" in location
        assert app.get("/api/config").json["user"] is None
    with Session(engine) as session:
        assert session.scalars(select(Login.subject)).all() == ["google:1234567890"]


def test_choose_a_name(app: webtest.TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in(app)
    user = app.put_json("/api/account/name", {"name": "  The   Reader "}).json
    assert user["name"] == "The Reader"
    assert app.get("/api/config").json["user"]["name"] == "The Reader"
    # nothing, too long, or unprintable is refused and changes nothing
    for bad in ("   ", "x" * 61, "tab\x07bell"):
        assert app.put_json("/api/account/name", {"name": bad}, status=400).json["error"]
    assert app.get("/api/config").json["user"]["name"] == "The Reader"
    # signing in again, any way, keeps the chosen name
    app.post("/auth/logout")
    github_as(monkeypatch, app, {"sub": "github:9", "email": "alice@example.com", "name": "alice-gh", "picture": "", "verified": True})
    assert app.get("/api/config").json["user"]["name"] == "The Reader"


def test_choosing_a_name_needs_a_session(app: webtest.TestApp) -> None:
    app.put_json("/api/account/name", {"name": "Nobody"}, status=401)


def test_shared_link_card(app: webtest.TestApp) -> None:
    page = app.get("/", headers={"X-Forwarded-Proto": "https"}).text
    assert '<meta property="og:image" content="https://localhost/static/social-card.png">' in page
    assert "__ORIGIN__" not in page
    assert app.get("/static/social-card.png").content_type == "image/png"


def test_every_dialog_field_has_balloon_help() -> None:
    """ Every field of every dialog says what it means when the mouse rests on it: its label has a title. """
    page = (Path(__file__).parent.parent / "src" / "myworld" / "html" / "library.html").read_text(encoding="utf-8")
    forms = re.findall(r'<form id="([^"]+)"(.*?)</form>', page, flags=re.DOTALL)
    assert len(forms) > 15
    bare = [(form, label) for form, body in forms for label in re.findall(r"<label\b[^>]*>", body) if not re.search(r'\btitle="[^"]{10,}"', label)]
    assert not bare, bare
    # and the one the request began with
    assert "The year the book was released in" in page


def test_what_adds_to_a_list_comes_in_with_its_plus() -> None:
    """ In every dialog a row to add something with (a title, a read, a name, a relation, a picture) is hidden until the + of its list. """
    page = (Path(__file__).parent.parent / "src" / "myworld" / "html" / "library.html").read_text(encoding="utf-8")
    adders = re.findall(r'<div class="(?:row )?adder"[^>]*>', page)
    assert len(adders) >= 15
    assert all(re.search(r"\bhidden\b", adder) for adder in adders), adders
    # a file is only ever chosen in such a row, under the pictures there are
    for form, body in re.findall(r'<form id="([^"]+)"(.*?)</form>', page, flags=re.DOTALL):
        files = body.count('type="file"')
        assert files == body.count("data-picture-adder hidden") == body.count("data-pictures="), form
        assert files == 0 or body.index("data-pictures=") < body.index("data-picture-adder") < body.index('type="file"'), form
    # the book's lists, and a city's photos
    for row in ("book-title-row", "person-relation-row", "person-organization-row"):
        assert f'<div class="row adder" id="{row}" hidden>' in page
    # a reading has several rows: its status, rating and language, its days, its review
    assert '<div class="adder" id="book-read-row" hidden>' in page
    # so has a name: its language and its parts
    assert '<div class="adder" id="person-name-row" hidden>' in page
    assert page.count('data-pictures="many"') == 3
