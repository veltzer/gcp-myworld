"""
Give every test a fresh app on an in-memory sqlite database, with Google
token verification stubbed out.
"""

from collections.abc import Iterator
from typing import Any

import pytest
import webtest
from sqlalchemy import create_engine, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from myworld import auth, create_app
from myworld.models import ROLE_ADMIN, Base, Login, User

FAKE_CLAIMS: dict[str, Any] = {
    "sub": "1234567890",
    "email": "alice@example.com",
    "name": "Alice",
    "picture": "https://example.com/alice.png",
    "email_verified": True,
}


def fake_claims(token: str) -> dict[str, Any]:
    """ What Google says of a token: the token is the sub; each sub but Alice's has an email of its own. """
    return dict(FAKE_CLAIMS, sub=token, email=FAKE_CLAIMS["email"] if token == FAKE_CLAIMS["sub"] else f"{token}@example.com")


class FakeMailer:
    """ Keeps the links instead of mailing them: (email, link) in the order sent. """

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.forgotten: list[str] = []

    def send(self, email: str, continue_url: str) -> None:
        self.sent.append((email, continue_url))

    def forget(self, email: str) -> None:
        self.forgotten.append(email)


@pytest.fixture(name="mailer")
def fixture_mailer() -> FakeMailer:
    return FakeMailer()


@pytest.fixture(name="engine")
def fixture_engine() -> Iterator[Engine]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(name="app")
def fixture_app(engine: Engine, mailer: FakeMailer, monkeypatch: pytest.MonkeyPatch) -> webtest.TestApp:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.delenv("CANONICAL_HOST", raising=False)
    monkeypatch.delenv("ALIAS_HOSTS", raising=False)
    monkeypatch.setattr(auth, "verify_google_token", fake_claims)
    return webtest.TestApp(create_app(engine, mailer))


def sign_in(app: webtest.TestApp, sub: str = "1234567890") -> None:
    """ Go through /auth/login the way the Google button would. """
    app.set_cookie("g_csrf_token", "csrf")
    response = app.post("/auth/login", {"credential": sub, "g_csrf_token": "csrf"})
    assert response.status_int == 302


def sign_in_admin(app: webtest.TestApp, engine: Engine, sub: str = "1234567890") -> None:
    """ Sign in, as an admin: the one who may change what everyone shares (countries, cities, places, ...). """
    sign_in(app, sub)
    with engine.begin() as connection:
        connection.execute(update(User).where(User.id.in_(select(Login.owner_id).where(Login.subject == "google:" + sub))).values(role=ROLE_ADMIN))
