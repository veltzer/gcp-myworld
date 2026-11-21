"""
Each user's theme (Settings): "system" (the device's) to start with, or
"light" or "dark", kept with their account so every device shows it.
"""

import webtest

from tests.conftest import sign_in


def test_each_user_picks_their_own_theme(app: webtest.TestApp) -> None:
    app.put_json("/api/account/theme", {"theme": "dark"}, status=401)
    sign_in(app)
    assert app.get("/api/config").json["user"]["theme"] == "system"
    assert app.put_json("/api/account/theme", {"theme": "dark"}).json["theme"] == "dark"
    assert app.get("/api/config").json["user"]["theme"] == "dark"
    assert "one of system, light, dark" in app.put_json("/api/account/theme", {"theme": "purple"}, status=400).json["error"]
    assert app.get("/api/config").json["user"]["theme"] == "dark"
    # another user's is their own
    sign_in(app, "bob")
    assert app.get("/api/config").json["user"]["theme"] == "system"
    assert app.put_json("/api/account/theme", {"theme": "light"}).json["theme"] == "light"
    sign_in(app)
    assert app.get("/api/config").json["user"]["theme"] == "dark"


def test_every_page_is_drawn_in_the_kept_theme_from_the_start(app: webtest.TestApp) -> None:
    for page in ("/", "/privacy"):
        assert 'localStorage.getItem("theme")' in app.get(page).text
