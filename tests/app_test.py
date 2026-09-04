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
