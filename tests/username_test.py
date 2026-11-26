"""
Each account's username: chosen by its user, one account's alone,
lowercase, and none of the names that would read as the site's own.
"""


from typing import TYPE_CHECKING

from tests.conftest import sign_in

if TYPE_CHECKING:
    import webtest


def test_a_new_account_has_no_username_until_it_chooses_one(app: webtest.TestApp) -> None:
    sign_in(app)
    assert app.get("/api/config").json["user"]["username"] is None
    assert app.put_json("/api/account/username", {"username": "Veltzer"}).json["username"] == "veltzer"
    assert app.get("/api/config").json["user"]["username"] == "veltzer"
    # changed again, and the same one again is no clash with itself
    assert app.put_json("/api/account/username", {"username": "mark.v"}).json["username"] == "mark.v"
    assert app.put_json("/api/account/username", {"username": "mark.v"}).json["username"] == "mark.v"


def test_a_username_is_one_accounts_alone(app: webtest.TestApp) -> None:
    sign_in(app, "someone-else")
    app.put_json("/api/account/username", {"username": "veltzer"})
    sign_in(app)
    assert app.put_json("/api/account/username", {"username": "VELTZER"}, status=409).json == {"error": "veltzer is taken: choose another"}


def test_what_a_username_may_be(app: webtest.TestApp) -> None:
    sign_in(app)
    wrong = {"error": "A username is 3 to 30 letters, digits, dots, dashes or underscores, starting with a letter."}
    for username in ("", "ab", "1abc", "has space", "a" * 31, "dana@home", "-dana"):
        assert app.put_json("/api/account/username", {"username": username}, status=400).json == wrong, username
    assert app.put_json("/api/account/username", {"username": "admin"}, status=400).json == {"error": "admin is kept for the site: choose another"}
    for username in ("dan", "dana_levi", "dana-levi.2", "a" * 30):
        app.put_json("/api/account/username", {"username": username})
