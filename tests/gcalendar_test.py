"""
Connecting Google Calendar (myworld.gcalendar): the consent screen and back,
the refresh token kept sealed, disconnecting, and reading the calendars.
Google is faked: nothing here goes to the network.
"""

import urllib.parse
from typing import Any

import pytest
import webtest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from myworld import gcalendar
from myworld.models import CalendarConnection, User
from tests.conftest import sign_in

REFRESH = "calendar-refresh-token"


class FakeGoogle:
    """ Google's token endpoint and the Calendar API, as far as the connector uses them. """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.revoked: list[str] = []
        self.scope = f"openid {gcalendar.SCOPE}"

    def token_post(self, data: dict[str, str]) -> dict[str, Any]:
        assert data["client_secret"] == "test-client-secret"
        if data["grant_type"] == "authorization_code":
            assert data["code"] == "good-code"
            return {"access_token": "access", "refresh_token": REFRESH, "scope": self.scope}
        if data["refresh_token"] != REFRESH:
            raise gcalendar.CalendarError("Google no longer accepts the Google Calendar connection")
        return {"access_token": "access"}

    def api_get(self, access_token: str, path: str, params: dict[str, str]) -> dict[str, Any]:
        assert access_token == "access"
        self.calls.append(path)
        if path == "calendars/primary":
            return {"id": "alice@example.com", "summary": "alice@example.com"}
        if path == "users/me/calendarList":
            # a page at a time, as Google does
            if params.get("pageToken") == "2":
                return {"items": [{"id": "holidays", "summary": "Holidays in Israel"}, {"id": "b", "summary": "Birthdays", "summaryOverride": "birthdays"}]}
            return {"items": [{"id": "work", "summary": "Work"}, {"id": "alice@example.com", "summary": "alice@example.com", "primary": True}], "nextPageToken": "2"}
        raise AssertionError(path)

    def revoke(self, token: str) -> None:
        self.revoked.append(token)


@pytest.fixture(name="fake")
def fixture_fake(monkeypatch: pytest.MonkeyPatch) -> FakeGoogle:
    fake = FakeGoogle()
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setattr(gcalendar, "token_post", fake.token_post)
    monkeypatch.setattr(gcalendar, "api_get", fake.api_get)
    monkeypatch.setattr(gcalendar, "revoke", fake.revoke)
    return fake


def query_of(response: webtest.TestResponse) -> dict[str, list[str]]:
    assert isinstance(response.location, str)
    return urllib.parse.parse_qs(urllib.parse.urlsplit(response.location).query)


def connect(app: webtest.TestApp) -> webtest.TestResponse:
    """ Go through /calendar/connect and Google's consent screen, saying yes. """
    response = app.get("/calendar/connect")
    assert response.status_int == 302
    query = query_of(response)
    assert (query["scope"], query["access_type"], query["prompt"]) == ([gcalendar.SCOPE], ["offline"], ["consent"])
    assert query["redirect_uri"][0].endswith("/calendar/callback")
    return app.get("/calendar/callback", {"state": query["state"][0], "code": "good-code"})


def alice(engine: Engine) -> User:
    with Session(engine) as session:
        return session.scalars(select(User).where(User.email == "alice@example.com")).one()


def test_connecting_keeps_the_refresh_token_sealed(app: webtest.TestApp, engine: Engine, fake: FakeGoogle) -> None:
    sign_in(app)
    assert app.get("/calendar/status").json["connected"] is False
    back = connect(app)
    assert back.location is not None
    assert back.location.endswith("/library#imports")
    status = app.get("/calendar/status").json
    assert (status["configured"], status["connected"], status["account"]) == (True, True, "alice@example.com")
    # the Imports page shows it too
    assert app.get("/api/importers").json["calendar"]["connected"] is True
    with Session(engine) as session:
        kept = session.get(CalendarConnection, alice(engine).id)
        assert kept is not None
        # not as it was given: sealed with a key from SECRET_KEY
        assert REFRESH not in kept.refresh_token
        assert gcalendar.unseal(kept.refresh_token) == REFRESH
        # the calendars, the primary one first and then by name
        client = gcalendar.client_for(session, alice(engine))
        assert gcalendar.my_calendars(client) == [("alice@example.com", "alice@example.com"), ("b", "birthdays"), ("holidays", "Holidays in Israel"), ("work", "Work")]
    # disconnecting revokes it at Google and forgets it (and again is fine)
    app.post("/calendar/disconnect", status=204)
    app.post("/calendar/disconnect", status=204)
    assert fake.revoked == [REFRESH]
    assert app.get("/calendar/status").json["connected"] is False
    with Session(engine) as session, pytest.raises(gcalendar.CalendarError, match="not connected"):
        gcalendar.client_for(session, alice(engine))


def test_a_callback_with_a_wrong_state_is_refused(app: webtest.TestApp, fake: FakeGoogle) -> None:
    sign_in(app)
    app.get("/calendar/connect")
    app.get("/calendar/callback", {"state": "forged", "code": "good-code"}, status=400)
    assert app.get("/calendar/status").json["connected"] is False
    assert fake.calls == []


def test_saying_no_on_the_consent_screen(app: webtest.TestApp, fake: FakeGoogle) -> None:
    sign_in(app)
    query = query_of(app.get("/calendar/connect"))
    back = app.get("/calendar/callback", {"state": query["state"][0], "error": "access_denied"})
    assert "calendar_error=Connecting+Google+Calendar+was+cancelled" in str(back.location)
    assert app.get("/calendar/status").json["connected"] is False
    assert fake.calls == []


def test_calendar_access_left_unticked_is_not_a_connection(app: webtest.TestApp, fake: FakeGoogle) -> None:
    sign_in(app)
    fake.scope = "openid"
    back = connect(app)
    assert "calendar_error=" in str(back.location)
    assert "not+granted" in str(back.location)
    assert app.get("/calendar/status").json["connected"] is False


def test_without_a_client_secret_the_calendar_cannot_be_connected(app: webtest.TestApp, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    sign_in(app)
    app.get("/calendar/connect", status=404)
    assert app.get("/api/importers").json["calendar"]["configured"] is False
