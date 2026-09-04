"""
End to end tests of the myworld app through webtest.
"""

import pytest
import webtest

from myworld import auth
from tests.conftest import sign_in


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
    for key in ("deploy_date", "git_describe", "revision"):
        assert key in response.json


def test_health(app: webtest.TestApp) -> None:
    assert app.get("/app/health").json == {"status": "ok"}


def test_config_anonymous(app: webtest.TestApp) -> None:
    config = app.get("/api/config").json
    assert config["user"] is None
    assert config["google_client_id"].endswith(".apps.googleusercontent.com")
    assert config["dev_login"] is False
    assert list(config["kinds"]) == ["book", "film", "series", "album", "game"]
    assert config["kinds"]["series"]["plural"] == "Series"
    assert "done" in config["statuses"]


def test_library_requires_login(app: webtest.TestApp) -> None:
    response = app.get("/library")
    assert response.status_int == 302
    assert response.location is not None
    assert response.location.endswith("/")
    app.get("/api/library", status=401)
    app.post_json("/api/library", {"kind": "book", "title": "x"}, status=401)


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
    assert app.get("/api/library?kind=book").json == []

    response = app.post_json("/api/library", {
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

    [listed] = app.get("/api/library?kind=book").json
    assert listed["work_id"] == work_id
    # films are a separate shelf
    assert app.get("/api/library?kind=film").json == []

    # adding the same work again updates the existing entry
    response = app.post_json("/api/library", {"kind": "book", "title": "Dune", "creator": "Frank Herbert", "year": 1965, "rating": 10})
    assert response.status_int == 200
    assert response.json["work_id"] == work_id
    assert len(app.get("/api/library").json) == 1

    updated = app.put_json(f"/api/library/{work_id}", {"status": "abandoned", "rating": "", "notes": "gave up"}).json
    assert updated["status"] == "abandoned"
    assert updated["rating"] is None
    assert updated["notes"] == "gave up"

    app.delete(f"/api/library/{work_id}", status=204)
    assert app.get("/api/library").json == []
    app.delete(f"/api/library/{work_id}", status=404)


def test_validation(app: webtest.TestApp) -> None:
    sign_in(app)
    bad = [
        {"kind": "book", "title": ""},
        {"kind": "scroll", "title": "x"},
        {"kind": "book", "title": "x", "rating": 11},
        {"kind": "book", "title": "x", "rating": "lots"},
        {"kind": "book", "title": "x", "status": "meh"},
        {"kind": "book", "title": "x", "finished_on": "yesterday"},
        {"kind": "book", "title": "x", "year": -5},
        {"kind": "book", "title": ["x"]},
    ]
    for body in bad:
        response = app.post_json("/api/library", body, status=400)
        assert "error" in response.json
    app.post("/api/library", "not json", status=400)
    app.get("/api/library?kind=scroll", status=400)


def test_users_are_isolated(app: webtest.TestApp) -> None:
    sign_in(app, sub="alice")
    entry = app.post_json("/api/library", {"kind": "film", "title": "Alien", "creator": "Ridley Scott", "year": 1979}).json
    work_id = entry["work_id"]

    app.post("/auth/logout")
    sign_in(app, sub="bob")
    assert app.get("/api/library").json == []
    # bob cannot touch alice's entry, even though the work row is shared
    app.put_json(f"/api/library/{work_id}", {"status": "done"}, status=404)
    app.delete(f"/api/library/{work_id}", status=404)

    # bob adding the same film reuses the shared work row and gets his own entry
    entry = app.post_json("/api/library", {"kind": "film", "title": "Alien", "creator": "Ridley Scott", "year": 1979, "rating": 7}).json
    assert entry["work_id"] == work_id
    assert entry["rating"] == 7
    app.post("/auth/logout")
    sign_in(app, sub="alice")
    [entry] = app.get("/api/library").json
    assert entry["rating"] is None


# ─── email and password ──────────────────────────────────────────────────────

def test_email_register_and_login(app: webtest.TestApp) -> None:
    assert app.get("/api/config").json["password_min_length"] == auth.PASSWORD_MIN_LENGTH
    response = app.post_json("/auth/email/register", {"email": "  Carol@Example.com ", "password": "correct horse"})
    assert response.status_int == 200
    assert response.json["next"].endswith("/library")
    user = app.get("/api/config").json["user"]
    assert user["email"] == "carol@example.com"
    assert user["name"] == "carol"

    app.post("/auth/logout")
    assert app.get("/api/config").json["user"] is None
    app.post_json("/auth/email/login", {"email": "carol@example.com", "password": "correct horse"}, status=200)
    assert app.get("/api/config").json["user"]["email"] == "carol@example.com"
    assert app.get("/library").status_int == 200


def test_email_register_rejects_bad_input(app: webtest.TestApp) -> None:
    for body, status in [
        ({"email": "carol@example.com", "password": "short"}, 400),
        ({"email": "not an email", "password": "correct horse"}, 400),
        ({"email": "carol@example.com"}, 400),
        ({"email": ["carol@example.com"], "password": "correct horse"}, 400),
    ]:
        response = app.post_json("/auth/email/register", body, status=status)
        assert "error" in response.json
    app.post("/auth/email/register", "not json", status=400)
    app.post_json("/auth/email/register", {"email": "carol@example.com", "password": "correct horse"}, status=200)
    app.post("/auth/logout")
    response = app.post_json("/auth/email/register", {"email": "carol@example.com", "password": "another one"}, status=409)
    assert "already" in response.json["error"]
    assert app.get("/api/config").json["user"] is None


def test_email_login_rejects_wrong_credentials(app: webtest.TestApp) -> None:
    app.post_json("/auth/email/register", {"email": "carol@example.com", "password": "correct horse"})
    app.post("/auth/logout")
    unknown = app.post_json("/auth/email/login", {"email": "nobody@example.com", "password": "correct horse"}, status=401)
    wrong = app.post_json("/auth/email/login", {"email": "carol@example.com", "password": "wrong horse"}, status=401)
    # the same message either way, so the form does not reveal which emails have accounts
    assert unknown.json["error"] == wrong.json["error"]
    assert app.get("/api/config").json["user"] is None


def test_email_account_is_separate_from_google_account(app: webtest.TestApp) -> None:
    # the Google user in FAKE_CLAIMS has the same email; the accounts must not merge
    sign_in(app)
    app.post_json("/api/library", {"kind": "book", "title": "Dune"})
    app.post("/auth/logout")
    app.post_json("/auth/email/register", {"email": "alice@example.com", "password": "correct horse"})
    assert app.get("/api/library").json == []
    # a Google account cannot be entered through the password form
    app.post("/auth/logout")
    app.post_json("/auth/email/login", {"email": "alice@example.com", "password": "anything at all"}, status=401)


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

    def fake_claims(provider: auth.OAuthProvider, token: str) -> dict[str, str]:
        assert (provider.key, token) == ("github", "access-token")
        return {"sub": "github:42", "email": "dave@example.com", "name": "Dave", "picture": ""}

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
    assert app.get("/api/config").json["user"] == {"email": "dave@example.com", "name": "Dave", "picture": ""}


def test_oauth_callback_failures_return_to_landing(app: webtest.TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    configure_github(monkeypatch)

    def failing_exchange(provider: auth.OAuthProvider, code: str, redirect_uri: str) -> str:
        raise auth.OAuthError("nope")

    monkeypatch.setattr(auth, "exchange_code", failing_exchange)
    start = app.get("/auth/oauth/github")
    assert start.location is not None
    state = start.location.split("state=")[1].split("&")[0]
    # the user cancelled on GitHub: no code
    response = app.get(f"/auth/oauth/github/callback?state={state}&error=access_denied")
    assert response.status_int == 302
    assert response.location is not None
    assert "error=" in response.location and "cancelled" in response.location

    start = app.get("/auth/oauth/github")
    assert start.location is not None
    state = start.location.split("state=")[1].split("&")[0]
    response = app.get(f"/auth/oauth/github/callback?code=abc&state={state}")
    assert response.status_int == 302
    assert response.location is not None
    assert "failed" in response.location
    assert app.get("/api/config").json["user"] is None
