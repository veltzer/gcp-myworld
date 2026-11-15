"""
Give every test a fresh app on an in-memory sqlite database, with Google
token verification stubbed out.
"""

from collections.abc import Iterator
from typing import Any

import pytest
import webtest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from myworld import auth, create_app
from myworld.models import Base

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


@pytest.fixture(name="engine")
def fixture_engine() -> Iterator[Engine]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(name="app")
def fixture_app(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> webtest.TestApp:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.delenv("CANONICAL_HOST", raising=False)
    monkeypatch.setattr(auth, "verify_google_token", fake_claims)
    return webtest.TestApp(create_app(engine))


def sign_in(app: webtest.TestApp, sub: str = "1234567890") -> None:
    """ Go through /auth/login the way the Google button would. """
    app.set_cookie("g_csrf_token", "csrf")
    response = app.post("/auth/login", {"credential": sub, "g_csrf_token": "csrf"})
    assert response.status_int == 302
